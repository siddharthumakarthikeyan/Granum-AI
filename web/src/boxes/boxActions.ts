/** Box edits, built on the cell edit stack.
 *
 * A box edit replaces the whole geometry value of one row, so undo, redo, discard and
 * commit work for boxes exactly as they do for labels -- one code path, one history.
 *
 * Predictions live in metrics and are read-only. Accepting one writes it into the
 * ground-truth column; rejecting one only dismisses it for this session.
 */

import type { Row } from "../api/types";
import type { StoreGet, StoreSet, StoreState } from "../store/store";
import { asBoxValue, type BoxInstance, type BoxValue } from "./model";

export type ReviewDecision = "accept" | "reject";

export interface PredictionRef {
  row: number;
  index: number;
}

export interface BoxActions {
  addBox: (row: number, column: string, vertices: number[], label: number) => string | null;
  updateBox: (row: number, column: string, index: number, patch: Partial<BoxInstance>) => string | null;
  deleteBoxes: (row: number, column: string, indices: number[]) => string | null;
  copyBox: (cut: boolean) => string | null;
  pasteBoxes: (row: number) => string | null;
  /** Accept or reject predictions now, or stage the decision for review. */
  reviewPredictions: (refs: PredictionRef[], decision: ReviewDecision, staged: boolean) => string | null;
  applyStaged: () => string | null;
  clearStaged: () => void;
  applyNms: (rows: number[], column: string, iouThreshold: number) => { removed: number; error: string | null };
  /** Relabel many boxes at once, one undo step. */
  relabelBoxes: (refs: PredictionRef[], column: string, label: number) => string | null;
}

export interface BoxState {
  boxClipboard: { instances: BoxInstance[]; width: number; height: number } | null;
  /** `${row}:${index}` of predictions dismissed this session. */
  dismissed: Set<string>;
  /** `${row}:${index}` -> staged decision. */
  staged: Map<string, ReviewDecision>;
}

export const predictionKey = (row: number, index: number) => `${row}:${index}`;

export function iou(a: number[], b: number[]): number {
  const [ax0 = 0, ay0 = 0, ax1 = 0, ay1 = 0] = a;
  const [bx0 = 0, by0 = 0, bx1 = 0, by1 = 0] = b;
  const iw = Math.max(0, Math.min(ax1, bx1) - Math.max(ax0, bx0));
  const ih = Math.max(0, Math.min(ay1, by1) - Math.max(ay0, by0));
  const inter = iw * ih;
  const union = (ax1 - ax0) * (ay1 - ay0) + (bx1 - bx0) * (by1 - by0) - inter;
  return union > 0 ? inter / union : 0;
}

/** Class-aware NMS. Higher score first; ties keep the earlier box. Returns kept indices. */
export function nmsIndices(instances: BoxInstance[], threshold: number): number[] {
  const order = instances
    .map((instance, index) => ({ index, score: typeof instance.confidence === "number" ? instance.confidence : 1 }))
    .sort((a, b) => b.score - a.score || a.index - b.index)
    .map((entry) => entry.index);
  const suppressed = new Set<number>();
  const keep: number[] = [];
  for (const i of order) {
    if (suppressed.has(i)) continue;
    keep.push(i);
    for (const j of order) {
      if (j === i || suppressed.has(j) || keep.includes(j)) continue;
      if (instances[j]!.label === instances[i]!.label && iou(instances[i]!.vertices, instances[j]!.vertices) > threshold) {
        suppressed.add(j);
      }
    }
  }
  return keep.sort((a, b) => a - b);
}

/** Merge accepted predictions into ground truth. A prediction overlapping an existing box
 * (IoU >= 0.5, any class) replaces it -- that is how a wrong class or a sloppy box gets
 * fixed in one keystroke. Otherwise it is added. */
export function mergeAccepted(truth: BoxInstance[], accepted: BoxInstance[], replaceIou = 0.5): BoxInstance[] {
  const out = truth.map((instance) => ({ ...instance }));
  const replaced = new Set<number>();
  for (const prediction of accepted) {
    let best = -1;
    let bestIou = replaceIou;
    out.forEach((instance, i) => {
      if (replaced.has(i)) return;
      const overlap = iou(instance.vertices, prediction.vertices);
      if (overlap >= bestIou) {
        best = i;
        bestIou = overlap;
      }
    });
    const fresh: BoxInstance = { vertices: [...prediction.vertices], label: prediction.label };
    if (best >= 0) {
      out[best] = { ...out[best]!, vertices: fresh.vertices, label: fresh.label };
      replaced.add(best);
    } else {
      out.push(fresh);
    }
  }
  return out;
}

function clampBox(vertices: number[], value: BoxValue): number[] {
  const [x0 = 0, y0 = 0, x1 = 0, y1 = 0] = vertices;
  const w = value.width || Infinity;
  const h = value.height || Infinity;
  const lo = (v: number, max: number) => Math.min(Math.max(v, 0), max);
  return [lo(Math.min(x0, x1), w), lo(Math.min(y0, y1), h), lo(Math.max(x0, x1), w), lo(Math.max(y0, y1), h)];
}

export function createBoxActions(set: StoreSet, get: StoreGet): BoxActions {
  const truthColumn = (state: StoreState) =>
    state.columns.find((c) => c.kind === "bounding_boxes_2d" && c.writable && c.source !== "metrics");
  const predictedColumn = (state: StoreState) =>
    state.columns.find((c) => c.kind === "bounding_boxes_2d" && c.source === "metrics");

  const valueOf = (row: Row | undefined, column: string): BoxValue | null => asBoxValue(row?.[column]);

  const write = (row: number, column: string, instances: BoxInstance[], label: string) => {
    const state = get();
    const current = valueOf(state.rows[row], column);
    if (!current) return "this row has no box value to edit";
    return state.editCells(column, [row], { ...current, instances }, label);
  };

  return {
    addBox: (row, column, vertices, label) => {
      const current = valueOf(get().rows[row], column);
      if (!current) return "this row has no box value to edit";
      const box = clampBox(vertices, current);
      if (box[2]! - box[0]! < 1 || box[3]! - box[1]! < 1) return "box is too small";
      return write(row, column, [...current.instances, { vertices: box, label }], "draw box");
    },

    updateBox: (row, column, index, patch) => {
      const current = valueOf(get().rows[row], column);
      const instance = current?.instances[index];
      if (!current || !instance) return "no such box";
      const next = { ...instance, ...patch };
      if (patch.vertices) next.vertices = clampBox(patch.vertices, current);
      const instances = current.instances.map((item, i) => (i === index ? next : item));
      return write(row, column, instances, patch.label !== undefined && !patch.vertices ? "relabel box" : "move box");
    },

    deleteBoxes: (row, column, indices) => {
      const current = valueOf(get().rows[row], column);
      if (!current) return "no such box";
      const drop = new Set(indices);
      const problem = write(row, column, current.instances.filter((_, i) => !drop.has(i)), `delete ${drop.size} box${drop.size === 1 ? "" : "es"}`);
      if (!problem) set({ focusedInstance: null });
      return problem;
    },

    copyBox: (cut) => {
      const state = get();
      const focused = state.focusedInstance;
      if (!focused) return "select a box first";
      const value = valueOf(state.rows[focused.row], focused.column);
      const instance = value?.instances[focused.index];
      if (!value || !instance) return "no such box";
      set({ boxClipboard: { instances: [{ vertices: [...instance.vertices], label: instance.label }], width: value.width, height: value.height } });
      if (cut) {
        const truth = truthColumn(state);
        if (focused.column !== truth?.name) return "predictions cannot be cut; copied instead";
        return get().deleteBoxes(focused.row, focused.column, [focused.index]);
      }
      return null;
    },

    pasteBoxes: (row) => {
      const state = get();
      const clip = state.boxClipboard;
      const truth = truthColumn(state);
      if (!clip) return "nothing copied";
      if (!truth) return "there is no editable box column";
      const current = valueOf(state.rows[row], truth.name);
      if (!current) return "this row has no box value to edit";
      // Same relative position on an image of a different size.
      const sx = clip.width && current.width ? current.width / clip.width : 1;
      const sy = clip.height && current.height ? current.height / clip.height : 1;
      const pasted = clip.instances.map((instance) => {
        const [x0 = 0, y0 = 0, x1 = 0, y1 = 0] = instance.vertices;
        return { vertices: clampBox([x0 * sx, y0 * sy, x1 * sx, y1 * sy], current), label: instance.label };
      });
      return write(row, truth.name, [...current.instances, ...pasted], "paste box");
    },

    reviewPredictions: (refs, decision, staged) => {
      const state = get();
      const truth = truthColumn(state);
      const predicted = predictedColumn(state);
      if (!predicted) return "there are no predictions";
      if (refs.length === 0) return "no predictions in scope";

      if (staged) {
        const next = new Map(state.staged);
        for (const ref of refs) next.set(predictionKey(ref.row, ref.index), decision);
        set({ staged: next });
        return null;
      }

      if (decision === "reject") {
        const dismissed = new Set(state.dismissed);
        for (const ref of refs) dismissed.add(predictionKey(ref.row, ref.index));
        set({ dismissed });
        return null;
      }

      if (!truth) return "there is no editable ground-truth column";
      // Group by the Table row, so a sample seen in several epochs is merged once.
      const byRow = new Map<number, BoxInstance[]>();
      for (const ref of refs) {
        const instance = valueOf(state.rows[ref.row], predicted.name)?.instances[ref.index];
        if (!instance) continue;
        const list = byRow.get(ref.row) ?? [];
        list.push(instance);
        byRow.set(ref.row, list);
      }
      let problem: string | null = null;
      // One undo step per row keeps multi-row accepts reversible row by row.
      for (const [row, accepted] of byRow) {
        const current = valueOf(get().rows[row], truth.name);
        if (!current) continue;
        problem = get().editCells(truth.name, [row], { ...current, instances: mergeAccepted(current.instances, accepted) },
          `accept ${accepted.length} prediction${accepted.length === 1 ? "" : "s"}`) ?? problem;
      }
      const dismissed = new Set(get().dismissed);
      for (const ref of refs) dismissed.add(predictionKey(ref.row, ref.index));
      set({ dismissed });
      return problem;
    },

    applyStaged: () => {
      const state = get();
      if (state.staged.size === 0) return "nothing staged";
      const accepts: PredictionRef[] = [];
      const rejects: PredictionRef[] = [];
      for (const [key, decision] of state.staged) {
        const [row, index] = key.split(":").map(Number) as [number, number];
        (decision === "accept" ? accepts : rejects).push({ row, index });
      }
      set({ staged: new Map() });
      const problem = accepts.length ? get().reviewPredictions(accepts, "accept", false) : null;
      if (rejects.length) get().reviewPredictions(rejects, "reject", false);
      return problem;
    },

    clearStaged: () => set({ staged: new Map() }),

    relabelBoxes: (refs, column, label) => {
      const state = get();
      const byRow = new Map<number, Set<number>>();
      for (const ref of refs) byRow.set(ref.row, (byRow.get(ref.row) ?? new Set()).add(ref.index));
      // Several rows are several cells; one batch keeps it a single undo step.
      const changesBefore = state.undoStack.length;
      let problem: string | null = null;
      for (const [row, indices] of byRow) {
        const current = valueOf(get().rows[row], column);
        if (!current) continue;
        const instances = current.instances.map((instance, i) => (indices.has(i) ? { ...instance, label } : instance));
        problem = get().editCells(column, [row], { ...current, instances }, "relabel boxes") ?? problem;
      }
      // Merge the per-row batches into one.
      const stack = get().undoStack;
      if (stack.length - changesBefore > 1) {
        const merged = { label: `relabel ${refs.length} box${refs.length === 1 ? "" : "es"}`, changes: stack.slice(changesBefore).flatMap((b) => b.changes) };
        set({ undoStack: [...stack.slice(0, changesBefore), merged] });
      }
      return problem;
    },

    applyNms: (rows, column, iouThreshold) => {
      let removed = 0;
      let error: string | null = null;
      const seen = new Set<string>();
      for (const row of rows) {
        const state = get();
        const target = state.address && state.rows[row] ? `${state.rows[row]!._src ?? 0}:${state.rows[row]!.example_id ?? row}` : String(row);
        if (seen.has(target)) continue; // same sample in another epoch
        seen.add(target);
        const current = valueOf(state.rows[row], column);
        if (!current || current.instances.length < 2) continue;
        const keep = nmsIndices(current.instances, iouThreshold);
        if (keep.length === current.instances.length) continue;
        removed += current.instances.length - keep.length;
        error = write(row, column, keep.map((i) => current.instances[i]!), `NMS at IoU ${iouThreshold}`) ?? error;
      }
      return { removed, error };
    },
  };
}
