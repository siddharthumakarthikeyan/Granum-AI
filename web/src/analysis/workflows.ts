/** Portable analysis recipes contain view settings and calculations, never data or executable code. */
import type { ColumnInfo } from "../api/types";
import { chartColumns, newChartId, type ChartSpec } from "../charts/spec";
import { isActive, isFilterable, makeElementFilters, makeFilter } from "../store/filtering";
import type { StoreState } from "../store/store";
import type { Filter, Region, Scope, SortKey, ViewMode } from "../store/types";
import { materializeColumns, parseVirtualColumns, type VirtualColumn } from "./virtualColumns";

export interface AnalysisWorkflow {
  version: 1;
  name: string;
  columns: { name: string; kind: string }[];
  calculations: VirtualColumn[];
  charts: ChartSpec[];
  filters: Filter[];
  sort: SortKey[];
  order: string[];
  hidden: string[];
  chartsPerRow: number;
  viewMode: ViewMode;
  gridSize: number;
}
const KEY = "granum.analysis.workflows.v1";
const invalid = (label: string): never => { throw new Error(`Invalid workflow: ${label}`); };
function object(value: unknown): Record<string, unknown> {
  if (!value || typeof value !== "object" || Array.isArray(value)) return invalid("expected an object");
  return value as Record<string, unknown>;
}
function text(value: unknown): string {
  if (typeof value !== "string" || !value.trim() || value.length > 256) return invalid("expected a name");
  return value;
}
function list(value: unknown, max = 256): unknown[] {
  if (!Array.isArray(value) || value.length > max) return invalid("too many or invalid entries");
  return value;
}
function strings(value: unknown): string[] { return list(value).map(text); }
function numeric(value: unknown, lo = -Infinity, hi = Infinity): number {
  if (typeof value !== "number" || !Number.isFinite(value) || value < lo || value > hi) return invalid("expected a finite number in range");
  return value;
}
function flag(value: unknown): boolean {
  if (typeof value !== "boolean") return invalid("expected a boolean");
  return value;
}
function nullableName(value: unknown): string | null { return value === null ? null : text(value); }
function pair(value: unknown): [number, number] {
  const parts = list(value, 2);
  if (parts.length !== 2) return invalid("expected two coordinates");
  return [numeric(parts[0]), numeric(parts[1])];
}

function parseChart(value: unknown): ChartSpec {
  const c = object(value);
  const base = { id: newChartId(), locked: flag(c.locked), overlays: strings(c.overlays) };
  if (c.kind === "image") return { ...base, kind: "image", image: text(c.image), labels: strings(c.labels) };
  if (c.kind !== "scatter") return invalid("unknown chart type");
  const slots = c.slots === null ? null : list(c.slots, 3).map(v => v === null || typeof v === "string" ? v : numeric(v));
  const trajectory = c.trajectory == null ? null : object(c.trajectory);
  return { ...base, kind: "scatter", x: text(c.x), y: text(c.y), z: c.z === undefined ? null : nullableName(c.z), color: nullableName(c.color), size: nullableName(c.size),
    trajectory: trajectory ? { groupBy: text(trajectory.groupBy), orderBy: text(trajectory.orderBy) } : null,
    pointSize: numeric(c.pointSize, 0.1, 100), slots, showFilteredOut: flag(c.showFilteredOut) };
}

function parseFilter(value: unknown): Filter {
  const f = object(value);
  if (f.scope !== "row" && f.scope !== "element") return invalid("filter scope");
  const base = { column: text(f.column), scope: f.scope as Scope, inverted: flag(f.inverted), locked: flag(f.locked),
    showFilteredOut: flag(f.showFilteredOut), ...(f.geometry ? { geometry: text(f.geometry), property: text(f.property) } : {}) };
  if (f.kind === "numeric") {
    const bounds = pair(f.bounds), range = pair(f.range);
    if (range[0] > range[1] || bounds[0] > bounds[1]) return invalid("reversed filter range");
    return { ...base, kind: "numeric", bounds, range };
  }
  if (f.kind === "boolean") return { ...base, kind: "boolean", value: f.value === null ? null : flag(f.value) };
  if (f.kind === "categorical") {
    const values = (v: unknown) => list(v, 5000).map(item => typeof item === "string" ? item : numeric(item));
    return { ...base, kind: "categorical", values: values(f.values), excluded: values(f.excluded) };
  }
  if (f.kind !== "region") return invalid("unknown filter type");
  const regions: Region[] = list(f.regions, 64).map(item => {
    const region = object(item);
    if (region.mode !== "add" && region.mode !== "subtract") return invalid("region operation");
    return { mode: region.mode, polygon: list(region.polygon, 4096).map(pair) };
  });
  return { ...base, kind: "region", x: text(f.x), y: text(f.y), regions };
}

export function parseWorkflow(value: unknown): AnalysisWorkflow {
  const w = object(value);
  if (w.version !== 1) return invalid("unsupported version");
  if (w.viewMode !== "list" && w.viewMode !== "grid" && w.viewMode !== "patches") return invalid("view mode");
  return {
    version: 1, name: text(w.name),
    columns: list(w.columns).map(v => { const c = object(v); return { name: text(c.name), kind: text(c.kind) }; }),
    calculations: parseVirtualColumns(w.calculations), charts: list(w.charts, 32).map(parseChart),
    filters: list(w.filters).map(parseFilter), sort: list(w.sort).map(v => {
      const s = object(v);
      if (s.direction !== "asc" && s.direction !== "desc") return invalid("sort direction");
      return { column: text(s.column), direction: s.direction };
    }),
    order: strings(w.order), hidden: strings(w.hidden), chartsPerRow: numeric(w.chartsPerRow, 1, 6),
    viewMode: w.viewMode, gridSize: numeric(w.gridSize, 40, 1000),
  };
}

export function captureWorkflow(state: StoreState, name: string): AnalysisWorkflow {
  const filters = Object.values(state.filters).filter(f => isActive(f) || f.locked);
  const required = new Set([
    ...state.charts.flatMap(chartColumns), ...state.sort.map(s => s.column),
    ...filters.flatMap(f => f.kind === "region" ? [f.x, f.y] : [f.geometry ?? f.column]),
    ...state.virtualColumns.flatMap(c => [...c.inputs, ...c.groupBy, ...(c.orderBy ? [c.orderBy] : [])]),
  ]);
  return parseWorkflow({
    version: 1, name: name.trim(), columns: state.columns.filter(c => required.has(c.name) && c.source !== "virtual")
      .map(c => ({ name: c.name, kind: c.kind })),
    calculations: state.virtualColumns, charts: state.charts, filters, sort: state.sort,
    order: state.order, hidden: [...state.hidden], chartsPerRow: state.chartsPerRow,
    viewMode: state.viewMode, gridSize: state.gridSize,
  });
}

export function validateWorkflow(workflow: AnalysisWorkflow, state: StoreState): void {
  const current = new Map(state.columns.filter(c => c.source !== "virtual").map(c => [c.name, c]));
  for (const c of workflow.columns) if (current.get(c.name)?.kind !== c.kind) throw new Error(`Workflow needs ${c.name} (${c.kind})`);
  const calculated = materializeColumns(state.rows, state.columns, workflow.calculations);
  const names = new Set([...calculated.columns.map(c => c.name), "#", "_src", "_row"]);
  for (const name of [...workflow.charts.flatMap(chartColumns), ...workflow.sort.map(s => s.column)]) {
    if (!names.has(name)) throw new Error(`Workflow needs column ${name}`);
  }
  for (const filter of workflow.filters) {
    const refs = filter.kind === "region" ? [filter.x, filter.y] : [filter.geometry ?? filter.column];
    if (refs.some(name => !names.has(name))) throw new Error(`Workflow filter needs ${refs.join(", ")}`);
  }
}

export function workflowView(workflow: AnalysisWorkflow, state: StoreState): Partial<StoreState> {
  const filters: Record<string, Filter> = {};
  for (const column of state.columns) {
    const filter = isFilterable(column) ? makeFilter(column, state.rows) : null;
    if (filter) filters[column.name] = filter;
    if (column.kind === "bounding_boxes_2d") {
      for (const element of makeElementFilters(column, state.rows)) filters[element.column] = element;
    }
  }
  for (const f of workflow.filters) {
    const current = filters[f.column];
    if (f.kind === "region") filters[f.column] = f;
    else if (current?.kind === f.kind) filters[f.column] = f.kind === "numeric" && current.kind === "numeric"
      ? { ...f, bounds: current.bounds } : f.kind === "categorical" && current.kind === "categorical"
        ? { ...f, values: current.values } : f;
    else throw new Error(`Workflow filter is incompatible with ${f.column}`);
  }
  const names = new Set(state.columns.map(c => c.name));
  const order = workflow.order.filter(n => names.has(n));
  return { filters, filterBasis: state.rows, charts: workflow.charts.map(c => ({ ...c, id: newChartId() })),
    sort: workflow.sort, order: [...order, ...state.columns.map(c => c.name).filter(n => !order.includes(n))],
    hidden: new Set(workflow.hidden.filter(n => names.has(n))), chartsPerRow: workflow.chartsPerRow,
    viewMode: workflow.viewMode, gridSize: workflow.gridSize };
}

export function readWorkflows(): AnalysisWorkflow[] {
  const raw = localStorage.getItem(KEY);
  return raw ? list(JSON.parse(raw), 100).map(parseWorkflow) : [];
}
export function writeWorkflows(workflows: AnalysisWorkflow[]): void {
  if (workflows.length > 100) throw new Error("Remove an old workflow before saving another");
  localStorage.setItem(KEY, JSON.stringify(workflows.map(parseWorkflow)));
}
export function compatibleColumns(columns: ColumnInfo[]): ColumnInfo[] { return columns.filter(c => c.source !== "session"); }
