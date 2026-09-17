import { describe, expect, it } from "vitest";
import type { ColumnInfo, Row } from "../../api/types";
import { toggleSlot, pointColors, FILTERED, OTHER, CATEGORICAL } from "../../charts/colors";
import { fitView, niceTicks, screenToData, dataToScreen, type Frame } from "../../charts/projection";
import { chartFromColumns } from "../../charts/spec";
import { drawMask, FILTERED_OUT, HIDDEN, SHOWN, visibleIndices } from "../derive";
import { filterRows, isActive, regionFilterKey } from "../filtering";
import { compileRegions, ellipsePolygon, insideRegions, pointInPolygon, simplifyPath } from "../geometry";
import { ROW_INDEX, type Filter, type NumericFilter, type RegionFilter } from "../types";

const column = (name: string, kind: ColumnInfo["kind"]): ColumnInfo => ({
  name, kind, writable: false, default_visible: true, number_role: null,
});
const square: [number, number][] = [[0, 0], [10, 0], [10, 10], [0, 10]];

function region(regions: RegionFilter["regions"], x = "x", y = "y"): RegionFilter {
  return {
    column: regionFilterKey(x, y), kind: "region", scope: "row", x, y, regions,
    inverted: false, locked: false, showFilteredOut: false,
  };
}

describe("geometry", () => {
  it("tests points against a polygon", () => {
    expect(pointInPolygon(square, 5, 5)).toBe(true);
    expect(pointInPolygon(square, 11, 5)).toBe(false);
    const concave: [number, number][] = [[0, 0], [10, 0], [10, 10], [5, 3], [0, 10]];
    expect(pointInPolygon(concave, 5, 8)).toBe(false); // inside the notch
    expect(pointInPolygon(concave, 2, 2)).toBe(true);
  });

  it("applies regions in order like paint strokes", () => {
    const hole: [number, number][] = [[4, 4], [6, 4], [6, 6], [4, 6]];
    const strokes = compileRegions([
      { mode: "add", polygon: square },
      { mode: "subtract", polygon: hole },
    ]);
    expect(insideRegions(strokes, 1, 1)).toBe(true);
    expect(insideRegions(strokes, 5, 5)).toBe(false);
    expect(insideRegions(strokes, 20, 20)).toBe(false);
  });

  it("treats a leading subtract as everything-except", () => {
    const strokes = compileRegions([{ mode: "subtract", polygon: square }]);
    expect(insideRegions(strokes, 5, 5)).toBe(false);
    expect(insideRegions(strokes, 50, 50)).toBe(true);
  });

  it("never includes missing values", () => {
    expect(insideRegions(compileRegions([{ mode: "subtract", polygon: square }]), NaN, 1)).toBe(false);
  });

  it("builds brush dabs and thins freehand paths", () => {
    expect(pointInPolygon(ellipsePolygon(0, 0, 5, 5), 0, 0)).toBe(true);
    expect(pointInPolygon(ellipsePolygon(0, 0, 5, 5), 6, 0)).toBe(false);
    const path = Array.from({ length: 100 }, (_, i) => [i * 0.1, 0] as [number, number]);
    expect(simplifyPath(path, 1).length).toBeLessThan(12);
  });
});

describe("region filters", () => {
  const rows: Row[] = [
    { _row: 0, x: 1, y: 1 },
    { _row: 1, x: 5, y: 5 },
    { _row: 2, x: 20, y: 20 },
    { _row: 3, x: null, y: 3 },
  ];

  it("narrows rows like any other filter, never passing a missing position", () => {
    const filter = region([{ mode: "add", polygon: square }]);
    expect(isActive(filter)).toBe(true);
    expect(filterRows(rows, [filter])).toEqual([0, 1]);
    expect(filterRows(rows, [{ ...filter, inverted: true }])).toEqual([2]);
  });

  it("is inactive with no regions", () => {
    expect(isActive(region([]))).toBe(false);
    expect(filterRows(rows, [region([])])).toEqual([0, 1, 2, 3]);
  });

  it("can use the row position as an axis", () => {
    const band: [number, number][] = [[1.5, 0], [3.5, 0], [3.5, 100], [1.5, 100]];
    const filter = region([{ mode: "add", polygon: band }], ROW_INDEX, "y");
    expect(filterRows(rows, [filter])).toEqual([2, 3]);
  });
});

describe("derived views", () => {
  const rows: Row[] = Array.from({ length: 6 }, (_, i) => ({ _row: i, v: i, w: i % 2 }));
  const numeric = (name: string, range: [number, number], showFilteredOut = false): NumericFilter => ({
    column: name, kind: "numeric", scope: "row", bounds: [0, 5], range,
    inverted: false, locked: false, showFilteredOut,
  });

  it("returns the same array while inputs are unchanged", () => {
    const filters = { v: numeric("v", [2, 5]) };
    const sort: never[] = [];
    expect(visibleIndices(rows, filters, sort)).toBe(visibleIndices(rows, filters, sort));
  });

  it("greys rows excluded only by filters that show filtered-out points", () => {
    const filters: Record<string, Filter> = {
      v: numeric("v", [0, 3], true), // rows 4, 5 excluded but shown grey
      w: { ...numeric("w", [0, 0]), bounds: [0, 1] }, // odd rows hidden
    };
    const mask = drawMask(rows, filters);
    expect([...mask]).toEqual([SHOWN, HIDDEN, SHOWN, HIDDEN, FILTERED_OUT, HIDDEN]);
  });
});

describe("chart creation from selected columns", () => {
  const columns = [
    column("image", "image"), column("loss", "float32"), column("confidence", "confidence"),
    column("label", "int64"), column("split", "string"),
  ];

  it("plots one numeric column against row position", () => {
    const spec = chartFromColumns(["loss"], columns);
    expect(spec).toMatchObject({ kind: "scatter", x: ROW_INDEX, y: "loss", color: null });
  });

  it("plots two numerics as x then y, and colours by a third", () => {
    expect(chartFromColumns(["loss", "confidence"], columns)).toMatchObject({ x: "loss", y: "confidence" });
    expect(chartFromColumns(["confidence", "loss", "label"], columns)).toMatchObject({
      x: "confidence", y: "loss", color: "label",
    });
  });

  it("opens an image chart for an image column alone", () => {
    expect(chartFromColumns(["image"], columns)).toMatchObject({ kind: "image", image: "image" });
  });

  it("explains what is wrong instead of failing silently", () => {
    expect(typeof chartFromColumns([], columns)).toBe("string");
    expect(chartFromColumns(["split"], columns)).toContain("not numeric");
  });
});

describe("colour", () => {
  it("keeps other categories' hues when one is toggled", () => {
    const slots = ["cat", "dog", "bird"];
    expect(toggleSlot(slots, "dog")).toEqual(["cat", null, "bird"]);
    expect(toggleSlot(["cat", null, "bird"], "frog")).toEqual(["cat", "frog", "bird"]);
    expect(toggleSlot(slots, "frog")).toEqual(["cat", "dog", "frog"]);
  });

  it("paints filtered-out grey, hides hidden, and greys unslotted categories", () => {
    const rows: Row[] = [{ _row: 0, c: "a" }, { _row: 1, c: "z" }, { _row: 2, c: "a" }, { _row: 3, c: "a" }];
    const mask = Uint8Array.from([SHOWN, SHOWN, FILTERED_OUT, HIDDEN]);
    const out = pointColors(rows, mask, { kind: "categorical", column: "c", slots: ["a", null, null] });
    expect([...out.slice(0, 3)]).toEqual(CATEGORICAL[0]);
    expect([...out.slice(4, 7)]).toEqual(OTHER);
    expect([...out.slice(8, 11)]).toEqual(FILTERED);
    expect(out[15]).toBe(0);
  });
});

describe("projection", () => {
  it("round-trips screen and data coordinates at any zoom", () => {
    const frame: Frame = {
      width: 400, height: 300, xDomain: [-5, 15], yDomain: [100, 200],
      view: { target: [0.3, 0.7], zoomX: 9.2, zoomY: 7.5 },
    };
    const [sx, sy] = dataToScreen(frame, 3.25, 142);
    const [x, y] = screenToData(frame, sx, sy);
    expect(x).toBeCloseTo(3.25, 9);
    expect(y).toBeCloseTo(142, 9);
  });

  it("fits the unit box inside the plot, y growing upward", () => {
    const frame: Frame = { width: 400, height: 200, xDomain: [0, 1], yDomain: [0, 1], view: fitView(400, 200) };
    const [left, bottom] = dataToScreen(frame, 0, 0);
    const [right, top] = dataToScreen(frame, 1, 1);
    expect(left).toBeGreaterThan(0);
    expect(right).toBeLessThan(400);
    expect(bottom).toBeGreaterThan(top);
  });

  it("picks round ticks", () => {
    expect(niceTicks(0, 1, 5)).toEqual([0, 0.2, 0.4, 0.6000000000000001, 0.8, 1]);
    expect(niceTicks(0, 1, 5).length).toBe(6);
  });
});
