/** Colour encoding for scatter points.
 *
 * The annotation palette: cyan, pink, amber. Validated against the dark panel surface
 * (#121418): adjacent-pair CVD separation worst ΔE 8.5, normal-vision floor 27.4.
 * Selection is near-white, so no data colour can be mistaken for it.
 */

import type { Row } from "../api/types";
import { FILTERED_OUT, SHOWN } from "../store/derive";
import { COLOR_SLOTS } from "./spec";

type RGB = [number, number, number];

export const CATEGORICAL: RGB[] = [
  [0x22, 0xd3, 0xee], // cyan
  [0xf4, 0x72, 0xb6], // pink
  [0xfb, 0xbf, 0x24], // amber
];
export const OTHER: RGB = [0x6b, 0x77, 0x86];
export const FILTERED: RGB = [0x2e, 0x33, 0x3b];
export const SELECTED: RGB = [0xf5, 0xf7, 0xfa];

/** Cyan, dark to light: on a dark surface small values recede toward it. */
const SEQUENTIAL: RGB[] = [
  [0x0e, 0x3a, 0x44], [0x15, 0x5e, 0x6d], [0x0e, 0x7f, 0x94],
  [0x06, 0xb6, 0xd4], [0x67, 0xe8, 0xf9], [0xcf, 0xfa, 0xfe],
];

export function sequential(t: number): RGB {
  const clamped = Math.min(1, Math.max(0, Number.isFinite(t) ? t : 0));
  const position = clamped * (SEQUENTIAL.length - 1);
  const lo = Math.floor(position);
  const hi = Math.min(SEQUENTIAL.length - 1, lo + 1);
  const f = position - lo;
  const a = SEQUENTIAL[lo]!;
  const b = SEQUENTIAL[hi]!;
  return [
    Math.round(a[0] + (b[0] - a[0]) * f),
    Math.round(a[1] + (b[1] - a[1]) * f),
    Math.round(a[2] + (b[2] - a[2]) * f),
  ];
}

export const SEQUENTIAL_CSS = `linear-gradient(90deg, ${SEQUENTIAL.map(
  (c) => `rgb(${c.join(",")})`,
).join(", ")})`;

export function css(color: RGB): string {
  return `rgb(${color.join(",")})`;
}

/** Distinct values of a column, sorted -- the legend order and the default slot order. */
export function categories(rows: Row[], column: string): (string | number)[] {
  const seen = new Set<string | number>();
  for (const row of rows) {
    const value = row[column];
    if (typeof value === "string" || typeof value === "number") seen.add(value);
    else if (typeof value === "boolean") seen.add(String(value));
  }
  return [...seen].sort((a, b) =>
    typeof a === "number" && typeof b === "number" ? a - b : String(a).localeCompare(String(b)),
  );
}

export function defaultSlots(values: (string | number)[]): (string | number | null)[] {
  return Array.from({ length: COLOR_SLOTS }, (_, i) => values[i] ?? null);
}

/** Promote or demote one category, keeping every other category's hue where it was.
 *
 * Colour follows the entity: toggling "cat" must not repaint "dog". A promoted value
 * takes the first empty slot, or the last slot when all are full.
 */
export function toggleSlot(
  slots: (string | number | null)[],
  value: string | number,
): (string | number | null)[] {
  const next = [...slots];
  const at = next.indexOf(value);
  if (at !== -1) {
    next[at] = null;
    return next;
  }
  const empty = next.indexOf(null);
  next[empty === -1 ? next.length - 1 : empty] = value;
  return next;
}

export type ColorMode =
  | { kind: "none" }
  | { kind: "categorical"; column: string; slots: (string | number | null)[] }
  | { kind: "numeric"; values: Float64Array; range: [number, number] };

/** RGBA per point. Filtered-out points are grey; hidden points are transparent. */
export function pointColors(rows: Row[], mask: Uint8Array, mode: ColorMode): Uint8Array {
  const out = new Uint8Array(rows.length * 4);
  const slotOf = new Map<string, number>();
  if (mode.kind === "categorical") {
    mode.slots.forEach((value, i) => {
      if (value !== null) slotOf.set(String(value), i);
    });
  }
  const [lo, hi] = mode.kind === "numeric" ? mode.range : [0, 1];
  const span = hi - lo || 1;

  for (let i = 0; i < rows.length; i += 1) {
    const o = i * 4;
    const state = mask[i]!;
    if (state === FILTERED_OUT) {
      out[o] = FILTERED[0];
      out[o + 1] = FILTERED[1];
      out[o + 2] = FILTERED[2];
      out[o + 3] = 170;
      continue;
    }
    if (state !== SHOWN) continue; // alpha stays 0

    let color: RGB = CATEGORICAL[0]!;
    if (mode.kind === "categorical") {
      const slot = slotOf.get(String(rows[i]![mode.column]));
      color = slot === undefined ? OTHER : CATEGORICAL[slot]!;
    } else if (mode.kind === "numeric") {
      color = sequential((mode.values[i]! - lo) / span);
    }
    out[o] = color[0];
    out[o + 1] = color[1];
    out[o + 2] = color[2];
    out[o + 3] = 230;
  }
  return out;
}
