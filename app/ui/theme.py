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
MUTED = "#63738a"   # darkened to clear WCAG AA on the page background
FAINT = "#637895"   # AA-compliant; the old value was 2.56:1

# semantic
PRIMARY = "#2563eb"
LOSS = "#dc2626"
WARN = "#b16105"
GAIN = "#05875f"
VIOLET = "#7c3aed"

STATUS_COLORS = {
    "SUCCESS": "#cbd5e1",
    "OOM_KILLED": LOSS,
    "DRIVER_CRASH": VIOLET,
    "TIMEOUT": WARN,
}

FONT = ('Inter, -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, '
        '"Helvetica Neue", Arial, sans-serif')
MONO = 'ui-monospace, SFMono-Regular, "SF Mono", Menlo, Consolas, monospace'

# Type scale (px) and a 4px vertical rhythm: every size and gap is drawn from
# these, so nothing is picked ad hoc.
SCALE = {"xs": 11.5, "sm": 12.5, "base": 14.5, "md": 15, "lg": 20, "xl": 28, "2xl": 40}

CSS = f"""
<style>
    /* Streamlit strips <link> tags from markdown HTML, so the webfont has to be
       pulled in from inside the stylesheet. @import must stay the first rule. */
    @import url('https://fonts.googleapis.com/css2?family=Inter:opsz,wght@14..32,400;14..32,500;14..32,600;14..32,700&display=swap');

    :root {{
        --s1: 4px;  --s2: 8px;  --s3: 12px; --s4: 16px;
        --s5: 24px; --s6: 32px; --s7: 48px;
    }}
    [data-testid="stAppViewContainer"] {{ background-color: {BG}; }}
    [data-testid="stHeader"] {{ background: transparent; }}
    .block-container {{ max-width: 1080px; padding-top: var(--s5); padding-bottom: 128px; }}

    html, body, [data-testid="stAppViewContainer"] *,
    [data-testid="stSidebar"] * {{
        font-family: {FONT} !important;
        color: {INK};
        font-size: {SCALE["md"]}px;
        -webkit-font-smoothing: antialiased;
        -moz-osx-font-smoothing: grayscale;
        font-feature-settings: "cv05" 1, "ss01" 1;
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
    .cards {{ display: grid; grid-template-columns: 1.35fr 1fr 1fr 1fr; gap: var(--s3); }}
    .card {{
        background: {SURFACE}; border: 1px solid {BORDER};
        border-radius: 10px; padding: var(--s4);
        transition: border-color .16s ease, box-shadow .16s ease;
    }}
    .card:hover {{ border-color: {BORDER_STRONG}; }}
    .card.lead {{ border-color: {BORDER_STRONG}; box-shadow: 0 1px 2px rgba(16,24,40,.05); }}
    .metric-k {{
        font-size: 11.5px; font-weight: 600; letter-spacing: .4px;
        text-transform: uppercase; color: {MUTED};
    }}
    .metric-v {{
        font-size: {SCALE["xl"]}px; font-weight: 650;
        letter-spacing: -1.1px; margin-top: var(--s1);
        line-height: 1.15;
    }}
    .card.lead .metric-v {{ font-size: {SCALE["2xl"]}px; letter-spacing: -1.8px; }}
    .metric-d {{ font-size: 12.5px; color: {MUTED}; margin-top: 4px; }}

    .srow {{
        display: flex; align-items: center; gap: var(--s3);
        padding: 9px 0; border-bottom: 1px solid {BORDER};
        font-size: 14px;
    }}
    .srow:last-of-type {{ border-bottom: none; }}
    .sseq {{ font-weight: 600; min-width: 210px; }}
    .sbar {{ width: 8px; height: 8px; border-radius: 50%; flex: none; }}
    .sfact {{ flex: 1; }}
    .sdead {{ color: {MUTED}; font-variant-numeric: tabular-nums; }}
    .snote {{ font-size: 12.5px; color: {MUTED}; margin-top: var(--s3); line-height: 1.55; }}
    @media (max-width: 640px) {{
        .srow {{ flex-wrap: wrap; }}
        .sseq {{ min-width: 100%; }}
    }}

    .verif {{
        display: flex; align-items: center; gap: var(--s2);
        background: {SURFACE}; border: 1px solid {BORDER};
        border-left: 3px solid {GAIN};
        border-radius: 8px; padding: 10px var(--s4); margin: var(--s3) 0;
        font-size: 13.5px; color: {INK};
    }}
    .vdot {{ width: 7px; height: 7px; border-radius: 50%; flex: none; }}

    .lead {{
        font-size: 14px; color: {MUTED}; line-height: 1.6;
        margin: -4px 0 var(--s3) 0; max-width: 720px;
    }}

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

    /* ---- focus, keyboard, touch targets ---- */
    /* every interactive control gets the same visible focus ring, and only when
       reached by keyboard - mouse users do not see it */
    .stButton > button:focus-visible,
    [data-testid="stExpander"] summary:focus-visible,
    [data-testid="stChatInput"] textarea:focus-visible,
    a:focus-visible {{
        outline: 2px solid {PRIMARY};
        outline-offset: 2px;
        border-radius: 8px;
    }}
    .stButton > button:active {{ transform: translateY(1px); }}
    /* WCAG 2.5.5: pointer targets stay at least 44px tall */
    .stButton > button {{ min-height: 44px; }}
    [data-testid="stExpander"] summary {{ min-height: 44px; display: flex; align-items: center; }}

    /* ---- loading skeletons ---- */
    .skel {{
        background: linear-gradient(90deg, #eef1f5 25%, #f6f8fa 37%, #eef1f5 63%);
        background-size: 400% 100%;
        animation: shimmer 1.4s ease-in-out infinite;
        border-radius: 6px;
    }}
    @keyframes shimmer {{ from {{ background-position: 100% 0; }} to {{ background-position: -100% 0; }} }}
    .skel-v {{ height: 30px; width: 70%; margin-top: var(--s1); }}
    .skel-d {{ height: 12px; width: 55%; margin-top: var(--s2); }}

    /* content settles in rather than popping */
    .cards, .callout, .wfbox, [data-testid="stChatMessage"] {{
        animation: rise .34s cubic-bezier(.16,.84,.44,1) both;
    }}
    @keyframes rise {{ from {{ opacity: 0; transform: translateY(6px); }} }}

    .wfbox {{
        background: {SURFACE}; border: 1px solid {BORDER};
        border-radius: 10px; padding: var(--s3) var(--s4) var(--s2);
        margin: var(--s3) 0;
    }}

    @media (prefers-reduced-motion: reduce) {{
        .cards, .callout, .wfbox, [data-testid="stChatMessage"], .skel {{
            animation: none;
        }}
        .stButton > button:active {{ transform: none; }}
    }}
    @media (max-width: 860px) {{
        .cards {{ grid-template-columns: repeat(2, 1fr); }}
        .block-container {{ padding-left: var(--s4); padding-right: var(--s4); }}
    }}
    @media (max-width: 560px) {{
        .cards {{ grid-template-columns: 1fr; gap: var(--s2); }}
        .card.lead .metric-v {{ font-size: {SCALE["xl"]}px; letter-spacing: -1px; }}
        .metric-v {{ font-size: {SCALE["lg"]}px; }}
        .topbar {{ flex-direction: column; align-items: flex-start; gap: var(--s2); }}
        .step {{ font-size: 12px; }}
        /* the pipeline is wider than a phone: let it scroll rather than shrink
           the labels into illegibility, and fade the edge so it reads as scrollable */
        .wfbox {{
            overflow-x: auto;
            -webkit-overflow-scrolling: touch;
            background:
                linear-gradient(90deg, {SURFACE} 30%, rgba(255,255,255,0)) left / 24px 100% no-repeat,
                linear-gradient(270deg, {SURFACE} 30%, rgba(255,255,255,0)) right / 24px 100% no-repeat,
                {SURFACE};
            background-attachment: local, local, scroll;
        }}
        .wfbox svg {{ min-width: 720px; }}
    }}
</style>
"""


def plotly_layout(fig, height=300, title=None, grid="y"):
    """Low-ink chart styling: no chrome, one axis of gridlines at most."""
    fig.update_layout(
        height=height,
        title=dict(text=title, font=dict(size=SCALE["base"], color=MUTED),
                   x=0, xanchor="left", y=0.97) if title else None,
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        font=dict(color=INK, size=13, family=FONT),
        margin=dict(l=4, r=8, t=38 if title else 6, b=28),
        showlegend=False,          # series are labelled directly instead
        hoverlabel=dict(bgcolor=SURFACE, bordercolor=BORDER, font_size=13,
                        font_family=FONT),
        hovermode="x unified",
        transition=dict(duration=280, easing="cubic-in-out"),
    )
    fig.update_xaxes(showgrid=False, zeroline=False, showline=False,
                     ticks="", tickfont=dict(size=12, color=MUTED))
    fig.update_yaxes(showgrid=(grid == "y"), gridcolor="#eef1f5", zeroline=False,
                     showline=False, ticks="", tickfont=dict(size=12, color=MUTED))
    return fig


def annotate(fig, x, y, text, color=INK, dy=-18):
    """Label a series where it lives, instead of in a legend."""
    fig.add_annotation(x=x, y=y, text=text, showarrow=False, yshift=-dy,
                       font=dict(size=12.5, color=color, family=FONT))
    return fig
