import html
from datetime import date, timedelta

from app.config import PALETTE
from app.stats import SHOW_DAYS, load_stats


def chart_svg(title: str, labels: list, series: dict, zero_base: bool) -> str:
    """series: {user: [value or None for each label]}"""
    head = f"<h2>{html.escape(title)}"
    allv = [v for vals in series.values() for v in vals if v is not None]
    if not allv:
        return f"<div class='chart'>{head}</h2><p class='msg'>No data yet.</p></div>"
    W, H, L, R, T, B = 320, 150, 34, 12, 14, 26
    real_hi, real_lo = max(allv), (0 if zero_base else min(allv))
    lo, hi = real_lo, (real_hi if real_hi != real_lo else real_lo + 1)
    n = len(labels)

    def x(i: int) -> float:
        return L + (W - L - R) * (i / (n - 1) if n > 1 else 0.5)

    def y(v: float) -> float:
        return T + (H - T - B) * (1 - (v - lo) / (hi - lo))

    lines = legend = ""
    total = 0
    for k, (user, vals) in enumerate(sorted(series.items())):
        color = PALETTE[k % len(PALETTE)]
        pts = [(i, v) for i, v in enumerate(vals) if v is not None]
        if len(pts) > 1:
            path = " ".join(f"{x(i):.1f},{y(v):.1f}" for i, v in pts)
            lines += f"<polyline points='{path}' style='stroke:{color}'/>"
        lines += "".join(
            f"<circle cx='{x(i):.1f}' cy='{y(v):.1f}' r='3' style='fill:{color}'/>"
            for i, v in pts
        )
        last = vals[-1] if vals and vals[-1] is not None else 0
        total += last
        legend += f"<span style='--c:{color}'>{html.escape(user)} {last}</span>"
    xl = "".join(
        f"<text x='{x(i):.1f}' y='{H - 8}' text-anchor='middle'>{html.escape(t)}</text>"
        for i, t in enumerate(labels)
    )
    ylab = f"<text x='{L - 6}' y='{y(real_lo) + 3:.1f}' text-anchor='end'>{real_lo}</text>"
    if real_hi != real_lo:
        ylab += f"<text x='{L - 6}' y='{y(real_hi) + 3:.1f}' text-anchor='end'>{real_hi}</text>"
    return (
        f"<div class='chart'>{head}<b>total {total}</b></h2>"
        f"<svg viewBox='0 0 {W} {H}' role='img' aria-label='{html.escape(title)}'>"
        f"<line class='axis' x1='{L}' y1='{y(real_lo):.1f}' x2='{W - R}' y2='{y(real_lo):.1f}'/>"
        f"{ylab}{lines}{xl}</svg><div class='legend'>{legend}</div></div>"
    )


def stats_html() -> str:
    stats = load_stats()
    cutoff = (date.today() - timedelta(days=SHOW_DAYS - 1)).isoformat()
    days = [d for d in sorted(stats) if d >= cutoff]
    labels = [d[5:] for d in days]
    names = sorted({u for d in days for u in stats[d].get("users", {})})

    def series(key: str) -> dict:
        return {
            u: [stats[d].get("users", {}).get(u, {}).get(key) for d in days]
            for u in names
        }

    return (
        chart_svg("Cards studied", labels, series("learned"), False)
        + chart_svg("Cards due", labels, series("due"), True)
        + "<p class='msg'>One line per user, last 7 days. Updated hourly; each day keeps its latest reading.</p>"
    )