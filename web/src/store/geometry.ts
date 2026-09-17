/** Point-in-region tests for chart selections.
 *
 * These run once per row per filter evaluation, so at a million rows the cost is the
 * whole story: each polygon is compiled once (bounding box plus flat coordinates) and
 * most points are rejected by the box before the ray cast runs.
 */

import type { Point, Region } from "./types";

export interface CompiledRegion {
  add: boolean;
  xs: Float64Array;
  ys: Float64Array;
  minX: number;
  maxX: number;
  minY: number;
  maxY: number;
}

export function compileRegion(region: Region): CompiledRegion {
  const count = region.polygon.length;
  const xs = new Float64Array(count);
  const ys = new Float64Array(count);
  let minX = Infinity;
  let maxX = -Infinity;
  let minY = Infinity;
  let maxY = -Infinity;
  region.polygon.forEach(([x, y], i) => {
    xs[i] = x;
    ys[i] = y;
    if (x < minX) minX = x;
    if (x > maxX) maxX = x;
    if (y < minY) minY = y;
    if (y > maxY) maxY = y;
  });
  return { add: region.mode === "add", xs, ys, minX, maxX, minY, maxY };
}

/** Even-odd ray cast. Points exactly on an edge may fall either way. */
export function insideCompiled(region: CompiledRegion, x: number, y: number): boolean {
  if (x < region.minX || x > region.maxX || y < region.minY || y > region.maxY) return false;
  const { xs, ys } = region;
  let inside = false;
  for (let i = 0, j = xs.length - 1; i < xs.length; j = i, i += 1) {
    const yi = ys[i]!;
    const yj = ys[j]!;
    if (yi > y !== yj > y) {
      const cross = ((xs[j]! - xs[i]!) * (y - yi)) / (yj - yi) + xs[i]!;
      if (x < cross) inside = !inside;
    }
  }
  return inside;
}

export function pointInPolygon(polygon: Point[], x: number, y: number): boolean {
  if (polygon.length < 3) return false;
  return insideCompiled(compileRegion({ mode: "add", polygon }), x, y);
}

const compiledCache = new WeakMap<Region[], CompiledRegion[]>();

export function compileRegions(regions: Region[]): CompiledRegion[] {
  let compiled = compiledCache.get(regions);
  if (!compiled) {
    compiled = regions.filter((r) => r.polygon.length >= 3).map(compileRegion);
    compiledCache.set(regions, compiled);
  }
  return compiled;
}

/** Apply regions in order, like paint strokes.
 *
 * Starting state depends on the first stroke: if it adds, everything starts outside;
 * if it subtracts, everything starts inside -- "shift-drag to remove this corner" on
 * an empty selection means "everything except this corner".
 */
export function insideRegions(compiled: CompiledRegion[], x: number, y: number): boolean {
  if (compiled.length === 0) return true;
  if (!Number.isFinite(x) || !Number.isFinite(y)) return false;
  let state = !compiled[0]!.add;
  for (const region of compiled) {
    if (state === region.add) continue; // this stroke cannot change the answer
    if (insideCompiled(region, x, y)) state = region.add;
  }
  return state;
}

/** A circle as a polygon -- brush dabs are stored as ordinary regions. */
export function ellipsePolygon(cx: number, cy: number, rx: number, ry: number, sides = 14): Point[] {
  const out: Point[] = [];
  for (let i = 0; i < sides; i += 1) {
    const angle = (i / sides) * Math.PI * 2;
    out.push([cx + Math.cos(angle) * rx, cy + Math.sin(angle) * ry]);
  }
  return out;
}

/** Drop vertices closer than `spacing` to the previous kept one. A freehand lasso
 * produces hundreds of near-duplicate points, and every one costs a ray-cast step. */
export function simplifyPath(points: Point[], spacing: number): Point[] {
  if (points.length <= 3) return points;
  const out: Point[] = [points[0]!];
  const limit = spacing * spacing;
  for (let i = 1; i < points.length; i += 1) {
    const [px, py] = out[out.length - 1]!;
    const [x, y] = points[i]!;
    if ((x - px) ** 2 + (y - py) ** 2 >= limit) out.push(points[i]!);
  }
  return out;
}
