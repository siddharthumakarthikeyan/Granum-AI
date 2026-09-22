/** Unrolling a gallery into one tile per labelled object.
 *
 * Scanning every instance of a class is how a mislabelled box gets caught: a "car" that is
 * plainly a van stands out in a wall of cars in a way it never does inside a busy street
 * scene. The rules are pure so they can be tested without a browser, and because the sums
 * that place a crop inside a square tile are exactly the kind that go wrong silently.
 *
 * Geometry arrives as fractions of the image, because that is what draws a box over a
 * thumbnail of any size. A crop needs pixels, so every patch carries both the box in the
 * image's own pixels and the size of the image it was cut from.
 */

import type { ImageBoxes, ImageRow } from "../api/types";

/** One labelled object, as something to look at on its own. */
export interface Patch {
  /** The image and the box's place in it: stable while the image's labels are unchanged. */
  id: string;
  item: ImageRow;
  index: number;
  label: number | null;
  /** The box in the source image's pixels. */
  x0: number;
  y0: number;
  x1: number;
  y1: number;
  /** The source image's own size, which the crop is scaled against. */
  width: number;
  height: number;
}

/** What a run over the gallery produced, and whether it was cut short. */
export interface PatchPage {
  patches: Patch[];
  /** Images whose boxes have been read so far: the rest are still being fetched. */
  read: number;
  /** Images in the list that have no boxes yet, so their objects are not here. */
  waiting: number;
  /** The limit was reached, so there are more objects in the images already read. */
  capped: boolean;
}

/** Every box of the images given, in gallery order, up to a limit.
 *
 * Only the images whose geometry has arrived contribute -- the Images tab fetches boxes a
 * screenful at a time, so a patch grid is built from what is in hand and grows as the rest
 * lands, rather than waiting for a dataset's worth of geometry.
 *
 * A class filter narrows the *objects* here, not the images: asked for cars, a patch grid
 * that also showed the pedestrians standing next to them would defeat the point of it.
 */
export function patchesFor(
  items: ImageRow[],
  boxes: Record<string, ImageBoxes>,
  classes: Set<number>,
  limit: number,
): PatchPage {
  const patches: Patch[] = [];
  let read = 0;
  let waiting = 0;
  let capped = false;
  for (const item of items) {
    const geometry = boxes[item.image];
    if (!geometry) {
      waiting += 1;
      continue;
    }
    read += 1;
    for (const [index, box] of geometry.b.entries()) {
      const [label, x0, y0, x1, y1] = box;
      if (classes.size > 0 && (label === null || !classes.has(label))) continue;
      if (patches.length >= limit) {
        capped = true;
        continue;
      }
      patches.push({
        id: `${item.image}\u0000${index}`,
        item,
        index,
        label,
        x0: x0 * geometry.w,
        y0: y0 * geometry.h,
        x1: x1 * geometry.w,
        y1: y1 * geometry.h,
        width: geometry.w,
        height: geometry.h,
      });
    }
  }
  return { patches, read, waiting, capped };
}

/** Where to put the image behind a square tile so that one box sits in the middle of it.
 *
 * The box is drawn at four fifths of the tile, so every patch carries a little of what was
 * around it: a box judged with nothing outside it cannot be judged as too tight or as the
 * wrong object at all. A degenerate box -- zero width after rounding, which real exports do
 * contain -- is floored to a pixel rather than dividing by zero.
 */
export function patchPlacement(patch: Patch, size: number) {
  const width = Math.max(patch.x1 - patch.x0, 1);
  const height = Math.max(patch.y1 - patch.y0, 1);
  const scale = (size * 0.8) / Math.max(width, height);
  const left = (size - width * scale) / 2;
  const top = (size - height * scale) / 2;
  return {
    /** The whole image, scaled so that the box fills four fifths of the tile. */
    backgroundSize: `${patch.width * scale}px ${patch.height * scale}px`,
    backgroundPosition: `${left - patch.x0 * scale}px ${top - patch.y0 * scale}px`,
    /** Where the box itself lands in the tile, for the outline over it. */
    box: { x: left, y: top, width: width * scale, height: height * scale },
  };
}
