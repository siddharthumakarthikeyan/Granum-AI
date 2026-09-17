/** Favourite charts, remembered per project and per object kind in this browser.
 *
 * A convenience, not data: if storage is blocked the dashboard behaves as if nothing
 * was ever saved.
 */

import { chartSignature, newChartId, type ChartSpec } from "./spec";

function key(project: string | null, kind: string | null): string {
  return `granum.favourite-charts.${project ?? "_"}.${kind ?? "_"}`;
}

export function loadFavourites(project: string | null, kind: string | null): ChartSpec[] {
  try {
    const raw = window.localStorage.getItem(key(project, kind));
    const parsed = raw ? (JSON.parse(raw) as ChartSpec[]) : [];
    return Array.isArray(parsed) ? parsed : [];
  } catch {
    return [];
  }
}

function save(project: string | null, kind: string | null, specs: ChartSpec[]): void {
  try {
    window.localStorage.setItem(key(project, kind), JSON.stringify(specs));
  } catch {
    // storage unavailable: favourites last for this session only
  }
}

/** Add the chart to favourites, or remove it if an identical chart is already there. */
export function toggleFavourite(
  project: string | null,
  kind: string | null,
  spec: ChartSpec,
): ChartSpec[] {
  const signature = chartSignature(spec);
  const current = loadFavourites(project, kind);
  const next = current.some((s) => chartSignature(s) === signature)
    ? current.filter((s) => chartSignature(s) !== signature)
    : [...current, { ...spec, overlays: [] }];
  save(project, kind, next);
  return next;
}

/** Favourites whose columns all exist in the object just opened, with fresh ids. */
export function restoreFavourites(
  project: string | null,
  kind: string | null,
  available: Set<string>,
  columnsOf: (spec: ChartSpec) => string[],
): ChartSpec[] {
  return loadFavourites(project, kind)
    .filter((spec) => columnsOf(spec).every((c) => available.has(c)))
    .map((spec) => ({ ...spec, id: newChartId() }));
}
