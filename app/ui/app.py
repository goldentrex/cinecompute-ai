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
    layout="wide",
    initial_sidebar_state="expanded",
)
st.markdown(theme.CSS, unsafe_allow_html=True)

if "agent" not in st.session_state:
    st.session_state.agent = CineComputeAgent()
if "messages" not in st.session_state:
    st.session_state.messages = []
if "mcp_logs" not in st.session_state:
    st.session_state.mcp_logs = []
if "live_calls" not in st.session_state:
    st.session_state.live_calls = 0

# Public deployments run on a shared API key, so each visitor gets a budget of
# live Gemini questions. Recorded presets replay for free and never count.
PUBLIC_DEMO = os.environ.get("PUBLIC_DEMO", "").strip().lower() in ("1", "true", "yes")
LIVE_QUESTION_BUDGET = int(os.environ.get("LIVE_QUESTION_BUDGET", "3"))


# --------------------------------------------------------------------------
# Rendering helpers
# --------------------------------------------------------------------------
def money_safe(text: str) -> str:
    r"""Escape `$` outside code fences.

    Streamlit renders `$...$` as LaTeX, which turns "$5,987.29 and $2,296" into
    unreadable math. A FinOps app cannot afford that, so dollar signs in prose
    are escaped while fenced code is left untouched.
    """
    parts = re.split(r"(```.*?```|`[^`]*`)", text, flags=re.DOTALL)
    return "".join(p if p.startswith("`") else p.replace("$", r"\$") for p in parts)


def kpi_card(label, value, sub="", color=theme.ACCENT, small=False):
    return (
        f'<div class="kpi" style="border-left-color:{color}">'
        f'<div class="kpi-label">{label}</div>'
        f'<div class="kpi-value{" sm" if small else ""}" style="color:{color}">{value}</div>'
        f'<div class="kpi-sub">{sub}</div></div>'
    )


def render_log(log, index, expanded=False):
    """Render one MCP tool execution into the inspector."""
    res = log["result"]
    latency = res.get("latency_ms")
    header = f"🔧 {log['tool']}"
    if latency is not None:
        header += f"  ·  {latency} ms  ·  {res.get('row_count', 0)} rows"

    with st.expander(header, expanded=expanded):
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
        elif "tables" in res:
            st.write(res["tables"])
        elif "schema" in res:
            st.dataframe(pd.DataFrame(res["schema"]), width="stretch")

        if "error" in res:
            st.error(res["error"])


# --------------------------------------------------------------------------
# Data
# --------------------------------------------------------------------------
@st.cache_data(ttl=60, show_spinner=False)
def dashboard():
    return load_dashboard()


kpis, frames, timing, db_error = dashboard()

# --------------------------------------------------------------------------
# Sidebar
# --------------------------------------------------------------------------
with st.sidebar:
    st.markdown("### 🎬 CineCompute AI")
    st.caption("Autonomous render-farm FinOps agent · Gemini × MCP × ClickHouse")
    st.divider()

    st.markdown("**Data plane**")
    st.caption(f"ClickHouse · `{settings.clickhouse_host}`")
    if kpis:
        st.caption(f"{kpis['events']:,} telemetry events indexed")
        st.markdown(
            f'<span class="speed-badge">⚡ dashboard: {timing["queries"]} queries '
            f'in {timing["total_ms"]} ms</span>',
            unsafe_allow_html=True,
        )

    st.divider()
    st.markdown("**Reasoning plane**")
    st.caption(f"Gemini · `{st.session_state.agent.model_name}`")

    _mode = cache.mode()
    _labels = {
        "off": "Live — every question calls Gemini",
        "record": "Recording — live calls, saved for replay",
        "replay": "Replay — saved answers cost no quota, new questions go live",
    }
    st.caption(f"Answer cache: `{_mode}` — {_labels.get(_mode, 'unknown')}")

    _cached = cache.list_cached()
    if _cached:
        with st.expander(f"{len(_cached)} recorded run(s)"):
            for q, when, model in _cached:
                st.caption(f"• {q[:70]}  \n`{model}` · {when}")

    if PUBLIC_DEMO:
        left = max(0, LIVE_QUESTION_BUDGET - st.session_state.live_calls)
        st.caption(f"Public demo · {left}/{LIVE_QUESTION_BUDGET} live questions left "
                   "(quick actions are free)")

    st.divider()
    if st.button("Clear conversation", width="stretch"):
        st.session_state.messages = []
        st.session_state.mcp_logs = []
        st.session_state.agent = CineComputeAgent()
        st.rerun()

# --------------------------------------------------------------------------
# Header + KPIs
# --------------------------------------------------------------------------
st.title("🎬 CineCompute AI — Render Farm FinOps")
st.markdown(
    '<p style="font-size:18px;color:#8b95ad;margin-top:-8px">'
    "An autonomous agent that finds why renders die, what it costs the production, "
    "and what the pipeline TD must change today.</p>",
    unsafe_allow_html=True,
)

if db_error:
    st.error(
        "**ClickHouse unreachable — the dashboard and the agent cannot query telemetry.**\n\n"
        f"`{db_error}`\n\n"
        "Check the IP access list and that the service is running, then reload."
    )
    st.stop()

waste_pct = 100.0 * kpis["wasted"] / kpis["total_spend"] if kpis["total_spend"] else 0
c1, c2, c3, c4 = st.columns(4)
c1.markdown(
    kpi_card("Total render spend", f"${kpis['total_spend']:,.0f}",
             f"across {kpis['events']:,} render events"),
    unsafe_allow_html=True)
c2.markdown(
    kpi_card("Farm failure rate", f"{kpis['failure_rate']:.1f}%",
             f"{kpis['wasted_gpu_hours']:,.0f} GPU-hours burned on failed jobs",
             color=theme.DANGER),
    unsafe_allow_html=True)
c3.markdown(
    kpi_card("Wasted compute", f"${kpis['wasted']:,.0f}",
             f"{waste_pct:.0f}% of every dollar spent produced no frame",
             color=theme.DANGER),
    unsafe_allow_html=True)
c4.markdown(
    kpi_card("Worst overrun", kpis["top_sequence"],
             f"{kpis['top_overrun']:+.1f}% vs budget · "
             f"{kpis['over_budget_count']} sequence(s) over",
             color=theme.WARN, small=True),
    unsafe_allow_html=True)

rec_pct = 100.0 * kpis["recoverable"] / kpis["wasted"] if kpis["wasted"] else 0
st.markdown(
    '<div class="hero">'
    f'<div class="hero-main">${kpis["recoverable"]:,.0f} of that waste is recoverable</div>'
    '<div class="hero-sub">'
    f'{rec_pct:.0f}% of all wasted spend traces to just two systemic faults — '
    f'${kpis["oom_waste"]:,.0f} of Houdini Karma OOM kills on SEQ_010_SPACE_BATTLE and '
    f'${kpis["crash_waste"]:,.0f} of L40S driver crashes on SEQ_045_UNDERWATER. '
    'Both are fixable in the pipeline today — the agent below proves it from the telemetry.'
    '</div>'
    f'<div class="hero-badge">⚡ {timing["queries"]} ClickHouse queries · '
    f'{timing["total_ms"]} ms · {kpis["events"]:,} rows scanned</div>'
    '</div>',
    unsafe_allow_html=True,
)

# --------------------------------------------------------------------------
# Charts
# --------------------------------------------------------------------------
g1, g2 = st.columns([1, 1])

with g1:
    b = frames["budget"]
    fig = go.Figure()
    fig.add_bar(name="Allocated budget", x=b["sequence_id"], y=b["budget_usd"],
                marker_color=theme.BORDER, marker_line_color=theme.MUTED, marker_line_width=1)
    fig.add_bar(name="Actual spend", x=b["sequence_id"], y=b["spend_usd"],
                marker_color=[theme.DANGER if p > 0 else theme.ACCENT for p in b["overrun_pct"]],
                text=[f"{p:+.0f}%" for p in b["overrun_pct"]],
                textposition="outside", textfont=dict(size=15, color=theme.INK))
    fig.update_layout(barmode="group", yaxis_title="USD")
    st.plotly_chart(theme.plotly_layout(fig, 330, "Budget vs actual spend, by sequence"),
                    use_container_width=True, config={"displayModeBar": False})

with g2:
    w = frames["waste"]
    fig = go.Figure()
    for status in ["OOM_KILLED", "DRIVER_CRASH", "TIMEOUT"]:
        part = w[w["status"] == status]
        if len(part):
            fig.add_bar(name=status, x=part["software"], y=part["wasted_usd"],
                        marker_color=theme.STATUS_COLORS.get(status, theme.INFO))
    fig.update_layout(barmode="stack", yaxis_title="Wasted USD")
    st.plotly_chart(theme.plotly_layout(fig, 330, "Where the money burns: waste by software × failure"),
                    use_container_width=True, config={"displayModeBar": False})

with st.expander("📉 Daily burn and failure hotspots", expanded=False):
    e1, e2 = st.columns([3, 2])
    with e1:
        bd = frames["burn"]
        fig = go.Figure()
        fig.add_scatter(x=bd["day"], y=bd["productive_usd"], name="Productive",
                        stackgroup="one", line=dict(width=0), fillcolor="rgba(0,255,204,0.35)")
        fig.add_scatter(x=bd["day"], y=bd["wasted_usd"], name="Wasted",
                        stackgroup="one", line=dict(width=0), fillcolor="rgba(255,77,109,0.55)")
        fig.update_layout(yaxis_title="USD / day")
        st.plotly_chart(theme.plotly_layout(fig, 280, "Daily spend: productive vs wasted"),
                        use_container_width=True, config={"displayModeBar": False})
    with e2:
        h = frames["hotspots"].copy()
        h.columns = ["Project · Sequence · Software", "Failure %", "Wasted $", "Jobs"]
        st.dataframe(h, width="stretch", hide_index=True, height=280)

st.divider()

# --------------------------------------------------------------------------
# Agent + MCP inspector
# --------------------------------------------------------------------------
chat_col, mcp_col = st.columns([3, 2])

with mcp_col:
    st.subheader("Live MCP Query Inspector")
    st.caption("Every SQL statement the agent writes, executed read-only against ClickHouse.")
    live_box = st.container()
    history_box = st.container()


def mcp_callback(name, args, result_str):
    """Log an MCP tool execution and stream it into the inspector immediately."""
    try:
        res_data = json.loads(result_str)
    except Exception:
        res_data = {"raw": result_str}

    log = {"tool": name, "args": args, "result": res_data}
    st.session_state.mcp_logs.append(log)
    with live_box:
        render_log(log, len(st.session_state.mcp_logs), expanded=True)


with chat_col:
    st.subheader("Ask the FinOps agent")

    presets = [
        ("🔥 Diagnose SEQ_010",
         "What is causing render failures in SEQ_010_SPACE_BATTLE and how much money did we lose?"),
        ("💰 Budget overruns",
         "Which sequences are currently exceeding their production budget limits?"),
        ("🎛️ GPU efficiency",
         "Compare GPU cost efficiency: A100 vs H100 vs L40S on Houdini Karma jobs."),
    ]
    preset_clicked = None
    for col, (label, question) in zip(st.columns(3), presets):
        if col.button(label, width="stretch"):
            preset_clicked = question

    for msg in st.session_state.messages:
        with st.chat_message(msg["role"], avatar="🎬" if msg["role"] == "assistant" else "👤"):
            st.markdown(money_safe(msg["content"]))
            if msg.get("replayed"):
                st.caption("↺ replayed from cache — no Gemini quota used")

    prompt = st.chat_input("Ask about failures, cost, budgets, GPUs…") or preset_clicked

    will_replay = cache.mode() == "replay" and cache.load(prompt) is not None if prompt else False
    if prompt and PUBLIC_DEMO and not will_replay \
            and st.session_state.live_calls >= LIVE_QUESTION_BUDGET:
        st.warning(
            f"**Live question limit reached ({LIVE_QUESTION_BUDGET} per visitor).** "
            "This public demo runs on a shared Gemini key. The three quick actions above "
            "still work instantly — they replay recorded agent runs, including the exact "
            "SQL the agent wrote. Clone the repo with your own API key for unlimited use."
        )
        prompt = None

    if prompt:
        if not will_replay:
            st.session_state.live_calls += 1
        st.session_state.messages.append({"role": "user", "content": prompt})
        with st.chat_message("user", avatar="👤"):
            st.markdown(money_safe(prompt))

        with st.chat_message("assistant", avatar="🎬"):
            with st.spinner("Querying 250k telemetry events…"):
                response_text = st.session_state.agent.process_message(
                    prompt, tool_callback=mcp_callback
                )
            st.markdown(money_safe(response_text))
            st.session_state.messages.append({
                "role": "assistant",
                "content": response_text,
                "replayed": getattr(st.session_state.agent, "replayed", False),
            })
            st.rerun()

    if not st.session_state.messages:
        st.info(
            "**How it works** — the agent has no pre-written SQL. It inspects the schema, "
            "writes its own ClickHouse queries, reads the results, and only then answers: "
            "root cause, financial impact, and the fix for the pipeline TD. "
            "Watch the inspector on the right fill up as it reasons."
        )

with history_box:
    if st.session_state.mcp_logs:
        total = sum(l["result"].get("latency_ms", 0) for l in st.session_state.mcp_logs)
        st.markdown(
            f'<span class="speed-badge">⚡ {len(st.session_state.mcp_logs)} agent queries · '
            f'{total:.0f} ms total in ClickHouse</span>',
            unsafe_allow_html=True,
        )
        if st.button("Clear log"):
            st.session_state.mcp_logs = []
            st.rerun()
        for i, log in enumerate(reversed(st.session_state.mcp_logs)):
            render_log(log, len(st.session_state.mcp_logs) - i, expanded=(i == 0))
    else:
        st.caption("No queries yet — ask a question to watch the agent work.")
