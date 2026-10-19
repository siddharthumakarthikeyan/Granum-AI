import type { Row } from "../api/types";
import { cellValue } from "../store/filtering";
import type { ScatterSpec } from "./spec";

/** Indices into the original rows. A source is part of sample identity, so identical
 * example IDs in different datasets can never be connected to each other. */
export function trajectoryEdges(rows: Row[], spec: ScatterSpec): [number, number][] {
  if (!spec.trajectory) return [];
  const { groupBy, orderBy } = spec.trajectory;
  const groups = new Map<string, { index: number; order: number }[]>();
  rows.forEach((row, index) => {
    const group = cellValue(row, groupBy, index), order = cellValue(row, orderBy, index);
    if (group == null || !["number", "string", "boolean"].includes(typeof group) || typeof order !== "number" || !Number.isFinite(order)) return;
    const key = JSON.stringify([row._src ?? null, group]);
    const values = groups.get(key) ?? [];
    values.push({ index, order }); groups.set(key, values);
  });
  const edges: [number, number][] = [];
  for (const group of groups.values()) {
    group.sort((a, b) => a.order - b.order || a.index - b.index);
    for (let i = 1; i < group.length; i++) {
      const a = group[i - 1]!, b = group[i]!;
      // Duplicate observations have no unambiguous temporal order.
      if (a.order === b.order || group[i - 2]?.order === a.order || group[i + 1]?.order === b.order) continue;
      edges.push([a.index, b.index]);
    }
  }
  return edges;
}
