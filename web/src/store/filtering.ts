/** Pure filtering logic.
 *
 * Kept free of React and of the store so it can be tested directly -- this is where
 * "which rows are visible" is decided, and it is the single most load-bearing
 * computation in the dashboard.
 */

import type { ColumnInfo, Row } from "../api/types";
import { compileRegions, insideRegions } from "./geometry";
import { isSessionColumn, sessionKeyFor, sessionValue, sessionVersion } from "./session";
import { numericVector } from "./vectors";
import {
  ROW_INDEX,
  type BooleanFilter, type CategoricalFilter, type Filter, type HistogramBin,
  type NumericFilter, type RegionFilter, type SortKey,
} from "./types";

const NUMERIC_KINDS = new Set([
  "int32", "int64", "float32", "confidence", "fraction",
  "probability", "iou", "sample_weight", "example_id", "epoch", "foreign_table_id",
]);

export function isNumericColumn(column: ColumnInfo): boolean {
  return NUMERIC_KINDS.has(column.kind);
}

/** A cell value, where `ROW_INDEX` resolves to the row's position. */
export function cellValue(row: Row, column: string, index: number): unknown {
  if (column === ROW_INDEX) return index;
  if (isSessionColumn(column)) return sessionValue(column, index);
  return row[column];
}

export function regionFilterKey(x: string, y: string): string {
  return `region:${x}|${y}`;
}

export function filterKindFor(column: ColumnInfo): Exclude<Filter["kind"], "region"> | null {
  if (column.kind === "bool") return "boolean";
  if (column.kind === "categorical_label") return "categorical";
  if (NUMERIC_KINDS.has(column.kind)) return "numeric";
  if (column.kind === "string") return "categorical";
  return null; // images, embeddings and urls are not filterable in Stage 4
}

export function isFilterable(column: ColumnInfo): boolean {
  return filterKindFor(column) !== null;
}

function numericValues(rows: Row[], column: string): number[] {
  const out: number[] = [];
  for (const row of rows) {
    const value = row[column];
    if (typeof value === "number" && Number.isFinite(value)) out.push(value);
  }
  return out;
}

/** Build a filter sitting wide open over the data actually loaded. */
export function makeFilter(column: ColumnInfo, rows: Row[]): Filter | null {
  const kind = filterKindFor(column);
  if (kind === null) return null;
  const common = {
    column: column.name,
    scope: "row" as const,
    inverted: false,
    locked: false,
    showFilteredOut: false,
  };

  if (kind === "numeric") {
    // A loop, not Math.min(...values): spreading a million arguments overflows the stack.
    const values = numericValues(rows, column.name);
    let lo = values.length ? Infinity : 0;
    let hi = values.length ? -Infinity : 1;
    for (const value of values) {
      if (value < lo) lo = value;
      if (value > hi) hi = value;
    }
    const bounds: [number, number] = lo === hi ? [lo, lo + 1] : [lo, hi];
    return { ...common, kind, bounds, range: [...bounds] as [number, number] };
  }

  if (kind === "boolean") {
    return { ...common, kind, value: null };
  }

  const seen = new Set<string | number>();
  for (const row of rows) {
    const value = row[column.name];
    if (typeof value === "string" || typeof value === "number") seen.add(value);
  }
  return { ...common, kind, values: [...seen].sort(), excluded: [] };
}

export function isActive(filter: Filter): boolean {
  if (filter.inverted) return true;
  switch (filter.kind) {
    case "numeric":
      return filter.range[0] > filter.bounds[0] || filter.range[1] < filter.bounds[1];
    case "categorical":
      return filter.excluded.length > 0;
    case "boolean":
      return filter.value !== null;
    case "region":
      return filter.regions.length > 0;
  }
}

export function passesNumeric(filter: NumericFilter, value: unknown): boolean {
  if (typeof value !== "number" || !Number.isFinite(value)) return false;
  const inside = value >= filter.range[0] && value <= filter.range[1];
  return filter.inverted ? !inside : inside;
}

export function passesCategorical(filter: CategoricalFilter, value: unknown): boolean {
  const key = value as string | number;
  const inside = !filter.excluded.includes(key);
  return filter.inverted ? !inside : inside;
}

export function passesBoolean(filter: BooleanFilter, value: unknown): boolean {
  if (filter.value === null) return true;
  const inside = Boolean(value) === filter.value;
  return filter.inverted ? !inside : inside;
}

function passesRegion(filter: RegionFilter, row: Row, index: number): boolean {
  const x = cellValue(row, filter.x, index);
  const y = cellValue(row, filter.y, index);
  // A point with no position is in no region, inverted or not -- matching numeric
  // filters, which never pass a missing value. (Number(null) is 0, not NaN.)
  if (typeof x !== "number" || typeof y !== "number") return false;
  if (!Number.isFinite(x) || !Number.isFinite(y)) return false;
  const inside = insideRegions(compileRegions(filter.regions), x, y);
  return filter.inverted ? !inside : inside;
}

/** `index` is the row's position; only region filters over `ROW_INDEX` need it. */
export function passes(filter: Filter, row: Row, index = -1): boolean {
  if (filter.kind === "region") return passesRegion(filter, row, index);
  if (filter.scope === "element") return rowPassesElements(row, filter.geometry!, [filter]);
  const value = cellValue(row, filter.column, index);
  switch (filter.kind) {
    case "numeric":
      return passesNumeric(filter, value);
    case "categorical":
      return passesCategorical(filter, value);
    case "boolean":
      return passesBoolean(filter, value);
  }
}

/** A row-level test: an ordinary filter, or all element filters of one geometry column
 * combined -- they must hold for the *same* instance, which separate filters cannot express. */
interface ElementGroup {
  column: string;
  kind: "elementGroup";
  geometry: string;
  members: Filter[];
}

type Unit = Filter | ElementGroup;

export function elementGroupKey(geometry: string): string {
  return `elements:${geometry}`;
}

const groupCache = new Map<string, ElementGroup>();

/** Active units, with element groups reused while their members are unchanged, so the
 * mask caches below keep hitting. */
function activeUnits(filters: Filter[]): Unit[] {
  const units: Unit[] = [];
  const byGeometry = new Map<string, Filter[]>();
  for (const filter of filters) {
    if (!isActive(filter)) continue;
    if (filter.scope === "element" && filter.geometry) {
      const members = byGeometry.get(filter.geometry) ?? [];
      members.push(filter);
      byGeometry.set(filter.geometry, members);
    } else {
      units.push(filter);
    }
  }
  for (const [geometry, members] of byGeometry) {
    const key = elementGroupKey(geometry);
    const cached = groupCache.get(key);
    if (cached && cached.members.length === members.length && cached.members.every((m, i) => m === members[i])) {
      units.push(cached);
    } else {
      const group: ElementGroup = { column: key, kind: "elementGroup", geometry, members };
      groupCache.set(key, group);
      units.push(group);
    }
  }
  return units;
}

const passMaskCache = new WeakMap<object, { rows: Row[]; version: number; mask: Uint8Array }>();

function unitPasses(unit: Unit, row: Row, index: number): boolean {
  return unit.kind === "elementGroup" ? rowPassesElements(row, unit.geometry, unit.members) : passes(unit, row, index);
}

/** 1 where a row passes this one filter. Cached per filter object: the store replaces a
 * filter when it changes, so dragging one range re-evaluates that filter only. */
export function passMask(rows: Row[], filter: Unit): Uint8Array {
  const hit = passMaskCache.get(filter);
  const version = isSessionColumn(filter.column) ? sessionVersion() : 0;
  if (hit && hit.rows === rows && hit.version === version) return hit.mask;
  const mask = new Uint8Array(rows.length);
  for (let index = 0; index < rows.length; index += 1) {
    if (unitPasses(filter, rows[index]!, index)) mask[index] = 1;
  }
  passMaskCache.set(filter, { rows, version, mask });
  return mask;
}

let failCache: { rows: Row[]; active: Unit[]; session: number; fails: Uint8Array } | null = null;

/** How many of the given (active) filters each row fails.
 *
 * One count answers every question the panels ask: a row is visible when it fails
 * nothing, and it passes "every filter except F" when its only failure is F. The
 * histograms used to answer that by re-filtering all rows once per widget and building
 * a Set of the survivors -- at a million rows, most of a second per change.
 */
function failCounts(rows: Row[], active: Unit[]): Uint8Array {
  const hit = failCache;
  const session = sessionKeyFor(active.filter((u): u is Filter => u.kind !== "elementGroup"));
  if (
    hit && hit.rows === rows && hit.session === session && hit.active.length === active.length &&
    hit.active.every((f, i) => f === active[i])
  ) {
    return hit.fails;
  }
  const fails = new Uint8Array(rows.length);
  for (const filter of active) {
    const mask = passMask(rows, filter);
    for (let index = 0; index < rows.length; index += 1) {
      if (mask[index] === 0) fails[index] = fails[index]! + 1;
    }
  }
  failCache = { rows, active, session, fails };
  return fails;
}

/** Failure counts plus the mask of the unit to discount, for "passes the others".
 * `ignore` is a filter column, or an element group key. */
function failureParts(rows: Row[], filters: Filter[], ignore: string | undefined) {
  const active = activeUnits(filters);
  const fails = failCounts(rows, active);
  const ignored = active.find((u) => u.column === ignore);
  return { fails, own: ignored ? passMask(rows, ignored) : null };
}

function othersFailing(rows: Row[], filters: Filter[], ignore: string | undefined) {
  const { fails, own } = failureParts(rows, filters, ignore);
  return (index: number) => fails[index]! - (own && own[index] === 0 ? 1 : 0);
}

/** Row indices passing every active filter, optionally ignoring one of them.
 *
 * `ignore` is what lets a histogram show the rows a *different* filter excluded in a
 * lighter shade than the ones this filter excluded itself.
 */
export function filterRows(
  rows: Row[],
  filters: Filter[],
  options: { ignore?: string } = {},
): number[] {
  const active = activeUnits(filters).filter((u) => u.column !== options.ignore);
  if (active.length === 0) return rows.map((_, index) => index);
  const failing = othersFailing(rows, filters, options.ignore);
  const out: number[] = [];
  for (let index = 0; index < rows.length; index += 1) {
    if (failing(index) === 0) out.push(index);
  }
  return out;
}

// ---------------------------------------------------------------------------
// element filters
// ---------------------------------------------------------------------------

interface InstanceLike {
  vertices?: number[];
  label?: number | null;
  [key: string]: unknown;
}

function instancesOf(row: Row, geometry: string): InstanceLike[] {
  const value = row[geometry] as { instances?: InstanceLike[] } | null | undefined;
  return Array.isArray(value?.instances) ? value!.instances! : [];
}

/** One property of one instance, including derived ones: `area`, and `missed` for a
 * ground-truth box no prediction matched (from the metrics' `gt_match`). */
export function elementValue(row: Row, geometry: string, index: number, property: string): unknown {
  const instances = instancesOf(row, geometry);
  const instance = instances[index];
  if (!instance) return undefined;
  if (property === "label") return instance.label;
  if (property === "area") {
    const [x0 = 0, y0 = 0, x1 = 0, y1 = 0] = instance.vertices ?? [];
    return (x1 - x0) * (y1 - y0);
  }
  if (property === "missed") {
    const match = row.gt_match;
    if (!Array.isArray(match) || match.length !== instances.length) return undefined;
    return match[index] === -1;
  }
  return instance[property];
}

function elementPasses(filter: Filter, value: unknown): boolean {
  switch (filter.kind) {
    case "numeric":
      return passesNumeric(filter, value);
    case "categorical":
      return passesCategorical(filter, value);
    case "boolean":
      return passesBoolean(filter, value);
    default:
      return true;
  }
}

/** Whether instance `index` passes every active element filter among `members`. */
export function instancePasses(row: Row, geometry: string, index: number, members: Filter[]): boolean {
  for (const filter of members) {
    if (!isActive(filter) || filter.scope !== "element" || filter.geometry !== geometry) continue;
    if (!elementPasses(filter, elementValue(row, geometry, index, filter.property!))) return false;
  }
  return true;
}

/** A row passes element filters while at least one of its instances passes all of them. */
export function rowPassesElements(row: Row, geometry: string, members: Filter[]): boolean {
  const count = instancesOf(row, geometry).length;
  for (let i = 0; i < count; i += 1) {
    if (instancePasses(row, geometry, i, members)) return true;
  }
  return false;
}

export function elementFilterKey(geometry: string, property: string): string {
  return `${geometry}.${property}`;
}

/** Wide-open element filters for a geometry column: class, area, every typed instance
 * property, and `missed` when per-box match results exist. */
export function makeElementFilters(column: ColumnInfo, rows: Row[]): Filter[] {
  const geometry = column.name;
  const common = { scope: "element" as const, geometry, inverted: false, locked: false, showFilteredOut: false };
  const out: Filter[] = [];

  const labels = new Set<number>();
  const numbers = new Map<string, [number, number]>();
  const numericProperties = ["area", ...Object.entries(column.instance_properties ?? {})
    .filter(([, kind]) => kind.startsWith("float") || kind.startsWith("int"))
    .map(([name]) => name)];
  let hasMatch = false;
  for (const row of rows) {
    const instances = instancesOf(row, geometry);
    if (Array.isArray(row.gt_match)) hasMatch = true;
    instances.forEach((instance, i) => {
      if (typeof instance.label === "number") labels.add(instance.label);
      for (const property of numericProperties) {
        const value = elementValue(row, geometry, i, property);
        if (typeof value !== "number" || !Number.isFinite(value)) continue;
        const range = numbers.get(property);
        if (!range) numbers.set(property, [value, value]);
        else {
          if (value < range[0]) range[0] = value;
          if (value > range[1]) range[1] = value;
        }
      }
    });
  }

  const labelValues = new Set<number>([...labels, ...Object.keys(column.value_map ?? {}).map(Number)]);
  out.push({ ...common, column: elementFilterKey(geometry, "label"), property: "label", kind: "categorical",
    values: [...labelValues].filter((v) => labels.has(v)).sort((a, b) => a - b), excluded: [] });
  for (const property of numericProperties) {
    const range = numbers.get(property);
    if (!range) continue;
    const bounds: [number, number] = range[0] === range[1] ? [range[0], range[0] + 1] : range;
    out.push({ ...common, column: elementFilterKey(geometry, property), property, kind: "numeric", bounds, range: [...bounds] });
  }
  for (const [property, kind] of Object.entries(column.instance_properties ?? {})) {
    if (kind === "bool") {
      out.push({ ...common, column: elementFilterKey(geometry, property), property, kind: "boolean", value: null });
    }
  }
  const isPrediction = column.source === "metrics";
  if (hasMatch && !isPrediction) {
    out.push({ ...common, column: elementFilterKey(geometry, "missed"), property: "missed", kind: "boolean", value: null });
  }
  return out;
}

/** Instances passing this geometry's element filters, in rows passing everything else,
 * against all instances: the "12 of 929 boxes" shown on filters and panels. */
export function elementCounts(rows: Row[], visible: number[], filters: Filter[], geometry: string): { shown: number; total: number } {
  let total = 0;
  for (const row of rows) total += instancesOf(row, geometry).length;
  let shown = 0;
  for (const index of visible) {
    const row = rows[index]!;
    const count = instancesOf(row, geometry).length;
    for (let i = 0; i < count; i += 1) if (instancePasses(row, geometry, i, filters)) shown += 1;
  }
  return { shown, total };
}

/** Element-level histogram: counts instances, not rows. */
export function elementHistogram(rows: Row[], filter: NumericFilter, allFilters: Filter[], binCount = 24): HistogramBin[] {
  const [lo, hi] = filter.bounds;
  const width = (hi - lo) / binCount || 1;
  const bins: HistogramBin[] = Array.from({ length: binCount }, (_, i) => ({
    lo: lo + i * width, hi: lo + (i + 1) * width, total: 0, filteredIn: 0, excludedHere: 0,
  }));
  const geometry = filter.geometry!;
  const failing = othersFailing(rows, allFilters, elementGroupKey(geometry));
  for (let r = 0; r < rows.length; r += 1) {
    const row = rows[r]!;
    const rowOk = failing(r) === 0;
    const count = instancesOf(row, geometry).length;
    for (let i = 0; i < count; i += 1) {
      const value = elementValue(row, geometry, i, filter.property!);
      if (typeof value !== "number" || !Number.isFinite(value)) continue;
      const bin = bins[Math.min(binCount - 1, Math.max(0, Math.floor((value - lo) / width)))]!;
      bin.total += 1;
      if (!passesNumeric(filter, value)) bin.excludedHere += 1;
      else if (rowOk && instancePasses(row, geometry, i, allFilters)) bin.filteredIn += 1;
    }
  }
  return bins;
}

export function elementCategoricalCounts(
  rows: Row[], filter: CategoricalFilter | BooleanFilter, allFilters: Filter[],
): Map<string | number, { total: number; filteredIn: number }> {
  const geometry = filter.geometry!;
  const failing = othersFailing(rows, allFilters, elementGroupKey(geometry));
  const counts = new Map<string | number, { total: number; filteredIn: number }>();
  for (let r = 0; r < rows.length; r += 1) {
    const row = rows[r]!;
    const rowOk = failing(r) === 0;
    const count = instancesOf(row, geometry).length;
    for (let i = 0; i < count; i += 1) {
      const raw = elementValue(row, geometry, i, filter.property!);
      if (raw === undefined || raw === null) continue;
      const key = typeof raw === "boolean" ? String(raw) : (raw as string | number);
      const bucket = counts.get(key) ?? { total: 0, filteredIn: 0 };
      bucket.total += 1;
      if (rowOk && instancePasses(row, geometry, i, allFilters)) bucket.filteredIn += 1;
      counts.set(key, bucket);
    }
  }
  return counts;
}

export function compareValues(a: unknown, b: unknown): number {
  if (a === b) return 0;
  if (a === null || a === undefined) return 1;
  if (b === null || b === undefined) return -1;
  if (typeof a === "number" && typeof b === "number") return a - b;
  return String(a).localeCompare(String(b));
}

/** Sort row indices by several keys. Earlier keys win. */
export function sortRows(rows: Row[], indices: number[], keys: SortKey[]): number[] {
  if (keys.length === 0) return indices;
  return [...indices].sort((left, right) => {
    for (const key of keys) {
      const result = compareValues(rows[left]![key.column], rows[right]![key.column]);
      if (result !== 0) return key.direction === "asc" ? result : -result;
    }
    return left - right;
  });
}

const NO_BIN = 255;
const slotCache = new WeakMap<Float64Array, { key: string; slots: Uint8Array; totals: number[] }>();

/** Which bin each value falls in. Depends only on the data and the filter's bounds, not
 * on its range, so dragging a range reuses it. */
function binSlots(values: Float64Array, lo: number, width: number, binCount: number) {
  const key = `${lo}|${width}|${binCount}`;
  const hit = slotCache.get(values);
  if (hit && hit.key === key) return hit;
  const slots = new Uint8Array(values.length);
  const totals = new Array<number>(binCount).fill(0);
  for (let index = 0; index < values.length; index += 1) {
    const value = values[index]!;
    if (!Number.isFinite(value)) {
      slots[index] = NO_BIN;
      continue;
    }
    const slot = Math.min(binCount - 1, Math.max(0, Math.floor((value - lo) / width)));
    slots[index] = slot;
    totals[slot] = totals[slot]! + 1;
  }
  const entry = { key, slots, totals };
  slotCache.set(values, entry);
  return entry;
}

/** Histogram for a numeric filter, split into filtered-in and filtered-out counts. */
export function histogram(
  rows: Row[],
  filter: NumericFilter,
  allFilters: Filter[],
  binCount = 24,
): HistogramBin[] {
  const [lo, hi] = filter.bounds;
  const width = (hi - lo) / binCount || 1;
  const bins: HistogramBin[] = Array.from({ length: binCount }, (_, i) => ({
    lo: lo + i * width,
    hi: lo + (i + 1) * width,
    total: 0,
    filteredIn: 0,
    excludedHere: 0,
  }));

  const { fails, own: ignoredOwn } = failureParts(rows, allFilters, filter.column);
  const own = passMask(rows, filter);
  const { slots, totals } = binSlots(numericVector(rows, filter.column), lo, width, binCount);
  totals.forEach((total, i) => (bins[i]!.total = total));

  for (let index = 0; index < slots.length; index += 1) {
    const slot = slots[index]!;
    if (slot === NO_BIN) continue;
    const bin = bins[slot]!;
    if (own[index] === 1) {
      const others = fails[index]! - (ignoredOwn !== null && ignoredOwn[index] === 0 ? 1 : 0);
      if (others === 0) bin.filteredIn += 1;
    } else {
      bin.excludedHere += 1;
    }
  }
  return bins;
}

export function categoricalCounts(
  rows: Row[],
  filter: CategoricalFilter,
  allFilters: Filter[],
): Map<string | number, { total: number; filteredIn: number }> {
  const failing = othersFailing(rows, allFilters, filter.column);
  const own = passMask(rows, filter);
  const counts = new Map<string | number, { total: number; filteredIn: number }>();
  for (const value of filter.values) counts.set(value, { total: 0, filteredIn: 0 });
  for (let index = 0; index < rows.length; index += 1) {
    const value = rows[index]![filter.column] as string | number;
    const bucket = counts.get(value);
    if (!bucket) continue;
    bucket.total += 1;
    if (own[index] === 1 && failing(index) === 0) bucket.filteredIn += 1;
  }
  return counts;
}
