import { decodeMask, encodeMask, maskBounds, polygonsToMask } from "./masks";

interface MaskShape {
  label: number | null; rle: unknown; polygons: number[][]; box: [number, number, number, number]; moved: boolean;
}

/** The edited region owns its pixels. Other classes lose overlapping pixels atomically. */
export function exclusiveMasks<T extends MaskShape>(shapes: T[], winner: number, width: number, height: number, panoptic = false): T[] {
  const selected = shapes[winner];
  if (!selected || (!selected.rle && !selected.polygons.length)) return shapes;
  const pixels = selected.rle ? decodeMask(selected.rle, width, height) : polygonsToMask(selected.polygons, width, height);
  return shapes.map((shape, index) => {
    if (index === winner || (!panoptic && selected.label === shape.label) || (!shape.rle && !shape.polygons.length)) return shape;
    // At most two decoded masks are live, independent of the number of classes.
    const other = shape.rle ? decodeMask(shape.rle, width, height) : polygonsToMask(shape.polygons, width, height);
    let changed = false;
    for (let i = 0; i < pixels.length; i++) if (pixels[i] && other[i]) { other[i] = 0; changed = true; }
    return changed ? { ...shape, polygons: [], rle: encodeMask(other, width, height), box: maskBounds(other, width, height), moved: true } : shape;
  });
}

export function nonemptyMask(shape: MaskShape): boolean {
  return Boolean((shape.rle || shape.polygons.length) && shape.box[2] > shape.box[0] && shape.box[3] > shape.box[1]);
}
