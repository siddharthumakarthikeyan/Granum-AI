import type { ColumnInfo } from "../api/types";
import { chartColumns } from "../charts/spec";
import { isActive, isFilterable, makeFilter } from "../store/filtering";
import type { StoreState } from "../store/store";
import { materializeColumns } from "./virtualColumns";

/** Run inside the same store transaction as edits/undo so no consumer sees stale calculations. */
export function reconcileAnalysis(previous: StoreState, patch: Partial<StoreState>): Partial<StoreState> {
  const definitions = patch.virtualColumns ?? previous.virtualColumns;
  if (!definitions.length && !previous.virtualColumns.length) return patch;
  if (patch.rows === undefined && patch.columns === undefined && patch.virtualColumns === undefined) return patch;
  const inputRows = patch.rows ?? previous.rows;
  const inputColumns = patch.columns ?? previous.columns;
  let derived: ReturnType<typeof materializeColumns>;
  let analysisError: string | null = null;
  try {
    derived = materializeColumns(inputRows, inputColumns, definitions);
  } catch (error) {
    // Undo can remove a newly-created input column. Keep definitions for redo, hide stale values.
    analysisError = error instanceof Error ? error.message : String(error);
    derived = materializeColumns(inputRows, inputColumns, []);
  }
  const names = new Set(derived.columns.map(c => c.name));
  const filters = { ...(patch.filters ?? previous.filters) };
  const oldVirtual = previous.columns.filter(c => c.source === "virtual");
  for (const col of oldVirtual) if (!names.has(col.name)) delete filters[col.name];
  for (const col of derived.columns.filter(c => c.source === "virtual")) {
    const fresh = isFilterable(col) ? makeFilter(col, derived.rows) : null;
    if (!fresh) continue;
    const old = filters[col.name];
    filters[col.name] = !old || old.kind !== fresh.kind || !isActive(old) ? fresh
      : old.kind === "numeric" && fresh.kind === "numeric" ? { ...old, bounds: fresh.bounds }
        : old.kind === "categorical" && fresh.kind === "categorical" ? { ...old, values: fresh.values } : old;
  }
  for (const [key, filter] of Object.entries(filters)) {
    if (filter.kind === "region" && ((!names.has(filter.x) && filter.x !== "#") || !names.has(filter.y))) delete filters[key];
  }
  const order = (patch.order ?? previous.order).filter(name => names.has(name));
  for (const col of derived.columns) if (!order.includes(col.name)) order.push(col.name);
  return {
    ...patch, ...derived, analysisError, filters, order,
    sort: (patch.sort ?? previous.sort).filter(key => names.has(key.column)),
    charts: (patch.charts ?? previous.charts).filter(chart => chartColumns(chart).every(name => names.has(name))),
    ...(patch.filterBasis === inputRows ? { filterBasis: derived.rows } : {}),
  };
}

export function baseColumns(columns: ColumnInfo[]): ColumnInfo[] {
  return columns.filter(c => c.source !== "virtual" && c.source !== "session");
}
