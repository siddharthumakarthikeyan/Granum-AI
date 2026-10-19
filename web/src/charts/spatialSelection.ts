import { compileRegion, insideCompiled } from "../store/geometry";
import type { Point } from "../store/types";
import type { Tool } from "./spec";

/** Select projected point centres at all visible depths, including overlapping points.
 * Projection is supplied by the same viewport that renders the chart. */
export function spatialHits(points: { index: number; screen: number[] }[], path: Point[], tool: Tool): number[] {
  if (!path.length) return [];
  const a = path[0]!, b = path[path.length - 1]!;
  const polygon: Point[] = tool === "rect" ? [a, [b[0], a[1]], b, [a[0], b[1]]] : path;
  const region = compileRegion({ mode: "add", polygon });
  return points.filter(({ screen: [x = NaN, y = NaN, z = NaN] }) => {
    if (![x, y, z].every(Number.isFinite) || z < 0 || z > 1) return false;
    if (tool !== "brush") return polygon.length >= 3 && insideCompiled(region, x, y);
    // Continuous brush strokes leave no gaps between pointer events.
    for (let i = 0; i < path.length; i++) {
      const from = path[Math.max(0, i - 1)]!, to = path[i]!;
      const dx = to[0] - from[0], dy = to[1] - from[1];
      const t = Math.min(1, Math.max(0, ((x - from[0]) * dx + (y - from[1]) * dy) / (dx * dx + dy * dy || 1)));
      if ((x - from[0] - t * dx) ** 2 + (y - from[1] - t * dy) ** 2 <= 14 ** 2) return true;
    }
    return false;
  }).map(p => p.index);
}
