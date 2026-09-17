/** The edit model: every change is recorded, nothing is written until commit.
 *
 * Edits are kept as an undo stack of batches. A batch is one user action -- assigning a
 * label to twenty selected rows is one batch of twenty cell changes, so one undo reverts
 * all of it. What gets committed is not the stack but its net effect: a cell changed and
 * changed back is not an edit.
 *
 * Changes address the *Table* row, not the dashboard row. In a Run view one sample
 * appears once per epoch; correcting its label must correct every one of those rows,
 * and commit once.
 */

import type { ColumnInfo, Row, ValueMap } from "../api/types";

export type EditableKind = "bool" | "string" | "float32" | "int32";
export const EDITABLE_KINDS: EditableKind[] = ["bool", "string", "float32", "int32"];

export interface CellChange {
  type: "cell";
  table: string;
  row: number;
  column: string;
  before: unknown;
  after: unknown;
}

export interface ColumnChange {
  type: "column";
  table: string;
  column: string;
  kind: EditableKind;
  default: unknown;
}

export interface ClassesChange {
  type: "classes";
  table: string;
  column: string;
  before: ValueMap;
  after: ValueMap;
}

export type Change = CellChange | ColumnChange | ClassesChange;

export interface Batch {
  label: string;
  changes: Change[];
}

/** Joins key parts. A control character, so no url or column name can contain it. */
const SEP = "\u001f";

export function targetKey(table: string, row: number): string {
  return `${table}${SEP}${row}`;
}

export function cellKey(table: string, row: number, column: string): string {
  return `${table}${SEP}${row}${SEP}${column}`;
}

export interface NetEdits {
  /** key -> the original value and the value to commit. */
  cells: Map<string, CellChange>;
  columns: ColumnChange[];
  /** `${table}\0${column}` -> original and final class map. */
  classes: Map<string, ClassesChange>;
}

function sameValue(a: unknown, b: unknown): boolean {
  if (a === b) return true;
  return JSON.stringify(a) === JSON.stringify(b);
}

/** Fold a stack of batches into what a commit would write. */
export function netEdits(batches: Batch[]): NetEdits {
  const cells = new Map<string, CellChange>();
  const columns = new Map<string, ColumnChange>();
  const classes = new Map<string, ClassesChange>();

  for (const batch of batches) {
    for (const change of batch.changes) {
      if (change.type === "cell") {
        const key = cellKey(change.table, change.row, change.column);
        const first = cells.get(key);
        cells.set(key, { ...change, before: first ? first.before : change.before });
      } else if (change.type === "column") {
        columns.set(`${change.table}${SEP}${change.column}`, change);
      } else {
        const key = `${change.table}${SEP}${change.column}`;
        const first = classes.get(key);
        classes.set(key, { ...change, before: first ? first.before : change.before });
      }
    }
  }

  // A cell of a column created in this session is always an edit: its "before" is only
  // the default the column was created with, and the column itself is new.
  const created = new Set(columns.keys());
  for (const [key, change] of cells) {
    const inNewColumn = created.has(`${change.table}${SEP}${change.column}`);
    if (!inNewColumn && sameValue(change.before, change.after)) cells.delete(key);
  }
  for (const [key, change] of classes) {
    if (sameValue(change.before, change.after)) classes.delete(key);
  }
  return { cells, columns: [...columns.values()], classes };
}

export function editCount(net: NetEdits): number {
  return net.cells.size + net.columns.length + net.classes.size;
}

/** The changes that undo a batch, in reverse order. */
export function invert(batch: Batch): Change[] {
  return [...batch.changes].reverse().map((change): Change => {
    if (change.type === "cell") return { ...change, before: change.after, after: change.before };
    if (change.type === "classes") return { ...change, before: change.after, after: change.before };
    return change; // column removal is handled by the applier
  });
}

// ---------------------------------------------------------------------------
// grouping for the commit dialog
// ---------------------------------------------------------------------------

export interface EditGroup {
  key: string;
  table: string;
  column: string;
  category: "cells" | "column" | "classes";
  count: number;
  title: string;
}

/** Edits grouped the way a reviewer thinks about them: per column, per kind. */
export function groupEdits(net: NetEdits): EditGroup[] {
  const groups = new Map<string, EditGroup>();
  for (const change of net.columns) {
    const key = `column${SEP}${change.table}${SEP}${change.column}`;
    groups.set(key, {
      key, table: change.table, column: change.column, category: "column", count: 1,
      title: `new ${change.kind} column "${change.column}"`,
    });
  }
  for (const change of net.classes.values()) {
    const key = `classes${SEP}${change.table}${SEP}${change.column}`;
    const added = Object.keys(change.after).filter((k) => !(k in change.before)).length;
    const removed = Object.keys(change.before).filter((k) => !(k in change.after)).length;
    const parts = [added && `+${added}`, removed && `−${removed}`].filter(Boolean).join(" ");
    groups.set(key, {
      key, table: change.table, column: change.column, category: "classes", count: 1,
      title: `classes of "${change.column}"${parts ? ` (${parts})` : " (renamed or recoloured)"}`,
    });
  }
  for (const change of net.cells.values()) {
    const key = `cells${SEP}${change.table}${SEP}${change.column}`;
    const group = groups.get(key);
    if (group) {
      group.count += 1;
      group.title = `"${change.column}" — ${group.count} cells`;
    } else {
      groups.set(key, {
        key, table: change.table, column: change.column, category: "cells", count: 1,
        title: `"${change.column}" — 1 cell`,
      });
    }
  }
  return [...groups.values()];
}

/** Changes that return one group to its original state. */
export function revertGroup(net: NetEdits, group: EditGroup): Change[] {
  if (group.category === "cells") {
    return [...net.cells.values()]
      .filter((c) => c.table === group.table && c.column === group.column)
      .map((c) => ({ ...c, before: c.after, after: c.before }));
  }
  if (group.category === "classes") {
    const change = net.classes.get(`${group.table}${SEP}${group.column}`);
    return change ? [{ ...change, before: change.after, after: change.before }] : [];
  }
  return [];
}

// ---------------------------------------------------------------------------
// commit payloads
// ---------------------------------------------------------------------------

export interface CommitPayload {
  url: string;
  values: Record<string, Record<string, unknown>>;
  new_columns: Record<string, [EditableKind, unknown]>;
  value_maps: Record<string, ValueMap>;
}

/** One sparse payload per Table touched. Only net changes are sent. */
export function commitPayloads(net: NetEdits): CommitPayload[] {
  const byTable = new Map<string, CommitPayload>();
  const payload = (table: string) => {
    let entry = byTable.get(table);
    if (!entry) {
      entry = { url: table, values: {}, new_columns: {}, value_maps: {} };
      byTable.set(table, entry);
    }
    return entry;
  };
  for (const change of net.columns) {
    payload(change.table).new_columns[change.column] = [change.kind, change.default];
  }
  for (const change of net.classes.values()) {
    payload(change.table).value_maps[change.column] = change.after;
  }
  for (const change of net.cells.values()) {
    const values = payload(change.table).values;
    (values[change.column] ??= {})[String(change.row)] = change.after;
  }
  return [...byTable.values()];
}

// ---------------------------------------------------------------------------
// addressing: dashboard rows <-> table rows
// ---------------------------------------------------------------------------

export interface RowAddressing {
  kind: "table" | "run";
  /** Table view: the table's url. Run view: joined input urls, indexed by `_src`. */
  sources: string[];
}

export function targetOf(address: RowAddressing, rows: Row[], index: number): { table: string; row: number } | null {
  if (address.kind === "table") return { table: address.sources[0]!, row: index };
  const row = rows[index];
  const source = address.sources[Number(row?._src ?? 0)];
  const exampleId = row?.example_id;
  if (source === undefined || typeof exampleId !== "number") return null;
  return { table: source, row: exampleId };
}

/** Table row -> every dashboard row showing it. Built once per loaded object. */
export function rowsByTarget(address: RowAddressing, rows: Row[]): Map<string, number[]> {
  const out = new Map<string, number[]>();
  for (let i = 0; i < rows.length; i += 1) {
    const target = targetOf(address, rows, i);
    if (!target) continue;
    const key = `${target.table}${SEP}${target.row}`;
    const list = out.get(key);
    if (list) list.push(i);
    else out.set(key, [i]);
  }
  return out;
}

export function isEditable(column: ColumnInfo | undefined): boolean {
  return Boolean(column && column.writable && column.source !== "metrics" && column.source !== "session");
}

/** Editable as one value in a cell or the assign bar. Structured columns such as boxes
 * are editable too, but through their own editor rather than a text box. */
export function isCellEditable(column: ColumnInfo | undefined): boolean {
  return isEditable(column) && column!.kind !== "bounding_boxes_2d" && column!.kind !== "geometry_2d";
}

/** Parse what a user typed into the value a column stores, or explain why not. */
export function parseCellInput(column: ColumnInfo, text: string): { value: unknown } | { error: string } {
  const trimmed = text.trim();
  switch (column.kind) {
    case "bool":
      if (/^(true|1|yes)$/i.test(trimmed)) return { value: true };
      if (/^(false|0|no)$/i.test(trimmed)) return { value: false };
      return { error: "true or false" };
    case "int32":
    case "int64":
      return /^-?\d+$/.test(trimmed) ? { value: Number(trimmed) } : { error: "a whole number" };
    case "sample_weight": {
      const value = Number(trimmed);
      return trimmed !== "" && Number.isFinite(value) && value >= 0
        ? { value }
        : { error: "a number ≥ 0" };
    }
    case "float32": {
      const value = Number(trimmed);
      return trimmed !== "" && Number.isFinite(value) ? { value } : { error: "a number" };
    }
    case "categorical_label": {
      const map = column.value_map ?? {};
      if (trimmed in map) return { value: Number(trimmed) };
      const byName = Object.entries(map).find(
        ([, entry]) => entry.internal_name === trimmed || entry.display_name === trimmed,
      );
      return byName ? { value: Number(byName[0]) } : { error: "one of the column's classes" };
    }
    default:
      return { value: text };
  }
}

export function defaultFor(kind: EditableKind): unknown {
  return kind === "bool" ? false : kind === "string" ? "" : 0;
}

/** The name shown for a class index: display name, internal name, or the raw index. */
export function className(column: ColumnInfo | undefined, value: unknown): string {
  const entry = column?.value_map?.[String(value)];
  if (!entry) return value === null || value === undefined ? "" : String(value);
  return entry.display_name || entry.internal_name;
}
