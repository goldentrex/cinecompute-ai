"""Product-UI theme following data-tooling conventions.

Neutral cool greys, a single blue primary, semantic status colours, a system
font stack and tabular figures - the idiom of Linear, Stripe and observability
consoles, rather than an editorial or brand-led look.
"""

# neutral ramp
BG = "#f7f8fa"
SURFACE = "#ffffff"
BORDER = "#e3e8ef"
BORDER_STRONG = "#cdd5df"
INK = "#0f172a"
MUTED = "#64748b"
FAINT = "#94a3b8"

# semantic
PRIMARY = "#2563eb"
LOSS = "#dc2626"
WARN = "#d97706"
GAIN = "#059669"
VIOLET = "#7c3aed"

STATUS_COLORS = {
    "SUCCESS": "#cbd5e1",
    "OOM_KILLED": LOSS,
    "DRIVER_CRASH": VIOLET,
    "TIMEOUT": WARN,
}

FONT = ('-apple-system, BlinkMacSystemFont, "Segoe UI", Inter, Roboto, '
        '"Helvetica Neue", Arial, sans-serif')
MONO = 'ui-monospace, SFMono-Regular, "SF Mono", Menlo, Consolas, monospace'

CSS = f"""
<style>
    [data-testid="stAppViewContainer"] {{ background-color: {BG}; }}
    [data-testid="stHeader"] {{ background: transparent; }}
    .block-container {{ max-width: 1080px; padding-top: 1.6rem; padding-bottom: 8rem; }}

    html, body, [data-testid="stAppViewContainer"] * {{
        font-family: {FONT};
        color: {INK};
        font-size: 15px;
    }}
    /* Streamlit draws its chevrons with a Material ligature font; the blanket
       font-family rule above would turn them into overlapping letter soup. */
    [data-testid="stIconMaterial"],
    .material-symbols-rounded,
    [class*="material-symbols"],
    span[data-testid="stExpanderToggleIcon"] {{
        font-family: "Material Symbols Rounded", "Material Symbols Outlined" !important;
    }}

    /* figures line up in columns, as in any real console */
    .tnum, .metric-v, .step .t {{ font-variant-numeric: tabular-nums; }}

    /* ---- top bar ---- */
    .topbar {{
        display: flex; align-items: center; justify-content: space-between;
        gap: 16px; padding-bottom: 14px; margin-bottom: 18px;
        border-bottom: 1px solid {BORDER};
    }}
    .brand {{ font-size: 15px; font-weight: 650; letter-spacing: -0.2px; }}
    .brand span {{ color: {MUTED}; font-weight: 450; }}
    .pill {{
        display: inline-flex; align-items: center; gap: 6px;
        background: {SURFACE}; border: 1px solid {BORDER};
        border-radius: 6px; padding: 4px 9px;
        font-size: 12px; color: {MUTED};
    }}
    .dot {{ width: 6px; height: 6px; border-radius: 50%; background: {GAIN};
            display: inline-block; }}

    /* ---- metric strip ---- */
    .cards {{ display: grid; grid-template-columns: repeat(4, 1fr); gap: 12px; }}
    .card {{
        background: {SURFACE}; border: 1px solid {BORDER};
        border-radius: 8px; padding: 14px 16px;
    }}
    .card.lead {{ border-color: {BORDER_STRONG}; box-shadow: 0 1px 2px rgba(16,24,40,.05); }}
    .metric-k {{
        font-size: 11.5px; font-weight: 600; letter-spacing: .4px;
        text-transform: uppercase; color: {MUTED};
    }}
    .metric-v {{ font-size: 27px; font-weight: 650; letter-spacing: -.6px; margin-top: 6px; }}
    .metric-d {{ font-size: 12.5px; color: {MUTED}; margin-top: 4px; }}

    .callout {{
        background: {SURFACE}; border: 1px solid {BORDER};
        border-left: 3px solid {PRIMARY};
        border-radius: 8px; padding: 14px 16px; margin: 12px 0 2px 0;
        font-size: 14.5px; line-height: 1.6; color: {INK};
    }}
    .callout b {{ font-weight: 650; }}

    .label {{
        font-size: 11.5px; font-weight: 600; letter-spacing: .5px;
        text-transform: uppercase; color: {MUTED}; margin: 26px 0 10px 0;
    }}

    /* ---- answer sections ---- */
    .sec-head {{
        font-size: 11.5px; font-weight: 700; letter-spacing: .6px;
        text-transform: uppercase; margin: 0 0 8px 0; color: {MUTED};
    }}
    .sec-head.cause {{ color: {PRIMARY}; }}
    .sec-head.money {{ color: {LOSS}; }}
    .sec-head.fix   {{ color: {GAIN}; }}

    [data-testid="stChatMessage"] {{ background: transparent; padding: 0; }}
    [data-testid="stChatMessage"] p, [data-testid="stChatMessage"] li {{
        font-size: 14.5px; line-height: 1.62;
    }}
    [data-testid="stVerticalBlockBorderWrapper"] {{
        background: {SURFACE}; border-radius: 8px;
    }}

    /* ---- query trail ---- */
    .steps {{ margin: 2px 0 14px 0; }}
    .step {{
        display: inline-flex; align-items: center; gap: 8px;
        background: {SURFACE}; border: 1px solid {BORDER}; border-radius: 6px;
        padding: 5px 10px; margin: 0 6px 6px 0;
        font-size: 12.5px; color: {MUTED}; font-family: {MONO};
    }}
    .step b {{ color: {INK}; font-weight: 600; }}
    .step .t {{ color: {GAIN}; }}

    /* ---- buttons ---- */
    .stButton > button {{
        background: {SURFACE}; border: 1px solid {BORDER}; border-radius: 8px;
        padding: 13px 14px; font-size: 14px; font-weight: 550; color: {INK};
        line-height: 1.4; height: 100%; text-align: left;
        transition: border-color .12s, box-shadow .12s;
    }}
    .stButton > button p, .stButton > button div {{
        white-space: normal !important; overflow: visible !important;
        text-overflow: clip !important; line-height: 1.4;
    }}
    .stButton > button:hover {{
        border-color: {PRIMARY}; color: {PRIMARY};
        box-shadow: 0 1px 3px rgba(37,99,235,.14);
    }}

    code {{
        font-family: {MONO}; font-size: 13px !important;
        background: #eef2f6 !important; color: #334155 !important;
        border-radius: 4px; padding: 1px 5px;
    }}
    [data-testid="stExpander"] details {{
        border: 1px solid {BORDER}; border-radius: 8px; background: {SURFACE};
    }}
    [data-testid="stExpander"] summary {{ font-size: 14px; font-weight: 600; }}
    hr {{ border-color: {BORDER}; margin: 26px 0 18px 0; }}
    .foot {{ font-size: 12.5px; color: {FAINT}; margin-top: 8px; line-height: 1.7; }}

    @media (max-width: 760px) {{ .cards {{ grid-template-columns: repeat(2, 1fr); }} }}
</style>
"""


def plotly_layout(fig, height=300, title=None):
    fig.update_layout(
        height=height,
        title=dict(text=title, font=dict(size=14, color=MUTED), x=0, xanchor="left") if title else None,
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        font=dict(color=INK, size=13, family=FONT),
        margin=dict(l=8, r=8, t=40 if title else 8, b=46),
        legend=dict(orientation="h", yanchor="top", y=-0.16, x=0, font=dict(size=12)),
        hoverlabel=dict(bgcolor=SURFACE, font_size=13),
    )
    fig.update_xaxes(gridcolor=BORDER, zerolinecolor=BORDER, tickfont=dict(size=12))
    fig.update_yaxes(gridcolor=BORDER, zerolinecolor=BORDER, tickfont=dict(size=12))
    return fig
