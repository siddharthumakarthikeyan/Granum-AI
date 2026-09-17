/** Store actions for editing: change cells, classes and columns; undo; commit.
 *
 * Every action records a batch and applies it to the loaded rows immediately, so
 * filters, charts and the grid show the corrected data before anything is written.
 * Nothing reaches disk until `commit`, which sends only the net changes.
 */

import { api } from "../api/client";
import type { ColumnInfo, CommitResult, Row, ValueMap } from "../api/types";
import {
  className, commitPayloads, editCount, invert, isEditable, netEdits, revertGroup, targetKey,
  targetOf, type Batch, type Change, type EditableKind, type EditGroup, type NetEdits,
} from "./editing";
import { isFilterable, makeFilter } from "./filtering";
import { isSessionColumn } from "./session";
import type { Filter } from "./types";
import type { StoreGet, StoreSet, StoreState } from "./store";

export interface EditActions {
  /** Set one column on the given dashboard rows. Returns an error message, or null. */
  editCells: (column: string, indices: number[], value: unknown, label?: string) => string | null;
  /** Weight 0 if any given row has weight, else 1. */
  toggleWeights: (indices: number[]) => string | null;
  addColumn: (name: string, kind: EditableKind, defaultValue: unknown) => string | null;
  setClasses: (column: string, valueMap: ValueMap) => string | null;
  undo: () => void;
  redo: () => void;
  discardAll: () => void;
  /** Replay recovered batches onto the freshly loaded rows. */
  restoreEdits: (batches: Batch[]) => void;
  discardGroup: (group: EditGroup) => void;
  setForceWeight: (on: boolean) => void;
  commit: (name: string, description: string) => Promise<{ results: CommitResult[]; error: string | null }>;
  pendingEdits: () => NetEdits;
}

let netCache: { stack: Batch[]; net: NetEdits } | null = null;

function pending(stack: Batch[]): NetEdits {
  if (netCache && netCache.stack === stack) return netCache.net;
  const net = netEdits(stack);
  netCache = { stack, net };
  return net;
}

function formatValue(column: ColumnInfo | undefined, value: unknown): string {
  if (column?.kind === "categorical_label") return className(column, value);
  return typeof value === "number" && !Number.isInteger(value) ? value.toFixed(3) : String(value);
}

/** Widen a filter so an edited value is not silently filtered out or left off its widget. */
function widenFilter(filter: Filter, value: unknown): Filter {
  if (filter.kind === "numeric" && typeof value === "number" && Number.isFinite(value)) {
    const [lo, hi] = filter.bounds;
    if (value >= lo && value <= hi) return filter;
    const bounds: [number, number] = [Math.min(lo, value), Math.max(hi, value)];
    const wasOpen = filter.range[0] <= lo && filter.range[1] >= hi;
    return { ...filter, bounds, range: wasOpen ? bounds : filter.range };
  }
  if (filter.kind === "categorical" && (typeof value === "string" || typeof value === "number")) {
    if (filter.values.includes(value)) return filter;
    return { ...filter, values: [...filter.values, value].sort() };
  }
  return filter;
}

/** Apply changes to the loaded rows, columns and filters. */
function applyChanges(state: StoreState, changes: Change[], direction: "do" | "undo"): Partial<StoreState> {
  let rows = state.rows;
  let copied = false;
  const touched = new Set<number>();
  const writable = (index: number): Row => {
    if (!copied) {
      rows = rows.slice();
      copied = true;
    }
    if (!touched.has(index)) {
      rows[index] = { ...rows[index]! };
      touched.add(index);
    }
    return rows[index]!;
  };

  let columns = state.columns;
  let order = state.order;
  let filters = state.filters;
  const address = state.address;
  const newColumns: ColumnInfo[] = [];

  for (const change of changes) {
    if (change.type === "cell") {
      for (const index of state.targets.get(targetKey(change.table, change.row)) ?? []) {
        writable(index)[change.column] = change.after;
      }
      const filter = filters[change.column];
      if (filter) {
        const widened = widenFilter(filter, change.after);
        if (widened !== filter) filters = { ...filters, [change.column]: widened };
      }
    } else if (change.type === "classes") {
      columns = columns.map((c) => (c.name === change.column ? { ...c, value_map: change.after } : c));
    } else if (direction === "do") {
      if (!columns.some((c) => c.name === change.column)) {
        const info: ColumnInfo = {
          name: change.column, kind: change.kind, writable: true, default_visible: true,
          number_role: null, source: "table",
        };
        const at = columns.findIndex((c) => isSessionColumn(c.name));
        columns = at === -1 ? [...columns, info] : [...columns.slice(0, at), info, ...columns.slice(at)];
        const orderAt = order.findIndex((name) => isSessionColumn(name));
        order = orderAt === -1
          ? [...order, change.column]
          : [...order.slice(0, orderAt), change.column, ...order.slice(orderAt)];
        newColumns.push(info);
      }
      if (address) {
        for (let i = 0; i < rows.length; i += 1) {
          if (targetOf(address, rows, i)?.table === change.table) writable(i)[change.column] = change.default;
        }
      }
    } else {
      columns = columns.filter((c) => c.name !== change.column);
      order = order.filter((name) => name !== change.column);
      if (filters[change.column]) {
        filters = { ...filters };
        delete filters[change.column];
      }
      for (let i = 0; i < rows.length; i += 1) {
        if (change.column in rows[i]!) delete writable(i)[change.column];
      }
    }
  }

  for (const info of newColumns) {
    const filter = isFilterable(info) ? makeFilter(info, rows) : null;
    if (filter) filters = { ...filters, [info.name]: filter };
  }
  return { rows, columns, order, filters };
}

export function createEditActions(set: StoreSet, get: StoreGet): EditActions {
  /** Record a batch and apply it. Starting a new branch of history clears redo. */
  const record = (label: string, changes: Change[]) => {
    if (changes.length === 0) return;
    set((state) => ({
      ...applyChanges(state, changes, "do"),
      undoStack: [...state.undoStack, { label, changes }],
      redoStack: [],
    }));
  };

  const editCells: EditActions["editCells"] = (column, indices, value, label) => {
    const state = get();
    const info = state.columns.find((c) => c.name === column);
    if (!isEditable(info)) return `"${column}" is read-only`;
    if (!state.address) return "nothing is open";

    const weight = state.columns.find((c) => c.kind === "sample_weight" && isEditable(c));
    const changes: Change[] = [];
    const seen = new Set<string>();
    for (const index of indices) {
      const target = targetOf(state.address, state.rows, index);
      if (!target) continue;
      const key = targetKey(target.table, target.row);
      if (seen.has(key)) continue;
      seen.add(key);
      const row = state.rows[index]!;
      const before = row[column];
      if (before !== value) {
        changes.push({ type: "cell", table: target.table, row: target.row, column, before, after: value });
      }
      // A sample someone just corrected is, by definition, one they want trained on.
      if (
        state.forceWeightOnCorrection && weight && column !== weight.name &&
        before !== value && row[weight.name] === 0
      ) {
        changes.push({
          type: "cell", table: target.table, row: target.row, column: weight.name, before: 0, after: 1,
        });
      }
    }
    const count = seen.size;
    record(label ?? `${column} → ${formatValue(info, value)} on ${count} row${count === 1 ? "" : "s"}`, changes);
    return null;
  };

  const rebuild = (keep: Batch[]) => {
    // Revert everything, then replay what survives. Simple and exactly right, at the
    // cost of the redo history.
    set((state) => {
      let working: StoreState = state;
      for (const batch of [...state.undoStack].reverse()) {
        working = { ...working, ...applyChanges(working, invert(batch), "undo") };
      }
      for (const batch of keep) {
        working = { ...working, ...applyChanges(working, batch.changes, "do") };
      }
      return { ...working, undoStack: keep, redoStack: [] };
    });
  };

  return {
    editCells,

    toggleWeights: (indices) => {
      const { columns, rows } = get();
      const weight = columns.find((c) => c.kind === "sample_weight" && isEditable(c));
      if (!weight) return "this object has no editable weight column";
      if (indices.length === 0) return "select rows first";
      const anyOn = indices.some((i) => Number(rows[i]?.[weight.name]) > 0);
      return editCells(weight.name, indices, anyOn ? 0 : 1);
    },

    addColumn: (name, kind, defaultValue) => {
      const state = get();
      const trimmed = name.trim();
      if (!trimmed) return "give the column a name";
      if (state.columns.some((c) => c.name === trimmed) || trimmed === "_row" || trimmed === "_src") {
        return `a column named "${trimmed}" already exists`;
      }
      if (!state.address) return "nothing is open";
      record(
        `new ${kind} column "${trimmed}"`,
        state.address.sources.map((table) => ({ type: "column", table, column: trimmed, kind, default: defaultValue })),
      );
      return null;
    },

    setClasses: (column, valueMap) => {
      const state = get();
      const info = state.columns.find((c) => c.name === column);
      if (!info || info.kind !== "categorical_label" || !isEditable(info)) {
        return `"${column}" does not have editable classes`;
      }
      const names = Object.values(valueMap).map((e) => e.internal_name.trim());
      if (names.some((n) => !n)) return "every class needs a name";
      if (new Set(names).size !== names.length) return "class names must be unique";
      const removed = Object.keys(info.value_map ?? {}).filter((k) => !(k in valueMap)).map(Number);
      const inUse = removed.filter((k) => state.rows.some((row) => row[column] === k));
      if (inUse.length > 0) {
        return `relabel the rows using ${inUse.map((k) => className(info, k)).join(", ")} before removing it`;
      }
      record(
        `classes of ${column}`,
        (state.address?.sources ?? []).map((table) => ({
          type: "classes", table, column, before: info.value_map ?? {}, after: valueMap,
        })),
      );
      return null;
    },

    undo: () =>
      set((state) => {
        const batch = state.undoStack[state.undoStack.length - 1];
        if (!batch) return state;
        return {
          ...applyChanges(state, invert(batch), "undo"),
          undoStack: state.undoStack.slice(0, -1),
          redoStack: [...state.redoStack, batch],
        };
      }),

    redo: () =>
      set((state) => {
        const batch = state.redoStack[state.redoStack.length - 1];
        if (!batch) return state;
        return {
          ...applyChanges(state, batch.changes, "do"),
          undoStack: [...state.undoStack, batch],
          redoStack: state.redoStack.slice(0, -1),
        };
      }),

    discardAll: () => rebuild([]),

    restoreEdits: (batches) => rebuild(batches),

    discardGroup: (group) => {
      const net = pending(get().undoStack);
      if (group.category === "cells" || group.category === "classes") {
        record(`discard ${group.title}`, revertGroup(net, group));
        return;
      }
      // Discarding a new column discards every edit made inside it.
      const keep = get()
        .undoStack.map((batch) => ({
          ...batch,
          changes: batch.changes.filter((c) => !(c.table === group.table && c.column === group.column)),
        }))
        .filter((batch) => batch.changes.length > 0);
      rebuild(keep);
    },

    setForceWeight: (on) => set({ forceWeightOnCorrection: on }),

    pendingEdits: () => pending(get().undoStack),

    commit: async (name, description) => {
      const state = get();
      const net = pending(state.undoStack);
      if (editCount(net) === 0) return { results: [], error: "there is nothing to commit" };
      const payloads = commitPayloads(net);
      set({ committing: true });
      const results: CommitResult[] = [];
      try {
        for (const payload of payloads) {
          results.push(await api.commit({ ...payload, name: name.trim() || undefined, description }));
        }
      } catch (error) {
        set({ committing: false });
        const message = error instanceof Error ? error.message : String(error);
        const partial = results.length > 0 ? ` (${results.map((r) => r.name).join(", ")} was written first)` : "";
        return { results, error: `commit failed: ${message}${partial}` };
      }

      // The edits are written; drop them before reloading so they are not kept as a draft.
      set({ committing: false, undoStack: [], redoStack: [] });
      await get().refreshProject();
      if (state.sourceKind === "table") {
        await get().openTable(results[0]!.url, results[0]!.name, { keepView: true });
      } else if (state.sourceUrl) {
        await get().openRun(state.sourceUrl, state.sourceName, { keepView: true });
      }
      return { results, error: null };
    },
  };
}
