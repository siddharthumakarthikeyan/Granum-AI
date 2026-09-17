/** Derived views over the loaded rows, memoized by input identity.
 *
 * Every panel asks "which rows are visible?" on every store change -- a selection
 * click included. At 80k rows that was a full filter and sort per click per panel. The
 * store replaces `rows`, `filters` and `sort` immutably, so reference equality is an
 * exact cache key.
 */

import type { Row } from "../api/types";
import { filterRows, isActive, sortRows } from "./filtering";
import { sessionKeyFor } from "./session";
import type { Filter, SortKey } from "./types";

export { numericVector } from "./vectors";

let visibleCache: {
  rows: Row[];
  filters: Record<string, Filter>;
  sort: SortKey[];
  session: number;
  result: number[];
} | null = null;

export function visibleIndices(
  rows: Row[],
  filters: Record<string, Filter>,
  sort: SortKey[],
): number[] {
  const hit = visibleCache;
  const session = sessionKeyFor(Object.values(filters));
  if (hit && hit.rows === rows && hit.filters === filters && hit.sort === sort && hit.session === session) {
    return hit.result;
  }
  const result = sortRows(rows, filterRows(rows, Object.values(filters)), sort);
  visibleCache = { rows, filters, sort, session, result };
  return result;
}

/** Per-row draw state for charts. */
export const HIDDEN = 0;
export const FILTERED_OUT = 1;
export const SHOWN = 2;

let maskCache: {
  rows: Row[];
  filters: Record<string, Filter>;
  session: number;
  result: Uint8Array;
} | null = null;

/** SHOWN when a row passes every filter; FILTERED_OUT when the only filters excluding
 * it have "show filtered-out" switched on; HIDDEN otherwise.
 *
 * Two passes rather than a per-row list of failing filters: the second pass ignores the
 * filters whose excluded rows should stay visible in grey.
 */
export function drawMask(rows: Row[], filters: Record<string, Filter>): Uint8Array {
  const hit = maskCache;
  const session = sessionKeyFor(Object.values(filters));
  if (hit && hit.rows === rows && hit.filters === filters && hit.session === session) return hit.result;

  const all = Object.values(filters);
  const mask = new Uint8Array(rows.length);
  for (const index of filterRows(rows, all)) mask[index] = SHOWN;
  const hard = all.filter((f) => isActive(f) && !f.showFilteredOut);
  if (hard.length < all.filter(isActive).length) {
    for (const index of filterRows(rows, hard)) {
      if (mask[index] !== SHOWN) mask[index] = FILTERED_OUT;
    }
  }
  maskCache = { rows, filters, session, result: mask };
  return mask;
}

export function extent(vector: Float64Array, mask?: Uint8Array, minState = SHOWN): [number, number] {
  let lo = Infinity;
  let hi = -Infinity;
  for (let i = 0; i < vector.length; i += 1) {
    if (mask && mask[i]! < minState) continue;
    const value = vector[i]!;
    if (value < lo) lo = value;
    if (value > hi) hi = value;
  }
  if (lo === Infinity) return [0, 1];
  return lo === hi ? [lo - 0.5, hi + 0.5] : [lo, hi];
}
