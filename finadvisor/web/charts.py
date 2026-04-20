"""Server-rendered SVG chart builders.

Everything here returns a string of SVG markup (no JavaScript, no
external fonts, no third-party libraries) so the web UI stays
stdlib-only and works in Termux or any other minimal Python install.

Charts are intentionally plain — just enough visual grammar
(`<polyline>` per series, `<circle>` markers with a `<title>` tooltip,
a couple of gridlines, a legend) to read spending trajectories at a
glance without shipping a charting library.
"""
from __future__ import annotations

import html
from typing import Sequence


# A small, color-blind-friendly palette. First slot is for the
# headline "Total" line so it pops against the others.
PALETTE = ("#2563eb", "#059669", "#d97706", "#9333ea", "#dc2626", "#0891b2")


def _esc(s) -> str:
    return html.escape(str(s), quote=True)


def _nice_max(v: float) -> float:
    """Round `v` up to a visually clean gridline ceiling."""
    if v <= 0:
        return 1.0
    # e.g. 1347 → 1500, 420 → 500, 8.3 → 10
    import math
    exp = math.floor(math.log10(v))
    step = 10 ** exp
    for m in (1, 1.25, 1.5, 2, 2.5, 3, 4, 5, 7.5, 10):
        cand = m * step
        if cand >= v:
            return cand
    return 10 * step


def _fmt_y(v: float) -> str:
    """Short labels: 1234 → '$1.2k', 850 → '$850'."""
    if v >= 1_000_000:
        return f"${v / 1_000_000:.1f}M"
    if v >= 1_000:
        return f"${v / 1_000:.1f}k"
    return f"${v:,.0f}"


def render_line_chart(
    series: dict[str, list[tuple[str, float]]],
    width: int = 720,
    height: int = 260,
    title: str = "",
) -> str:
    """Build a multi-series line chart.

    `series` maps a label → ordered [(month, amount), ...] points. All
    series must share the same X-axis month set (missing points are
    interpolated as 0).
    """
    if not series:
        return ""

    # Union of all months across series, sorted.
    months: list[str] = sorted({
        m for points in series.values() for m, _ in points
    })
    if not months:
        return ""

    # Build a dense lookup so each series contributes a y per month.
    dense: dict[str, list[float]] = {}
    for label, points in series.items():
        lookup = dict(points)
        dense[label] = [float(lookup.get(m, 0.0)) for m in months]

    all_values = [v for vs in dense.values() for v in vs]
    y_max = _nice_max(max(all_values) if all_values else 1.0)

    # Layout. Leave room on the left for Y labels and below for X ticks.
    pad_left = 54
    pad_right = 12
    pad_top = 14
    pad_bottom = 30
    plot_w = max(10, width - pad_left - pad_right)
    plot_h = max(10, height - pad_top - pad_bottom)

    def sx(i: int) -> float:
        if len(months) == 1:
            return pad_left + plot_w / 2
        return pad_left + (i / (len(months) - 1)) * plot_w

    def sy(v: float) -> float:
        return pad_top + (1 - v / y_max) * plot_h

    # Gridlines (4 horizontal lines at 0/25/50/75/100% of y_max).
    grid_bits: list[str] = []
    for i in range(5):
        frac = i / 4
        y = pad_top + (1 - frac) * plot_h
        value = y_max * frac
        grid_bits.append(
            f'<line x1="{pad_left}" y1="{y:.1f}" '
            f'x2="{pad_left + plot_w}" y2="{y:.1f}" '
            f'stroke="#e5e7eb" stroke-width="1"/>'
        )
        grid_bits.append(
            f'<text x="{pad_left - 6}" y="{y + 4:.1f}" '
            f'text-anchor="end" font-size="10" fill="#6b7280">'
            f'{_esc(_fmt_y(value))}</text>'
        )

    # X-axis month ticks.
    tick_bits: list[str] = []
    for i, m in enumerate(months):
        x = sx(i)
        tick_bits.append(
            f'<text x="{x:.1f}" y="{pad_top + plot_h + 16}" '
            f'text-anchor="middle" font-size="10" fill="#374151">'
            f'{_esc(m)}</text>'
        )

    # Series — polyline + per-point circle with a <title> tooltip.
    series_bits: list[str] = []
    legend_bits: list[str] = []
    for idx, (label, values) in enumerate(dense.items()):
        color = PALETTE[idx % len(PALETTE)]
        pts = " ".join(f"{sx(i):.1f},{sy(v):.1f}" for i, v in enumerate(values))
        # Total gets a beefier stroke so it visually dominates.
        stroke_w = 2.5 if label.lower() == "total" else 1.75
        series_bits.append(
            f'<polyline fill="none" stroke="{color}" '
            f'stroke-width="{stroke_w}" stroke-linejoin="round" '
            f'stroke-linecap="round" points="{pts}"/>'
        )
        for i, v in enumerate(values):
            tooltip = f"{label} · {months[i]} · {_fmt_y(v)}"
            series_bits.append(
                f'<circle cx="{sx(i):.1f}" cy="{sy(v):.1f}" r="3" '
                f'fill="white" stroke="{color}" stroke-width="1.5">'
                f'<title>{_esc(tooltip)}</title></circle>'
            )
        # Legend row: colored swatch + label.
        legend_bits.append(
            f'<span style="display:inline-flex;align-items:center;'
            f'gap:6px;margin-right:14px;font-size:12px;color:#374151">'
            f'<span style="display:inline-block;width:14px;height:3px;'
            f'background:{color};border-radius:2px"></span>'
            f'{_esc(label)}</span>'
        )

    title_html = (
        f'<div style="font-size:13px;font-weight:600;color:#111827;'
        f'margin-bottom:4px">{_esc(title)}</div>' if title else ""
    )
    svg = (
        f'<svg viewBox="0 0 {width} {height}" width="100%" '
        f'height="{height}" role="img" '
        f'style="max-width:100%;height:auto;display:block">'
        + "".join(grid_bits)
        + "".join(series_bits)
        + "".join(tick_bits)
        + "</svg>"
    )
    return (
        f'<div>{title_html}'
        f'<div style="margin-bottom:6px">{"".join(legend_bits)}</div>'
        f'{svg}</div>'
    )


def render_sparkline(
    values: Sequence[float], width: int = 120, height: int = 28,
    color: str = "#2563eb",
) -> str:
    """Tiny inline trend indicator — a single polyline scaled to the
    values' own min/max. Used next to category rows on /trends."""
    vs = list(values)
    if not vs:
        return ""
    lo, hi = min(vs), max(vs)
    span = max(hi - lo, 1e-9)
    if len(vs) == 1:
        points = f"0,{height / 2:.1f} {width},{height / 2:.1f}"
    else:
        points = " ".join(
            f"{(i / (len(vs) - 1)) * width:.1f},"
            f"{height - ((v - lo) / span) * height:.1f}"
            for i, v in enumerate(vs)
        )
    return (
        f'<svg viewBox="0 0 {width} {height}" width="{width}" '
        f'height="{height}" preserveAspectRatio="none" '
        f'style="display:block">'
        f'<polyline fill="none" stroke="{_esc(color)}" stroke-width="1.5" '
        f'stroke-linejoin="round" stroke-linecap="round" '
        f'points="{points}"/>'
        f"</svg>"
    )
