import { OrbitViewport } from "@deck.gl/core";
import { expect, it } from "vitest";
import type { Row } from "../api/types";
import { ROW_INDEX } from "../store/types";
import { scatterSpec } from "./spec";
import { spatialHits } from "./spatialSelection";
import { trajectoryEdges } from "./trajectories";

it("orders trajectories by epoch while keeping source datasets and duplicate epochs separate", () => {
  const rows: Row[] = [
    { _row: 0, _src: "train", id: 1, epoch: 2 },
    { _row: 1, _src: "valid", id: 1, epoch: 0 },
    { _row: 2, _src: "train", id: 1, epoch: 0 },
    { _row: 3, _src: "train", id: 1, epoch: 1 },
    { _row: 4, _src: "valid", id: 1, epoch: 1 },
  ];
  const spec = { ...scatterSpec("x", "y"), trajectory: { groupBy: "id", orderBy: "epoch" } };
  expect(trajectoryEdges(rows, spec)).toEqual([[2, 3], [3, 0], [1, 4]]);
  expect(trajectoryEdges([...rows, { _row: 5, _src: "train", id: 1, epoch: 1 }], spec)).toEqual([[1, 4]]);
  expect(trajectoryEdges(rows, { ...spec, trajectory: { groupBy: "id", orderBy: ROW_INDEX } })).toEqual([[0, 2], [2, 3], [1, 4]]);
});

it("selects overlapping projected centres at all visible depths but excludes clipped and missing points", () => {
  const points = [
    { index: 0, screen: [10, 10, .1] }, { index: 1, screen: [10, 10, .9] },
    { index: 2, screen: [10, 10, -1] }, { index: 3, screen: [10, 10, 2] },
    { index: 4, screen: [NaN, 10, .5] }, { index: 5, screen: [100, 100, .5] },
  ];
  expect(spatialHits(points, [[0, 0], [20, 20]], "rect")).toEqual([0, 1]);
  expect(spatialHits(points, [[0, 0], [30, 0], [0, 30]], "lasso")).toEqual([0, 1]);
  expect(spatialHits(points, [[0, 0], [200, 0]], "brush")).toEqual([0, 1]);
});

it("uses the same orbit camera projection for area selection after rotating", () => {
  for (const rotationOrbit of [0, 45, 180]) {
    const viewport = new OrbitViewport({ width: 800, height: 600, target: [0, 0, 0], rotationX: 20, rotationOrbit, zoom: 0 });
    const points = [[0, 0, 0], [5, 5, 5], [10000, 10000, 10000]].map((position, index) => ({ index, screen: viewport.project(position) }));
    expect(spatialHits(points, [[350, 250], [450, 350]], "rect")).toEqual([0, 1]);
  }
});
