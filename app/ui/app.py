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

from app.agent import cache
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
if "agent" not in st.session_state:
    st.session_state.agent = CineComputeAgent()

PUBLIC_DEMO = os.environ.get("PUBLIC_DEMO", "").strip().lower() in ("1", "true", "yes")
LIVE_QUESTION_BUDGET = int(os.environ.get("LIVE_QUESTION_BUDGET", "3"))


# --------------------------------------------------------------------------
# Rendering helpers
# --------------------------------------------------------------------------
def money_safe(text: str) -> str:
    r"""Escape `$` outside code spans: Streamlit reads `$...$` as LaTeX."""
    parts = re.split(r"(```.*?```|`[^`]*`)", text, flags=re.DOTALL)
    return "".join(p if p.startswith("`") else p.replace("$", r"\$") for p in parts)


SECTION_STYLE = [("cause", "Why it happens"), ("money", "What it costs"), ("fix", "What to do")]


def render_answer(text: str):
    """Three labelled blocks rather than one wall of prose."""
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
        head += f" · {res['latency_ms']} ms in ClickHouse"
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
    f'<div class="card"><div class="metric-k">Total spend</div>'
    f'<div class="metric-v">${kpis["total_spend"]:,.0f}</div>'
    f'<div class="metric-d">{kpis["events"]:,} render jobs</div></div>'
    f'</div>',
    unsafe_allow_html=True,
)

st.markdown(
    f'<div class="callout">Two faults account for most of the waste: '
    f'<b>${kpis["oom_waste"]:,.0f}</b> of Houdini Karma out-of-memory kills on '
    f'SEQ_010_SPACE_BATTLE, and <b>${kpis["crash_waste"]:,.0f}</b> of L40S driver '
    f'crashes on SEQ_045_UNDERWATER. Both are fixable in the pipeline today.</div>',
    unsafe_allow_html=True,
)

st.markdown('<div class="label">Ask the agent</div>', unsafe_allow_html=True)

# --------------------------------------------------------------------------
# Ask
# --------------------------------------------------------------------------
PRESETS = [
    ("Why do renders fail\non SEQ_010?",
     "What is causing render failures in SEQ_010_SPACE_BATTLE and how much money did we lose?"),
    ("Which sequences are\nover budget?",
     "Which sequences are currently exceeding their production budget limits?"),
    ("Which GPUs waste\nthe most money?",
     "Compare GPU cost efficiency: A100 vs H100 vs L40S on Houdini Karma jobs."),
]

preset_clicked = None
for col, (label, question) in zip(st.columns(3), PRESETS):
    if col.button(label, width="stretch"):
        preset_clicked = question


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

will_replay = bool(prompt) and cache.mode() == "replay" and cache.load(prompt) is not None
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
    answer = st.session_state.agent.process_message(prompt, tool_callback=mcp_callback)
    _paint("answering", "Writing the analysis")
    st.session_state.messages.append({
        "role": "assistant",
        "content": answer,
        "replayed": getattr(st.session_state.agent, "replayed", False),
        "steps": st.session_state.mcp_logs[turn_start:],
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
    if answer_msg.get("replayed"):
        st.caption("Replayed from a recorded run — no API quota used.")

    with st.expander("See the SQL the agent wrote"):
        for log in answer_msg.get("steps") or []:
            render_log(log)

# --------------------------------------------------------------------------
# Details, on demand
# --------------------------------------------------------------------------
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
                    use_container_width=True, config={"displayModeBar": False})

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
                    use_container_width=True, config={"displayModeBar": False})

    h = frames["hotspots"].copy()
    h.columns = ["Project · Sequence · Software", "Failure %", "Wasted $", "Jobs"]
    st.dataframe(h, width="stretch", hide_index=True)

st.markdown(
    f'<div class="foot">Gemini <code>{st.session_state.agent.model_name}</code> writing its own '
    f'read-only SQL against ClickHouse · dashboard computed in '
    f'{timing["total_ms"]:.0f} ms of engine time over {timing["rows_scanned"]:,} rows'
    + (f' · {max(0, LIVE_QUESTION_BUDGET - st.session_state.live_calls)} live questions left'
       if PUBLIC_DEMO else '')
    + '</div>',
    unsafe_allow_html=True,
)
