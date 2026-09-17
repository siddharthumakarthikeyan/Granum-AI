import { beforeEach, describe, expect, it } from "vitest";
import type { ColumnInfo, Row } from "../../api/types";
import { mergeAccepted, nmsIndices } from "../../boxes/boxActions";
import { rowsByTarget } from "../editing";
import { emptySelection } from "../selection";
import { useStore } from "../store";

const VM = { 0: { internal_name: "cat", display_name: "", color: "" }, 1: { internal_name: "dog", display_name: "", color: "" } };
const TRUTH: ColumnInfo = { name: "bbs", kind: "bounding_boxes_2d", writable: true, default_visible: true, number_role: null, source: "table", value_map: VM, instance_properties: {} };
const PRED: ColumnInfo = { ...TRUTH, name: "bbs_predicted", writable: false, source: "metrics", instance_properties: { confidence: "float32", matched: "bool" } };
const b = (x: number, label = 0, extra = {}) => ({ vertices: [x, 10, x + 20, 30], label, ...extra });

describe("pure box operations", () => {
  it("accepting a prediction replaces the label it overlaps, or adds it", () => {
    const truth = [b(0, 0), b(100, 0)];
    const merged = mergeAccepted(truth, [b(1, 1), b(300, 1)]);
    expect(merged).toHaveLength(3);
    expect(merged[0]).toMatchObject({ label: 1, vertices: [1, 10, 21, 30] }); // class fixed in place
    expect(merged[2]).toMatchObject({ label: 1, vertices: [300, 10, 320, 30] });
    expect(truth[0]!.label).toBe(0); // input untouched
  });

  it("NMS keeps the highest scoring box per class", () => {
    const instances = [b(0, 0, { confidence: 0.2 }), b(1, 0, { confidence: 0.9 }), b(0, 1, { confidence: 0.5 }), b(200, 0)];
    expect(nmsIndices(instances, 0.5)).toEqual([1, 2, 3]);
  });

  it("NMS without scores keeps the first box", () => {
    expect(nmsIndices([b(0), b(1), b(2)], 0.5)).toEqual([0]);
  });
});

function open() {
  const rows: Row[] = [0, 1].map((epoch) => ({
    _row: epoch, _src: 0, example_id: 0, epoch,
    image: "/a.png",
    bbs: { width: 200, height: 100, instances: [b(0, 0)] },
    bbs_predicted: { width: 200, height: 100, instances: [b(2, 1, { confidence: 0.9, matched: false }), b(150, 0, { confidence: 0.8, matched: false })] },
  }));
  rows.push({ _row: 2, _src: 0, example_id: 1, epoch: 0, image: "/b.png", bbs: { width: 400, height: 200, instances: [] }, bbs_predicted: { width: 400, height: 200, instances: [] } });
  const address = { kind: "run" as const, sources: ["/t"] };
  useStore.setState({
    sourceKind: "run", columns: [TRUTH, PRED], rows, filterBasis: rows, address, targets: rowsByTarget(address, rows),
    undoStack: [], redoStack: [], filters: {}, sort: [], selection: emptySelection(), visited: new Set(),
    forceWeightOnCorrection: false, liveFilters: true, focusedInstance: null, boxClipboard: null,
    dismissed: new Set(), staged: new Map(),
  });
}

const truthOf = (row = 0) => (useStore.getState().rows[row]!.bbs as { instances: { vertices: number[]; label: number }[] }).instances;

beforeEach(open);

describe("box edits through the store", () => {
  it("draws, moves, relabels and deletes, each undoable, on every epoch's row", () => {
    const s = useStore.getState();
    expect(s.addBox(0, "bbs", [50, 20, 90, 60], 1)).toBeNull();
    expect(truthOf(1)).toHaveLength(2); // epoch 1 row shows the same sample
    useStore.getState().updateBox(0, "bbs", 1, { vertices: [40, 20, 80, 60] });
    useStore.getState().updateBox(0, "bbs", 1, { label: 0 });
    expect(truthOf()[1]).toEqual({ vertices: [40, 20, 80, 60], label: 0 });
    useStore.getState().deleteBoxes(0, "bbs", [0]);
    expect(truthOf()).toHaveLength(1);
    expect(useStore.getState().undoStack.map((batch) => batch.label)).toEqual(["draw box", "move box", "relabel box", "delete 1 box"]);
    useStore.getState().undo();
    useStore.getState().undo();
    expect(truthOf()[1]).toEqual({ vertices: [40, 20, 80, 60], label: 1 });
  });

  it("clamps boxes to the image and refuses slivers", () => {
    expect(useStore.getState().addBox(0, "bbs", [190, 90, 250, 150], 0)).toBeNull();
    expect(truthOf().at(-1)!.vertices).toEqual([190, 90, 200, 100]);
    expect(useStore.getState().addBox(0, "bbs", [5, 5, 5.5, 50], 0)).toMatch(/too small/);
  });

  it("copies a box and pastes it at the same relative position on another image", () => {
    useStore.getState().focusInstance({ row: 0, column: "bbs", index: 0 });
    expect(useStore.getState().copyBox(false)).toBeNull();
    expect(useStore.getState().pasteBoxes(2)).toBeNull();
    expect(truthOf(2)).toEqual([{ vertices: [0, 20, 40, 60], label: 0 }]); // image is 2x larger
  });

  it("cut removes the original", () => {
    useStore.getState().focusInstance({ row: 0, column: "bbs", index: 0 });
    useStore.getState().copyBox(true);
    expect(truthOf()).toHaveLength(0);
  });

  it("accepts predictions immediately: replaces overlapping labels, adds the rest, dismisses them", () => {
    expect(useStore.getState().reviewPredictions([{ row: 0, index: 0 }, { row: 0, index: 1 }], "accept", false)).toBeNull();
    expect(truthOf()).toEqual([{ vertices: [2, 10, 22, 30], label: 1 }, { vertices: [150, 10, 170, 30], label: 0 }]);
    expect([...useStore.getState().dismissed]).toEqual(["0:0", "0:1"]);
  });

  it("stages decisions and applies them as edits", () => {
    const s = useStore.getState();
    s.reviewPredictions([{ row: 0, index: 1 }], "accept", true);
    s.reviewPredictions([{ row: 0, index: 0 }], "reject", true);
    expect(truthOf()).toHaveLength(1);
    expect(useStore.getState().staged.size).toBe(2);
    expect(useStore.getState().applyStaged()).toBeNull();
    expect(truthOf()).toHaveLength(2);
    expect(useStore.getState().dismissed.has("0:0")).toBe(true);
    expect(useStore.getState().staged.size).toBe(0);
  });

  it("applies NMS once per sample as one undoable edit", () => {
    useStore.getState().addBox(0, "bbs", [1, 10, 21, 30], 0); // duplicate of box 0
    const { removed } = useStore.getState().applyNms([0, 1, 2], "bbs", 0.5);
    expect(removed).toBe(1);
    expect(truthOf()).toHaveLength(1);
    expect(useStore.getState().undoStack.at(-1)!.label).toBe("NMS at IoU 0.5");
  });

  it("predictions are read-only", () => {
    expect(useStore.getState().updateBox(0, "bbs_predicted", 0, { label: 0 })).toMatch(/read-only/);
  });
});
