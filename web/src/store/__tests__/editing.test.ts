import { describe, expect, it } from "vitest";
import type { ColumnInfo, Row } from "../../api/types";
import {
  cellKey, commitPayloads, editCount, groupEdits, netEdits, parseCellInput, revertGroup,
  rowsByTarget, targetKey, targetOf, type Batch,
} from "../editing";

const T = "/tables/initial";
const cell = (row: number, column: string, before: unknown, after: unknown, table = T) =>
  ({ type: "cell" as const, table, row, column, before, after });

describe("net edits", () => {
  it("keeps the original value and the latest value per cell", () => {
    const batches: Batch[] = [
      { label: "a", changes: [cell(0, "label", 0, 1)] },
      { label: "b", changes: [cell(0, "label", 1, 2)] },
    ];
    const net = netEdits(batches);
    expect(net.cells.get(cellKey(T, 0, "label"))).toMatchObject({ before: 0, after: 2 });
    expect(editCount(net)).toBe(1);
  });

  it("drops a cell changed back to where it started", () => {
    const net = netEdits([
      { label: "a", changes: [cell(0, "label", 0, 1), cell(1, "label", 1, 0)] },
      { label: "b", changes: [cell(0, "label", 1, 0)] },
    ]);
    expect([...net.cells.keys()]).toEqual([cellKey(T, 1, "label")]);
  });

  it("keeps cells of a new column even when set to the default", () => {
    const net = netEdits([
      { label: "col", changes: [{ type: "column", table: T, column: "ok", kind: "bool", default: false }] },
      { label: "set", changes: [cell(0, "ok", false, false)] },
    ]);
    expect(net.cells.size).toBe(1);
  });
});

describe("grouping and reverting", () => {
  const net = netEdits([
    { label: "labels", changes: [cell(0, "label", 0, 1), cell(1, "label", 0, 1)] },
    { label: "weights", changes: [cell(2, "weight", 1, 0)] },
    {
      label: "classes",
      changes: [{
        type: "classes", table: T, column: "label",
        before: { 0: { internal_name: "cat", display_name: "", color: "" } },
        after: {
          0: { internal_name: "cat", display_name: "", color: "" },
          1: { internal_name: "fox", display_name: "", color: "" },
        },
      }],
    },
  ]);

  it("groups by column and kind", () => {
    const titles = groupEdits(net).map((g) => g.title).sort();
    expect(titles).toEqual(['"label" — 2 cells', '"weight" — 1 cell', 'classes of "label" (+1)']);
  });

  it("reverts one group without touching the others", () => {
    const group = groupEdits(net).find((g) => g.column === "label" && g.category === "cells")!;
    const after = netEdits([
      { label: "x", changes: [...net.cells.values()] },
      { label: "discard", changes: revertGroup(net, group) },
    ]);
    expect([...after.cells.values()].map((c) => c.column)).toEqual(["weight"]);
  });
});

describe("commit payloads", () => {
  it("sends one sparse payload per table", () => {
    const net = netEdits([{
      label: "x",
      changes: [
        cell(3, "label", 0, 2),
        cell(7, "weight", 1, 0),
        cell(1, "label", 0, 1, "/tables/val"),
        { type: "column", table: T, column: "note", kind: "string", default: "" },
      ],
    }]);
    const payloads = commitPayloads(net);
    expect(payloads).toHaveLength(2);
    expect(payloads.find((p) => p.url === T)).toEqual({
      url: T,
      values: { label: { "3": 2 }, weight: { "7": 0 } },
      new_columns: { note: ["string", ""] },
      value_maps: {},
    });
  });
});

describe("row addressing", () => {
  it("maps run rows to their input table row via example_id and _src", () => {
    const rows: Row[] = [
      { _row: 0, example_id: 5, _src: 0, epoch: 0 },
      { _row: 1, example_id: 5, _src: 0, epoch: 1 },
      { _row: 2, example_id: 5, _src: 1, epoch: 0 },
    ];
    const address = { kind: "run" as const, sources: ["/train", "/val"] };
    expect(targetOf(address, rows, 1)).toEqual({ table: "/train", row: 5 });
    const map = rowsByTarget(address, rows);
    expect(map.get(targetKey("/train", 5))).toEqual([0, 1]);
    expect(map.get(targetKey("/val", 5))).toEqual([2]);
  });

  it("maps table rows to themselves", () => {
    expect(targetOf({ kind: "table", sources: [T] }, [{ _row: 0 }], 0)).toEqual({ table: T, row: 0 });
  });
});

describe("parsing typed input", () => {
  const col = (kind: ColumnInfo["kind"], extra: Partial<ColumnInfo> = {}): ColumnInfo => ({
    name: "c", kind, writable: true, default_visible: true, number_role: null, ...extra,
  });

  it("accepts class names or indices for categorical columns", () => {
    const label = col("categorical_label", {
      value_map: {
        0: { internal_name: "cat", display_name: "Cat", color: "" },
        1: { internal_name: "dog", display_name: "", color: "" },
      },
    });
    expect(parseCellInput(label, "1")).toEqual({ value: 1 });
    expect(parseCellInput(label, "dog")).toEqual({ value: 1 });
    expect(parseCellInput(label, "Cat")).toEqual({ value: 0 });
    expect(parseCellInput(label, "fox")).toHaveProperty("error");
  });

  it("validates numbers, weights and booleans", () => {
    expect(parseCellInput(col("int32"), "1.5")).toHaveProperty("error");
    expect(parseCellInput(col("sample_weight"), "-1")).toHaveProperty("error");
    expect(parseCellInput(col("sample_weight"), "0.5")).toEqual({ value: 0.5 });
    expect(parseCellInput(col("bool"), "yes")).toEqual({ value: true });
    expect(parseCellInput(col("float32"), "")).toHaveProperty("error");
  });
});
