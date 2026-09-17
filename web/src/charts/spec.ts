/** What a chart is, independent of how it is drawn.
 *
 * Specs are plain data so they can be cloned, compared and saved as favourites.
 */

import type { ColumnInfo } from "../api/types";
import { isFilterable, isNumericColumn } from "../store/filtering";
import { ROW_INDEX } from "../store/types";

/** Drag payload type for a column header dropped onto a chart. */
export const COLUMN_DRAG_TYPE = "application/x-granum-column";

export type Tool = "pan" | "rect" | "lasso" | "polygon" | "brush";

/** Categories that get a colour slot. Only three categorical hues stay tellable apart in
 * a scatter on this surface (validated all-pairs, including colour-vision deficiency);
 * every other category draws as neutral "other" until promoted from the legend. */
export const COLOR_SLOTS = 3;

export interface ScatterSpec {
  id: string;
  kind: "scatter";
  x: string;
  y: string;
  color: string | null;
  size: string | null;
  pointSize: number;
  /** Fixed-length slot table: slots[i] is the category drawn in hue i, or null. */
  slots: (string | number | null)[] | null;
  showFilteredOut: boolean;
  locked: boolean;
  overlays: string[];
}

export interface ImageSpec {
  id: string;
  kind: "image";
  image: string;
  /** Columns written in the image corners. */
  labels: string[];
  locked: boolean;
  overlays: string[];
}

export type ChartSpec = ScatterSpec | ImageSpec;

let counter = 0;
export function newChartId(): string {
  counter += 1;
  return `chart-${Date.now().toString(36)}-${counter}`;
}

export function scatterSpec(x: string, y: string, color: string | null = null): ScatterSpec {
  return {
    id: newChartId(),
    kind: "scatter",
    x,
    y,
    color,
    size: null,
    pointSize: 3,
    slots: null,
    showFilteredOut: false,
    locked: false,
    overlays: [],
  };
}

/** Corner labels for an image chart: the label and the prediction when they exist. */
export function defaultImageLabels(columns: ColumnInfo[]): string[] {
  const names = columns.map((c) => c.name);
  const preferred = ["label", "predicted", "loss", "confidence"].filter((n) => names.includes(n));
  if (preferred.length > 0) return preferred;
  return columns
    .filter((c) => c.kind !== "image" && c.kind !== "embedding")
    .slice(0, 2)
    .map((c) => c.name);
}

/** Build a chart from the columns selected in the Rows panel, in the order they were
 * selected:
 *
 *   one numeric   -> row position versus that value
 *   two numerics  -> first on x, second on y
 *   a third column -> colour by it
 *   an image column alone -> an image chart
 *
 * Returns a message instead of a spec when the selection cannot make a chart.
 */
export function chartFromColumns(selected: string[], columns: ColumnInfo[]): ChartSpec | string {
  const byName = new Map(columns.map((c) => [c.name, c]));
  const picked = selected.map((n) => byName.get(n)).filter((c): c is ColumnInfo => Boolean(c));

  if (picked.length === 0) {
    return "Select 1–3 columns first: click a header, ctrl+click to add more";
  }

  const image = picked.find((c) => c.kind === "image");
  const numeric = picked.filter(isNumericColumn);

  if (image && numeric.length === 0) {
    return {
      id: newChartId(),
      kind: "image",
      image: image.name,
      labels: defaultImageLabels(columns),
      locked: false,
      overlays: [],
    };
  }

  if (numeric.length === 0) {
    return `A scatter needs a numeric column; ${picked.map((c) => c.name).join(", ")} ${picked.length === 1 ? "is" : "are"} not numeric`;
  }

  const [first, second] = numeric;
  const colorColumn = picked.find(
    (c, i) => i >= 2 && isFilterable(c) && c !== first && c !== second,
  );

  if (numeric.length === 1) {
    const other = picked.find((c) => c !== first && isFilterable(c));
    return scatterSpec(ROW_INDEX, first!.name, other ? other.name : null);
  }
  return scatterSpec(first!.name, second!.name, colorColumn ? colorColumn.name : null);
}

/** Two specs draw the same chart. Used to recognise a favourite. */
export function chartSignature(spec: ChartSpec): string {
  return spec.kind === "scatter"
    ? `scatter|${spec.x}|${spec.y}|${spec.color ?? ""}|${spec.size ?? ""}`
    : `image|${spec.image}`;
}

export function chartColumns(spec: ChartSpec): string[] {
  const out = spec.kind === "scatter"
    ? [spec.x, spec.y, spec.color, spec.size]
    : [spec.image, ...spec.labels];
  return out.filter((c): c is string => c !== null && c !== ROW_INDEX);
}
