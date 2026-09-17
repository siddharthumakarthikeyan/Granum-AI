/** Pure selection logic, shared by every panel.
 *
 * Element selection (a bounding box inside a row) is modelled here from the start.
 * Stage 4 never populates it, but Escape already knows the priority order it will need
 * in Stage 7: elements first, then rows, then columns.
 */

import type { Selection } from "./types";

export function emptySelection(): Selection {
  return { rows: new Set(), columns: new Set(), elements: new Map(), anchor: null };
}

export function cloneSelection(selection: Selection): Selection {
  return {
    rows: new Set(selection.rows),
    columns: new Set(selection.columns),
    elements: new Map([...selection.elements].map(([k, v]) => [k, new Set(v)])),
    anchor: selection.anchor,
  };
}

export type ClickModifier = "none" | "ctrl" | "shift";

/** Apply a click on a row, given the currently visible ordering. */
export function selectRow(
  selection: Selection,
  row: number,
  modifier: ClickModifier,
  visible: number[],
): Selection {
  const next = cloneSelection(selection);

  if (modifier === "ctrl") {
    if (next.rows.has(row)) next.rows.delete(row);
    else next.rows.add(row);
    next.anchor = row;
    return next;
  }

  if (modifier === "shift" && next.anchor !== null) {
    const from = visible.indexOf(next.anchor);
    const to = visible.indexOf(row);
    if (from !== -1 && to !== -1) {
      const [lo, hi] = from <= to ? [from, to] : [to, from];
      next.rows = new Set(visible.slice(lo, hi + 1));
      return next;
    }
  }

  next.rows = new Set([row]);
  next.anchor = row;
  return next;
}

export function selectAll(selection: Selection, visible: number[]): Selection {
  const next = cloneSelection(selection);
  next.rows = new Set(visible);
  return next;
}

export function moveSelection(
  selection: Selection,
  visible: number[],
  delta: number,
): Selection {
  const next = cloneSelection(selection);
  if (visible.length === 0) return next;
  const current = next.anchor === null ? -1 : visible.indexOf(next.anchor);
  const target = Math.min(visible.length - 1, Math.max(0, current + delta));
  const row = visible[target]!;
  next.rows = new Set([row]);
  next.anchor = row;
  return next;
}

export function toggleColumn(
  selection: Selection,
  column: string,
  modifier: ClickModifier,
): Selection {
  const next = cloneSelection(selection);
  if (modifier === "ctrl") {
    if (next.columns.has(column)) next.columns.delete(column);
    else next.columns.add(column);
    return next;
  }
  next.columns = new Set([column]);
  return next;
}

/** What Escape clears, in priority order.
 *
 * Elements first, then rows, then columns. One keystroke should peel back one layer,
 * not wipe everything -- a user who lassoed boxes inside a selected row expects the
 * boxes to clear first.
 */
export function escapeSelection(selection: Selection): Selection {
  const next = cloneSelection(selection);
  if (next.elements.size > 0) {
    next.elements = new Map();
    return next;
  }
  if (next.rows.size > 0) {
    next.rows = new Set();
    next.anchor = null;
    return next;
  }
  next.columns = new Set();
  return next;
}

export function isEmpty(selection: Selection): boolean {
  return (
    selection.rows.size === 0 &&
    selection.columns.size === 0 &&
    selection.elements.size === 0
  );
}
