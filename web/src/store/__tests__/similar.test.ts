/** Reading a neighbour-graph report against the images a dataset holds now.
 *
 * The case that runs through these: a picture can be in a dataset several times because the
 * export augmented it, and that is not the same fact as two pictures being the same shot.
 */

import { describe, expect, it } from "vitest";
import type { ImageRow, LeakPair, SimilarImages } from "../../api/types";
import {
  leakSide,
  leakSides,
  likeRows,
  liveExports,
  liveGroups,
  liveLeaks,
  liveOutliers,
  marksFor,
  redundantImages,
} from "../../images/similar";

function image(path: string, set: string): ImageRow {
  return { row: 0, image: path, objects: 1, classes: [0], set, table: `t/${set}`, added: "2026-09-01" };
}

const rows = [
  image("/d/train/a.jpg", "train"),
  image("/d/train/a_flip.jpg", "train"),
  image("/d/valid/a.jpg", "valid"),
  image("/d/test/a.jpg", "test"),
  image("/d/train/b.jpg", "train"),
];
const byImage = new Map(rows.map((row) => [row.image, row]));

describe("groups of repeated pictures", () => {
  it("is not a group when every image came from one picture", () => {
    // A flip of a picture is as close to it as anything can be, and is not a repetition of it.
    expect(liveGroups([["/d/train/a.jpg", "/d/train/a_flip.jpg"]], byImage, [0], [[0, 0]])).toEqual([]);
  });

  it("keeps only the images the dataset still holds", () => {
    const groups = liveGroups([["/d/train/a.jpg", "/d/valid/a.jpg", "/d/gone.jpg"]], byImage, [0], [[0, 1, 2]]);
    expect(groups).toHaveLength(1);
    expect(groups[0]!.images.map((i) => i.item.image)).toEqual(["/d/train/a.jpg", "/d/valid/a.jpg"]);
    expect(groups[0]!.sources).toBe(2);
  });

  it("drops a group once only one picture is left in it", () => {
    // Its other picture was deleted; what remains is one picture and its own copy.
    expect(liveGroups([["/d/train/a.jpg", "/d/train/a_flip.jpg", "/d/gone.jpg"]], byImage, [0], [[0, 0, 1]])).toEqual([]);
  });

  it("keeps the training picture and the export's copies of it, and offers the rest", () => {
    // Sent in an order that would keep the wrong one if the order were trusted.
    const groups = liveGroups(
      [["/d/valid/a.jpg", "/d/train/a_flip.jpg", "/d/test/a.jpg", "/d/train/a.jpg"]],
      byImage, [0.01], [[1, 0, 2, 0]],
    );
    const group = groups[0]!;
    // The keeper and its own copies come first, in whatever order their names sort.
    expect(group.images.slice(0, 2).map((i) => i.item.image).sort())
      .toEqual(["/d/train/a.jpg", "/d/train/a_flip.jpg"]);
    expect(group.images.slice(0, 2).every((i) => i.family === group.images[0]!.family)).toBe(true);
    expect(redundantImages(groups)).toEqual(["/d/test/a.jpg", "/d/valid/a.jpg"]);
    expect(group.crossesSets).toBe(true);
  });

  it("puts the group with the most pictures first, not the most images", () => {
    const groups = liveGroups(
      [
        // Two pictures, four images: one flip each.
        ["/d/train/a.jpg", "/d/train/a_flip.jpg", "/d/valid/a.jpg", "/d/test/a.jpg"],
        // Three pictures, three images.
        ["/d/train/b.jpg", "/d/valid/a.jpg", "/d/test/a.jpg"],
      ],
      byImage, [0.1, 0.1], [[0, 0, 1, 1], [0, 1, 2]],
    );
    expect(groups.map((group) => group.sources)).toEqual([3, 2]);
  });

  it("keeps each group's spread beside it, whatever the order they arrive in", () => {
    const groups = liveGroups(
      [["/d/train/b.jpg", "/d/test/a.jpg"], ["/d/train/a.jpg", "/d/valid/a.jpg", "/d/gone.jpg"]],
      byImage, [0.31, 0.02], [[0, 1], [0, 1, 2]],
    );
    expect(groups.map((group) => group.spread)).toEqual([0.02, 0.31]);
  });
});

describe("the export's own copies", () => {
  it("lists each picture's copies, and says when a split was cut through one", () => {
    const sets = liveExports([
      { source: "a", images: ["/d/train/a.jpg", "/d/train/a_flip.jpg"], sets: ["train"] },
      { source: "c", images: ["/d/valid/a.jpg", "/d/test/a.jpg"], sets: ["valid", "test"] },
    ], byImage);
    // The one whose copies straddle a split comes first: that one is a leak.
    expect(sets.map((set) => set.source)).toEqual(["c", "a"]);
    expect(sets.map((set) => set.crossesSets)).toEqual([true, false]);
    expect(sets[0]!.sets).toEqual(["test", "valid"]);
  });

  it("forgets a copy set once its copies are gone", () => {
    expect(liveExports([{ source: "d", images: ["/d/train/b.jpg", "/d/gone.jpg"], sets: ["train"] }], byImage)).toEqual([]);
  });
});

describe("leaks", () => {
  const pair = (a: string, b: string, distance = 0.01, sameSource = false): LeakPair => ({
    a, b, sets: ["train", "valid"], distance, same_image: distance <= 0.05, same_source: sameSource,
  });

  it("measures the distance as a share of the dataset's typical distance", () => {
    const leaks = liveLeaks([pair("/d/train/a.jpg", "/d/valid/a.jpg", 0.04)], byImage, 0.4);
    expect(leaks[0]!.share).toBeCloseTo(0.1);
    expect(leaks[0]!.sameImage).toBe(true);
  });

  it("carries the fact that both sides are copies of one picture", () => {
    // Far apart in the embedding, and still a leak: the split was cut through one picture.
    const leaks = liveLeaks([pair("/d/train/a.jpg", "/d/valid/a.jpg", 0.6, true)], byImage, 0.4);
    expect(leaks[0]!.sameSource).toBe(true);
    expect(leaks[0]!.sameImage).toBe(false);
  });

  it("is not a leak once both sides are in one set", () => {
    // Moving an image is how a reader fixes a leak: it must vanish without a recompute.
    const moved = new Map(byImage);
    moved.set("/d/valid/a.jpg", image("/d/valid/a.jpg", "train"));
    expect(liveLeaks([pair("/d/train/a.jpg", "/d/valid/a.jpg")], moved, 0.4)).toEqual([]);
  });

  it("forgets a pair whose image has been deleted", () => {
    expect(liveLeaks([pair("/d/train/a.jpg", "/d/gone.jpg")], byImage, 0.4)).toEqual([]);
  });

  it("counts each leaked image once per side, whatever it pairs with", () => {
    const leaks = liveLeaks([
      pair("/d/train/a.jpg", "/d/valid/a.jpg"),
      pair("/d/train/a.jpg", "/d/test/a.jpg", 0.02),
    ], byImage, 0.4);
    // One image each, so the tie is broken by name rather than left to chance.
    expect(leakSides(leaks)).toEqual([
      { set: "test", images: 1 },
      { set: "train", images: 1 },
      { set: "valid", images: 1 },
    ]);
    expect(leakSide(leaks, "train")).toEqual(["/d/train/a.jpg"]);
  });
});

describe("marks on the gallery", () => {
  it("separates being a repeat, being an exported copy, and leaking", () => {
    const groups = liveGroups([["/d/train/a.jpg", "/d/valid/a.jpg"]], byImage, [0.1], [[0, 1]]);
    const exports = liveExports(
      [{ source: "a", images: ["/d/train/a.jpg", "/d/train/a_flip.jpg"], sets: ["train"] }],
      byImage,
    );
    const leaks = liveLeaks(
      [{ a: "/d/train/a.jpg", b: "/d/valid/a.jpg", sets: ["train", "valid"], distance: 0.01, same_image: true, same_source: false }],
      byImage, 0.4,
    );
    const marks = marksFor(groups, exports, leaks);
    expect(marks.get("/d/train/a.jpg")).toEqual({ copies: 2, exports: 2, leak: true });
    // The flip repeats nothing: it is a copy of a picture, so no copy count and no leak.
    expect(marks.get("/d/train/a_flip.jpg")).toEqual({ copies: 0, exports: 2, leak: false });
    expect(marks.get("/d/train/b.jpg")).toBeUndefined();
  });
});

describe("images with nothing like them", () => {
  it("keeps the ones the dataset still holds, furthest from anything first", () => {
    const outliers = liveOutliers([
      { image: "/d/train/b.jpg", score: 0.95, set: "train", alone: true },
      { image: "/d/gone.jpg", score: 1.4, set: "train", alone: true },
      { image: "/d/train/a.jpg", score: 1.2, set: "train", alone: true },
    ], byImage);
    expect(outliers.map((row) => row.item.image)).toEqual(["/d/train/a.jpg", "/d/train/b.jpg"]);
    expect(outliers[0]!.score).toBe(1.2);
  });

  it("keeps the ones the policy calls alone apart from the merely furthest", () => {
    // A set where nothing is isolated still has a loneliest image, and it is listed.
    const outliers = liveOutliers([
      { image: "/d/train/a.jpg", score: 0.4, set: "train", alone: false },
      { image: "/d/train/b.jpg", score: 0.3, set: "train", alone: false },
    ], byImage);
    expect(outliers.map((row) => row.alone)).toEqual([false, false]);
  });
});

describe("what else looks like this one", () => {
  const answer = (neighbours: SimilarImages["neighbours"], scale = 0.4): SimilarImages =>
    ({ image: "/d/train/a.jpg", set: "train", scale, neighbours });

  it("reads each distance as a share of the dataset's typical distance", () => {
    const rows = likeRows(answer([
      { image: "/d/valid/a.jpg", set: "valid", distance: 0.02 },
      { image: "/d/train/b.jpg", set: "train", distance: 0.4 },
    ]), byImage);
    expect(rows.map((row) => row.item.image)).toEqual(["/d/valid/a.jpg", "/d/train/b.jpg"]);
    expect(rows[0]!.share).toBeCloseTo(0.05);
    expect(rows[1]!.share).toBeCloseTo(1);
  });

  it("keeps the service's order rather than re-sorting it", () => {
    const rows = likeRows(answer([
      { image: "/d/train/b.jpg", set: "train", distance: 0.3 },
      { image: "/d/valid/a.jpg", set: "valid", distance: 0.3 },
    ]), byImage);
    expect(rows.map((row) => row.item.image)).toEqual(["/d/train/b.jpg", "/d/valid/a.jpg"]);
  });

  it("drops what the gallery cannot place, and never the image itself", () => {
    const rows = likeRows(answer([
      { image: "/d/train/a.jpg", set: "train", distance: 0 },
      { image: "/d/gone.jpg", set: "train", distance: 0.1 },
      { image: "/d/valid/a.jpg", set: "valid", distance: 0.2 },
    ]), byImage);
    expect(rows.map((row) => row.item.image)).toEqual(["/d/valid/a.jpg"]);
  });

  it("reads a distance as nothing when the dataset has no scale to read it against", () => {
    const rows = likeRows(answer([{ image: "/d/valid/a.jpg", set: "valid", distance: 0.2 }], 0), byImage);
    expect(rows[0]!.share).toBe(0);
  });
});
