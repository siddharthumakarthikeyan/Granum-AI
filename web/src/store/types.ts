import type { ColumnInfo, Row } from "../api/types";

/** What a filter or selection addresses.
 *
 * Stage 4 only ever produces "row". Stage 7 introduces bounding boxes, where a filter
 * narrows individual elements *within* a row and a row survives until all of its
 * elements are filtered out. Carrying the scope now means that change is additive
 * rather than a rewrite of every panel.
 */
export type Scope = "row" | "element";

export type FilterKind = "numeric" | "categorical" | "boolean" | "region";

/** Element filters address one property of the instances in a geometry column.
 * Their `column` key is `${geometry}.${property}`. */
export interface ElementAddress {
  geometry?: string;
  property?: string;
}

export interface NumericFilter extends ElementAddress {
  column: string;
  kind: "numeric";
  scope: Scope;
  /** Full data range, for drawing the track and the histogram. */
  bounds: [number, number];
  /** Currently selected range. */
  range: [number, number];
  inverted: boolean;
  locked: boolean;
  showFilteredOut: boolean;
}

export interface CategoricalFilter extends ElementAddress {
  column: string;
  kind: "categorical";
  scope: Scope;
  values: (string | number)[];
  excluded: (string | number)[];
  inverted: boolean;
  locked: boolean;
  showFilteredOut: boolean;
}

export interface BooleanFilter extends ElementAddress {
  column: string;
  kind: "boolean";
  scope: Scope;
  value: boolean | null;
  inverted: boolean;
  locked: boolean;
  showFilteredOut: boolean;
}

/** A 2D point in data coordinates. */
export type Point = [number, number];

/** One painted shape. Regions apply in order, like strokes: an "add" region switches
 * the points inside it on, a "subtract" region switches them off again. */
export interface Region {
  mode: "add" | "subtract";
  polygon: Point[];
}

/** A selection drawn on a chart, kept as a filter over the chart's two axes.
 *
 * Living in the filter store rather than in the chart is what makes lasso-to-filter
 * work: the Rows panel and every histogram narrow for the same reason they narrow
 * under any other filter. The polygons are in data coordinates, so panning or zooming
 * the chart afterwards does not move the selection.
 */
export interface RegionFilter extends ElementAddress {
  column: string;
  kind: "region";
  scope: Scope;
  /** Axis columns. `ROW_INDEX` stands for the row position. */
  x: string;
  y: string;
  regions: Region[];
  inverted: boolean;
  locked: boolean;
  showFilteredOut: boolean;
}

export type Filter = NumericFilter | CategoricalFilter | BooleanFilter | RegionFilter;

/** Pseudo-column meaning "the row's position", for one-column id-versus-value charts. */
export const ROW_INDEX = "#";

export interface Selection {
  rows: Set<number>;
  columns: Set<string>;
  /** row index -> selected element indices. Unused until Stage 7. */
  elements: Map<number, Set<number>>;
  anchor: number | null;
}

export type SortDirection = "asc" | "desc";
export interface SortKey {
  column: string;
  direction: SortDirection;
}

export type ViewMode = "list" | "grid" | "patches";

export interface ColumnView {
  hidden: Set<string>;
  order: string[];
  widths: Record<string, number>;
}

export interface HistogramBin {
  lo: number;
  hi: number;
  total: number;
  /** Passing this filter and every other filter. */
  filteredIn: number;
  /** Excluded by this filter specifically. */
  excludedHere: number;
}

export interface DerivedView {
  /** Row indices passing every active filter, in current sort order. */
  visible: number[];
  /** Row indices excluded by at least one filter. */
  excluded: number[];
}

export interface TableState {
  url: string | null;
  columns: ColumnInfo[];
  rows: Row[];
  total: number;
  loading: boolean;
  error: string | null;
}
