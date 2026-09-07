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


def render_steps(logs):
    """What the agent asked the database, and how fast it answered."""
    if not logs:
        return
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
    st.markdown(
        f'<div class="steps">{"".join(chips)}</div>',
        unsafe_allow_html=True,
    )


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


kpis, frames, timing, db_error = dashboard()

# --------------------------------------------------------------------------
# The one thing on screen
# --------------------------------------------------------------------------
if db_error:
    st.error(f"Cannot reach ClickHouse, so there is nothing to report.\n\n`{db_error}`")
    st.stop()

st.markdown('<div class="eyebrow">Render farm · last 30 days</div>', unsafe_allow_html=True)
st.markdown(f'<div class="headline">${kpis["recoverable"]:,.0f}</div>', unsafe_allow_html=True)
st.markdown(
    f'<p class="standfirst">of your <b>${kpis["wasted"]:,.0f}</b> in wasted render spend is '
    f'recoverable. Two faults cause most of it, and both are fixable in the pipeline today.</p>',
    unsafe_allow_html=True,
)
st.markdown(
    f'<div class="footnote">Out of ${kpis["total_spend"]:,.0f} spent across '
    f'{kpis["events"]:,} render jobs · {kpis["failure_rate"]:.0f}% of them failed</div>',
    unsafe_allow_html=True,
)

st.markdown("<hr>", unsafe_allow_html=True)

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


def mcp_callback(name, args, result_str):
    try:
        res_data = json.loads(result_str)
    except Exception:
        res_data = {"raw": result_str}
    st.session_state.mcp_logs.append({"tool": name, "args": args, "result": res_data})


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
    with st.spinner("Reading the telemetry…"):
        answer = st.session_state.agent.process_message(prompt, tool_callback=mcp_callback)
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
if answer_msg:
    question = next((m["content"] for m in st.session_state.messages if m["role"] == "user"), "")
    st.markdown("<hr>", unsafe_allow_html=True)
    st.markdown(f'<div class="eyebrow">Answering: {question}</div>', unsafe_allow_html=True)
    render_steps(answer_msg.get("steps"))
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
        f'<div class="metric-row">'
        f'<div><div class="metric-n">${kpis["total_spend"]:,.0f}</div>'
        f'<div class="metric-l">total render spend</div></div>'
        f'<div><div class="metric-n" style="color:{theme.LOSS}">{kpis["failure_rate"]:.1f}%</div>'
        f'<div class="metric-l">of jobs failed</div></div>'
        f'<div><div class="metric-n" style="color:{theme.LOSS}">${kpis["wasted"]:,.0f}</div>'
        f'<div class="metric-l">produced no frame</div></div>'
        f'<div><div class="metric-n">{kpis["wasted_gpu_hours"]:,.0f}</div>'
        f'<div class="metric-l">GPU-hours burnt</div></div>'
        f'</div>',
        unsafe_allow_html=True,
    )

    b = frames["budget"]
    fig = go.Figure()
    fig.add_bar(name="Budget", x=b["sequence_id"], y=b["budget_usd"], marker_color="#d8d4ca")
    fig.add_bar(name="Actually spent", x=b["sequence_id"], y=b["spend_usd"],
                marker_color=[theme.LOSS if p > 0 else theme.GAIN for p in b["overrun_pct"]],
                text=[f"{p:+.0f}%" for p in b["overrun_pct"]],
                textposition="outside", textfont=dict(size=15))
    fig.update_layout(barmode="group", yaxis_title="USD")
    st.plotly_chart(theme.plotly_layout(fig, 320, "Budget vs actual spend"),
                    use_container_width=True, config={"displayModeBar": False})

    w = frames["waste"]
    fig = go.Figure()
    for status in ("OOM_KILLED", "DRIVER_CRASH", "TIMEOUT"):
        part = w[w["status"] == status]
        if len(part):
            fig.add_bar(name=status, x=part["software"], y=part["wasted_usd"],
                        marker_color=theme.STATUS_COLORS[status])
    fig.update_layout(barmode="stack", yaxis_title="Wasted USD")
    st.plotly_chart(theme.plotly_layout(fig, 320, "Where the money burns"),
                    use_container_width=True, config={"displayModeBar": False})

    h = frames["hotspots"].copy()
    h.columns = ["Project · Sequence · Software", "Failure %", "Wasted $", "Jobs"]
    st.dataframe(h, width="stretch", hide_index=True)

st.markdown(
    f'<div class="footnote">Gemini <code>{st.session_state.agent.model_name}</code> writing its own '
    f'read-only SQL against ClickHouse · dashboard computed in '
    f'{timing["total_ms"]:.0f} ms of engine time over {timing["rows_scanned"]:,} rows'
    + (f' · {max(0, LIVE_QUESTION_BUDGET - st.session_state.live_calls)} live questions left'
       if PUBLIC_DEMO else '')
    + '</div>',
    unsafe_allow_html=True,
)
