"""Shared visual language for the CineCompute UI (dark VFX studio look)."""

INK = "#e8ecf4"        # primary text
MUTED = "#8b95ad"      # secondary text
BG = "#0b0e14"         # page background
PANEL = "#151a23"      # card background
BORDER = "#232a36"

ACCENT = "#00ffcc"     # healthy / money
DANGER = "#ff4d6d"     # failure / waste
WARN = "#ffb020"       # at-risk
INFO = "#5b9dff"       # neutral series

STATUS_COLORS = {
    "SUCCESS": ACCENT,
    "OOM_KILLED": DANGER,
    "DRIVER_CRASH": "#c86bff",
    "TIMEOUT": WARN,
}

CSS = f"""
<style>
    [data-testid="stAppViewContainer"] {{
        background-color: {BG};
        color: {INK};
    }}
    [data-testid="stSidebar"] {{
        background-color: #0e131b;
        border-right: 1px solid {BORDER};
    }}
    /* the sidebar carries the architecture story - keep it readable on video */
    [data-testid="stSidebar"] p,
    [data-testid="stSidebar"] li,
    [data-testid="stSidebar"] label,
    [data-testid="stSidebar"] [data-testid="stCaptionContainer"] p {{
        color: #b9c2d4 !important;
        font-size: 14px;
    }}
    [data-testid="stSidebar"] h3 {{ color: {INK}; }}
    [data-testid="stSidebar"] strong {{ color: {INK}; }}
    html, body, [data-testid="stAppViewContainer"] * {{
        font-size: 16px;
    }}
    h1 {{ font-size: 40px !important; letter-spacing: -0.5px; }}
    h2 {{ font-size: 26px !important; }}
    h3 {{ font-size: 21px !important; }}

    /* KPI cards */
    .kpi {{
        background: linear-gradient(180deg, {PANEL} 0%, #11151d 100%);
        padding: 18px 20px;
        border-radius: 12px;
        border: 1px solid {BORDER};
        border-left: 5px solid {ACCENT};
        height: 100%;
    }}
    .kpi-label {{
        font-size: 12.5px;
        color: {MUTED};
        text-transform: uppercase;
        letter-spacing: 1.4px;
        font-weight: 600;
    }}
    .kpi-value {{
        font-size: 36px;
        font-weight: 700;
        color: {ACCENT};
        line-height: 1.15;
        margin-top: 6px;
        overflow-wrap: anywhere;
    }}
    .kpi-value.sm {{ font-size: 19px; letter-spacing: -0.3px; }}
    .kpi-sub {{ font-size: 13px; color: {MUTED}; margin-top: 6px; }}

    /* agent answer readability */
    [data-testid="stChatMessage"] {{
        background-color: {PANEL};
        border: 1px solid {BORDER};
        border-radius: 12px;
        padding: 6px 14px;
    }}
    [data-testid="stChatMessage"] p,
    [data-testid="stChatMessage"] li {{
        font-size: 16.5px;
        line-height: 1.65;
        color: {INK};
    }}
    [data-testid="stChatMessage"] h3 {{
        color: {ACCENT};
        margin-top: 18px;
        border-bottom: 1px solid {BORDER};
        padding-bottom: 6px;
    }}
    code {{ font-size: 14px !important; }}

    .hero {{
        margin: 18px 0 6px 0;
        padding: 18px 22px;
        border-radius: 12px;
        background: linear-gradient(90deg, rgba(0,255,204,0.10) 0%, rgba(0,255,204,0.02) 60%, transparent 100%);
        border: 1px solid rgba(0,255,204,0.28);
    }}
    .hero-main {{ font-size: 27px; font-weight: 700; color: {ACCENT}; }}
    .hero-sub {{ font-size: 15.5px; color: {INK}; margin-top: 6px; line-height: 1.6; max-width: 1100px; }}
    .hero-badge {{ font-size: 13px; color: {MUTED}; margin-top: 10px; letter-spacing: 0.3px; }}

    .speed-badge {{
        display: inline-block;
        background: rgba(0,255,204,0.10);
        border: 1px solid rgba(0,255,204,0.35);
        color: {ACCENT};
        border-radius: 999px;
        padding: 4px 12px;
        font-size: 13px;
        font-weight: 600;
    }}
</style>
"""


def plotly_layout(fig, height=300, title=None):
    """Apply the dark studio theme to a Plotly figure."""
    fig.update_layout(
        height=height,
        title=dict(text=title, font=dict(size=17, color=INK), x=0, xanchor="left") if title else None,
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        font=dict(color=INK, size=14),
        margin=dict(l=10, r=10, t=46 if title else 12, b=54),
        # Titles here are long, so the legend goes underneath the plot rather
        # than colliding with the title on the same line.
        legend=dict(orientation="h", yanchor="top", y=-0.18, x=0, font=dict(size=13)),
        hoverlabel=dict(bgcolor=PANEL, font_size=14),
    )
    fig.update_xaxes(gridcolor=BORDER, zerolinecolor=BORDER, tickfont=dict(size=13))
    fig.update_yaxes(gridcolor=BORDER, zerolinecolor=BORDER, tickfont=dict(size=13))
    return fig
