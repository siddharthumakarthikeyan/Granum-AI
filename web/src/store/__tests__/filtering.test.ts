import { describe, expect, it } from "vitest";
import type { ColumnInfo, Row } from "../../api/types";
import {
  categoricalCounts, filterKindFor, filterRows, histogram,
  isActive, isFilterable, makeFilter, passes, sortRows,
} from "../filtering";
import type { CategoricalFilter, NumericFilter } from "../types";

const column = (name: string, kind: ColumnInfo["kind"]): ColumnInfo => ({
  name, kind, writable: false, default_visible: true, number_role: null,
});

const rows: Row[] = [
  { _row: 0, loss: 0.1, label: "cat", ok: true },
  { _row: 1, loss: 2.4, label: "dog", ok: false },
  { _row: 2, loss: 0.9, label: "cat", ok: true },
  { _row: 3, loss: 1.6, label: "bird", ok: false },
];

describe("filter kinds", () => {
  it("maps column kinds to widget kinds", () => {
    expect(filterKindFor(column("a", "float32"))).toBe("numeric");
    expect(filterKindFor(column("a", "confidence"))).toBe("numeric");
    expect(filterKindFor(column("a", "sample_weight"))).toBe("numeric");
    expect(filterKindFor(column("a", "categorical_label"))).toBe("categorical");
    expect(filterKindFor(column("a", "string"))).toBe("categorical");
    expect(filterKindFor(column("a", "bool"))).toBe("boolean");
  });

  it("does not offer filters for images or embeddings", () => {
    expect(isFilterable(column("image", "image"))).toBe(false);
    expect(isFilterable(column("emb", "embedding"))).toBe(false);
    expect(isFilterable(column("u", "url"))).toBe(false);
  });
});

describe("makeFilter", () => {
  it("opens a numeric filter across the full data range", () => {
    const filter = makeFilter(column("loss", "float32"), rows) as NumericFilter;
    expect(filter.bounds).toEqual([0.1, 2.4]);
    expect(filter.range).toEqual([0.1, 2.4]);
    expect(isActive(filter)).toBe(false);
  });

  it("gives a constant column a non-zero width so the track is drawable", () => {
    const flat: Row[] = [{ _row: 0, x: 5 }, { _row: 1, x: 5 }];
    const filter = makeFilter(column("x", "float32"), flat) as NumericFilter;
    expect(filter.bounds[1]).toBeGreaterThan(filter.bounds[0]);
  });

  it("collects distinct categorical values", () => {
    const filter = makeFilter(column("label", "string"), rows) as CategoricalFilter;
    expect(filter.values).toEqual(["bird", "cat", "dog"]);
    expect(filter.excluded).toEqual([]);
  });
});

describe("filterRows", () => {
  it("passes everything when no filter is active", () => {
    const filter = makeFilter(column("loss", "float32"), rows)!;
    expect(filterRows(rows, [filter])).toEqual([0, 1, 2, 3]);
  });

  it("narrows on a numeric range", () => {
    const filter = makeFilter(column("loss", "float32"), rows) as NumericFilter;
    expect(filterRows(rows, [{ ...filter, range: [0.5, 2.0] }])).toEqual([2, 3]);
  });

  it("inverts a numeric range", () => {
    const filter = makeFilter(column("loss", "float32"), rows) as NumericFilter;
    expect(filterRows(rows, [{ ...filter, range: [0.5, 2.0], inverted: true }])).toEqual([0, 1]);
  });

  it("excludes categorical values", () => {
    const filter = makeFilter(column("label", "string"), rows) as CategoricalFilter;
    expect(filterRows(rows, [{ ...filter, excluded: ["cat"] }])).toEqual([1, 3]);
  });

  it("combines filters with AND", () => {
    const loss = makeFilter(column("loss", "float32"), rows) as NumericFilter;
    const label = makeFilter(column("label", "string"), rows) as CategoricalFilter;
    const result = filterRows(rows, [
      { ...loss, range: [0.5, 3.0] },
      { ...label, excluded: ["bird"] },
    ]);
    expect(result).toEqual([1, 2]);
  });

  it("can ignore one filter, which is how the histogram splits its bars", () => {
    const loss = makeFilter(column("loss", "float32"), rows) as NumericFilter;
    const narrowed = { ...loss, range: [0.0, 0.2] as [number, number] };
    expect(filterRows(rows, [narrowed])).toEqual([0]);
    expect(filterRows(rows, [narrowed], { ignore: "loss" })).toEqual([0, 1, 2, 3]);
  });

  it("treats a boolean filter of null as inactive", () => {
    const filter = makeFilter(column("ok", "bool"), rows)!;
    expect(isActive(filter)).toBe(false);
    expect(filterRows(rows, [filter]).length).toBe(4);
  });

  it("filters on booleans", () => {
    const filter = makeFilter(column("ok", "bool"), rows)!;
    expect(filterRows(rows, [{ ...filter, value: true } as never])).toEqual([0, 2]);
  });

  it("drops rows whose numeric value is missing", () => {
    const sparse: Row[] = [{ _row: 0, x: 1 }, { _row: 1 }];
    const filter = makeFilter(column("x", "float32"), sparse) as NumericFilter;
    expect(passes({ ...filter, range: [0, 10] }, sparse[1]!)).toBe(false);
  });
});

describe("sortRows", () => {
  it("returns input order with no keys", () => {
    expect(sortRows(rows, [0, 1, 2, 3], [])).toEqual([0, 1, 2, 3]);
  });

  it("sorts ascending and descending", () => {
    expect(sortRows(rows, [0, 1, 2, 3], [{ column: "loss", direction: "asc" }]))
      .toEqual([0, 2, 3, 1]);
    expect(sortRows(rows, [0, 1, 2, 3], [{ column: "loss", direction: "desc" }]))
      .toEqual([1, 3, 2, 0]);
  });

  it("breaks ties with the second key", () => {
    const ties: Row[] = [
      { _row: 0, a: 1, b: "z" }, { _row: 1, a: 1, b: "a" }, { _row: 2, a: 0, b: "m" },
    ];
    const result = sortRows(ties, [0, 1, 2], [
      { column: "a", direction: "asc" },
      { column: "b", direction: "asc" },
    ]);
    expect(result).toEqual([2, 1, 0]);
  });

  it("sorts strings alphabetically", () => {
    expect(sortRows(rows, [0, 1, 2, 3], [{ column: "label", direction: "asc" }]))
      .toEqual([3, 0, 2, 1]);
  });

  it("puts nulls last", () => {
    const sparse: Row[] = [{ _row: 0, x: 5 }, { _row: 1, x: null }, { _row: 2, x: 1 }];
    expect(sortRows(sparse, [0, 1, 2], [{ column: "x", direction: "asc" }]))
      .toEqual([2, 0, 1]);
  });
});

describe("histogram", () => {
  it("counts every value across bins", () => {
    const filter = makeFilter(column("loss", "float32"), rows) as NumericFilter;
    const bins = histogram(rows, filter, [filter], 4);
    expect(bins).toHaveLength(4);
    expect(bins.reduce((sum, b) => sum + b.total, 0)).toBe(4);
  });

  it("separates rows this filter excluded from rows it kept", () => {
    const filter = makeFilter(column("loss", "float32"), rows) as NumericFilter;
    const narrowed = { ...filter, range: [0.0, 0.5] as [number, number] };
    const bins = histogram(rows, narrowed, [narrowed], 4);
    expect(bins.reduce((s, b) => s + b.filteredIn, 0)).toBe(1);
    expect(bins.reduce((s, b) => s + b.excludedHere, 0)).toBe(3);
  });

  it("shows the full distribution even when this filter is narrow", () => {
    const filter = makeFilter(column("loss", "float32"), rows) as NumericFilter;
    const narrowed = { ...filter, range: [0.0, 0.5] as [number, number] };
    const bins = histogram(rows, narrowed, [narrowed], 4);
    expect(bins.reduce((s, b) => s + b.total, 0)).toBe(4);
  });
});

describe("categoricalCounts", () => {
  it("counts filtered-in per value", () => {
    const filter = makeFilter(column("label", "string"), rows) as CategoricalFilter;
    const counts = categoricalCounts(rows, filter, [filter]);
    expect(counts.get("cat")).toEqual({ total: 2, filteredIn: 2 });
    expect(counts.get("dog")).toEqual({ total: 1, filteredIn: 1 });
  });

  it("zeroes filtered-in for excluded values but keeps the total", () => {
    const filter = makeFilter(column("label", "string"), rows) as CategoricalFilter;
    const counts = categoricalCounts(rows, { ...filter, excluded: ["cat"] }, [filter]);
    expect(counts.get("cat")).toEqual({ total: 2, filteredIn: 0 });
  });
});

describe("column kinds that must not be filterable", () => {
  it("never offers a filter for a vector column", () => {
    // A Run view infers kinds from JSON. An array must land on "embedding", or the
    // panel offers a categorical filter over hundreds of distinct vectors.
    expect(isFilterable(column("features", "embedding"))).toBe(false);
  });
});

describe("scale", () => {
  it("builds a numeric filter over a million rows without overflowing the stack", () => {
    const rows: Row[] = Array.from({ length: 1_000_000 }, (_, i) => ({ _row: i, v: i % 1000 }));
    const filter = makeFilter(column("v", "float32"), rows) as NumericFilter;
    expect(filter.bounds).toEqual([0, 999]);
  });
});
