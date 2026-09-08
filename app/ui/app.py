import html
import json
import os
import re
import sys

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

# Streamlit puts this file's own directory first on sys.path, where `app.py`
# shadows the `app` package. Insert the project root ahead of it.
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if PROJECT_ROOT in sys.path:
    sys.path.remove(PROJECT_ROOT)
sys.path.insert(0, PROJECT_ROOT)

from app.agent import cache, model_state
from app.agent.gemini_client import CineComputeAgent
from app.config import settings
from app.ui import theme
from app.ui.analytics import load_dashboard
from app.ui import workflow

st.set_page_config(
    page_title="CineCompute AI",
    page_icon="🎬",
    layout="centered",
    initial_sidebar_state="collapsed",
)
st.markdown(theme.CSS, unsafe_allow_html=True)

for key, default in (("messages", []), ("mcp_logs", []), ("live_calls", 0)):
    if key not in st.session_state:
        st.session_state[key] = default
# A redeploy leaves already-open browser sessions holding an agent built by the
# previous version of the code, whose methods have the previous signatures: a
# session open across the deploy that added `verify=` died with a TypeError at
# the call site. Probing for one attribute was too narrow a test - an object from
# a superseded module is not an instance of the class we just imported, so ask
# that instead, which stays correct whatever changes next.
if not isinstance(st.session_state.get("agent"), CineComputeAgent):
    st.session_state.agent = CineComputeAgent()

PUBLIC_DEMO = os.environ.get("PUBLIC_DEMO", "").strip().lower() in ("1", "true", "yes")
LIVE_QUESTION_BUDGET = int(os.environ.get("LIVE_QUESTION_BUDGET", "3"))


# --------------------------------------------------------------------------
# Rendering helpers
# --------------------------------------------------------------------------
# Models reach for LaTeX when they show arithmetic, whatever the prompt says. A
# `$$\frac{a}{b}$$` block renders as literal backslashes once dollars are escaped,
# so it is rewritten as plain text before anything else touches the answer.
_MATH_BLOCK = re.compile(r"\$\$(.+?)\$\$|\\\[(.+?)\\\]", re.DOTALL)


def _plain_math(match: "re.Match") -> str:
    body = match.group(1) or match.group(2) or ""
    body = re.sub(r"\\text\{([^{}]*)\}", r"\1", body)
    body = re.sub(r"\\frac\{([^{}]*)\}\{([^{}]*)\}", r"\1 / \2", body)
    body = body.replace(r"\times", "x").replace(r"\cdot", "x")
    body = body.replace(r"\%", "%").replace(r"\$", "$")
    body = re.sub(r"\\[a-zA-Z]+", "", body)          # any remaining command
    body = body.replace("{", "").replace("}", "")
    return " ".join(body.split())


# The same habit also shows up outside a math block, mid-sentence:
# `= \mathbf{+\$133,005.76}` renders as visible backslashes.
_TEX_WRAP = re.compile(r"\\(?:mathbf|mathrm|mathit|text|textbf|bf|it|emph)\{([^{}]*)\}")
_TEX_OPS = ((r"\times", "x"), (r"\cdot", "x"), (r"\approx", "~"),
            (r"\le", "<="), (r"\ge", ">="), (r"\%", "%"), (r"\$", "$"))


def strip_math(text: str) -> str:
    """Turn LaTeX arithmetic into the plain line a production manager can read."""
    text = _MATH_BLOCK.sub(_plain_math, text)
    for _ in range(3):                      # commands nest: \mathbf{\text{x}}
        text, n = _TEX_WRAP.subn(r"\1", text)
        if not n:
            break
    for tex, plain in _TEX_OPS:
        text = text.replace(tex, plain)
    # inline math was delimited by single dollars, which now sit next to the
    # dollar amounts they wrapped: "$$207,691.72 ... = +$133,005.76$"
    text = re.sub(r"\$\$+", "$", text)
    text = re.sub(r"(\d)\s*\$(?!\d)", r"\1", text)
    return text


def money_safe(text: str) -> str:
    r"""Escape `$` outside code spans: Streamlit reads `$...$` as LaTeX."""
    parts = re.split(r"(```.*?```|`[^`]*`)", text, flags=re.DOTALL)
    return "".join(p if p.startswith("`") else p.replace("$", r"\$") for p in parts)


SECTION_STYLE = [("cause", "Why it happens"), ("money", "What it costs"),
                 ("fix", "What to do"), ("note", "Draft note to the artist")]


def render_answer(text: str):
    """Three labelled blocks rather than one wall of prose."""
    text = strip_math(text)
    parts = re.split(r"^###\s*\d\.\s*(.+?)\s*$", text, flags=re.MULTILINE)
    if len(parts) < 3:
        st.markdown(money_safe(text))
        return

    if parts[0].strip():
        st.markdown(money_safe(parts[0].strip()))

    for idx in range(1, len(parts) - 1, 2):
        body = parts[idx + 1].strip()
        cls, label = SECTION_STYLE[idx // 2] if idx // 2 < len(SECTION_STYLE) else ("cause", parts[idx])
        with st.container(border=True):
            st.markdown(f'<div class="sec-head {cls}">{label}</div>', unsafe_allow_html=True)
            st.markdown(money_safe(body))


def _num(v, money):
    """Format a checked figure. `&#36;` not `$`: Streamlit reads `$...$` as LaTeX."""
    if v is None:
        return "not reproducible"
    return ("&#36;" if money else "") + f"{v:,.2f}".removesuffix(".00" if not money else "")


def render_flag(v):
    """Show a caught discrepancy in full, in the page, at the moment it is caught.

    A mismatch is the verifier doing its job, so it must read that way. Hiding it
    behind an expander leaves a judge with a red banner and no way to tell whether
    the product is unreliable or whether the check is.
    """
    money = "$" in (v.get("context") or "")
    stated, found = v["expected"], v["found"]
    gap = None if found is None else stated - found
    what = v.get("checking") or "the figure in the sentence below"
    sentence = html.escape((v.get("context") or "")).replace("*", "").strip()
    sentence = sentence.replace("$", "&#36;")
    nums = [("Analysis stated", _num(stated, money), ""),
            ("Database returns", _num(found, money), "")]
    if gap:
        nums.append(("Difference", _num(abs(gap), money), " gap"))

    cells = "".join(
        f'<div class="vflag-num"><span class="vflag-k">{k}</span>'
        f'<span class="vflag-v{cls}">{val}</span></div>'
        for k, val, cls in nums
    )
    st.markdown(
        f'<div class="vflag">'
        f'<div class="vflag-what">Flagged: <b>{what}</b></div>'
        f'<div class="vflag-nums">{cells}</div>'
        f'<div class="vflag-why">In the analysis: \u201c{sentence}\u201d<br>'
        f'The check query below recomputed this figure from the '
        f'raw events and got a different answer. Nothing was corrected automatically - '
        f'the point is that the discrepancy is visible instead of being read as fact.'
        f'</div></div>',
        unsafe_allow_html=True,
    )


def render_verification(verdicts, summary):
    """A second agent re-derived each figure from the database. Show the result."""
    if not summary or not summary.get("checked"):
        return

    confirmed, checked = summary["confirmed"], summary["checked"]
    contradicted = summary.get("contradicted", 0)
    colour = theme.GAIN if contradicted == 0 else theme.WARN
    label = (f"{confirmed} of {checked} figures re-derived from the database"
             if contradicted == 0 else
             f"{confirmed} of {checked} figures re-derived · "
             f"{contradicted} flagged as not reproducible")

    st.markdown(
        f'<div class="verif" style="border-color:{colour}">'
        f'<span class="vdot" style="background:{colour}"></span>'
        f'<b>Checked by a second agent</b> · {label}</div>',
        unsafe_allow_html=True,
    )

    for v in verdicts:
        if v["status"] == "contradicted":
            render_flag(v)

    with st.expander("See each check"):
        st.caption(
            "The verifier is never shown the figure it is checking. It writes one "
            "query per claim, the query runs against ClickHouse through MCP, and the "
            "comparison is arithmetic - no model decides whether a number is right. "
            "A flag (≠) means the check did not reproduce the figure: read the "
            "query, since it can also mean the check measured something slightly "
            "different."
        )
        for v in verdicts:
            mark = {"confirmed": "✓", "contradicted": "≠", "unchecked": "–"}[v["status"]]
            what = v.get("checking") or v["claim"]
            money = "$" in (v.get("context") or "")
            line = (f'`{mark}` **{what}** — analysis: {_num(v["expected"], money)} · '
                    f're-derived: {_num(v["found"], money)}')
            st.markdown(line)
            st.code(v["sql"], language="sql")


def render_steps(logs, as_html=False):
    """What the agent asked the database, and how fast it answered."""
    if not logs:
        return "" if as_html else None
    chips = []
    for i, log in enumerate(logs, 1):
        res, name = log["result"], log["tool"]
        if name == "run_query":
            n = res.get("row_count", 0)
            label = f"query · {n} row" + ("" if n == 1 else "s")
        elif name == "describe_table":
            label = f"read schema of {log['args'].get('table_name', '')}"
        else:
            label = name
        ms = res.get("latency_ms")
        t = f' <span class="t">{ms} ms</span>' if ms is not None else ""
        chips.append(f'<span class="step"><b>{i}. {label}</b>{t}</span>')
    html = f'<div class="steps">{"".join(chips)}</div>'
    if as_html:
        return html
    st.markdown(html, unsafe_allow_html=True)


def render_log(log, expanded=False):
    res = log["result"]
    head = f"{log['tool']}"
    if res.get("latency_ms") is not None:
        # this is the MCP call round-trip, not ClickHouse's own execution time
        head += f" · {res['latency_ms']} ms via MCP"
        if res.get("rows_scanned"):
            head += f" · {res['rows_scanned']:,} rows scanned"
    with st.expander(head, expanded=expanded):
        if res.get("raw_query"):
            st.code(res["raw_query"], language="sql")
        elif log["args"]:
            st.json(log["args"])
        if res.get("data"):
            df = pd.DataFrame(res["data"]).head(8)
            try:
                st.dataframe(df, width="stretch")
            except Exception:
                st.dataframe(df.astype(str), width="stretch")
        elif "schema" in res:
            st.dataframe(pd.DataFrame(res["schema"]), width="stretch")
        elif "tables" in res:
            st.write(res["tables"])
        if "error" in res:
            st.error(res["error"])


@st.cache_data(ttl=60, show_spinner=False)
def dashboard():
    return load_dashboard()


def skeleton_cards():
    """Shown while the first ClickHouse round-trip is in flight (~1s from the US)."""
    cell = ('<div class="card"><div class="metric-k skel" style="height:11px;width:45%"></div>'
            '<div class="skel skel-v"></div><div class="skel skel-d"></div></div>')
    return f'<div class="cards">{cell * 4}</div>'


_boot = st.empty()
if dashboard.clear is not None and "booted" not in st.session_state:
    _boot.markdown(skeleton_cards(), unsafe_allow_html=True)

kpis, frames, timing, db_error = dashboard()
st.session_state.booted = True
_boot.empty()

# --------------------------------------------------------------------------
# The one thing on screen
# --------------------------------------------------------------------------
if db_error:
    st.markdown(
        '<div class="callout" role="alert" style="border-left-color:' + theme.LOSS + '">'
        '<b>ClickHouse is unreachable</b>, so there is nothing to report yet. '
        'Check the service is running and that this host is allowed to connect.'
        '</div>', unsafe_allow_html=True)
    with st.expander("Technical detail"):
        st.code(db_error)
    st.stop()

st.markdown(
    f'<div class="topbar">'
    f'<div class="brand">CineCompute <span>· render farm FinOps</span></div>'
    f'<div><span class="pill"><span class="dot"></span>ClickHouse · '
    f'{kpis["events"]:,} events</span></div>'
    f'</div>',
    unsafe_allow_html=True,
)

waste_pct = 100.0 * kpis["wasted"] / kpis["total_spend"] if kpis["total_spend"] else 0
st.markdown(
    f'<div class="cards">'
    f'<div class="card lead"><div class="metric-k">Recoverable</div>'
    f'<div class="metric-v" style="color:{theme.GAIN}">${kpis["recoverable"]:,.0f}</div>'
    f'<div class="metric-d">from 2 systemic faults</div></div>'
    f'<div class="card"><div class="metric-k">Wasted spend</div>'
    f'<div class="metric-v" style="color:{theme.LOSS}">${kpis["wasted"]:,.0f}</div>'
    f'<div class="metric-d">{waste_pct:.0f}% of all spend</div></div>'
    f'<div class="card"><div class="metric-k">Failure rate</div>'
    f'<div class="metric-v">{kpis["failure_rate"]:.1f}%</div>'
    f'<div class="metric-d">{kpis["wasted_gpu_hours"]:,.0f} GPU-hours lost</div></div>'
    # Total spend is history and says nothing about the landing point; the
    # forecast does, and it is the figure a production wants at 07:00.
    f'<div class="card"><div class="metric-k">Forecast at completion</div>'
    f'<div class="metric-v" style="color:{theme.WARN}">${kpis["forecast_total"]:,.0f}</div>'
    f'<div class="metric-d">{kpis["completion_pct"]:.0f}% of frames delivered</div></div>'
    f'</div>',
    unsafe_allow_html=True,
)

st.markdown(
    f'<div class="callout">Two faults account for it: '
    f'<b>${kpis["oom_waste"]:,.0f}</b> of Houdini Karma jobs killed at the 80 GB VRAM '
    f'ceiling on SEQ_010_SPACE_BATTLE, and <b>${kpis["crash_waste"]:,.0f}</b> of L40S '
    f'driver crashes on SEQ_045_UNDERWATER. Both are scheduler settings, not artistry '
    f'- they can be changed today.</div>',
    unsafe_allow_html=True,
)

sched = frames["schedule"].merge(
    frames["progress"][["sequence_id", "completion_pct", "forecast_usd",
                        "forecast_overrun", "cost_per_frame"]],
    on="sequence_id", how="left")
_worst = sched.sort_values("days_of_budget_left").iloc[0]
_in_trouble = int((sched["verdict"] != "ok").sum())
_forecast_worst = sched.sort_values("forecast_overrun", ascending=False).iloc[0]

st.markdown('<div class="label">Schedule risk</div>', unsafe_allow_html=True)
_rows = []
for _, r in sched.iterrows():
    colour = {"over": theme.LOSS, "at_risk": theme.WARN, "ok": theme.GAIN}[r["verdict"]]
    left = ("budget already spent" if r["budget_left"] < 0
            else f'{r["days_of_budget_left"]:.0f} days of budget left')
    _rows.append(
        f'<div class="srow">'
        f'<span class="sseq">{r["sequence_id"]}</span>'
        f'<span class="sbar" style="background:{colour}"></span>'
        f'<span class="sfact">{left} · {r["completion_pct"]:.0f}% of frames done</span>'
        f'<span class="sdead">{r["days_to_deadline"]} days to {r["deadline"]:%d %b}</span>'
        f'</div>'
    )
st.markdown(
    f'<div class="card">{"".join(_rows)}'
    f'<div class="snote">Burn is the average over the observed window '
    f'(${_worst["burn_per_day"]:,.0f}/day for {_worst["sequence_id"]}). '
    f'Days of budget left compares that burn to what is unspent. Completion is '
    f'frames delivered against frames ordered, so the money and the work are '
    f'measured separately: {_forecast_worst["sequence_id"]} has spent '
    f'${_forecast_worst["spend_usd"]:,.0f} of a ${_forecast_worst["budget_usd"]:,.0f} '
    f'budget for {_forecast_worst["completion_pct"]:.0f}% of its frames, so at '
    f'${_forecast_worst["cost_per_frame"]:.2f} per delivered frame it lands near '
    f'<b>${_forecast_worst["forecast_usd"]:,.0f}</b> - '
    f'${_forecast_worst["forecast_overrun"]:,.0f} over. That holds only if the cost '
    f'per frame does not change; fixing the two faults above is what changes it.'
    f'</div></div>',
    unsafe_allow_html=True,
)

# --------------------------------------------------------------------------
# Waste with a name on it
# --------------------------------------------------------------------------
_artists = frames["artists"]
if len(_artists):
    st.markdown('<div class="label">Where the waste comes from</div>',
                unsafe_allow_html=True)
    _farm_rate = kpis["failure_rate"]
    _arows = []
    for _, r in _artists.head(3).iterrows():
        _off = r["failure_rate"] / _farm_rate if _farm_rate else 1.0
        _colour = theme.LOSS if _off >= 1.5 else theme.MUTED
        _arows.append(
            f'<div class="srow">'
            f'<span class="sseq">{r["artist_id"]}</span>'
            f'<span class="sbar" style="background:{_colour}"></span>'
            f'<span class="sfact">${r["wasted_usd"]:,.0f} wasted · '
            f'{r["failure_rate"]:.1f}% of {r["jobs"]:,} jobs failed</span>'
            f'<span class="sdead">{_off:.1f}x the farm rate</span>'
            f'</div>'
        )
    st.markdown(
        f'<div class="card">{"".join(_arows)}'
        f'<div class="snote">Ranked by money, with the rate that justifies the '
        f'ranking: a busy artist fails more often simply by submitting more, so a '
        f'raw count would accuse the wrong person. The farm average is '
        f'{_farm_rate:.1f}%. This points at a scene habit that can be fixed - '
        f'dense geometry, no proxy meshes - not at a performance problem. Artist '
        f'identifiers are synthetic, like the rest of this telemetry.</div></div>',
        unsafe_allow_html=True,
    )

st.markdown('<div class="label">Ask the agent</div>', unsafe_allow_html=True)
if getattr(st.session_state.agent, 'setup_error', None):
    st.warning(
        'Live questions are unavailable on this deployment - the recorded '
        'analyses below still work and show the real SQL the agent wrote.'
    )
    # the message names the misconfiguration; it never contains the credential
    with st.expander("Why live questions are off"):
        st.code(st.session_state.agent.setup_error)

# --------------------------------------------------------------------------
# Ask
# --------------------------------------------------------------------------
PRESETS = [
    ("Why do renders fail\non SEQ_010?",
     "What is causing render failures in SEQ_010_SPACE_BATTLE and how much money did we lose?"),
    ("Forecast SEQ_010 and\nname the crash source",
     "Forecast the final cost of SEQ_010_SPACE_BATTLE from its cost per delivered "
     "frame, compare it to the allocated budget, and identify whether one artist is "
     "behind an abnormal share of its failures."),
    ("Which GPUs waste\nthe most money?",
     "Compare GPU cost efficiency: A100 vs H100 vs L40S on Houdini Karma jobs."),
]

preset_clicked = None
for col, (label, question) in zip(st.columns(3), PRESETS):
    if col.button(label, width="stretch"):
        preset_clicked = question

# A recorded answer cannot prove the agent writes its own SQL. This one is never
# cached: it always runs live, so the pipeline and the queries are the real thing.
LIVE_PROBE = (
    "Across the whole farm, which single shot_id wastes the most money? Group by "
    "shot_id alone so the total is not split. Then, for that shot, break its failures "
    "down by software and GPU, and say what you would change."
)
if st.button("▶  Watch it work live  ·  runs a fresh, unrecorded question",
             width="stretch", disabled=st.session_state.agent.client is None):
    preset_clicked = LIVE_PROBE


# Placeholders the tool callback paints into while the turn is still running,
# so the pipeline animates with the work instead of after it.
wf_slot = st.empty()
steps_slot = st.empty()
_live = {"queries": 0, "ms": 0.0, "steps": []}


def _paint(phase, label=""):
    # aria-live so a screen reader announces each step as the loop advances
    wf_slot.markdown(
        f'<div class="wfbox" role="status" aria-live="polite">'
        f'{workflow.render(phase, _live["queries"], _live["ms"], label)}</div>',
        unsafe_allow_html=True,
    )


def mcp_callback(name, args, result_str):
    """Log a tool execution and repaint the pipeline as it happens."""
    try:
        res_data = json.loads(result_str)
    except Exception:
        res_data = {"raw": result_str}

    log = {"tool": name, "args": args, "result": res_data}
    st.session_state.mcp_logs.append(log)
    _live["steps"].append(log)

    if name == "run_query":
        _live["queries"] += 1
        _live["ms"] += res_data.get("latency_ms") or 0
        rows = res_data.get("row_count", 0)
        label = f"Query {_live['queries']} returned {rows} row" + ("" if rows == 1 else "s")
    else:
        label = f"Inspecting {args.get('table_name', 'the schema')}"

    _paint("querying", label)
    steps_slot.markdown(render_steps(_live["steps"], as_html=True), unsafe_allow_html=True)


prompt = st.chat_input("Or ask your own question…") or preset_clicked

is_live_probe = prompt == LIVE_PROBE
will_replay = (bool(prompt) and not is_live_probe
               and cache.mode() == "replay" and cache.load(prompt) is not None)
if prompt and PUBLIC_DEMO and not will_replay \
        and st.session_state.live_calls >= LIVE_QUESTION_BUDGET:
    st.warning(
        f"You have used the {LIVE_QUESTION_BUDGET} live questions this shared demo allows. "
        "The three buttons above still work — they replay recorded runs, SQL included."
    )
    prompt = None

if prompt:
    if not will_replay:
        st.session_state.live_calls += 1
    st.session_state.messages = [{"role": "user", "content": prompt}]
    turn_start = len(st.session_state.mcp_logs)
    _paint("thinking", "Sending the question to Gemini")
    answer = st.session_state.agent.process_message(
        prompt, tool_callback=mcp_callback, no_cache=is_live_probe,
        verify=is_live_probe)
    _paint("answering", "Writing the analysis")
    st.session_state.messages.append({
        "role": "assistant",
        "content": answer,
        "replayed": getattr(st.session_state.agent, "replayed", False),
        "steps": st.session_state.mcp_logs[turn_start:],
        "verdicts": getattr(st.session_state.agent, "verdicts", []),
        "verification": getattr(st.session_state.agent, "verification", {}),
    })
    st.rerun()

# --------------------------------------------------------------------------
# The answer
# --------------------------------------------------------------------------
answer_msg = next((m for m in st.session_state.messages if m["role"] == "assistant"), None)

# Paint the resting state of the pipeline: idle before anything is asked, and the
# finished loop with its totals once an answer is on screen.
_done_steps = (answer_msg or {}).get("steps") or []
_done_ms = sum(l["result"].get("latency_ms") or 0 for l in _done_steps)
_done_q = sum(1 for l in _done_steps if l["tool"] == "run_query")
_paint("done" if answer_msg else "idle",
       f"Answered from {_done_q} quer{'y' if _done_q == 1 else 'ies'}" if answer_msg else "")

if answer_msg:
    question = next((m["content"] for m in st.session_state.messages if m["role"] == "user"), "")
    st.markdown("<hr>", unsafe_allow_html=True)
    st.markdown(f'<div class="label">Answering · {question}</div>', unsafe_allow_html=True)
    render_steps(_done_steps)
    render_answer(answer_msg["content"])
    render_verification(answer_msg.get("verdicts") or [], answer_msg.get("verification") or {})
    if answer_msg.get("replayed"):
        st.caption("Replayed from a recorded run — no API quota used.")

    with st.expander("See the SQL the agent wrote"):
        for log in answer_msg.get("steps") or []:
            render_log(log)

# --------------------------------------------------------------------------
# Details, on demand
# --------------------------------------------------------------------------
st.markdown("<hr>", unsafe_allow_html=True)

# --------------------------------------------------------------------------
# Act on it: a sweep nobody asked for, and the fix it implies
# --------------------------------------------------------------------------
st.markdown('<div class="label">Act on it</div>', unsafe_allow_html=True)
st.markdown(
    '<p class="lede">The agent explains. These two do not ask it anything: they sweep '
    'the farm in SQL and turn what they find into scheduler rules you can hand to '
    'Deadline or Tractor.</p>',
    unsafe_allow_html=True,
)


@st.cache_data(ttl=120, show_spinner=False)
def farm_audit():
    from app.remediation import audit, policy_json
    incidents = audit()
    return incidents, policy_json(incidents)


act_left, act_right = st.columns([1, 1])
if act_left.button("Audit the whole farm", width="stretch"):
    st.session_state.show_audit = True

try:
    _incidents, _policy = farm_audit()
except Exception as _e:                       # never break the page over this
    _incidents, _policy = None, None
    act_right.caption(f"Audit unavailable: {str(_e)[:60]}")

if _policy is not None:
    act_right.download_button(
        "Download the scheduler policy", _policy,
        file_name="cinecompute-remediation.json", mime="application/json",
        width="stretch",
    )

if st.session_state.get("show_audit") and _incidents is not None:
    import json as _json
    _n = len(_incidents)
    _rec = _json.loads(_policy)["recoverable_usd"]
    st.markdown(
        f'<div class="callout">Swept every project x sequence x software x GPU slice '
        f'of the farm. <b>{_n} systemic incidents</b> account for '
        f'<b>${_rec:,.0f}</b> of recoverable spend. No question was asked and no model '
        f'was involved - this is SQL over the telemetry.</div>',
        unsafe_allow_html=True,
    )
    _table = _incidents[["sequence_id", "software", "gpu_model", "all_jobs",
                         "failure_rate", "wasted_usd", "dominant_failure", "severity"]]
    _table.columns = ["Sequence", "Software", "GPU", "Jobs", "Failure %",
                      "Wasted $", "Dominant failure", "Severity"]
    st.dataframe(_table, width="stretch", hide_index=True)
    with st.expander("The scheduler policy this implies"):
        st.caption(
            "Each rule carries the counts that justify it. Generated from the "
            "telemetry by SQL, so it cannot contain an invented figure."
        )
        st.code(_policy, language="json")

st.markdown("<hr>", unsafe_allow_html=True)

with st.expander("Show the numbers behind this"):
    st.markdown(
        f'<div class="cards">'
        f'<div class="card"><div class="metric-k">Jobs</div>'
        f'<div class="metric-v">{kpis["events"]:,}</div>'
        f'<div class="metric-d">render tasks recorded</div></div>'
        f'<div class="card"><div class="metric-k">Successful</div>'
        f'<div class="metric-v">{kpis["successful"]:,}</div>'
        f'<div class="metric-d">produced a frame</div></div>'
        f'<div class="card"><div class="metric-k">GPU-hours lost</div>'
        f'<div class="metric-v" style="color:{theme.LOSS}">{kpis["wasted_gpu_hours"]:,.0f}</div>'
        f'<div class="metric-d">spent on failed jobs</div></div>'
        f'<div class="card"><div class="metric-k">Over budget</div>'
        f'<div class="metric-v" style="color:{theme.WARN}">{kpis["over_budget_count"]}</div>'
        f'<div class="metric-d">of 3 sequences</div></div>'
        f'</div>',
        unsafe_allow_html=True,
    )

    bd = frames["burn"]
    fig = go.Figure()
    fig.add_scatter(
        x=bd["day"], y=bd["productive_usd"], name="Productive",
        mode="lines", line=dict(color=theme.BORDER_STRONG, width=2, shape="spline", smoothing=1.0),
        fill="tozeroy", fillcolor="rgba(205,213,223,.28)", hovertemplate="%{y:$,.0f} productive<extra></extra>",
    )
    fig.add_scatter(
        x=bd["day"], y=bd["wasted_usd"], name="Wasted",
        mode="lines", line=dict(color=theme.LOSS, width=2.6, shape="spline", smoothing=1.0),
        fill="tozeroy", fillcolor="rgba(220,38,38,.14)", hovertemplate="%{y:$,.0f} wasted<extra></extra>",
    )
    theme.annotate(fig, bd["day"].iloc[-1], bd["wasted_usd"].iloc[-1], "Wasted", theme.LOSS, dy=14)
    theme.annotate(fig, bd["day"].iloc[len(bd) // 2], bd["productive_usd"].iloc[len(bd) // 2],
                   "Productive", theme.MUTED, dy=-14)
    st.plotly_chart(theme.plotly_layout(fig, 260, "Daily spend"),
                    width="stretch", config={"displayModeBar": False})

    # Spend against work delivered, and the same line continued at the current
    # cost per frame. The x-axis is completion, not time: the arithmetic supports
    # "what the remaining frames cost", not "when they land".
    pf = frames["progress"]
    _budget_total = float(pf["budget_usd"].sum())
    _pct = (100.0 * bd["cum_frames"] / max(kpis["frames_target"], 1)).round(2)
    fig = go.Figure()
    _spent_now = float(bd["cum_spend"].iloc[-1])
    fig.add_scatter(
        x=[kpis["completion_pct"], 100], y=[_spent_now, kpis["forecast_total"]],
        name="Projected", mode="lines",
        line=dict(color=theme.WARN, width=2.4, dash="dash"),
        hovertemplate="%{y:$,.0f} at %{x:.0f}% complete<extra></extra>",
    )
    fig.add_scatter(
        x=_pct, y=bd["cum_spend"], name="Spent", mode="lines",
        line=dict(color=theme.INK, width=2.6, shape="spline", smoothing=1.0),
        hovertemplate="%{y:$,.0f} at %{x:.0f}% complete<extra></extra>",
    )
    fig.add_hline(y=_budget_total, line=dict(color=theme.MUTED, width=1.4, dash="dot"))
    theme.annotate(fig, 100, kpis["forecast_total"],
                   f'${kpis["forecast_total"]:,.0f}', theme.WARN, dy=-14)
    theme.annotate(fig, 12, _budget_total,
                   f'budget ${_budget_total:,.0f}', theme.MUTED, dy=-14)
    fig.update_xaxes(ticksuffix="%", range=[0, 108])
    st.plotly_chart(
        theme.plotly_layout(fig, 280, "Spend against frames delivered, continued to completion"),
        width="stretch", config={"displayModeBar": False})
    st.caption(
        f'{kpis["frames_done"]:,} of {kpis["frames_target"]:,} frames delivered for '
        f'${_spent_now:,.0f}. At the same cost per delivered frame the '
        f'remaining {kpis["frames_target"] - kpis["frames_done"]:,} frames cost '
        f'${kpis["forecast_total"] - _spent_now:,.0f} more, landing '
        f'${kpis["forecast_overrun"]:,.0f} over the combined budget. The dashed line is '
        f'that arithmetic, not a schedule prediction.'.replace("$", r"\$")
    )

    b = frames["budget"]
    fig = go.Figure()
    fig.add_bar(name="Budget", x=b["sequence_id"], y=b["budget_usd"],
                marker=dict(color="#e8ecf2", line=dict(width=0)),
                hovertemplate="budget %{y:$,.0f}<extra></extra>")
    fig.add_bar(name="Spent", x=b["sequence_id"], y=b["spend_usd"],
                marker=dict(color=[theme.LOSS if p > 0 else theme.GAIN for p in b["overrun_pct"]],
                            line=dict(width=0)),
                text=[f"{p:+.0f}%" for p in b["overrun_pct"]], textposition="outside",
                textfont=dict(size=13, family=theme.FONT),
                hovertemplate="spent %{y:$,.0f}<extra></extra>")
    fig.update_layout(barmode="group", bargap=0.45, bargroupgap=0.08)
    fig.update_traces(marker_cornerradius=5, selector=dict(type="bar"))
    st.plotly_chart(theme.plotly_layout(fig, 280, "Budget vs actual spend"),
                    width="stretch", config={"displayModeBar": False})

    h = frames["hotspots"].copy()
    h.columns = ["Project · Sequence · Software", "Failure %", "Wasted $", "Jobs"]
    st.dataframe(h, width="stretch", hide_index=True)

st.markdown(
    '<div class="foot">Synthetic render-farm telemetry - 250,000 events over 30 days, generated deterministically by <code>scripts/seed_vfx_data.py</code>, VRAM peaks bounded by each card&rsquo;s real capacity.</div>'
    f'<div class="foot">Gemini <code>{st.session_state.agent.model_name}</code> '
    f'({getattr(st.session_state.agent, "backend", "ai-studio")}) writing its own '
    f'read-only SQL, reaching '
    f'ClickHouse only through the official MCP server · dashboard computed in '
    f'{timing["total_ms"]:.0f} ms of engine time over {timing["rows_scanned"]:,} rows'
    + (f' · {max(0, LIVE_QUESTION_BUDGET - st.session_state.live_calls)} live questions left'
       if PUBLIC_DEMO else '')
    + '</div>',
    unsafe_allow_html=True,
)
