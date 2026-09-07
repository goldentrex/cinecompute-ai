# CineCompute AI — Devpost submission draft

*Paste the sections below into the Devpost form. Every figure was re-checked
against the database immediately before writing it down.*

---

## Inspiration

A render farm loses money quietly. A frame dies at 78 GB of VRAM, the scheduler
retries it, and the cost is gone before anyone reads a log. The waste is not one
catastrophe — it is a quarter of a million small events nobody has time to add
up. Production finds out when the sequence is over budget, and by then the
delivery date is the real problem.

## What it does

CineCompute AI answers one question: **where is the render budget going, and what
should the pipeline change today?**

Across 250,000 render events it finds **$97,885 of spend that produced no frame**
— 25% of everything spent — and shows that **$65,999 of it traces to two systemic
faults**: Houdini Karma jobs hitting the 80 GB VRAM ceiling on SEQ_010_SPACE_BATTLE
($10,079), and an L40S pool crashing on SEQ_045_UNDERWATER ($55,919).

It does four things a chat window does not:

**Writes its own SQL.** No pre-written queries. It inspects the schema, queries,
reads the result, queries again, and only then answers: why it happens, what it
costs, what to do. Every statement is shown live with its latency. One button
runs a question that is never cached, so what you watch is the real loop.

**Checks its own arithmetic.** A second agent re-derives every figure from the
database. It is shown the claim but never its value, writes one query per figure,
and the comparison is arithmetic — no model decides whether a number is right.
Against an answer with two deliberately falsified figures it contradicts exactly
those two; against the real answers it re-derives 16 of 17.

**Reads the calendar, not just the budget.** `production_budgets` carries a
delivery date. Two sequences have already spent their budget with 38 and 55 days
left before delivery, and the one that looks healthy on money has four days of
runway for 85 days of calendar.

**Sweeps unprompted and emits the fix.** One click ranks every project × sequence
× software × GPU slice: 12 systemic incidents, $57,836 recoverable. It exports
them as scheduler rules — VRAM floors, node exclusions, retry caps — each carrying
the counts that justify it. Advice becomes a file a render manager can apply.

## How we built it

```
Streamlit UI  ──►  Gemini 3 on Vertex AI (google-genai)
                        │  tools/list, tools/call   (MCP, stdio transport)
                        ▼
                 mcp-clickhouse 0.6  ──►  ClickHouse Cloud
```

The agent holds no database driver. It launches the **official ClickHouse MCP
server** as a subprocess, calls `initialize`, discovers the tools it publishes,
and issues every query as a `tools/call`. Because the tool list is discovered
rather than declared, the model can only call what the server offers. Writes are
refused twice: the server opens ClickHouse with `readonly=1`, and a client-side
allowlist rejects non-reads before they are sent.

The audit and the scheduler policy are pure SQL with no model in the path, so
they cannot contain an invented figure — and a test asserts the headline equals
the sum of its rules.

**Technologies:** Gemini 3 via `google-genai` on Vertex AI, with failover across
six models; the official `mcp-clickhouse` server; ClickHouse Cloud; Streamlit;
Plotly. Deployed on Streamlit Community Cloud against a read-only ClickHouse user
scoped to two tables.

**Data:** synthetic render-farm telemetry from `scripts/seed_vfx_data.py` —
250,000 events over 30 days, 3 projects, 4 DCC packages, 4 GPU models, two
engineered anomalies. Deterministic, and physically consistent: VRAM peaks never
exceed the capacity of the card the job ran on.

**Tests:** `pytest -q`, 19 tests, no API cost. They assert the properties that
past mistakes made necessary — writes refused before a round-trip, engine metrics
kept away from the model, every prompt rule still present, and every figure in the
recorded answers still matching ClickHouse.

## Challenges

**A hostname typo cost hours.** `*.clickhouse.cloud` is wildcard DNS, so a
misspelled service ID still resolves and still accepts TCP — the load balancer
then closes before the TLS handshake. The symptom is identical to a firewall
block, which sent us hunting the IP access list. One character: `so9rfg1hnc`
versus `so9rfglhnc`.

**Gemini 3 looked unavailable on Vertex.** Every 3.x model returned 404 in
us-central1, us-east5 and europe-west4. They are served from the `global`
endpoint, which serves nine. Concluding from one region would have meant shipping
either the older models or no Google Cloud at all.

**The SDK was executing our tools for us.** Passing Python callables to
`google-genai` enables Automatic Function Calling: the SDK ran the tools itself,
`response.function_calls` was always empty, and the live query inspector — the
centrepiece of the demo — could never have populated.

**Dollar signs became mathematics.** Streamlit renders `$...$` as LaTeX, so
"$5,987.29 and $2,296" turned into unreadable equations in a FinOps app.

**Measuring the wrong thing.** Hosted in the US against a Singapore database, the
dashboard reported 1131 ms and made ClickHouse look slow. Reading `elapsed_ns`
from the query summary gives the honest number: ~60 ms of engine time for 1.5
million rows scanned, with the network hop reported separately.

## What we learned

**An agent will fill any shape you give it.** Forcing the three-section format on
every question made it answer "what is the weather in Paris?" with a render-farm
report containing an invented job total. Letting it choose the shape fixed both
the relevance and the fabrication.

**Never show a model your own instrumentation.** We added `rows_scanned` to the
tool payload for the inspector; the model promptly reported 173,728 scanned rows
as 83,485 render tasks.

**A verifier is only as good as the context you give it.** Ours first invented
column names, because we never gave it the schema. Then it dropped filters,
because the claim's context window cut off the sentence that carried them. Then it
compared the wrong quantities, because it did not know the user's question. Fixed,
it went from 1 confirmation in 6 to 4 in 4 on the same answer.

**Verification changes what you ship.** Checking every number against an
independent query caught a total presented as waste ($101,416 instead of
$31,680), a 100% crash rate that was 61.2%, and an amount attributed to driver
crashes that actually covered every failure mode. None would have been visible by
reading the answers.

## What's next

Structured agent output instead of markdown parsing; a watchlist that alerts when
a sequence crosses its budget or its date; and writing the remediation policy
back to the farm scheduler instead of exporting it.
