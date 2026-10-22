import { expect, it } from "vitest";
import type { ColumnInfo, Row } from "../api/types";
import { filterRows, makeElementFilters } from "../store/filtering";
import { summarizeLandmarks } from "./landmarks";

const column: ColumnInfo = { name: "pose", kind: "bounding_boxes_2d", writable: false, default_visible: true, number_role: null,
  instance_properties: { keypoint_0_oks: "float32", keypoint_0_confidence: "float32", keypoint_1_oks: "float32" } };
const rows: Row[] = [
  { _row: 0, pose: { instances: [{ keypoint_0_oks: .1, keypoint_0_confidence: 0 }, { keypoint_0_oks: .9, keypoint_0_confidence: .8 }] } },
  { _row: 1, pose: { instances: [{ keypoint_0_oks: null, keypoint_0_confidence: .6 }] } },
  { _row: 2, pose: { instances: [{ keypoint_0_oks: .6, keypoint_0_confidence: NaN }] } },
];

it("reports per-landmark observation means without scoring nulls as zero", () => {
  const [zero, one] = summarizeLandmarks(column, rows, [0, 1, 2]);
  expect(zero?.meanOks).toBeCloseTo(1.6 / 3);
  expect(zero?.scored).toBe(3);
  expect(zero?.unavailable).toBe(1);
  expect(zero?.meanConfidence).toBeCloseTo(1.4 / 3);
  expect(one?.meanOks).toBeNull();
  expect(one?.unavailable).toBe(4);
});

it("narrows both images and individual objects, keeping missing scores out", () => {
  const filter = makeElementFilters(column, rows).find(f => f.property === "keypoint_0_oks")!;
  expect(filter.kind).toBe("numeric");
  if (filter.kind !== "numeric") throw new Error("expected a numeric landmark filter");
  const active = { ...filter, range: [.5, 1] as [number, number], inverted: true };
  const visible = filterRows(rows, [active]);
  expect(visible).toEqual([0]);
  expect(summarizeLandmarks(column, rows, visible, [active])[0]).toMatchObject({ scored: 1, unavailable: 0, meanOks: .1, meanConfidence: 0 });
  expect(filterRows(rows, [{ ...active, range: [1, 1] }])).toEqual([0, 2]);
});

it("keeps class-specific landmark layouts separate", () => {
  const mixed: Row[] = [{ _row: 0, pose: { instances: [
    { label: 3, keypoint_0_oks: .2 }, { label: 7, keypoint_0_oks: 1 },
  ] } }];
  expect(summarizeLandmarks(column, mixed, [0], [], 3)[0]).toMatchObject({ meanOks: .2, scored: 1 });
  expect(summarizeLandmarks(column, mixed, [0], [], 7)[0]).toMatchObject({ meanOks: 1, scored: 1 });
});
