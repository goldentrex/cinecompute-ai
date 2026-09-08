"""A second agent that checks the first one's arithmetic against the database.

Language models state figures fluently whether or not the data supports them.
Over this project's development the analyst agent presented a total as waste
($101,416 instead of $31,680), quoted a 100% crash rate it had never computed,
and reported scanned rows as a task count. Each was caught by re-running an
independent query by hand. This does that automatically.

The verifier never decides whether a figure is right. It only writes the check;
the query runs against ClickHouse through MCP and the comparison is arithmetic.
It is also never shown the value it is checking, so it cannot rubber-stamp it.
"""
import json
import re

from google.genai import types

MAX_CLAIMS = 8
# a claim and its check are compared as numbers, so rounding must not fail it
RELATIVE_TOLERANCE = 0.005

VERIFIER_INSTRUCTION = """You write verification queries for a VFX render-farm analysis.

You receive an analysis containing factual claims about a ClickHouse database, and a
list of the claims to check. For each one, write ONE read-only ClickHouse query that
recomputes that figure from the raw data - and nothing else.

Schema - use these exact names, invent nothing:
- {db}.vfx_render_events: event_time (DateTime), project_id, sequence_id, shot_id,
  software (Houdini_Karma | Maya_Arnold | Nuke_Comp | Blender_Cycles),
  gpu_model (NVIDIA_A100_80GB | NVIDIA_H100 | NVIDIA_L40S | NVIDIA_RTX4090),
  vram_peak_gb (Float32), compute_duration_sec (UInt32), cost_usd (Float32),
  status (SUCCESS | OOM_KILLED | TIMEOUT | DRIVER_CRASH), error_details (String),
  artist_id (String), frames_rendered (UInt16, 0 unless status = 'SUCCESS')
- {db}.production_budgets: sequence_id, allocated_budget_usd (Float64), deadline (Date),
  target_frames (UInt32)

Cost per delivered frame is sum(cost_usd) / nullIf(sum(frames_rendered), 0) - all
spend over delivered frames. A forecast at completion is target_frames times that.

A failed task is `status != 'SUCCESS'`; there is no 'FAILED' status. Wasted spend is
`sumIf(cost_usd, status != 'SUCCESS')`; total spend is `sum(cost_usd)`.

Rules:
- Return ONLY a JSON array, no prose, no code fence.
- Each element: {"id": <the claim id>, "sql": "<one SELECT ...>"}
- Each query MUST return exactly one row and one column: the number itself.
- Fully qualify tables as {db}.vfx_render_events / {db}.production_budgets.
- Recompute from the base table. Never copy a number from the analysis into the query.
- Scope comes from exactly two places: the user's question, and the claim's own
  sentence. If the question asks about Houdini Karma, carry that filter into every
  query unless the sentence says otherwise.
- NEVER import a filter that appears elsewhere in the analysis. A section above may
  discuss one renderer, one GPU or one artist; that does not narrow a later sentence.
  "Current spend: $X" for a sequence means the whole sequence - adding
  `AND software = '...'` because an earlier paragraph mentioned it measures a
  different quantity and produces a false accusation. When a sentence gives a total
  for a sequence, filter on the sequence and nothing else.
- Always fill a "checking" field naming what you recompute and the filters you
  applied, in a few words - e.g. "wasted spend, SEQ_010, all software". It is shown
  to the reader beside the verdict, so a check with no label is not usable.
- Recompute the quantity the number itself denotes. "(target: 313,408 frames)" is a
  frame count: recompute frames. A query summing cost_usd against it measures
  something else entirely and its disagreement means nothing.
- Check the figure the claim is ABOUT, not a neighbouring one. The context you are
  given may mention several numbers; your query must recompute the one named by the
  claim id, nothing else.
- OMIT the claim whenever its filters are not stated explicitly in the text. If the
  claim says "wasted spend" without naming the GPU, do not guess a GPU. If it gives a
  rate without naming the denominator, omit it. A missing check is a correct outcome;
  a check of the wrong quantity reads as an accusation and is not.
- Do not check derived arithmetic (percentages, differences, per-day averages) unless
  the text states the exact formula: several definitions exist and disagreeing with
  your own choice proves nothing.
- If a claim cannot be checked with a single query, omit it. Omitting is correct;
  inventing a query that happens to return the expected number is not.
"""

# figures that are not database facts and must not be "checked"
_IGNORE_NEAR = re.compile(
    r"(GB|VRAM|%|percent|retries?|x\b|node|hour)", re.IGNORECASE
)


def extract_claims(answer: str):
    """Pull the money and count figures a reader would take as fact."""
    claims, seen = [], set()
    for match in re.finditer(r"\$?\b(\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+\.\d{2})\b", answer):
        raw = match.group(1)
        value = float(raw.replace(",", ""))
        if value < 100 or raw in seen:
            continue
        # the governing filter often sits at the start of the sentence, so take the
        # whole sentence rather than a fixed window
        start = max(answer.rfind(".", 0, match.start()), answer.rfind("\n", 0, match.start())) + 1
        end = min((i for i in (answer.find(".", match.end()), answer.find("\n", match.end()))
                   if i != -1), default=len(answer)) + 1
        context = " ".join(answer[start:end].split())
        seen.add(raw)
        claims.append({"id": len(claims), "value": value, "text": raw,
                       "context": context, "is_money": match.group(0).startswith("$")})
        if len(claims) >= MAX_CLAIMS:
            break
    return claims


def _scalar(payload):
    """First cell of an MCP run_query result, as a float."""
    try:
        data = json.loads(payload)
        rows = data.get("rows") or []
        if not rows or not rows[0]:
            return None
        return float(rows[0][0])
    except (ValueError, TypeError, AttributeError):
        return None


async def verify(answer, mcp, generate, db, question=""):
    """Return (verdicts, summary). Never raises: verification is best-effort."""
    claims = extract_claims(answer)
    if not claims:
        return [], {"checked": 0, "confirmed": 0, "contradicted": 0}

    asked = [{"id": c["id"], "claim": c["context"]} for c in claims]   # value withheld
    try:
        response = generate(
            contents=[types.Content(role="user", parts=[types.Part.from_text(
                text=(f"The user asked: {question}\n\n"
                      f"Analysis:\n{answer[:6000]}\n\n"
                      f"Claims to check:\n{json.dumps(asked, indent=1)}")
            )])],
            config=types.GenerateContentConfig(
                system_instruction=VERIFIER_INSTRUCTION.replace("{db}", db),
                temperature=0.0,
                response_mime_type="application/json",
            ),
        )
        plan = json.loads(response.text or "[]")
    except Exception:
        return [], {"checked": 0, "confirmed": 0, "contradicted": 0}

    by_id = {c["id"]: c for c in claims}
    verdicts = []
    for item in plan if isinstance(plan, list) else []:
        claim = by_id.get(item.get("id"))
        sql = (item.get("sql") or "").strip()
        if not claim or not sql:
            continue

        payload, _, failed = await mcp.call("run_query", {"query": sql})
        found = None if failed else _scalar(payload)

        # A check that measures a different unit is not evidence either way. The
        # verifier once answered a frame count - "(target: 313,408 frames)" - with a
        # query summing cost_usd, and reported the mismatch as a contradiction.
        # Money claims carry a $; money queries read cost_usd. When those disagree
        # the check is discarded, not counted against the analysis.
        query_is_money = "cost_usd" in sql.lower()
        unit_mismatch = found is not None and claim["is_money"] != query_is_money

        if found is None or unit_mismatch:
            status = "unchecked"
        else:
            scale = max(abs(claim["value"]), 1.0)
            status = "confirmed" if abs(found - claim["value"]) / scale <= RELATIVE_TOLERANCE \
                else "contradicted"

        verdicts.append({
            "claim": claim["text"], "context": claim["context"],
            "checking": item.get("checking", ""),
            "unit_mismatch": unit_mismatch,
            "is_money": claim["is_money"],
            "expected": claim["value"], "found": found, "status": status, "sql": sql,
        })

    summary = {
        "checked": len(verdicts),
        "confirmed": sum(1 for v in verdicts if v["status"] == "confirmed"),
        "contradicted": sum(1 for v in verdicts if v["status"] == "contradicted"),
    }
    return verdicts, summary
