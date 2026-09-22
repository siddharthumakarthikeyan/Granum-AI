/** Counting what a selection of images is made of.
 *
 * The distinction these guard: counts come from the image rows and cover the whole
 * selection, while sizes come from geometry fetched a page at a time and cover only what
 * has arrived. A panel that blurred the two would report a dataset's object sizes from its
 * first hundred and twenty images.
 */

import { describe, expect, it } from "vitest";
import type { ImageBoxes, ImageRow, QaState } from "../../api/types";
import { byBoxSize, byClass, byObjectCount, byStatus, bySet } from "../../images/stats";

function image(path: string, set: string, objects: number, classes: number[]): ImageRow {
  return { row: 0, image: path, objects, classes, set, table: `t/${set}`, added: "2026-09-01" };
}

const items = [
  image("/d/a.jpg", "train", 0, []),
  image("/d/b.jpg", "train", 3, [0]),
  image("/d/c.jpg", "train", 40, [0, 1]),
  image("/d/d.jpg", "valid", 1, [1]),
];

describe("counts over the selection", () => {
  it("counts images per set, most first", () => {
    expect(bySet(items)).toEqual([
      { key: "train", label: "train", count: 3 },
      { key: "valid", label: "valid", count: 1 },
    ]);
  });

  it("puts every image in exactly one review state, unreviewed by default", () => {
    const statuses: Record<string, QaState> = {
      "/d/a.jpg": { status: "reviewed", comments: 0 },
      "/d/b.jpg": { status: "rework", comments: 1 },
    };
    expect(byStatus(items, statuses).map((bar) => bar.count)).toEqual([1, 1, 2]);
  });

  it("buckets objects per image and leaves out the buckets nothing landed in", () => {
    expect(byObjectCount(items)).toEqual([
      { key: "none", label: "none", count: 1 },
      { key: "1", label: "1", count: 1 },
      { key: "2–3", label: "2–3", count: 1 },
      { key: "32–63", label: "32–63", count: 1 },
    ]);
  });

  it("counts an image once per class it contains, most images first", () => {
    const bars = byClass(items, { "0": "car", "1": "person" }, () => "#fff");
    expect(bars.map((bar) => [bar.label, bar.count])).toEqual([["car", 2], ["person", 2]]);
  });
});

describe("object sizes, over the geometry in hand", () => {
  const boxes: Record<string, ImageBoxes> = {
    // A tiny box, a mid one, and one covering most of the image.
    "/d/b.jpg": { w: 100, h: 100, b: [[0, 0, 0, 0.02, 0.02], [0, 0, 0, 0.3, 0.3]] },
    "/d/d.jpg": { w: 100, h: 100, b: [[1, 0, 0, 0.9, 0.9]] },
  };

  it("reads a box as the share of its image it covers", () => {
    const sizes = byBoxSize(items, boxes);
    // 0.04% under 0.1%; 9% in 5-25%; 81% over 25%.
    expect(sizes.bars.map((bar) => bar.count)).toEqual([1, 0, 0, 1, 1]);
  });

  it("says how much of the selection it actually covers", () => {
    const sizes = byBoxSize(items, boxes);
    expect(sizes.images).toBe(2);
    expect(sizes.objects).toBe(3);
    expect(byBoxSize(items, {}).objects).toBe(0);
  });
});
