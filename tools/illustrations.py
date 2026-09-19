#!/usr/bin/env python3
"""Draw the site's illustration charts as SVG files in public/assets/illustrations/.

They are illustrations of what Granum shows, drawn from made-up numbers with the app's
colours, not measured results; every page that uses one captions it "Illustration".
Pages show them as <img> inside <figure data-chart>; site.js swaps each for the inline SVG and
marks the figure .pre, then .in when it scrolls into view, so the chart animates in. Without the
script (or inside an <img>) nothing matches .pre and the chart is drawn complete.

    python tools/illustrations.py
"""

from __future__ import annotations

import math
import random
from pathlib import Path

OUT = Path(__file__).resolve().parents[1] / "public" / "assets" / "illustrations"

EARLY, MID, LATE = "#9fe0bc", "#5bb58a", "#2f7d5c"
UNSTABLE, NEVER = "#e3aa4a", "#ec6f8b"
CYAN, GREY = "#22d3ee", "#6c757f"
GRID, AXIS, TEXT, TEXT2 = "#20242b", "#2e333b", "#9aa3ad", "#6c757f"

STYLE = f"""<style>
  .t {{ font-family: 'Instrument Sans', system-ui, sans-serif; fill: {TEXT}; font-size: 12px; }}
  .m {{ font-family: 'JetBrains Mono', ui-monospace, monospace; fill: {TEXT2}; font-size: 11px; }}
  .h {{ font-family: 'Instrument Sans', system-ui, sans-serif; fill: #eceef1; font-size: 15px; font-weight: 700; }}
  .reveal {{ transition: clip-path 1.6s cubic-bezier(.2,.7,.2,1); }}
  .grow {{ transform-box: fill-box; transform-origin: left; transition: transform 1.1s cubic-bezier(.2,.7,.2,1); }}
  .fade {{ transition: opacity .6s ease 1.1s; }}
  .pre:not(.in) .reveal {{ clip-path: inset(0 100% 0 0); }}
  .pre:not(.in) .grow {{ transform: scaleX(0); }}
  .pre:not(.in) .fade {{ opacity: 0; }}
  @media (prefers-reduced-motion: reduce) {{ .reveal, .grow, .fade {{ transition: none; }} }}
</style>"""


def smooth(points: list[tuple[float, float]]) -> str:
    """A Catmull-Rom curve through the points, as SVG cubic segments."""
    d = f"M{points[0][0]:.1f},{points[0][1]:.1f}"
    for i in range(len(points) - 1):
        p0 = points[max(0, i - 1)]
        p1, p2 = points[i], points[i + 1]
        p3 = points[min(len(points) - 1, i + 2)]
        c1 = (p1[0] + (p2[0] - p0[0]) / 6, p1[1] + (p2[1] - p0[1]) / 6)
        c2 = (p2[0] - (p3[0] - p1[0]) / 6, p2[1] - (p3[1] - p1[1]) / 6)
        d += f" C{c1[0]:.1f},{c1[1]:.1f} {c2[0]:.1f},{c2[1]:.1f} {p2[0]:.1f},{p2[1]:.1f}"
    return d


def learning() -> str:
    """Share of images learned by each epoch, stacked by when they were learned."""
    w, h = 760, 380
    left, right, top, bottom = 56, 178, 34, 330
    epochs = 30
    shares = {"early": .46, "mid": .27, "late": .13, "unstable": .06, "never": .08}

    def cdf(e: float, start: float, end: float) -> float:
        if e <= start:
            return 0.0
        if e >= end:
            return 1.0
        x = (e - start) / (end - start)
        return x * x * (3 - 2 * x)

    xs = [left + (right_edge := w - right - left) * (e - 1) / (epochs - 1) for e in range(1, epochs + 1)]
    y = lambda v: bottom - (bottom - top) * v  # noqa: E731
    layers = []
    base = [0.0] * epochs
    specs = [("early", EARLY, 1, 6), ("mid", MID, 4, 16), ("late", LATE, 12, 29)]
    for name, colour, start, end in specs:
        tops = [base[i] + shares[name] * cdf(i + 1, start, end) for i in range(epochs)]
        upper = [(xs[i], y(tops[i])) for i in range(epochs)]
        lower = [(xs[i], y(base[i])) for i in range(epochs)][::-1]
        path = smooth(upper) + " L" + " L".join(f"{x:.1f},{yy:.1f}" for x, yy in lower) + " Z"
        layers.append(f'<path d="{path}" fill="{colour}" opacity=".92"/>')
        base = tops
    # Unstable images: learned, then lost again, a little each epoch.
    rng = random.Random(7)
    wobble = [shares["unstable"] * (0.25 + 0.55 * cdf(i + 1, 3, 12)) * (0.7 + 0.3 * math.sin(i * 1.3) + 0.1 * rng.random()) for i in range(epochs)]
    tops = [base[i] + wobble[i] for i in range(epochs)]
    upper = [(xs[i], y(tops[i])) for i in range(epochs)]
    lower = [(xs[i], y(base[i])) for i in range(epochs)][::-1]
    layers.append(f'<path d="{smooth(upper)} L{" L".join(f"{x:.1f},{yy:.1f}" for x, yy in lower)} Z" fill="{UNSTABLE}" opacity=".9"/>')

    grid = "".join(
        f'<line x1="{left}" x2="{w - right}" y1="{y(v):.1f}" y2="{y(v):.1f}" stroke="{GRID}"/>'
        f'<text class="m" x="{left - 10}" y="{y(v) + 4:.1f}" text-anchor="end">{int(v * 100)}%</text>'
        for v in (0, .25, .5, .75, 1)
    )
    ticks = "".join(f'<text class="m" x="{xs[e - 1]:.1f}" y="{bottom + 20}" text-anchor="middle">{e}</text>' for e in (1, 5, 10, 15, 20, 25, 30))
    legend_items = [("Learned early", EARLY, shares["early"]), ("Learned mid-training", MID, shares["mid"]),
                    ("Learned late", LATE, shares["late"]), ("Unstable", UNSTABLE, shares["unstable"]),
                    ("Never learned", NEVER, shares["never"])]
    legend = "".join(
        f'<g class="fade" transform="translate({w - right + 22},{top + 12 + i * 44})">'
        f'<rect width="10" height="10" y="-9" rx="2" fill="{c}"/>'
        f'<text class="t" x="18">{label}</text><text class="m" x="18" y="16">{int(v * 1000):,} images</text></g>'
        for i, (label, c, v) in enumerate(legend_items)
    )
    never_band = (f'<rect class="fade" x="{left}" y="{y(1):.1f}" width="{w - right - left}" height="{y(1 - shares["never"]) - y(1):.1f}" '
                  f'fill="{NEVER}" fill-opacity=".14"/><text class="m fade" x="{w - right - 8}" y="{y(1) + 15:.1f}" text-anchor="end" fill="{NEVER}" '
                  f'style="fill:{NEVER}">never learned</text>')
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {w} {h}" role="img" aria-label="Illustration: share of 1,000 training '
            f'images learned by each epoch, split into learned early, mid-training, late, unstable, and never learned">{STYLE}'
            f'{grid}{never_band}<g class="reveal">{"".join(layers)}</g>'
            f'<line x1="{left}" x2="{w - right}" y1="{bottom}" y2="{bottom}" stroke="{AXIS}"/>{ticks}'
            f'<text class="m" x="{(left + w - right) / 2:.0f}" y="{h - 8}" text-anchor="middle">epoch</text>{legend}</svg>')


def curves() -> str:
    """Validation mAP50 of two runs: before and after reviewing the data."""
    w, h = 760, 360
    left, right, top, bottom = 56, 120, 30, 310
    epochs = 40
    rng = random.Random(3)
    y = lambda v: bottom - (bottom - top) * v / 0.8  # noqa: E731
    x = lambda e: left + (w - right - left) * (e - 1) / (epochs - 1)  # noqa: E731

    def run(ceiling: float, rate: float, jitter: float) -> list[tuple[float, float]]:
        return [(x(e), y(ceiling * (1 - math.exp(-e / rate)) + rng.uniform(-jitter, jitter) * (1 - e / (epochs + 8)))) for e in range(1, epochs + 1)]

    before = run(0.58, 7.5, 0.018)
    after = run(0.69, 6.5, 0.014)
    grid = "".join(
        f'<line x1="{left}" x2="{w - right}" y1="{y(v):.1f}" y2="{y(v):.1f}" stroke="{GRID}"/>'
        f'<text class="m" x="{left - 10}" y="{y(v) + 4:.1f}" text-anchor="end">{v:.1f}</text>'
        for v in (0, .2, .4, .6, .8)
    )
    ticks = "".join(f'<text class="m" x="{x(e):.1f}" y="{bottom + 20}" text-anchor="middle">{e}</text>' for e in (1, 10, 20, 30, 40))
    area = smooth(after) + f" L{x(epochs):.1f},{bottom} L{x(1):.1f},{bottom} Z"
    end_b, end_a = before[-1], after[-1]
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {w} {h}" role="img" aria-label="Illustration: validation mAP50 over 40 '
            f'epochs for a run on the original labels and a higher run after reviewing the data">{STYLE}'
            f'<defs><linearGradient id="ga" x1="0" x2="0" y1="0" y2="1"><stop offset="0" stop-color="{CYAN}" stop-opacity=".28"/>'
            f'<stop offset="1" stop-color="{CYAN}" stop-opacity="0"/></linearGradient></defs>{grid}'
            f'<g class="reveal"><path d="{area}" fill="url(#ga)"/>'
            f'<path d="{smooth(before)}" fill="none" stroke="{GREY}" stroke-width="2.2" stroke-dasharray="5 4"/>'
            f'<path d="{smooth(after)}" fill="none" stroke="{CYAN}" stroke-width="2.6"/></g>'
            f'<line x1="{left}" x2="{w - right}" y1="{bottom}" y2="{bottom}" stroke="{AXIS}"/>{ticks}'
            f'<text class="m" x="{(left + w - right) / 2:.0f}" y="{h - 8}" text-anchor="middle">epoch</text>'
            f'<g class="fade"><circle cx="{end_a[0]:.1f}" cy="{end_a[1]:.1f}" r="4.5" fill="{CYAN}"/>'
            f'<text class="t" x="{end_a[0] + 12:.1f}" y="{end_a[1] - 4:.1f}" style="fill:#eceef1">After review</text>'
            f'<text class="m" x="{end_a[0] + 12:.1f}" y="{end_a[1] + 12:.1f}">run 2</text>'
            f'<circle cx="{end_b[0]:.1f}" cy="{end_b[1]:.1f}" r="4" fill="{GREY}"/>'
            f'<text class="t" x="{end_b[0] + 12:.1f}" y="{end_b[1] - 4:.1f}">Original labels</text>'
            f'<text class="m" x="{end_b[0] + 12:.1f}" y="{end_b[1] + 12:.1f}">run 1</text></g>'
            f'<text class="m" x="{left}" y="{top - 12}">validation mAP50</text></svg>')


def classes() -> str:
    """Per class: share of images learned, with the weakest classes at the top."""
    rows = [("tricycle", .41, .22, 94), ("bicycle", .48, .19, 312), ("awning-tricycle", .52, .17, 58),
            ("people", .63, .12, 840), ("motor", .71, .09, 1204), ("van", .79, .06, 690),
            ("pedestrian", .82, .05, 1690), ("truck", .86, .04, 420), ("car", .94, .02, 3210)]
    w, h = 760, 40 + len(rows) * 34
    left, right = 150, 90
    span = w - left - right
    out = []
    for i, (name, learned, never, count) in enumerate(rows):
        yy = 30 + i * 34
        weak = learned < 0.55
        out.append(
            f'<text class="t" x="{left - 14}" y="{yy + 14}" text-anchor="end" style="fill:{"#eceef1" if weak else TEXT};font-weight:{600 if weak else 400}">{name}</text>'
            f'<rect x="{left}" y="{yy}" width="{span}" height="20" rx="3" fill="#171a1f"/>'
            f'<rect class="grow" x="{left}" y="{yy}" width="{span * learned:.1f}" height="20" rx="3" fill="{MID}" style="transition-delay:{i * .06:.2f}s"/>'
            f'<rect class="grow" x="{left + span * (1 - never):.1f}" y="{yy}" width="{span * never:.1f}" height="20" rx="3" fill="{NEVER}" '
            f'style="transition-delay:{.4 + i * .06:.2f}s"/>'
            f'<text class="m fade" x="{w - right + 12}" y="{yy + 14}">{int(learned * 100)}%</text>'
        )
    legend = (f'<g class="fade" transform="translate({left},{h - 6})"><rect width="10" height="10" y="-9" rx="2" fill="{MID}"/>'
              f'<text class="m" x="16">learned</text><rect x="92" width="10" height="10" y="-9" rx="2" fill="{NEVER}"/>'
              f'<text class="m" x="108">never learned</text></g>')
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {w} {h + 10}" role="img" aria-label="Illustration: share of images '
            f'learned per class; tricycle, bicycle and awning-tricycle are the weakest">{STYLE}'
            f'<text class="m" x="{left}" y="14">share of images learned, by class</text>{"".join(out)}{legend}</svg>')


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    for name, draw in (("learning", learning), ("curves", curves), ("classes", classes)):
        (OUT / f"{name}.svg").write_text(draw())
        print(OUT / f"{name}.svg")


if __name__ == "__main__":
    main()
