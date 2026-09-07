"""Light editorial theme.

The first version was a dark "VFX studio" dashboard that accumulated panels
until nothing stood out. This one is built the other way round: one question is
answered per screen, in type large enough to read on video, and everything else
waits behind a disclosure.
"""

INK = "#14141a"        # primary text
MUTED = "#6b6b76"      # secondary text
FAINT = "#9a9aa4"
BG = "#faf9f6"         # page
PANEL = "#ffffff"      # cards
BORDER = "#e6e3dc"

LOSS = "#c0392b"       # money burnt
GAIN = "#1f7a5c"       # money recoverable
NEUTRAL = "#5b6b8c"    # everything else
WARN = "#b8860b"

STATUS_COLORS = {
    "SUCCESS": "#c8cdd6",
    "OOM_KILLED": LOSS,
    "DRIVER_CRASH": "#8e44ad",
    "TIMEOUT": WARN,
}

CSS = f"""
<style>
    [data-testid="stAppViewContainer"] {{ background-color: {BG}; }}
    [data-testid="stHeader"] {{ background: transparent; }}
    /* the chat input is fixed to the bottom; leave room so it never covers text */
    .block-container {{ max-width: 940px; padding-top: 2.2rem; padding-bottom: 8rem; }}

    html, body, [data-testid="stAppViewContainer"] * {{
        color: {INK};
        font-size: 17px;
    }}

    /* --- the one thing on screen --- */
    .eyebrow {{
        font-size: 13px;
        letter-spacing: 2px;
        text-transform: uppercase;
        color: {MUTED};
        font-weight: 600;
        margin-bottom: 10px;
    }}
    .headline {{
        font-size: 62px;
        line-height: 1.03;
        font-weight: 700;
        letter-spacing: -2px;
        color: {LOSS};
        margin: 0;
    }}
    .standfirst {{
        font-size: 21px;
        line-height: 1.5;
        color: {INK};
        margin: 16px 0 6px 0;
        max-width: 660px;
    }}
    .standfirst b {{ color: {LOSS}; font-weight: 650; }}
    .footnote {{ font-size: 15px; color: {MUTED}; margin-top: 10px; }}

    hr {{ border-color: {BORDER}; margin: 30px 0 22px 0; }}

    /* --- answer sections --- */
    .sec-head {{
        font-size: 12.5px;
        font-weight: 700;
        letter-spacing: 1.6px;
        text-transform: uppercase;
        margin: 0 0 10px 0;
        color: {MUTED};
    }}
    .sec-head.cause {{ color: {NEUTRAL}; }}
    .sec-head.money {{ color: {LOSS}; }}
    .sec-head.fix   {{ color: {GAIN}; }}

    [data-testid="stChatMessage"] {{ background: transparent; padding: 0; }}
    [data-testid="stChatMessage"] p,
    [data-testid="stChatMessage"] li {{ font-size: 17px; line-height: 1.68; }}
    [data-testid="stVerticalBlockBorderWrapper"] {{
        background: {PANEL};
        border-radius: 12px;
    }}

    /* --- agent step trail --- */
    .steps {{ margin: 4px 0 18px 0; line-height: 2.2; }}
    .step {{
        display: inline-block;
        background: {PANEL};
        border: 1px solid {BORDER};
        border-radius: 999px;
        padding: 5px 13px;
        margin: 0 7px 6px 0;
        font-size: 13px;
        color: {MUTED};
    }}
    .step b {{ color: {INK}; font-weight: 600; }}
    .step .t {{ color: {GAIN}; font-weight: 600; }}

    /* --- buttons: the primary call to action --- */
    .stButton > button {{
        background: {PANEL};
        border: 1px solid {BORDER};
        border-radius: 10px;
        padding: 16px 14px;
        font-size: 16px;
        font-weight: 600;
        color: {INK};
        line-height: 1.35;
        height: 100%;
        transition: border-color .15s, box-shadow .15s;
    }}
    .stButton > button:hover {{
        border-color: {INK};
        box-shadow: 0 2px 10px rgba(0,0,0,.06);
        color: {INK};
    }}

    code {{
        font-size: 14px !important;
        background: #f2f0ea !important;
        color: #333 !important;
    }}
    [data-testid="stExpander"] details {{
        border: 1px solid {BORDER};
        border-radius: 10px;
        background: {PANEL};
    }}
    [data-testid="stExpander"] summary {{ font-size: 16px; font-weight: 600; }}

    .metric-row {{ display: flex; gap: 34px; flex-wrap: wrap; margin: 6px 0 4px 0; }}
    .metric-n {{ font-size: 30px; font-weight: 700; letter-spacing: -0.6px; }}
    .metric-l {{ font-size: 13.5px; color: {MUTED}; margin-top: 2px; }}
</style>
"""


def plotly_layout(fig, height=300, title=None):
    """Light, low-ink chart styling."""
    fig.update_layout(
        height=height,
        title=dict(text=title, font=dict(size=16, color=INK), x=0, xanchor="left") if title else None,
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        font=dict(color=INK, size=14),
        margin=dict(l=10, r=10, t=46 if title else 10, b=50),
        legend=dict(orientation="h", yanchor="top", y=-0.16, x=0, font=dict(size=13)),
        hoverlabel=dict(bgcolor=PANEL, font_size=14),
    )
    fig.update_xaxes(gridcolor=BORDER, zerolinecolor=BORDER, tickfont=dict(size=13))
    fig.update_yaxes(gridcolor=BORDER, zerolinecolor=BORDER, tickfont=dict(size=13))
    return fig
