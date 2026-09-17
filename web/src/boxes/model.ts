/** Boxes as the dashboard sees them: which column is truth, which is prediction, and
 * how each box should be drawn.
 *
 * Roles are what a reviewer scans for, so they drive the default styling:
 *   truth      solid cyan     a labelled object
 *   missed     solid amber    a labelled object no prediction matched
 *   matched    dashed cyan    a prediction that found a labelled object
 *   unmatched  dashed pink    a prediction with no labelled object -- a false positive,
 *                             or an object nobody labelled
 * Cyan, amber and pink are the validated categorical trio; dash style and the label
 * text are secondary encodings, so no role depends on colour alone.
 */

import type { ColumnInfo, Row } from "../api/types";
import { className } from "../store/editing";
import { instancePasses } from "../store/filtering";
import type { Filter } from "../store/types";

export interface BoxInstance {
  vertices: number[];
  label: number | null;
  [property: string]: unknown;
}

export interface BoxValue {
  width: number;
  height: number;
  instances: BoxInstance[];
}

export type BoxRole = "truth" | "missed" | "matched" | "unmatched" | "skip" | "skipped";

export const ROLE_STYLE: Record<BoxRole, { color: string; dash: string | null; label: string }> = {
  truth: { color: "#22d3ee", dash: null, label: "labelled" },
  missed: { color: "#fbbf24", dash: null, label: "labelled, missed by the model" },
  matched: { color: "#22d3ee", dash: "6 4", label: "predicted, matches a label" },
  unmatched: { color: "#f472b6", dash: "6 4", label: "predicted, matches no label" },
  skip: { color: "#6b7786", dash: "2 3", label: "an area to skip: not scored" },
  skipped: { color: "#6b7786", dash: "6 4", label: "predicted inside an area to skip: not scored" },
};

/** Plain names for the legend. */
export const ROLE_NAMES: Record<BoxRole, string> = {
  truth: "Label", missed: "False negative", matched: "True positive",
  unmatched: "False positive", skip: "Ignore region", skipped: "In ignore region",
};

export function isBoxColumn(column: ColumnInfo | undefined): boolean {
  return column?.kind === "bounding_boxes_2d";
}

export function asBoxValue(value: unknown): BoxValue | null {
  if (!value || typeof value !== "object" || !Array.isArray((value as BoxValue).instances)) return null;
  return value as BoxValue;
}

/** The ground-truth column (editable data) and the prediction column (metrics), if any. */
export function boxColumns(columns: ColumnInfo[]): { truth: ColumnInfo | null; predicted: ColumnInfo | null } {
  const boxes = columns.filter(isBoxColumn);
  const predicted = boxes.find((c) => c.source === "metrics") ?? null;
  const truth = boxes.find((c) => c !== predicted) ?? null;
  return { truth, predicted };
}

export interface BoxDisplay {
  showTruth: boolean;
  showPredicted: boolean;
  /** Predictions below this confidence are not drawn. */
  minConfidence: number;
  annotate: "all" | "selected" | "none";
  colorBy: "role" | "class";
  /** Instance property scaling each box's opacity, e.g. confidence. */
  opacityBy: string | null;
}

export const DEFAULT_BOX_DISPLAY: BoxDisplay = {
  showTruth: true,
  showPredicted: true,
  minConfidence: 0.25,
  // Crowded scenes turn into unreadable text with every box labelled.
  annotate: "selected",
  colorBy: "role",
  opacityBy: null,
};

export interface InstanceRef {
  column: string;
  index: number;
}

export interface DrawnBox extends InstanceRef {
  role: BoxRole;
  x0: number;
  y0: number;
  x1: number;
  y1: number;
  label: number | null;
  text: string;
  color: string;
  dash: string | null;
  opacity: number;
  confidence: number | null;
  iou: number | null;
  /** A staged review decision on a prediction. */
  staged?: "accept" | "reject";
}

const CLASS_HUES = ["#22d3ee", "#f472b6", "#fbbf24"];

export function classColor(column: ColumnInfo, label: number | null): string {
  const entry = label === null ? undefined : column.value_map?.[String(label)];
  if (entry?.color) return entry.color;
  // Without a class colour the hue is a hint only; the label text carries identity.
  return CLASS_HUES[Math.abs(label ?? 0) % CLASS_HUES.length]!;
}

function clamp01(value: unknown): number {
  const n = typeof value === "number" && Number.isFinite(value) ? value : 1;
  return Math.min(1, Math.max(0.15, n));
}

/** Every box to draw for one row, ground truth first. */
export function drawnBoxes(
  row: Row | undefined,
  truth: ColumnInfo | null,
  predicted: ColumnInfo | null,
  display: BoxDisplay,
  /** Element filters: instances failing them are not drawn. */
  filters: Filter[] = [],
  review: { row: number; dismissed: Set<string>; staged: Map<string, "accept" | "reject"> } | null = null,
): DrawnBox[] {
  if (!row) return [];
  const out: DrawnBox[] = [];
  const truthValue = truth ? asBoxValue(row[truth.name]) : null;
  const predictedValue = predicted ? asBoxValue(row[predicted.name]) : null;
  const gtMatch = Array.isArray(row.gt_match) ? (row.gt_match as number[]) : null;
  // gt_match describes the ground truth the metrics were computed on; after an edit that
  // adds or removes boxes it no longer lines up, and "missed" would be a guess.
  const matchValid = gtMatch !== null && truthValue !== null && gtMatch.length === truthValue.instances.length;

  const push = (column: ColumnInfo, index: number, instance: BoxInstance, role: BoxRole) => {
    const [x0 = 0, y0 = 0, x1 = 0, y1 = 0] = instance.vertices;
    const confidence = typeof instance.confidence === "number" ? instance.confidence : null;
    const iou = typeof instance.iou === "number" ? instance.iou : null;
    const name = className(column, instance.label);
    const style = ROLE_STYLE[role];
    out.push({
      column: column.name, index, role, x0, y0, x1, y1, label: instance.label,
      text: confidence !== null ? `${name} ${confidence.toFixed(2)}` : name,
      color: display.colorBy === "class" ? classColor(column, instance.label) : style.color,
      dash: style.dash,
      opacity: display.opacityBy ? clamp01(instance[display.opacityBy]) : 1,
      confidence, iou,
    });
  };

  if (truth && truthValue && display.showTruth) {
    truthValue.instances.forEach((instance, i) => {
      if (!instancePasses(row, truth.name, i, filters)) return;
      const role = instance.iscrowd || (matchValid && gtMatch![i] === -2)
        ? "skip"
        : predictedValue && matchValid && gtMatch![i] === -1 ? "missed" : "truth";
      push(truth, i, instance, role);
    });
  }
  if (predicted && predictedValue && display.showPredicted) {
    predictedValue.instances.forEach((instance, i) => {
      const confidence = typeof instance.confidence === "number" ? instance.confidence : 1;
      if (confidence < display.minConfidence) return;
      if (!instancePasses(row, predicted.name, i, filters)) return;
      const key = review ? `${review.row}:${i}` : "";
      if (review?.dismissed.has(key)) return;
      push(predicted, i, instance, instance.matched ? "matched" : instance.ignored ? "skipped" : "unmatched");
      const decision = review?.staged.get(key);
      if (decision) {
        const drawn = out[out.length - 1]!;
        drawn.staged = decision;
        drawn.text = `${decision === "accept" ? "✓" : "✗"} ${drawn.text}`;
      }
    });
  }
  return out;
}

/** "3 · person ×2, car" */
export function summarizeBoxes(value: unknown, column: ColumnInfo): string {
  const boxes = asBoxValue(value);
  if (!boxes) return "";
  if (boxes.instances.length === 0) return "0";
  const counts = new Map<string, number>();
  for (const instance of boxes.instances) {
    const name = className(column, instance.label);
    counts.set(name, (counts.get(name) ?? 0) + 1);
  }
  const parts = [...counts].sort((a, b) => b[1] - a[1]).map(([name, n]) => (n > 1 ? `${name} ×${n}` : name));
  return `${boxes.instances.length} · ${parts.join(", ")}`;
}
