/** Unrolling a gallery into one tile per object, and placing a crop inside that tile.
 *
 * The sums here fail silently -- a patch placed wrongly still looks like a picture -- so
 * they are checked against numbers worked out by hand rather than against a snapshot.
 */

import { describe, expect, it } from "vitest";
import type { ImageBoxes, ImageRow } from "../../api/types";
import { patchPlacement, patchesFor } from "../../images/patches";

function image(path: string, set = "train"): ImageRow {
  return { row: 0, image: path, objects: 2, classes: [0, 1], set, table: `t/${set}`, added: "2026-09-01" };
}

const rows = [image("/d/a.jpg"), image("/d/b.jpg"), image("/d/c.jpg")];

const boxes: Record<string, ImageBoxes> = {
  "/d/a.jpg": { w: 100, h: 50, b: [[0, 0.1, 0.2, 0.3, 0.6], [1, 0.5, 0.5, 0.9, 1.0]] },
  "/d/b.jpg": { w: 200, h: 100, b: [[1, 0, 0, 0.5, 0.5]] },
};

describe("the objects of a gallery", () => {
  it("follows the gallery's order and turns fractions into the image's own pixels", () => {
    const page = patchesFor(rows, boxes, new Set(), 100);
    expect(page.patches.map((patch) => patch.item.image)).toEqual(["/d/a.jpg", "/d/a.jpg", "/d/b.jpg"]);
    expect(page.patches[0]).toMatchObject({ index: 0, label: 0, x0: 10, y0: 10, x1: 30, y1: 30, width: 100, height: 50 });
    // One image's geometry has not arrived, so its objects are not here and it is counted.
    expect(page.read).toBe(2);
    expect(page.waiting).toBe(1);
    expect(page.capped).toBe(false);
  });

  it("narrows the objects, not only the images, when a class is chosen", () => {
    const page = patchesFor(rows, boxes, new Set([1]), 100);
    expect(page.patches.map((patch) => patch.index)).toEqual([1, 0]);
    expect(page.patches.every((patch) => patch.label === 1)).toBe(true);
    // The image is still read: it is only its other class's boxes that are left out.
    expect(page.read).toBe(2);
  });

  it("says when it stopped rather than quietly drawing a short list", () => {
    const page = patchesFor(rows, boxes, new Set(), 2);
    expect(page.patches).toHaveLength(2);
    expect(page.capped).toBe(true);
  });

  it("gives each object of an image its own tile identity", () => {
    const page = patchesFor(rows, boxes, new Set(), 100);
    expect(new Set(page.patches.map((patch) => patch.id)).size).toBe(page.patches.length);
  });
});

describe("placing a crop inside a square tile", () => {
  const page = patchesFor(rows, boxes, new Set(), 100);

  it("draws the box at four fifths of the tile, centred, with its surroundings around it", () => {
    // 20 x 20 px box in a 100 x 50 image, in a 100 px tile: scale 80/20 = 4.
    const place = patchPlacement(page.patches[0]!, 100);
    expect(place.backgroundSize).toBe("400px 200px");
    expect(place.box).toEqual({ x: 10, y: 10, width: 80, height: 80 });
    // The image is pushed left and up by where the box sits in it, then by the centring.
    expect(place.backgroundPosition).toBe("-30px -30px");
  });

  it("scales a wide box by its long side, so nothing is cut off", () => {
    // 100 x 50 px box in a 200 x 100 image: scale 80/100 = 0.8, so the height is half of it.
    const place = patchPlacement(page.patches[2]!, 100);
    expect(place.box).toEqual({ x: 10, y: 30, width: 80, height: 40 });
  });

  it("survives a box with no area, which real exports do contain", () => {
    const flat = patchesFor([image("/d/f.jpg")], { "/d/f.jpg": { w: 10, h: 10, b: [[0, 0.5, 0.5, 0.5, 0.5]] } }, new Set(), 10);
    const place = patchPlacement(flat.patches[0]!, 100);
    expect(Number.isFinite(place.box.width) && place.box.width > 0).toBe(true);
  });
});
