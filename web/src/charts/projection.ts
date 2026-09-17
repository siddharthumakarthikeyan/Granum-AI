/** Screen <-> data coordinates for a scatter chart.
 *
 * Points are uploaded in a normalised [0, 1] world so each axis can zoom independently
 * without Float32 precision trouble on large values. This mirrors deck.gl's
 * OrthographicViewport with `flipY: false`: one world unit is `2 ** zoom` pixels and
 * y grows upward. Selections are converted back to data coordinates before they are
 * stored, so they stay put when the chart is panned.
 */

import type { Point } from "../store/types";

export interface ViewState {
  target: [number, number];
  zoomX: number;
  zoomY: number;
}

export interface Frame {
  width: number;
  height: number;
  xDomain: [number, number];
  yDomain: [number, number];
  view: ViewState;
}

export function normalise(value: number, domain: [number, number]): number {
  return (value - domain[0]) / (domain[1] - domain[0]);
}

export function dataToScreen(frame: Frame, x: number, y: number): Point {
  const { width, height, view } = frame;
  const nx = normalise(x, frame.xDomain);
  const ny = normalise(y, frame.yDomain);
  return [
    width / 2 + (nx - view.target[0]) * 2 ** view.zoomX,
    height / 2 - (ny - view.target[1]) * 2 ** view.zoomY,
  ];
}

export function screenToData(frame: Frame, sx: number, sy: number): Point {
  const { width, height, view, xDomain, yDomain } = frame;
  const nx = view.target[0] + (sx - width / 2) / 2 ** view.zoomX;
  const ny = view.target[1] - (sy - height / 2) / 2 ** view.zoomY;
  return [
    xDomain[0] + nx * (xDomain[1] - xDomain[0]),
    yDomain[0] + ny * (yDomain[1] - yDomain[0]),
  ];
}

/** A view showing the normalised box [x0, x1] x [y0, y1] with a small margin. */
export function fitView(
  width: number,
  height: number,
  box: { x0: number; x1: number; y0: number; y1: number } = { x0: 0, x1: 1, y0: 0, y1: 1 },
  padding = 0.06,
): ViewState {
  const spanX = Math.max(box.x1 - box.x0, 1e-9) * (1 + padding * 2);
  const spanY = Math.max(box.y1 - box.y0, 1e-9) * (1 + padding * 2);
  return {
    target: [(box.x0 + box.x1) / 2, (box.y0 + box.y1) / 2],
    zoomX: Math.log2(Math.max(width, 1) / spanX),
    zoomY: Math.log2(Math.max(height, 1) / spanY),
  };
}

/** Round tick values covering [lo, hi], about `count` of them. */
export function niceTicks(lo: number, hi: number, count = 5): number[] {
  if (!Number.isFinite(lo) || !Number.isFinite(hi) || hi <= lo) return [];
  const raw = (hi - lo) / Math.max(1, count);
  const magnitude = 10 ** Math.floor(Math.log10(raw));
  const residual = raw / magnitude;
  const step = (residual > 5 ? 10 : residual > 2 ? 5 : residual > 1 ? 2 : 1) * magnitude;
  const out: number[] = [];
  for (let v = Math.ceil(lo / step) * step; v <= hi + step * 1e-9; v += step) {
    out.push(Math.abs(v) < step * 1e-9 ? 0 : v);
    if (out.length > 50) break;
  }
  return out;
}

export function formatTick(value: number): string {
  const abs = Math.abs(value);
  if (abs !== 0 && (abs >= 1e5 || abs < 1e-3)) return value.toExponential(1);
  return String(Number(value.toPrecision(4)));
}
