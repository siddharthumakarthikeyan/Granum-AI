import { expect, it } from "vitest";
import { decodeMask, translateMask } from "./masks";
import { exclusiveMasks } from "./semanticEditing";

const shape = (label: number, polygon: number[]) => ({ label, box: [0, 0, 10, 10] as [number, number, number, number], polygons: [polygon], rle: null as unknown, moved: false });

it("subtracts a polygon from other classes without mutating the undo snapshot", () => {
  const before = [shape(1, [0, 0, 8, 0, 8, 8, 0, 8]), shape(2, [4, 0, 10, 0, 10, 10, 4, 10])];
  const snapshot = JSON.stringify(before);
  const after = exclusiveMasks(before, 1, 10, 10);
  expect(JSON.stringify(before)).toBe(snapshot);
  expect(after[1]).toBe(before[1]);
  expect(decodeMask(after[0]!.rle).reduce((a, b) => a + b, 0)).toBe(32);
  expect(after[0]!.box).toEqual([0, 0, 4, 8]);
});

it("a moved bitmap takes ownership only at its final position", () => {
  const initial = [shape(1, [0, 0, 4, 0, 4, 4, 0, 4]), shape(2, [4, 0, 8, 0, 8, 4, 4, 4])];
  const raster = exclusiveMasks(initial, 1, 10, 10);
  // Move a 4-by-4 bitmap two pixels into the other class.
  const moved = { ...raster[0]!, polygons: [], rle: translateMask({ size: [10, 10], counts: [0, 4, 6, 4, 6, 4, 6, 4, 66] }, 2, 0) };
  const after = exclusiveMasks([moved, initial[1]!], 0, 10, 10);
  expect(decodeMask(after[1]!.rle).reduce((a, b) => a + b, 0)).toBe(8);
  expect(initial[1]!.rle).toBeNull();
});
