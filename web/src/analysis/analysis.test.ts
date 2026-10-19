import { beforeEach, describe, expect, it } from "vitest";
import type { ColumnInfo, Row } from "../api/types";
import { scatterSpec } from "../charts/spec";
import { useStore } from "../store/store";
import { emptySelection } from "../store/selection";
import { rowsByTarget } from "../store/editing";
import { materializeColumns, parseVirtualColumns, type VirtualColumn } from "./virtualColumns";
import { reconcileAnalysis } from "./state";
import { captureWorkflow, parseWorkflow, validateWorkflow, workflowView } from "./workflows";

const col = (name: string): ColumnInfo => ({ name, kind: "float32", source: "table", writable: true, default_visible: true, number_role: null });
const columns = [col("loss"), col("objects"), col("epoch"), col("example_id")];
const rows: Row[] = [
  { _row: 0, _src: 0, loss: 8, objects: 2, epoch: 2, example_id: 1 },
  { _row: 1, _src: 0, loss: 4, objects: 2, epoch: 1, example_id: 1 },
  { _row: 2, _src: 1, loss: 2, objects: 0, epoch: 1, example_id: 1 },
  { _row: 3, _src: 0, loss: null, objects: 1, epoch: 1, example_id: 2 },
];
const ratio: VirtualColumn = { name: "ratio", operation: "divide", inputs: ["loss", "objects"], groupBy: [] };

describe("calculated columns", () => {
  it("chains calculations, preserves missing values, and never mutates source rows", () => {
    const result = materializeColumns(rows, columns, [ratio, { name: "rank", operation: "rank", inputs: ["ratio"], groupBy: [] }]);
    expect(result.rows.map(r => r.ratio)).toEqual([4, 2, null, null]);
    expect(result.rows.map(r => r.rank)).toEqual([2, 1, null, null]);
    expect(rows[0]).not.toHaveProperty("ratio");
    expect(result.columns.at(-1)?.writable).toBe(false);
  });
  it("orders temporal calculations by epoch and keeps equal sample ids in different datasets separate", () => {
    const result = materializeColumns(rows, columns, [{ name: "delta", operation: "difference", inputs: ["loss"], groupBy: ["_src", "example_id"], orderBy: "epoch" }]);
    expect(result.rows.map(r => r.delta)).toEqual([4, null, null, null]);
  });
  it("handles rank ties, missing groups and group aggregates over all rows", () => {
    const result = materializeColumns([...rows, { ...rows[0]!, _row: 4 }], columns, [
      { name: "rank", operation: "rank", inputs: ["loss"], groupBy: [] },
      { name: "mean", operation: "group_mean", inputs: ["loss"], groupBy: ["_src"] },
    ]);
    expect(result.rows.map(r => r.rank)).toEqual([3.5, 2, 1, null, 3.5]);
    expect(result.rows[0]!.mean).toBeCloseTo(20 / 3);
    expect(result.rows[2]!.mean).toBe(2);
  });
  it("rejects cycles, unknown operations, collisions and reserved names", () => {
    expect(() => materializeColumns(rows, columns, [{ ...ratio, inputs: ["ratio", "loss"] }])).toThrow("needs ratio");
    expect(() => materializeColumns(rows, columns, [{ ...ratio, name: "loss" }])).toThrow("already exists");
    expect(() => parseVirtualColumns([{ ...ratio, operation: "eval" }])).toThrow();
    expect(() => parseVirtualColumns([{ ...ratio, name: "__proto__" }])).toThrow();
  });
});

describe("reactive workspace analysis", () => {
  beforeEach(() => useStore.setState({ rows, columns, order: columns.map(c => c.name), virtualColumns: [],
    analysisError: null, filters: {}, charts: [], sort: [], hidden: new Set(), selection: emptySelection(),
    address: { kind: "table", sources: ["table"] }, sourceUrl: "table", sourceKind: "table", filterBasis: rows,
    targets: rowsByTarget({ kind: "table", sources: ["table"] }, rows), undoStack: [], redoStack: [],
  }));
  it("recomputes atomically after data changes while preserving active numeric filters", () => {
    expect(useStore.getState().setVirtualColumns([ratio])).toBeNull();
    const state = useStore.getState();
    const patch = reconcileAnalysis(state, { rows: rows.map((r, i) => i === 0 ? { ...r, loss: 20 } : r) });
    expect(patch.rows![0]!.ratio).toBe(10);
    expect(state.rows[0]!.ratio).toBe(4);
    expect(patch.filters!.ratio!.kind).toBe("numeric");
  });
  it("updates calculations through actual edit, undo and redo actions", () => {
    const store = useStore.getState();
    expect(store.setVirtualColumns([ratio])).toBeNull();
    expect(store.editCells("loss", [0], 20)).toBeNull();
    expect(useStore.getState().rows[0]!.ratio).toBe(10);
    store.undo();
    expect(useStore.getState().rows[0]!.ratio).toBe(4);
    store.redo();
    expect(useStore.getState().rows[0]!.ratio).toBe(10);
  });
  it("hides stale calculations when undo removes an input and restores them when the input returns", () => {
    useStore.getState().setVirtualColumns([ratio]);
    const state = useStore.getState();
    const missing = reconcileAnalysis(state, { columns: state.columns.filter(c => c.name !== "objects") });
    expect(missing.analysisError).toContain("objects");
    expect(missing.rows![0]).not.toHaveProperty("ratio");
    const restored = reconcileAnalysis({ ...state, ...missing }, { columns });
    expect(restored.analysisError).toBeNull();
    expect(restored.rows![0]!.ratio).toBe(4);
  });
  it("round-trips a portable analysis setup and rejects incompatible schemas", () => {
    useStore.getState().setVirtualColumns([ratio]);
    useStore.setState({ charts: [scatterSpec("epoch", "ratio")] });
    const state = useStore.getState();
    const workflow = parseWorkflow(JSON.parse(JSON.stringify(captureWorkflow(state, "Loss review"))));
    expect(() => validateWorkflow(workflow, state)).not.toThrow();
    expect(workflowView(workflow, state).charts![0]!.kind).toBe("scatter");
    expect(() => validateWorkflow(workflow, { ...state, columns: [col("epoch")] })).toThrow();
    expect(JSON.stringify(workflow)).not.toContain('"rows"');
    expect(() => parseWorkflow({ ...workflow, charts: [{ ...workflow.charts[0], pointSize: Infinity }] })).toThrow();
  });
});
