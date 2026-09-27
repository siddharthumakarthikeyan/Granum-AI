/** Ordering, grouping, filtering and summarising the gallery by the set's own columns.
 *
 * Every number here decides what a reader believes about their data -- a mean over the
 * wrong denominator, a quantile off by one order statistic, a group that quietly drops the
 * images a column says nothing about -- and none of it announces itself on screen. So the
 * expectations are worked out by hand.
 */

import { describe, expect, it } from "vitest";
import type { FieldInfo, ImageRow } from "../../api/types";
import {
  compareFieldValues,
  displayValue,
  fieldFilterActive,
  fieldHistogram,
  fieldValue,
  fieldValueCounts,
  filterByFields,
  flattenGroups,
  groupImages,
  makeFieldFilter,
  openFieldFilter,
  passesFieldFilter,
  quantile,
  restoreFieldFilter,
  shuffleImages,
  sliceImages,
  sortByField,
  summarizeField,
  type FieldFilter,
  type NumberFieldFilter,
  type ValueFieldFilter,
} from "../../images/fields";

function image(path: string, values?: ImageRow["values"], set = "train"): ImageRow {
  return { row: 0, image: path, objects: 1, classes: [0], set, table: `t/${set}`, added: "2026-09-01", ...(values ? { values } : {}) };
}

const width: FieldInfo = { name: "width", label: "Width", kind: "number", present: 4 };
const city: FieldInfo = { name: "city", label: "City", kind: "string", present: 3, values: ["Aachen", "Bonn"] };
const night: FieldInfo = { name: "night", label: "Night", kind: "bool", present: 2, values: [true, false] };
const weather: FieldInfo = { name: "weather", label: "Weather", kind: "class", present: 2, classes: { "0": "sun", "1": "rain" } };

const rows = [
  image("/a.jpg", { width: 640, city: "Aachen", night: true, weather: 0 }),
  image("/b.jpg", { width: 1280, city: "Bonn", night: false, weather: 1 }),
  image("/c.jpg", { width: 800, city: "Bonn" }),
  image("/d.jpg"),
];

describe("a field's value on an image", () => {
  it("is absent rather than null when the image says nothing", () => {
    expect(fieldValue(rows[0]!, "width")).toBe(640);
    expect(fieldValue(rows[2]!, "night")).toBeUndefined();
    expect(fieldValue(rows[3]!, "width")).toBeUndefined();
  });

  it("reads back the way a person wrote it", () => {
    expect(displayValue(weather, 1)).toBe("rain");
    expect(displayValue(weather, 7)).toBe("7"); // a class the value map does not name
    expect(displayValue(night, true)).toBe("Yes");
    expect(displayValue(width, 0.123456)).toBe("0.1235");
    expect(displayValue(width, 640)).toBe("640");
  });
});

describe("a filter built from a field descriptor", () => {
  it("opens over the range the data spans", () => {
    const filter = makeFieldFilter(width, rows) as NumberFieldFilter;
    expect(filter.bounds).toEqual([640, 1280]);
    expect(filter.range).toEqual([640, 1280]);
    expect(fieldFilterActive(filter)).toBe(false);
  });

  it("offers every value of a small column, and reads them off the images otherwise", () => {
    expect(makeFieldFilter(city, rows)).toMatchObject({ kind: "values", values: ["Aachen", "Bonn"] });
    const unnamed: FieldInfo = { name: "city", label: "City", kind: "string", present: 3 };
    expect(makeFieldFilter(unnamed, rows)).toMatchObject({ values: ["Aachen", "Bonn"] });
  });

  it("is nothing at all when no image carries the field", () => {
    expect(makeFieldFilter({ ...width, name: "missing" }, rows)).toBeNull();
    expect(makeFieldFilter({ ...city, name: "missing", values: undefined }, rows)).toBeNull();
  });

  it("lets an image with no value through until asked not to", () => {
    const filter = makeFieldFilter(width, rows) as NumberFieldFilter;
    const narrowed: FieldFilter = { ...filter, range: [700, 1300] };
    expect(passesFieldFilter(narrowed, rows[0]!)).toBe(false); // 640 is outside
    expect(passesFieldFilter(narrowed, rows[2]!)).toBe(true); // 800 is inside
    expect(passesFieldFilter(narrowed, rows[3]!)).toBe(true); // no width at all
    const strict: FieldFilter = { ...narrowed, withoutValue: false };
    expect(passesFieldFilter(strict, rows[3]!)).toBe(false);
    expect(fieldFilterActive({ ...filter, withoutValue: false })).toBe(true);
  });

  it("excludes the values switched off, whatever their type", () => {
    const filter = makeFieldFilter(night, rows)!;
    const off: FieldFilter = { ...filter, kind: "values", excluded: ["false"] } as FieldFilter;
    expect(passesFieldFilter(off, rows[0]!)).toBe(true);
    expect(passesFieldFilter(off, rows[1]!)).toBe(false);
  });
});

describe("a column with thousands of values", () => {
  const wide: FieldInfo = { name: "source", label: "Source", kind: "string", present: 3, distinct: 6468, wide: true };
  const paths = [
    image("/a.jpg", { source: "0000235_01900_d.jpg" }),
    image("/b.jpg", { source: "0000229_00001_d.jpg" }),
    image("/c.jpg"),
  ];

  it("is asked as a search rather than offered as a list", () => {
    const filter = makeFieldFilter(wide, paths)!;
    expect(filter).toEqual({ name: "source", kind: "text", query: "", withoutValue: true });
    expect(fieldFilterActive(filter)).toBe(false);
  });

  it("matches on any part of the value, whatever the case, and blank matches everything", () => {
    const filter = { ...makeFieldFilter(wide, paths)!, query: "0235_019" } as FieldFilter;
    expect(paths.filter((item) => passesFieldFilter(filter, item)).map((r) => r.image)).toEqual(["/a.jpg", "/c.jpg"]);
    expect(passesFieldFilter({ ...filter, query: "D.JPG" } as FieldFilter, paths[0]!)).toBe(true);
    expect(fieldFilterActive({ ...filter, query: "   " } as FieldFilter)).toBe(false);
    // Asked not to, an image with no value is out even though the query says nothing about it.
    expect(passesFieldFilter({ ...filter, withoutValue: false } as FieldFilter, paths[2]!)).toBe(false);
  });
});

describe("opening a filter again, and restoring one from a saved view", () => {
  it("opens every kind of filter wide", () => {
    const number = { ...(makeFieldFilter(width, rows) as NumberFieldFilter), range: [700, 800] as [number, number], withoutValue: false };
    expect(openFieldFilter(number)).toMatchObject({ range: [640, 1280], withoutValue: true });
    const values = { ...(makeFieldFilter(city, rows) as ValueFieldFilter), excluded: ["Bonn"], withoutValue: false };
    expect(openFieldFilter(values)).toMatchObject({ excluded: [], withoutValue: true });
    const text: FieldFilter = { name: "source", kind: "text", query: "x", withoutValue: false };
    expect(openFieldFilter(text)).toMatchObject({ query: "", withoutValue: true });
  });

  it("keeps today's bounds and takes only the reader's choice from the view", () => {
    const built = makeFieldFilter(width, rows) as NumberFieldFilter;
    const restored = restoreFieldFilter(built, { kind: "number", range: [700, 900], bounds: [0, 5], withoutValue: false });
    expect(restored).toMatchObject({ bounds: [640, 1280], range: [700, 900], withoutValue: false });
  });

  it("ignores a saved filter that no longer matches the column, rather than half-applying it", () => {
    const built = makeFieldFilter(width, rows) as NumberFieldFilter;
    expect(restoreFieldFilter(built, { kind: "values", excluded: ["1"] })).toBe(built);
    expect(restoreFieldFilter(built, null)).toBe(built);
    expect(restoreFieldFilter(built, "nonsense")).toBe(built);
  });

  it("refuses a saved range that would empty the gallery", () => {
    const built = makeFieldFilter(width, rows) as NumberFieldFilter;
    expect(restoreFieldFilter(built, { kind: "number", range: [900, 700] })).toMatchObject({ range: [640, 1280] });
    expect(restoreFieldFilter(built, { kind: "number", range: ["x", null] })).toMatchObject({ range: [640, 1280] });
  });
});

describe("filtering the gallery by fields", () => {
  const filters: Record<string, FieldFilter> = {
    width: { name: "width", kind: "number", bounds: [640, 1280], range: [700, 1280], withoutValue: false },
    city: { name: "city", kind: "values", values: ["Aachen", "Bonn"], excluded: [], withoutValue: true },
  };

  it("keeps only the images every active filter leaves", () => {
    expect(filterByFields(rows, filters).map((r) => r.image)).toEqual(["/b.jpg", "/c.jpg"]);
  });

  it("can ignore one filter, so a widget counts against the others", () => {
    expect(filterByFields(rows, filters, "width").map((r) => r.image))
      .toEqual(["/a.jpg", "/b.jpg", "/c.jpg", "/d.jpg"]);
  });

  it("returns the images untouched when nothing is narrowing", () => {
    const open: Record<string, FieldFilter> = { width: { ...filters.width!, range: [640, 1280], withoutValue: true } as FieldFilter };
    expect(filterByFields(rows, open)).toBe(rows);
  });
});

describe("what a widget draws itself against", () => {
  it("counts each bin before and after its own filter", () => {
    const filter: NumberFieldFilter = { name: "width", kind: "number", bounds: [640, 1280], range: [640, 900], withoutValue: true };
    const bins = fieldHistogram(rows, filter, 4);
    // Bins are 160 wide: 640–800, 800–960, 960–1120, 1120–1280.
    expect(bins.map((b) => b.total)).toEqual([1, 1, 0, 1]);
    expect(bins.map((b) => b.shown)).toEqual([1, 1, 0, 0]);
    expect(bins[3]!.hi).toBe(1280);
  });

  it("counts a field's values and the images that have none", () => {
    const { counts, missing } = fieldValueCounts(rows, "city");
    expect(counts.get("Bonn")).toBe(2);
    expect(counts.get("Aachen")).toBe(1);
    expect(missing).toBe(1);
  });
});

describe("ordering by a field", () => {
  it("puts numbers in order and the images with no value last, both ways round", () => {
    expect(sortByField(rows, "width", "asc").map((r) => r.image)).toEqual(["/a.jpg", "/c.jpg", "/b.jpg", "/d.jpg"]);
    expect(sortByField(rows, "width", "desc").map((r) => r.image)).toEqual(["/b.jpg", "/c.jpg", "/a.jpg", "/d.jpg"]);
  });

  it("breaks a tie by image, so the order never wobbles between renders", () => {
    const tied = [image("/z.jpg", { width: 1 }), image("/y.jpg", { width: 1 })];
    expect(sortByField(tied, "width", "asc").map((r) => r.image)).toEqual(["/y.jpg", "/z.jpg"]);
    expect(sortByField(tied, "width", "desc").map((r) => r.image)).toEqual(["/y.jpg", "/z.jpg"]);
  });

  it("compares strings the way a file list should and flags before values", () => {
    expect(compareFieldValues("img2", "img10")).toBeLessThan(0);
    expect(compareFieldValues(false, true)).toBeLessThan(0);
    expect(compareFieldValues(undefined, 1)).toBeGreaterThan(0);
    expect(compareFieldValues(1, undefined)).toBeLessThan(0);
    expect(compareFieldValues(undefined, undefined)).toBe(0);
  });
});

describe("a shuffled gallery", () => {
  const many = Array.from({ length: 40 }, (_, i) => image(`/${i}.jpg`));

  it("is the same order every time for one seed, and a different one for another", () => {
    const once = shuffleImages(many, 7).map((r) => r.image);
    expect(shuffleImages(many, 7).map((r) => r.image)).toEqual(once);
    expect(shuffleImages(many, 8).map((r) => r.image)).not.toEqual(once);
  });

  it("keeps every image exactly once and does not touch the list given", () => {
    const shuffled = shuffleImages(many, 3);
    expect(new Set(shuffled.map((r) => r.image)).size).toBe(40);
    expect(many[0]!.image).toBe("/0.jpg");
    expect(shuffled.map((r) => r.image)).not.toEqual(many.map((r) => r.image));
  });

  it("survives a seed of zero, which a modulo would turn into a fixed point", () => {
    expect(shuffleImages(many, 0).map((r) => r.image)).not.toEqual(many.map((r) => r.image));
  });
});

describe("taking a slice of the gallery", () => {
  it("skips then takes, and a take of nothing means everything", () => {
    expect(sliceImages(rows, 1, 2).map((r) => r.image)).toEqual(["/b.jpg", "/c.jpg"]);
    expect(sliceImages(rows, 2, 0).map((r) => r.image)).toEqual(["/c.jpg", "/d.jpg"]);
    expect(sliceImages(rows, 0, 0)).toBe(rows);
    expect(sliceImages(rows, 9, 2)).toEqual([]);
  });
});

describe("grouping the gallery by a field", () => {
  it("groups by value, commonest first for free text, and puts the valueless last", () => {
    const grouping = groupImages(rows, city);
    expect(grouping.groups.map((g) => [g.label, g.items.length])).toEqual([["Bonn", 2], ["Aachen", 1], ["No value", 1]]);
    expect(grouping.binned).toBe(false);
    expect(flattenGroups(grouping).map((r) => r.image)).toEqual(["/b.jpg", "/c.jpg", "/a.jpg", "/d.jpg"]);
  });

  it("names class groups and keeps numbers and classes in their own order", () => {
    expect(groupImages(rows, weather).groups.map((g) => g.label)).toEqual(["sun", "rain", "No value"]);
    expect(groupImages(rows, width).groups.map((g) => g.label)).toEqual(["640", "800", "1280", "No value"]);
  });

  it("cuts a continuous column into ranges rather than into one group per image", () => {
    const many = Array.from({ length: 100 }, (_, i) => image(`/${i}.jpg`, { width: i }));
    const grouping = groupImages(many, width, { limit: 4 });
    expect(grouping.binned).toBe(true);
    expect(grouping.groups.map((g) => g.label)).toEqual(["0 – 24.75", "24.75 – 49.5", "49.5 – 74.25", "74.25 – 99"]);
    expect(grouping.groups.map((g) => g.items.length)).toEqual([25, 25, 25, 25]);
    expect(flattenGroups(grouping)).toHaveLength(100);
  });

  it("gathers the tail of a wide text column instead of drawing hundreds of headings", () => {
    const many = Array.from({ length: 30 }, (_, i) => image(`/${i}.jpg`, { city: `c${i}` }));
    const grouping = groupImages(many, { ...city, values: undefined }, { limit: 5 });
    expect(grouping.groups).toHaveLength(6);
    expect(grouping.groups[5]).toMatchObject({ key: "other", label: "25 more values" });
    expect(flattenGroups(grouping)).toHaveLength(30);
  });

  it("groups by something that is not a column at all, given how to read it", () => {
    const mixed = [image("/a.jpg", undefined, "train"), image("/b.jpg", undefined, "valid"), image("/c.jpg", undefined, "train")];
    const grouping = groupImages(mixed, { name: "set", label: "Set", kind: "string", present: 3 },
                                 { valueFor: (item) => item.set });
    expect(grouping.groups.map((g) => [g.label, g.items.length])).toEqual([["train", 2], ["valid", 1]]);
  });

  it("is one group when every image shares a value", () => {
    const same = [image("/a.jpg", { city: "Bonn" }), image("/b.jpg", { city: "Bonn" })];
    expect(groupImages(same, city).groups).toEqual([{ key: "Bonn", label: "Bonn", items: same }]);
  });
});

describe("what a column adds up to over the images on screen", () => {
  it("reports bounds, mean, deviation and quantiles, counting the missing as missing", () => {
    const summary = summarizeField(rows, "width");
    expect(summary).toMatchObject({ count: 4, present: 3, missing: 1, distinct: 3, min: 640, max: 1280 });
    expect(summary.mean).toBeCloseTo((640 + 1280 + 800) / 3, 10);
    // Population deviation over 640, 800, 1280: mean 906.66…
    expect(summary.std).toBeCloseTo(Math.sqrt(((640 - 2720 / 3) ** 2 + (800 - 2720 / 3) ** 2 + (1280 - 2720 / 3) ** 2) / 3), 8);
    expect(summary.quantiles).toEqual({ "0.25": 720, "0.5": 800, "0.75": 1040 });
    expect(summary.sum).toBe(2720);
  });

  it("ranks the values of a text column and offers no arithmetic over them", () => {
    const summary = summarizeField(rows, "city");
    expect(summary.top[0]).toEqual({ value: "Bonn", count: 2 });
    expect(summary.mean).toBeUndefined();
    expect(summary.quantiles).toBeUndefined();
  });

  it("does not average a flag, where true is an integer in disguise", () => {
    const summary = summarizeField(rows, "night");
    expect(summary.mean).toBeUndefined();
    expect(summary.present).toBe(2);
  });

  it("says nothing rather than NaN when the column is empty here", () => {
    const summary = summarizeField(rows, "nope");
    expect(summary).toMatchObject({ count: 4, present: 0, missing: 4, distinct: 0, top: [] });
    expect(summary.mean).toBeUndefined();
  });

  it("interpolates a quantile between order statistics, as numpy does", () => {
    expect(quantile([1, 2, 3, 4], 0.25)).toBe(1.75);
    expect(quantile([1, 2, 3, 4], 0.5)).toBe(2.5);
    expect(quantile([5], 0.9)).toBe(5);
    expect(quantile([], 0.5)).toBeNaN();
  });
});
