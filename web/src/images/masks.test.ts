import { describe, expect, it } from "vitest";
import { decodeMask, encodeMask, maskBounds, paintMask, polygonsToMask, rleCounts, translateMask } from "./masks";
import { fitOriented, orientedBox, orientedCorners, resizeOriented } from "./oriented";

describe("pixel annotation editing", () => {
  it("keeps holes, disconnected regions, and column-major orientation", () => {
    const mask = new Uint8Array(100);
    paintMask(mask, 10, 10, [3, 3], [7, 7], 2, 1);
    paintMask(mask, 10, 10, [5, 5], [5, 5], 1, 0);
    const before = mask.slice(), encoded = encodeMask(mask, 10, 10);
    expect(decodeMask(JSON.parse(JSON.stringify(encoded)))).toEqual(before);
    expect(mask[5 * 10 + 5]).toBe(0);
    expect(mask[3 * 10 + 3]).toBe(1);
    const shifted = decodeMask(translateMask(encoded, 1, -1));
    expect(shifted[4 * 10 + 2]).toBe(1);
    expect(mask).toEqual(before);
  });
  it("decodes compressed COCO runs and rejects malformed or oversized masks", () => {
    expect(rleCounts({ size: [3, 3], counts: "1320" }).counts).toEqual([1, 3, 2, 3]);
    expect(decodeMask({ size: [3, 3], counts: "1320" })).toEqual(new Uint8Array([0, 1, 1, 1, 0, 0, 1, 1, 1]));
    for (const counts of [[1, 20], [-1, 10], [2.5, 6.5], "P", "~"]) expect(() => decodeMask({ size: [3, 3], counts })).toThrow();
    expect(() => decodeMask({ size: [100000, 100000], counts: [10000000000] })).toThrow();
  });
  it("rasterizes polygon union and computes bounds after erasing", () => {
    const mask = polygonsToMask([[1, 2, 4, 2, 4, 5, 1, 5]], 8, 8);
    expect(mask.reduce((a, b) => a + b, 0)).toBe(9);
    expect(maskBounds(mask, 8, 8)).toEqual([1, 2, 4, 5]);
    paintMask(mask, 8, 8, [2, 3], [2, 3], 10, 0);
    expect(maskBounds(mask, 8, 8)).toEqual([0, 0, 0, 0]);
  });
});

describe("oriented annotations", () => {
  it("keeps rotated corners inside the image without distorting the rectangle", () => {
    for (const angle of [Math.PI / 6, Math.PI / 3, Math.PI / 2]) {
      const box = { cx: 4, cy: 5, width: 180, height: 80, angle };
      const points = fitOriented(orientedCorners(box), 100, 50), fitted = orientedBox(points)!;
      expect(points.every((value, i) => value >= -1e-7 && value <= (i % 2 ? 50 : 100) + 1e-7)).toBe(true);
      expect(fitted.angle).toBeCloseTo(angle);
      expect(fitted.width / fitted.height).toBeCloseTo(box.width / box.height);
      const a = [points[2]! - points[0]!, points[3]! - points[1]!];
      const b = [points[6]! - points[0]!, points[7]! - points[1]!];
      expect(a[0]! * b[0]! + a[1]! * b[1]!).toBeCloseTo(0);
      expect(fitOriented(points, 100, 50)).toEqual(points.map(p => expect.closeTo(p, 7)));
    }
  });
  it("rotates without changing object dimensions and resizes in the rotated frame", () => {
    const box = { cx: 50, cy: 50, width: 40, height: 20, angle: Math.PI / 3 };
    const points = orientedCorners(box), read = orientedBox(points)!;
    expect(read.width).toBeCloseTo(box.width);
    expect(read.height).toBeCloseTo(box.height);
    expect(read.angle).toBeCloseTo(box.angle);
    const resized = resizeOriented(points, 0, [points[0]! - 5, points[1]! - 8]);
    expect(orientedBox(resized)!.angle).toBeCloseTo(box.angle);
    expect(resized[4]).toBeCloseTo(points[4]!);
    expect(resized[5]).toBeCloseTo(points[5]!);
  });
});
