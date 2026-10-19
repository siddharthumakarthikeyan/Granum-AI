import type { ColumnInfo, Row } from "../api/types";
import { asBoxValue } from "../boxes/model";
import { instancePasses } from "../store/filtering";
import type { Filter } from "../store/types";

export function landmarkIndices(column: ColumnInfo): number[] {
  return [...new Set(Object.keys(column.instance_properties ?? {}).flatMap(name => {
    const match = /^keypoint_(\d+)_(oks|confidence)$/.exec(name);
    return match ? [Number(match[1])] : [];
  }))].sort((a, b) => a - b);
}

export interface LandmarkSummary {
  index: number; scored: number; unavailable: number; confidenceCount: number;
  meanOks: number | null; meanConfidence: number | null;
}

/** Average observations, not averages of per-image averages. Null OKS is unscored. */
export function summarizeLandmarks(column: ColumnInfo, rows: Row[], visible: number[], filters: Filter[] = [], label?: number): LandmarkSummary[] {
  const totals = landmarkIndices(column).map(index => ({ index, scored: 0, unavailable: 0, confidenceCount: 0, oks: 0, confidence: 0 }));
  for (const rowIndex of visible) {
    const row = rows[rowIndex];
    if (!row) continue;
    const instances = asBoxValue(row[column.name])?.instances ?? [];
    instances.forEach((instance, i) => {
      if (label !== undefined && instance.label !== label) return;
      if (!instancePasses(row, column.name, i, filters)) return;
      for (const summary of totals) {
        const oks = instance[`keypoint_${summary.index}_oks`];
        const confidence = instance[`keypoint_${summary.index}_confidence`];
        if (typeof oks === "number" && Number.isFinite(oks)) { summary.oks += oks; summary.scored++; }
        else summary.unavailable++;
        if (typeof confidence === "number" && Number.isFinite(confidence)) { summary.confidence += confidence; summary.confidenceCount++; }
      }
    });
  }
  return totals.map(({ oks, confidence, ...summary }) => ({ ...summary,
    meanOks: summary.scored ? oks / summary.scored : null,
    meanConfidence: summary.confidenceCount ? confidence / summary.confidenceCount : null }));
}
