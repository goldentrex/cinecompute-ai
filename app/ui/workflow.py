"""Live pipeline diagram.

Renders the agent loop as an SVG whose nodes light up while the turn is running:
the question reaches Gemini, Gemini writes SQL that goes out as an MCP tools/call,
ClickHouse answers, and the loop either repeats or produces the analysis. The UI re-renders
this into a placeholder from the tool callback, so it animates as work happens.
"""

from app.ui import theme

# phase -> (index of the active node, caption)
PHASES = {
    "idle":      (-1, "Every question travels this path - no pre-written SQL anywhere"),
    "thinking":  (1, "Gemini is deciding what to ask"),
    "querying":  (3, "ClickHouse is executing the query"),
    "answering": (4, "Composing the analysis"),
    "done":      (5, "Done"),
}

NODES = [
    ("Question", "the ask"),
    ("Gemini", "writes SQL"),
    ("MCP server", "mcp-clickhouse"),
    ("ClickHouse", "250k events"),
    ("Analysis", "cause · cost · fix"),
]

W, H = 1000, 132
PAD_X, NODE_W, NODE_H = 8, 178, 58
GAP = (W - 2 * PAD_X - len(NODES) * NODE_W) / (len(NODES) - 1)
NODE_Y = 30


def _x(i):
    return PAD_X + i * (NODE_W + GAP)


def render(phase="idle", queries=0, total_ms=0.0, last_label=""):
    """Return the SVG for the given loop state."""
    active, caption = PHASES.get(phase, PHASES["idle"])
    running = phase not in ("idle", "done")

    parts = [
        f'<svg viewBox="0 0 {W} {H}" width="100%" role="img" '
        f'aria-label="Agent pipeline, {caption}" style="display:block">',
        f"""<style>
        .wf-node {{ fill: {theme.SURFACE}; stroke: {theme.BORDER}; stroke-width: 1.5; }}
        .wf-node.on {{ stroke: {theme.PRIMARY}; stroke-width: 2; }}
        .wf-node.past {{ stroke: {theme.BORDER_STRONG}; }}
        .wf-t {{ font: 600 15px {theme.FONT}; fill: {theme.INK}; }}
        .wf-s {{ font: 400 11.5px {theme.FONT}; fill: {theme.FAINT}; }}
        .wf-t.on {{ fill: {theme.PRIMARY}; }}
        .wf-link {{ stroke: {theme.BORDER_STRONG}; stroke-width: 1.5; fill: none; }}
        .wf-link.past {{ stroke: {theme.PRIMARY}; stroke-opacity: .45; }}
        .wf-flow {{
            stroke: {theme.PRIMARY}; stroke-width: 2.5; fill: none;
            stroke-dasharray: 7 11; stroke-linecap: round;
            animation: wfdash 1s linear infinite;
        }}
        @keyframes wfdash {{ to {{ stroke-dashoffset: -18; }} }}
        .wf-halo {{ fill: none; stroke: {theme.PRIMARY}; stroke-width: 2;
                    animation: wfpulse 1.6s ease-out infinite; }}
        @keyframes wfpulse {{
            0%   {{ stroke-opacity: .55; transform: scale(1); }}
            70%  {{ stroke-opacity: 0;   transform: scale(1.035); }}
            100% {{ stroke-opacity: 0;   transform: scale(1.035); }}
        }}
        .wf-cap {{ font: 500 12.5px {theme.FONT}; fill: {theme.MUTED}; }}
        .wf-badge {{ font: 600 11px {theme.MONO}; fill: {theme.GAIN}; }}
        @media (prefers-reduced-motion: reduce) {{
            .wf-flow, .wf-halo {{ animation: none; }}
        }}
        </style>""",
    ]

    # connectors
    for i in range(len(NODES) - 1):
        x1 = _x(i) + NODE_W
        x2 = _x(i + 1)
        y = NODE_Y + NODE_H / 2
        mid = (x1 + x2) / 2
        d = f"M {x1} {y} C {mid} {y}, {mid} {y}, {x2} {y}"
        done_link = active > i
        parts.append(f'<path d="{d}" class="wf-link{" past" if done_link else ""}"/>')
        if running and active == i + 1:
            parts.append(f'<path d="{d}" class="wf-flow"/>')

    # nodes
    for i, (title, sub) in enumerate(NODES):
        x, is_on = _x(i), (i == active)
        state = "on" if is_on else ("past" if i < active else "")
        parts.append(
            f'<rect x="{x}" y="{NODE_Y}" width="{NODE_W}" height="{NODE_H}" rx="9" '
            f'class="wf-node {state}"/>'
        )
        if is_on and running:
            parts.append(
                f'<rect x="{x}" y="{NODE_Y}" width="{NODE_W}" height="{NODE_H}" rx="9" '
                f'class="wf-halo" style="transform-origin:{x + NODE_W / 2}px {NODE_Y + NODE_H / 2}px"/>'
            )
        parts.append(
            f'<text x="{x + 16}" y="{NODE_Y + 25}" class="wf-t {"on" if is_on else ""}">{title}</text>'
            f'<text x="{x + 16}" y="{NODE_Y + 43}" class="wf-s">{sub}</text>'
        )

    caption_txt = last_label or caption
    parts.append(f'<text x="{PAD_X}" y="{H - 10}" class="wf-cap">{caption_txt}</text>')
    if queries:
        parts.append(
            f'<text x="{W - PAD_X}" y="{H - 10}" text-anchor="end" class="wf-badge">'
            f'{queries} quer{"y" if queries == 1 else "ies"} · {total_ms:.0f} ms via MCP</text>'
        )
    parts.append("</svg>")
    return "".join(parts)
