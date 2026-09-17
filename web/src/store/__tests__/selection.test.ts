import { describe, expect, it } from "vitest";
import {
  cloneSelection, emptySelection, escapeSelection, isEmpty,
  moveSelection, selectAll, selectRow, toggleColumn,
} from "../selection";

const visible = [0, 1, 2, 3, 4];

describe("selectRow", () => {
  it("replaces the selection on a plain click", () => {
    let s = selectRow(emptySelection(), 2, "none", visible);
    expect([...s.rows]).toEqual([2]);
    s = selectRow(s, 4, "none", visible);
    expect([...s.rows]).toEqual([4]);
  });

  it("adds and removes with ctrl", () => {
    let s = selectRow(emptySelection(), 1, "none", visible);
    s = selectRow(s, 3, "ctrl", visible);
    expect([...s.rows].sort()).toEqual([1, 3]);
    s = selectRow(s, 3, "ctrl", visible);
    expect([...s.rows]).toEqual([1]);
  });

  it("selects a range with shift, in visible order", () => {
    let s = selectRow(emptySelection(), 1, "none", visible);
    s = selectRow(s, 3, "shift", visible);
    expect([...s.rows].sort()).toEqual([1, 2, 3]);
  });

  it("selects a range backwards", () => {
    let s = selectRow(emptySelection(), 3, "none", visible);
    s = selectRow(s, 1, "shift", visible);
    expect([...s.rows].sort()).toEqual([1, 2, 3]);
  });

  it("ranges follow the filtered order, not raw row numbers", () => {
    const filtered = [7, 2, 9];
    let s = selectRow(emptySelection(), 7, "none", filtered);
    s = selectRow(s, 9, "shift", filtered);
    expect([...s.rows].sort((a, b) => a - b)).toEqual([2, 7, 9]);
  });

  it("falls back to a single selection when shift has no anchor", () => {
    const s = selectRow(emptySelection(), 2, "shift", visible);
    expect([...s.rows]).toEqual([2]);
  });
});

describe("keyboard traversal", () => {
  it("moves down and up within the visible rows", () => {
    let s = selectRow(emptySelection(), 1, "none", visible);
    s = moveSelection(s, visible, 1);
    expect([...s.rows]).toEqual([2]);
    s = moveSelection(s, visible, -1);
    expect([...s.rows]).toEqual([1]);
  });

  it("clamps at both ends", () => {
    let s = selectRow(emptySelection(), 0, "none", visible);
    s = moveSelection(s, visible, -5);
    expect([...s.rows]).toEqual([0]);
    s = selectRow(s, 4, "none", visible);
    s = moveSelection(s, visible, 5);
    expect([...s.rows]).toEqual([4]);
  });

  it("does nothing when nothing is visible", () => {
    const s = moveSelection(emptySelection(), [], 1);
    expect(isEmpty(s)).toBe(true);
  });
});

describe("escape priority", () => {
  it("clears elements first, then rows, then columns", () => {
    let s = emptySelection();
    s.rows = new Set([1, 2]);
    s.columns = new Set(["loss"]);
    s.elements = new Map([[1, new Set([0])]]);

    s = escapeSelection(s);
    expect(s.elements.size).toBe(0);
    expect(s.rows.size).toBe(2);

    s = escapeSelection(s);
    expect(s.rows.size).toBe(0);
    expect(s.columns.size).toBe(1);

    s = escapeSelection(s);
    expect(isEmpty(s)).toBe(true);
  });
});

describe("columns and select-all", () => {
  it("toggles columns with ctrl and replaces without", () => {
    let s = toggleColumn(emptySelection(), "loss", "none");
    expect([...s.columns]).toEqual(["loss"]);
    s = toggleColumn(s, "acc", "ctrl");
    expect([...s.columns].sort()).toEqual(["acc", "loss"]);
    s = toggleColumn(s, "acc", "ctrl");
    expect([...s.columns]).toEqual(["loss"]);
    s = toggleColumn(s, "iou", "none");
    expect([...s.columns]).toEqual(["iou"]);
  });

  it("select-all covers only the visible rows", () => {
    const s = selectAll(emptySelection(), [1, 3]);
    expect([...s.rows].sort()).toEqual([1, 3]);
  });
});

describe("immutability", () => {
  it("never mutates the selection it was given", () => {
    const original = emptySelection();
    original.rows = new Set([1]);
    const copy = cloneSelection(original);
    const next = selectRow(original, 2, "ctrl", visible);
    expect([...original.rows]).toEqual([...copy.rows]);
    expect([...next.rows].sort()).toEqual([1, 2]);
  });
});
