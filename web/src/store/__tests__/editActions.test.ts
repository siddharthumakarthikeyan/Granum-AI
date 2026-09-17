import { beforeEach, describe, expect, it } from "vitest";
import type { ColumnInfo, Row } from "../../api/types";
import { groupEdits, rowsByTarget } from "../editing";
import { makeFilter } from "../filtering";
import { sessionColumnInfos, sessionValue } from "../session";
import { useStore } from "../store";
import { emptySelection } from "../selection";
import type { Filter } from "../types";

const TRAIN = "/tables/train";
const column = (name: string, kind: ColumnInfo["kind"], extra: Partial<ColumnInfo> = {}): ColumnInfo => ({
  name, kind, writable: false, default_visible: true, number_role: null, source: "table", ...extra,
});
const LABEL = column("label", "categorical_label", {
  writable: true,
  value_map: {
    0: { internal_name: "cat", display_name: "", color: "" },
    1: { internal_name: "dog", display_name: "", color: "" },
  },
});

/** A run view: 3 samples x 2 epochs, sample 2 already weighted out. */
function openRunView() {
  const rows: Row[] = [];
  for (const epoch of [0, 1]) {
    for (const id of [0, 1, 2]) {
      rows.push({ _row: rows.length, _src: 0, example_id: id, label: 0, weight: id === 2 ? 0 : 1, loss: id + epoch, epoch });
    }
  }
  const columns = [
    LABEL,
    column("weight", "sample_weight", { writable: true }),
    column("example_id", "example_id", { source: "metrics" }),
    column("loss", "float32", { source: "metrics" }),
    column("epoch", "epoch", { source: "metrics" }),
    ...sessionColumnInfos(),
  ];
  const address = { kind: "run" as const, sources: [TRAIN] };
  const filters: Record<string, Filter> = {};
  for (const c of columns) {
    const f = makeFilter(c, rows);
    if (f) filters[c.name] = f;
  }
  useStore.setState({
    sourceKind: "run", sourceUrl: "/runs/r", columns, rows, filterBasis: rows, total: rows.length,
    address, targets: rowsByTarget(address, rows), undoStack: [], redoStack: [],
    filters, sort: [], order: columns.map((c) => c.name), hidden: new Set(),
    selection: emptySelection(), visited: new Set(), forceWeightOnCorrection: true, liveFilters: true,
  });
}

const labels = () => useStore.getState().rows.map((r) => r.label);
const weights = () => useStore.getState().rows.map((r) => r.weight);

beforeEach(openRunView);

describe("editing cells", () => {
  it("corrects a sample on every epoch's row and records one cell edit", () => {
    const { editCells, pendingEdits } = useStore.getState();
    expect(editCells("label", [1], 1)).toBeNull();
    expect(labels()).toEqual([0, 1, 0, 0, 1, 0]);
    expect(pendingEdits().cells.size).toBe(1);
  });

  it("assigns across a multi-row selection as one undoable step", () => {
    const s = useStore.getState();
    s.editCells("label", [0, 1, 3], 1); // row 3 is sample 0 again
    expect(useStore.getState().undoStack).toHaveLength(1);
    expect(useStore.getState().pendingEdits().cells.size).toBe(2);
    useStore.getState().undo();
    expect(labels()).toEqual([0, 0, 0, 0, 0, 0]);
    useStore.getState().redo();
    expect(labels()).toEqual([1, 1, 0, 1, 1, 0]);
  });

  it("refuses read-only columns", () => {
    expect(useStore.getState().editCells("loss", [0], 9)).toMatch(/read-only/);
    expect(useStore.getState().undoStack).toHaveLength(0);
  });

  it("gives a corrected sample non-zero weight when the setting is on", () => {
    useStore.getState().editCells("label", [2], 1);
    expect(weights()).toEqual([1, 1, 1, 1, 1, 1]);
    useStore.getState().undo();
    expect(weights()).toEqual([1, 1, 0, 1, 1, 0]);

    useStore.getState().setForceWeight(false);
    useStore.getState().editCells("label", [2], 1);
    expect(weights()).toEqual([1, 1, 0, 1, 1, 0]);
  });

  it("toggles weight between 0 and 1 for a selection", () => {
    useStore.getState().toggleWeights([0, 1]);
    expect(weights()).toEqual([0, 0, 0, 0, 0, 0]);
    useStore.getState().toggleWeights([0, 2]);
    expect(weights()).toEqual([1, 0, 1, 1, 0, 1]);
  });

  it("widens a numeric filter so an edited value is not hidden", () => {
    useStore.getState().toggleWeights([0]);
    const filter = useStore.getState().filters.weight;
    expect(filter?.kind === "numeric" && filter.bounds[0]).toBe(0);
  });
});

describe("discarding", () => {
  it("discards one group and keeps the rest", () => {
    const s = useStore.getState();
    s.setForceWeight(false);
    s.editCells("label", [0], 1);
    s.toggleWeights([1]);
    const group = groupEdits(useStore.getState().pendingEdits()).find((g) => g.column === "label")!;
    useStore.getState().discardGroup(group);
    expect(labels()).toEqual([0, 0, 0, 0, 0, 0]);
    expect(weights()).toEqual([1, 0, 0, 1, 0, 0]);
    expect(useStore.getState().pendingEdits().cells.size).toBe(1);
  });

  it("discard all restores the loaded rows", () => {
    const s = useStore.getState();
    s.editCells("label", [0, 1, 2], 1);
    s.addColumn("reviewed", "bool", false);
    useStore.getState().discardAll();
    expect(labels()).toEqual([0, 0, 0, 0, 0, 0]);
    expect(useStore.getState().columns.some((c) => c.name === "reviewed")).toBe(false);
    expect(useStore.getState().undoStack).toHaveLength(0);
  });
});

describe("new columns and classes", () => {
  it("creates an editable, filterable column before the session columns", () => {
    expect(useStore.getState().addColumn("reviewed", "bool", false)).toBeNull();
    const state = useStore.getState();
    const names = state.columns.map((c) => c.name);
    expect(names.indexOf("reviewed")).toBeLessThan(names.indexOf("Edited"));
    expect(state.rows.every((r) => r.reviewed === false)).toBe(true);
    expect(state.filters.reviewed?.kind).toBe("boolean");
    expect(state.editCells("reviewed", [0], true)).toBeNull();
    expect(useStore.getState().rows[3]!.reviewed).toBe(true);
    expect(useStore.getState().addColumn("reviewed", "bool", false)).toMatch(/already exists/);
  });

  it("adds a class and refuses to remove one still in use", () => {
    const s = useStore.getState();
    const map = { ...LABEL.value_map!, 2: { internal_name: "fox", display_name: "Fox", color: "#f80" } };
    expect(s.setClasses("label", map)).toBeNull();
    expect(useStore.getState().columns.find((c) => c.name === "label")!.value_map![2]!.display_name).toBe("Fox");
    expect(useStore.getState().setClasses("label", { 1: LABEL.value_map![1]! })).toMatch(/relabel/);
  });
});

describe("session columns and live filters", () => {
  it("marks edited, visited and selected rows", () => {
    const s = useStore.getState();
    s.editCells("label", [0], 1);
    s.clickRow(4, "none");
    expect(sessionValue("Edited", 0)).toBe(true);
    expect(sessionValue("Edited", 3)).toBe(true); // same sample, other epoch
    expect(sessionValue("Edited", 1)).toBe(false);
    expect(sessionValue("Selected", 4)).toBe(true);
    expect(sessionValue("Visited", 4)).toBe(true);
  });

  it("filters on a session column", () => {
    useStore.getState().editCells("label", [1], 1);
    useStore.getState().setFilter("Edited", { value: true });
    expect(useStore.getState().visibleRows()).toEqual([1, 4]);
  });

  it("keeps an edited row visible while live filters are off", () => {
    const s = useStore.getState();
    s.setFilter("label", { excluded: [1] }); // show cats only
    expect(useStore.getState().visibleRows()).toEqual([0, 1, 2, 3, 4, 5]);
    useStore.getState().setLiveFilters(false);
    useStore.getState().editCells("label", [0], 1);
    expect(useStore.getState().visibleRows()).toContain(0);
    useStore.getState().setLiveFilters(true);
    expect(useStore.getState().visibleRows()).not.toContain(0);
  });
});


describe("recovering unsaved edits", () => {
  it("replays a saved stack onto freshly loaded rows exactly", () => {
    const { editCells } = useStore.getState();
    editCells("label", [1], 1);
    editCells("weight", [2], 1);
    const saved = JSON.parse(JSON.stringify(useStore.getState().undoStack));
    const expected = { labels: labels(), weights: weights() };

    openRunView(); // the page reloads: original rows, no edits
    expect(labels()).toEqual([0, 0, 0, 0, 0, 0]);
    useStore.getState().restoreEdits(saved);

    expect(labels()).toEqual(expected.labels);
    expect(weights()).toEqual(expected.weights);
    expect(useStore.getState().undoStack).toHaveLength(2);
    useStore.getState().undo();
    expect(weights()).toEqual([1, 1, 0, 1, 1, 0]);
  });
});
