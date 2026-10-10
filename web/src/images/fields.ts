/** Sorting, grouping, filtering and summarising the gallery by the set's own columns.
 *
 * The ribbon used to offer four orders and a fixed set of filters, so an import's own
 * columns -- `width`, `city`, `capture_time`, `removed_reason`, a weight -- were in the
 * table and unreachable. `/api/images` now describes them (`fields`) and carries their
 * values per image, and everything here is the reading of that: which images a field filter
 * leaves, what order a field puts them in, which groups it cuts them into, and what a
 * column adds up to over whatever the ribbon has left.
 *
 * Pure, and tested directly, for the reason the table's filtering is: these are the sums
 * that decide what a reader is looking at, and the arithmetic that places a value in a bin
 * or a quantile is exactly the kind that goes wrong quietly.
 */

import type { FieldInfo, ImageRow } from "../api/types";

export type FieldValue = number | string | boolean;

/** Groups, bins and value lists stop here: past this a control is a wall, not a control. */
export const MAX_GROUPS = 24;

/** A field's value on one image, or undefined when this image has none.
 *
 * Absent rather than null: the payload leaves a missing value out, so "not in the object"
 * is the only way a value can be missing and there is one thing to test for.
 */
export function fieldValue(item: ImageRow, name: string): FieldValue | undefined {
  const value = item.values?.[name];
  if (value === null || value === undefined) return undefined;
  return value;
}

export function numberValue(item: ImageRow, name: string): number | undefined {
  const value = fieldValue(item, name);
  return typeof value === "number" && Number.isFinite(value) ? value : undefined;
}

/** How a value reads on a chip, a group heading or a summary row. */
export function displayValue(field: FieldInfo | undefined, value: FieldValue): string {
  if (field?.kind === "class") {
    const name = field.classes?.[String(value)];
    return name ?? String(value);
  }
  if (typeof value === "boolean") return value ? "Yes" : "No";
  if (typeof value === "number") return Number.isInteger(value) ? String(value) : String(Number(value.toFixed(4)));
  return String(value);
}

// ---------------------------------------------------------------------------
// filters
// ---------------------------------------------------------------------------

export interface NumberFieldFilter {
  name: string;
  kind: "number";
  /** The range the data spans, which the widget is drawn against. */
  bounds: [number, number];
  /** The range the reader has asked for, inside those bounds. */
  range: [number, number];
  /** Whether images with no value for this field still pass. */
  withoutValue: boolean;
}

export interface ValueFieldFilter {
  name: string;
  kind: "values";
  /** Every value the field takes, in the order they are offered. */
  values: FieldValue[];
  /** The values switched off, as strings so a chip's key and its test agree. */
  excluded: string[];
  withoutValue: boolean;
}

/** A column with thousands of distinct values -- file names, hashes, free text. A list of
 *  them is not a control, so it is asked as a question: which of these contain this? */
export interface TextFieldFilter {
  name: string;
  kind: "text";
  query: string;
  withoutValue: boolean;
}

export type FieldFilter = NumberFieldFilter | ValueFieldFilter | TextFieldFilter;

/** A filter sitting wide open over the images given, or null when the field says nothing
 *  about any of them. */
export function makeFieldFilter(field: FieldInfo, items: ImageRow[]): FieldFilter | null {
  if (field.kind === "number") {
    let lo = Infinity;
    let hi = -Infinity;
    let seen = false;
    for (const item of items) {
      const value = numberValue(item, field.name);
      if (value === undefined) continue;
      seen = true;
      if (value < lo) lo = value;
      if (value > hi) hi = value;
    }
    if (!seen) return null;
    const bounds: [number, number] = lo === hi ? [lo, lo] : [lo, hi];
    return { name: field.name, kind: "number", bounds, range: [...bounds], withoutValue: true };
  }

  // Thousands of distinct values: a list of them is a wall, so it is a search instead.
  if (field.wide) return { name: field.name, kind: "text", query: "", withoutValue: true };

  // The service lists the values of a small-cardinality column; otherwise they are read
  // off the images in hand, which is the same answer for the payload the ribbon holds.
  const values: FieldValue[] = field.values ? [...field.values] : [];
  if (values.length === 0) {
    const seen = new Set<FieldValue>();
    for (const item of items) {
      const value = fieldValue(item, field.name);
      if (value !== undefined) seen.add(value);
    }
    values.push(...[...seen].sort(compareFieldValues));
  }
  if (values.length === 0) return null;
  return { name: field.name, kind: "values", values, excluded: [], withoutValue: true };
}

export function fieldFilterActive(filter: FieldFilter): boolean {
  if (!filter.withoutValue) return true;
  if (filter.kind === "number") {
    return filter.range[0] > filter.bounds[0] || filter.range[1] < filter.bounds[1];
  }
  if (filter.kind === "text") return filter.query.trim().length > 0;
  return filter.excluded.length > 0;
}

export function passesFieldFilter(filter: FieldFilter, item: ImageRow): boolean {
  const value = fieldValue(item, filter.name);
  if (value === undefined) return filter.withoutValue;
  if (filter.kind === "number") {
    if (typeof value !== "number" || !Number.isFinite(value)) return filter.withoutValue;
    return value >= filter.range[0] && value <= filter.range[1];
  }
  if (filter.kind === "text") {
    const query = filter.query.trim().toLowerCase();
    return query.length === 0 || String(value).toLowerCase().includes(query);
  }
  return !filter.excluded.includes(String(value));
}

/** The images passing every active field filter, optionally ignoring one of them.
 *
 * `ignore` is what lets a widget count its own values against the images the *other*
 * filters leave, so its numbers do not all collapse to the choice it has just made.
 */
export function filterByFields(
  items: ImageRow[],
  filters: Record<string, FieldFilter>,
  ignore?: string,
): ImageRow[] {
  const active = Object.values(filters).filter((f) => f.name !== ignore && fieldFilterActive(f));
  if (active.length === 0) return items;
  return items.filter((item) => active.every((filter) => passesFieldFilter(filter, item)));
}

export function activeFieldFilters(filters: Record<string, FieldFilter>): FieldFilter[] {
  return Object.values(filters).filter(fieldFilterActive);
}

/** The same filter, wide open again. One place, because there are three kinds of them and
 *  three callers -- reset one, clear all, and open a saved view. */
export function openFieldFilter(filter: FieldFilter): FieldFilter {
  if (filter.kind === "number") return { ...filter, range: [...filter.bounds] as [number, number], withoutValue: true };
  if (filter.kind === "text") return { ...filter, query: "", withoutValue: true };
  return { ...filter, excluded: [], withoutValue: true };
}

/** A saved view's choice applied to the widget today's data built.
 *
 * The bounds and the value list belong to the data in hand, not to the view: a range saved
 * over last month's set must narrow this month's set, not redefine what its column spans.
 * A kind that no longer matches -- the column changed type, or grew past the point where it
 * is listed rather than searched -- is left as it is rather than half-restored.
 */
export function restoreFieldFilter(built: FieldFilter, saved: unknown): FieldFilter {
  if (!saved || typeof saved !== "object") return built;
  const from = saved as {
    kind?: string; withoutValue?: boolean; range?: unknown; query?: unknown; excluded?: unknown;
  };
  if (from.kind !== built.kind) return built;
  const withoutValue = from.withoutValue !== false;
  if (built.kind === "number") {
    const range: unknown[] = Array.isArray(from.range) && from.range.length === 2 ? from.range : built.range;
    const [lo, hi] = [Number(range[0]), Number(range[1])];
    // A saved range that is not two numbers, or is the wrong way round, would silently
    // empty the gallery; fall back to the bounds the data gives.
    if (!Number.isFinite(lo) || !Number.isFinite(hi) || lo > hi) return { ...built, withoutValue };
    return { ...built, range: [lo, hi], withoutValue };
  }
  if (built.kind === "text") return { ...built, query: String(from.query ?? ""), withoutValue };
  return { ...built, excluded: Array.isArray(from.excluded) ? from.excluded.map(String) : [], withoutValue };
}

// ---------------------------------------------------------------------------
// widgets: what a filter draws itself against
// ---------------------------------------------------------------------------

export interface FieldBin {
  lo: number;
  hi: number;
  /** Images of this bin before this filter, and after it. */
  total: number;
  shown: number;
}

/** A numeric field's histogram: `total` over the images the other filters leave, `shown`
 *  over those this filter leaves too, which is the two-tone bar the table panel draws. */
export function fieldHistogram(items: ImageRow[], filter: NumberFieldFilter, binCount = 24): FieldBin[] {
  const [lo, hi] = filter.bounds;
  const width = (hi - lo) / binCount || 1;
  const bins: FieldBin[] = Array.from({ length: binCount }, (_, i) => ({
    lo: lo + i * width, hi: lo + (i + 1) * width, total: 0, shown: 0,
  }));
  for (const item of items) {
    const value = numberValue(item, filter.name);
    if (value === undefined) continue;
    const at = Math.min(binCount - 1, Math.max(0, Math.floor((value - lo) / width)));
    const bin = bins[at]!;
    bin.total += 1;
    if (value >= filter.range[0] && value <= filter.range[1]) bin.shown += 1;
  }
  return bins;
}

/** How many of the given images carry each value of a field, and how many carry none. */
export function fieldValueCounts(items: ImageRow[], name: string): { counts: Map<string, number>; missing: number } {
  const counts = new Map<string, number>();
  let missing = 0;
  for (const item of items) {
    const value = fieldValue(item, name);
    if (value === undefined) {
      missing += 1;
      continue;
    }
    const key = String(value);
    counts.set(key, (counts.get(key) ?? 0) + 1);
  }
  return { counts, missing };
}

// ---------------------------------------------------------------------------
// ordering
// ---------------------------------------------------------------------------

/** Numbers by size, everything else by name, and a missing value last either way.
 *
 * Last in both directions on purpose: "order by capture time, newest first" should not
 * open on the images that have no capture time.
 */
export function compareFieldValues(a: FieldValue | undefined, b: FieldValue | undefined): number {
  if (a === b) return 0;
  if (a === undefined) return 1;
  if (b === undefined) return -1;
  if (typeof a === "number" && typeof b === "number") return a - b;
  if (typeof a === "boolean" || typeof b === "boolean") return Number(a) - Number(b);
  return String(a).localeCompare(String(b), undefined, { numeric: true });
}

/** Images ordered by one field. Missing values keep their place at the end. */
export function sortByField(items: ImageRow[], name: string, direction: "asc" | "desc"): ImageRow[] {
  const sign = direction === "asc" ? 1 : -1;
  const missing = (item: ImageRow) => (fieldValue(item, name) === undefined ? 1 : 0);
  return [...items].sort((a, b) => {
    const gap = missing(a) - missing(b);
    if (gap !== 0) return gap;
    const by = compareFieldValues(fieldValue(a, name), fieldValue(b, name));
    return by !== 0 ? by * sign : a.image.localeCompare(b.image);
  });
}

/** A seeded shuffle: the same seed puts the same images in the same order.
 *
 * Seeded rather than random because a shuffled gallery is something a reader works through
 * and comes back to, and because "the first 200 of a shuffle" is only a defensible sample
 * of a set if it can be named and handed to someone else. mulberry32, which is small enough
 * to read and good enough for choosing what to look at.
 */
export function shuffleImages(items: ImageRow[], seed: number): ImageRow[] {
  let state = (seed >>> 0) || 1;
  const random = () => {
    state = (state + 0x6d2b79f5) >>> 0;
    let t = state;
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
  const out = [...items];
  for (let i = out.length - 1; i > 0; i -= 1) {
    const j = Math.floor(random() * (i + 1));
    [out[i], out[j]] = [out[j]!, out[i]!];
  }
  return out;
}

/** `skip` images off the front, then at most `take`. Zero take means everything. */
export function sliceImages(items: ImageRow[], skip: number, take: number): ImageRow[] {
  const from = Math.max(0, Math.floor(skip));
  if (from === 0 && take <= 0) return items;
  return items.slice(from, take > 0 ? from + Math.floor(take) : undefined);
}

// ---------------------------------------------------------------------------
// grouping
// ---------------------------------------------------------------------------

export interface ImageGroup {
  /** Stable across renders: the value, or the bin's lower edge. */
  key: string;
  label: string;
  items: ImageRow[];
}

export interface Grouping {
  field: FieldInfo;
  groups: ImageGroup[];
  /** True when a continuous column was cut into ranges rather than into its own values. */
  binned: boolean;
}

/** The images cut into groups by one field.
 *
 * A column with few values groups by them. A number with more distinct values than a reader
 * can scan is cut into equal ranges instead -- grouping an aerial set by `width` into eleven
 * thousand groups of one is not a grouping, it is the gallery with headings. Images with no
 * value for the field come last, in their own group, because "which ones does this column say
 * nothing about" is usually the question worth asking of a sparse column.
 */
export function groupImages(
  items: ImageRow[],
  field: FieldInfo,
  options: { limit?: number; valueFor?: (item: ImageRow) => FieldValue | undefined } = {},
): Grouping {
  const limit = options.limit ?? MAX_GROUPS;
  // The ribbon also groups by things that are not columns -- the set an image is in, its
  // review status -- and they group by exactly the same rules. Not named `valueOf`: every
  // object inherits one from Object.prototype, so a `??` would never reach the fallback.
  const read = options.valueFor ?? ((item: ImageRow) => fieldValue(item, field.name));
  const withValue: ImageRow[] = [];
  const without: ImageRow[] = [];
  const distinct = new Set<string>();
  for (const item of items) {
    const value = read(item);
    if (value === undefined) without.push(item);
    else {
      withValue.push(item);
      distinct.add(String(value));
    }
  }

  const groups: ImageGroup[] = [];
  let binned = false;
  if (field.kind === "number" && distinct.size > limit) {
    binned = true;
    let lo = Infinity;
    let hi = -Infinity;
    for (const item of withValue) {
      const value = Number(read(item));
      if (value < lo) lo = value;
      if (value > hi) hi = value;
    }
    const width = (hi - lo) / limit || 1;
    const buckets: ImageRow[][] = Array.from({ length: limit }, () => []);
    for (const item of withValue) {
      const value = Number(read(item));
      buckets[Math.min(limit - 1, Math.max(0, Math.floor((value - lo) / width)))]!.push(item);
    }
    buckets.forEach((bucket, at) => {
      if (bucket.length === 0) return;
      const from = lo + at * width;
      const to = at === limit - 1 ? hi : from + width;
      groups.push({ key: `bin:${at}`, label: `${round(from)} – ${round(to)}`, items: bucket });
    });
  } else {
    const byValue = new Map<string, { value: FieldValue; items: ImageRow[] }>();
    for (const item of withValue) {
      const value = read(item)!;
      const key = String(value);
      const bucket = byValue.get(key) ?? { value, items: [] };
      bucket.items.push(item);
      byValue.set(key, bucket);
    }
    const ordered = [...byValue.entries()];
    // Numbers and classes read in order; free text reads with the commonest first, because
    // there the interesting group is the big one, not the alphabetically first.
    if (field.kind === "string") ordered.sort((a, b) => b[1].items.length - a[1].items.length || a[0].localeCompare(b[0]));
    else ordered.sort((a, b) => compareFieldValues(a[1].value, b[1].value));
    for (const [key, bucket] of ordered.slice(0, limit)) {
      groups.push({ key, label: displayValue(field, bucket.value), items: bucket.items });
    }
    const rest = ordered.slice(limit);
    if (rest.length > 0) {
      groups.push({
        key: "other",
        label: `${rest.length} more values`,
        items: rest.flatMap(([, bucket]) => bucket.items),
      });
    }
  }
  if (without.length > 0) groups.push({ key: "none", label: "No value", items: without });
  return { field, groups, binned };
}

/** A grouping read back as a flat list, in group order: FiftyOne's `flatten`. */
export function flattenGroups(grouping: Grouping): ImageRow[] {
  return grouping.groups.flatMap((group) => group.items);
}

function round(value: number): string {
  if (Number.isInteger(value)) return String(value);
  const scale = Math.abs(value) >= 100 ? 1 : Math.abs(value) >= 1 ? 2 : 4;
  return String(Number(value.toFixed(scale)));
}

// ---------------------------------------------------------------------------
// summary
// ---------------------------------------------------------------------------

export interface FieldSummary {
  count: number;
  present: number;
  missing: number;
  distinct: number;
  top: { value: FieldValue; count: number }[];
  min?: number;
  max?: number;
  sum?: number;
  mean?: number;
  std?: number;
  quantiles?: Record<string, number>;
}

/** What a column adds up to over the images given: bounds, mean, deviation, quantiles,
 *  distinct values and the commonest ones.
 *
 * The same readings as `granum.core.fields.summarize` on the Python side, over the images
 * the ribbon has left rather than over a whole column -- which is the point of having it
 * here: a mean over the validation set's night shots is a different number from the mean,
 * and it is the one a reader is asking about.
 */
export function summarizeField(
  items: ImageRow[],
  name: string,
  quantiles: number[] = [0.25, 0.5, 0.75],
): FieldSummary {
  let missing = 0;
  let numeric = true;
  const numbers: number[] = [];
  const counts = new Map<FieldValue, number>();
  for (const item of items) {
    const value = fieldValue(item, name);
    if (value === undefined) {
      missing += 1;
      continue;
    }
    if (typeof value === "number" && Number.isFinite(value)) numbers.push(value);
    else numeric = false;
    counts.set(value, (counts.get(value) ?? 0) + 1);
  }
  const top = [...counts.entries()]
    .sort((a, b) => b[1] - a[1] || String(a[0]).localeCompare(String(b[0])))
    .slice(0, 12)
    .map(([value, count]) => ({ value, count }));
  const summary: FieldSummary = {
    count: items.length,
    present: items.length - missing,
    missing,
    distinct: counts.size,
    top,
  };
  if (!numeric || numbers.length === 0) return summary;

  numbers.sort((a, b) => a - b);
  const mean = numbers.reduce((sum, value) => sum + value, 0) / numbers.length;
  // Population deviation: this describes the images in hand, it does not estimate a
  // population from them.
  const variance = numbers.reduce((sum, value) => sum + (value - mean) ** 2, 0) / numbers.length;
  summary.min = numbers[0];
  summary.max = numbers[numbers.length - 1];
  summary.sum = numbers.reduce((sum, value) => sum + value, 0);
  summary.mean = mean;
  summary.std = Math.sqrt(variance);
  summary.quantiles = Object.fromEntries(quantiles.map((fraction) => [String(fraction), quantile(numbers, fraction)]));
  return summary;
}

/** Linear interpolation between order statistics, as numpy and the Python side do it. */
export function quantile(sorted: number[], fraction: number): number {
  if (sorted.length === 0) return NaN;
  const position = fraction * (sorted.length - 1);
  const low = Math.floor(position);
  const high = Math.ceil(position);
  if (low === high) return sorted[low]!;
  return sorted[low]! * (1 - (position - low)) + sorted[high]! * (position - low);
}
