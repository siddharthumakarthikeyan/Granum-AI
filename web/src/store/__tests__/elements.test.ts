import { describe, expect, it } from "vitest";
import type { ColumnInfo, Row } from "../../api/types";
import { drawnBoxes, DEFAULT_BOX_DISPLAY } from "../../boxes/model";
import {
  elementCategoricalCounts, elementCounts, elementHistogram, elementValue, filterRows,
  makeElementFilters, rowPassesElements,
} from "../filtering";
import type { BooleanFilter, CategoricalFilter, Filter, NumericFilter } from "../types";

const PREDICTED: ColumnInfo = {
  name: "pred", kind: "bounding_boxes_2d", writable: false, default_visible: true, number_role: null,
  source: "metrics", instance_properties: { confidence: "float32", iou: "float32", matched: "bool" },
  value_map: { 0: { internal_name: "cat", display_name: "", color: "" }, 1: { internal_name: "dog", display_name: "", color: "" } },
};
const TRUTH: ColumnInfo = { ...PREDICTED, name: "gt", source: "table", writable: true, instance_properties: {} };

const box = (x0: number, label: number, extra: Record<string, unknown> = {}) =>
  ({ vertices: [x0, 0, x0 + 10, 20], label, ...extra });

const rows: Row[] = [
  {
    _row: 0,
    gt: { width: 100, height: 100, instances: [box(0, 0), box(50, 1)] },
    gt_match: [0, -1],
    // a confident matched box, and an unconfident unmatched one
    pred: { width: 100, height: 100, instances: [box(0, 0, { confidence: 0.9, matched: true }), box(80, 1, { confidence: 0.3, matched: false })] },
  },
  {
    _row: 1,
    gt: { width: 100, height: 100, instances: [] },
    gt_match: [],
    pred: { width: 100, height: 100, instances: [box(10, 1, { confidence: 0.8, matched: false })] },
  },
  { _row: 2, gt: { width: 100, height: 100, instances: [box(5, 0)] }, gt_match: [-1], pred: { width: 100, height: 100, instances: [] } },
];

const filtersFor = (column: ColumnInfo) =>
  Object.fromEntries(makeElementFilters(column, rows).map((f) => [f.property!, f])) as Record<string, Filter>;

describe("element filters", () => {
  const pred = filtersFor(PREDICTED);
  const gt = filtersFor(TRUTH);

  it("are built from the instances: class, area, typed properties, and missed for ground truth", () => {
    // iou is declared but no instance carries a value, so it gets no widget
    expect(Object.keys(pred).sort()).toEqual(["area", "confidence", "label", "matched"]);
    expect((pred.confidence as NumericFilter).bounds).toEqual([0.3, 0.9]);
    expect((pred.label as CategoricalFilter).values).toEqual([0, 1]);
    expect(Object.keys(gt)).toContain("missed");
    expect(Object.keys(pred)).not.toContain("missed");
  });

  it("derive area and missed", () => {
    expect(elementValue(rows[0]!, "gt", 0, "area")).toBe(200);
    expect(elementValue(rows[0]!, "gt", 1, "missed")).toBe(true);
    expect(elementValue(rows[0]!, "gt", 0, "missed")).toBe(false);
  });

  it("combine on the same instance, not across instances", () => {
    // unmatched AND confident: row 0 has one of each but no single box that is both
    const unmatched: BooleanFilter = { ...(pred.matched as BooleanFilter), value: false };
    const confident: NumericFilter = { ...(pred.confidence as NumericFilter), range: [0.5, 1] };
    const both = [unmatched, confident];
    expect(rowPassesElements(rows[0]!, "pred", both)).toBe(false);
    expect(rowPassesElements(rows[1]!, "pred", both)).toBe(true);
    expect(filterRows(rows, both)).toEqual([1]);
  });

  it("drop rows whose every instance is filtered out, including rows with none", () => {
    const dogs: CategoricalFilter = { ...(pred.label as CategoricalFilter), excluded: [0] };
    expect(filterRows(rows, [dogs])).toEqual([0, 1]);
  });

  it("mix with row filters of other geometries", () => {
    const missed: BooleanFilter = { ...(gt.missed as BooleanFilter), value: true };
    const confident: NumericFilter = { ...(pred.confidence as NumericFilter), range: [0.5, 1] };
    expect(filterRows(rows, [missed, confident])).toEqual([0]);
  });

  it("count instances for panels and filters", () => {
    const confident: NumericFilter = { ...(pred.confidence as NumericFilter), range: [0.5, 1] };
    const visible = filterRows(rows, [confident]);
    expect(elementCounts(rows, visible, [confident], "pred")).toEqual({ shown: 2, total: 3 });
  });

  it("histograms and category counts count boxes", () => {
    const confidence = pred.confidence as NumericFilter;
    const bins = elementHistogram(rows, confidence, [confidence], 4);
    expect(bins.reduce((n, b) => n + b.total, 0)).toBe(3);
    const narrowed: NumericFilter = { ...confidence, range: [0.5, 1] };
    const narrowedBins = elementHistogram(rows, narrowed, [narrowed], 4);
    expect(narrowedBins.reduce((n, b) => n + b.filteredIn, 0)).toBe(2);
    expect(narrowedBins.reduce((n, b) => n + b.excludedHere, 0)).toBe(1);
    const labels = elementCategoricalCounts(rows, pred.label as CategoricalFilter, [narrowed]);
    expect(labels.get(1)).toEqual({ total: 2, filteredIn: 1 });
  });

  it("hide filtered-out boxes when drawing", () => {
    const confident: NumericFilter = { ...(pred.confidence as NumericFilter), range: [0.5, 1] };
    const drawn = drawnBoxes(rows[0], TRUTH, PREDICTED, { ...DEFAULT_BOX_DISPLAY, minConfidence: 0 }, [confident]);
    expect(drawn.filter((b) => b.column === "pred").map((b) => b.index)).toEqual([0]);
    expect(drawn.filter((b) => b.column === "gt").map((b) => b.role)).toEqual(["truth", "missed"]);
  });
});

describe("element counts under random filter combinations", () => {
  // Small deterministic PRNG so failures reproduce.
  let seed = 7;
  const rand = () => ((seed = (seed * 16807) % 2147483647) / 2147483647);
  const pick = <T,>(items: T[]) => items[Math.floor(rand() * items.length)]!;

  function randomRows(): Row[] {
    return Array.from({ length: 30 }, (_, r) => {
      const gtCount = Math.floor(rand() * 4);
      const predCount = Math.floor(rand() * 5);
      return {
        _row: r,
        score: rand(),
        gt: { width: 100, height: 100, instances: Array.from({ length: gtCount }, () => box(rand() * 80, Math.floor(rand() * 2))) },
        gt_match: Array.from({ length: gtCount }, () => (rand() < 0.3 ? -1 : 0)),
        pred: {
          width: 100, height: 100,
          instances: Array.from({ length: predCount }, () => box(rand() * 80, Math.floor(rand() * 2), { confidence: rand(), matched: rand() < 0.5 })),
        },
      };
    });
  }

  it("keep panel counts, histograms and category counts consistent", () => {
    for (let trial = 0; trial < 300; trial += 1) {
      const data = randomRows();
      const base = [...makeElementFilters(PREDICTED, data), ...makeElementFilters(TRUTH, data)];
      const active: Filter[] = base.map((f) => {
        if (rand() < 0.5) return f;
        if (f.kind === "numeric") {
          const [lo, hi] = f.bounds;
          const a = lo + rand() * (hi - lo);
          const b = a + rand() * (hi - a);
          return { ...f, range: [a, b], inverted: rand() < 0.2 };
        }
        if (f.kind === "boolean") return { ...f, value: pick([true, false, null]) };
        if (f.kind === "categorical") return { ...f, excluded: f.values.filter(() => rand() < 0.4) };
        return f;
      });
      // plus a row-level filter
      const rowFilter: NumericFilter = { column: "score", kind: "numeric", scope: "row", bounds: [0, 1], range: [rand() * 0.5, 1], inverted: false, locked: false, showFilteredOut: false };
      const filters = [...active, rowFilter];
      const visible = filterRows(data, filters);

      for (const geometry of ["pred", "gt"]) {
        const members = filters.filter((f) => f.scope === "element" && f.geometry === geometry);
        const { shown } = elementCounts(data, visible, filters, geometry);
        // every visible row has a passing instance for each geometry with active filters
        const anyActive = members.some((f) => f.kind === "numeric" ? f.inverted || f.range[0] > f.bounds[0] || f.range[1] < f.bounds[1]
          : f.kind === "boolean" ? f.value !== null || f.inverted : f.kind === "categorical" ? f.excluded.length > 0 || f.inverted : false);
        if (anyActive) for (const r of visible) expect(rowPassesElements(data[r]!, geometry, members)).toBe(true);

        // histogram filtered-in totals equal the panel count, for every numeric member
        for (const f of members.filter((m): m is NumericFilter => m.kind === "numeric")) {
          const bins = elementHistogram(data, f, filters, 8);
          // instances with a value outside the bounds cannot occur: bounds come from the data
          expect(bins.reduce((n, bin) => n + bin.filteredIn, 0)).toBe(shown);
        }
        for (const f of members.filter((m): m is CategoricalFilter => m.kind === "categorical")) {
          const counts = elementCategoricalCounts(data, f, filters);
          expect([...counts.values()].reduce((n, c) => n + c.filteredIn, 0)).toBe(shown);
        }
      }
    }
  });
});
