/** The single store the three panels share.
 *
 * Rows, Filters and Charts are linked because they read the same state, not because
 * they message each other. A filter change repaints the grid for the same reason it
 * repaints a histogram: both derive from `visibleRows`.
 */

import { create } from "zustand";
import { api } from "../api/client";
import type {
  ColumnInfo, Health, ImportSummary, ObjectEntry, ProjectSummary, Row, RowPage, RunMetadata,
} from "../api/types";
import {
  loadFavourites, restoreFavourites, toggleFavourite as toggleStoredFavourite,
} from "../charts/favourites";
import {
  chartColumns, chartFromColumns, chartSignature, newChartId, type ChartSpec,
} from "../charts/spec";
import { createBoxActions, type BoxActions, type BoxState } from "../boxes/boxActions";
import { DEFAULT_BOX_DISPLAY, type BoxDisplay, type InstanceRef } from "../boxes/model";
import { createEditActions, type EditActions } from "./editActions";
import { rowsByTarget, targetKey, type Batch, type RowAddressing } from "./editing";
import { isActive, isFilterable, makeElementFilters, makeFilter, regionFilterKey } from "./filtering";
import { visibleIndices } from "./derive";
import { draftKey, flushDrafts, scheduleDraft } from "./drafts";
import { isSessionColumn, sessionColumnInfos, setSession } from "./session";

/** Derived per image: the number of labelled boxes. */
export const BOX_COUNT_COLUMN = "boxes_per_image";
import {
  ClickModifier, emptySelection, escapeSelection, moveSelection,
  selectAll, selectRow, toggleColumn,
} from "./selection";
import type { Filter, Region, RegionFilter, Selection, SortKey, ViewMode } from "./types";

export type RegionMode = "replace" | "add" | "subtract";

export const PAGE_SIZE = 5000;
const PAGE_CONCURRENCY = 4;

/** Every row of an object, not just its first page.
 *
 * Filters, histograms and sorting all run client-side over `rows`, so a partial load
 * is silently wrong: a run with 80k metrics rows showed one epoch's worth and built
 * its epoch filter from that. Pages after the first are fetched a few at a time.
 */
export async function fetchAllRows(
  fetchPage: (offset: number, limit: number) => Promise<RowPage>,
): Promise<RowPage> {
  const first = await fetchPage(0, PAGE_SIZE);
  const offsets: number[] = [];
  for (let offset = first.rows.length; offset < first.total; offset += PAGE_SIZE) {
    offsets.push(offset);
  }
  const pages: Row[][] = new Array(offsets.length);
  let next = 0;
  const worker = async () => {
    while (next < offsets.length) {
      const slot = next++;
      pages[slot] = (await fetchPage(offsets[slot]!, PAGE_SIZE)).rows;
    }
  };
  await Promise.all(Array.from({ length: Math.min(PAGE_CONCURRENCY, offsets.length) }, worker));
  return { ...first, offset: 0, limit: first.total, rows: first.rows.concat(...pages) };
}

let columnsCache: {
  columns: ColumnInfo[];
  order: string[];
  hidden: Set<string>;
  result: ColumnInfo[];
} | null = null;

/** Bumped on every open, so a slow load cannot overwrite the object opened after it. */
let openToken = 0;

export type Page = "projects" | "tables" | "runs" | "data";

export interface OpenOptions {
  /** Keep filters, charts, sort, columns and selection -- used when reopening after a commit. */
  keepView?: boolean;
}

interface State extends EditActions, BoxActions, BoxState {
  // navigation
  page: Page;
  project: string | null;
  projects: ProjectSummary[];
  tables: ObjectEntry[];
  runs: ObjectEntry[];
  imports: ImportSummary[];
  lineageEdges: { from: string; to: string }[];
  health: Health | null;
  /** The project whose lists are loaded, so revisiting it does not refetch. */
  loadedProject: string | null;

  // open object
  sourceUrl: string | null;
  sourceKind: "table" | "run" | null;
  sourceName: string;
  run: RunMetadata | null;
  columns: ColumnInfo[];
  rows: Row[];
  total: number;

  // view
  filters: Record<string, Filter>;
  liveFilters: boolean;
  sort: SortKey[];
  hidden: Set<string>;
  order: string[];
  viewMode: ViewMode;
  gridSize: number;
  selection: Selection;

  // boxes
  boxDisplay: BoxDisplay;
  /** The one box being inspected or edited. Escape clears it before the row selection. */
  focusedInstance: (InstanceRef & { row: number }) | null;

  // charts
  charts: ChartSpec[];
  chartsPerRow: number;
  favourites: Set<string>;

  // editing
  address: RowAddressing | null;
  /** Table row -> dashboard rows showing it. */
  targets: Map<string, number[]>;
  undoStack: Batch[];
  redoStack: Batch[];
  visited: Set<number>;
  forceWeightOnCorrection: boolean;
  committing: boolean;
  /** Rows as they were when filters last changed; filters read these while live is off. */
  filterBasis: Row[];

  // status
  loading: boolean;
  error: string | null;
  serviceOk: boolean;

  // actions
  boot: () => Promise<void>;
  openProject: (name: string) => Promise<void>;
  refreshProjects: () => Promise<void>;
  setPage: (page: Page) => void;
  refreshProject: () => Promise<void>;
  openTable: (url: string, name: string, options?: OpenOptions) => Promise<void>;
  openRun: (url: string, name: string, options?: OpenOptions) => Promise<void>;
  back: () => void;

  setFilter: (column: string, next: Partial<Filter>) => void;
  resetFilter: (column: string) => void;
  toggleFilterLock: (column: string) => void;
  clearFilters: () => void;
  setLiveFilters: (on: boolean) => void;

  toggleSort: (column: string, additive: boolean) => void;
  hideColumns: (columns: string[]) => void;
  showColumn: (column: string) => void;
  hideOthers: (keep: string[]) => void;
  moveColumn: (column: string, before: string | null) => void;
  setViewMode: (mode: ViewMode) => void;
  setGridSize: (size: number) => void;

  clickRow: (row: number, modifier: ClickModifier) => void;
  clickColumn: (column: string, modifier: ClickModifier) => void;
  selectAllRows: () => void;
  moveCursor: (delta: number) => void;
  clearSelection: () => void;

  setBoxDisplay: (patch: Partial<BoxDisplay>) => void;
  focusInstance: (instance: (InstanceRef & { row: number }) | null) => void;

  addChartFromSelection: () => string | null;
  addChart: (spec: ChartSpec) => void;
  updateChart: (id: string, patch: Partial<ChartSpec>) => void;
  removeChart: (id: string) => void;
  cloneChart: (id: string) => void;
  toggleFavourite: (id: string) => void;
  setChartsPerRow: (count: number) => void;
  applyRegion: (x: string, y: string, polygons: Region["polygon"][], mode: RegionMode) => void;
  removeFilter: (column: string) => void;

  visibleRows: () => number[];
  excludedRows: () => number[];
  activeFilterCount: () => number;
  visibleColumns: () => ColumnInfo[];
}

const initialView = {
  filters: {} as Record<string, Filter>,
  sort: [] as SortKey[],
  hidden: new Set<string>(),
  order: [] as string[],
  selection: emptySelection(),
};

export type StoreState = State;
export type StoreSet = (
  partial: Partial<State> | ((state: State) => Partial<State> | State),
) => void;
export type StoreGet = () => State;

export const useStore = create<State>((set, get) => ({
  page: "projects",
  project: null,
  projects: [],
  tables: [],
  runs: [],
  imports: [],
  lineageEdges: [],
  health: null,
  loadedProject: null,

  sourceUrl: null,
  sourceKind: null,
  sourceName: "",
  run: null,
  columns: [],
  rows: [],
  total: 0,

  ...initialView,
  liveFilters: true,
  boxDisplay: DEFAULT_BOX_DISPLAY,
  focusedInstance: null,
  boxClipboard: null,
  dismissed: new Set(),
  staged: new Map(),
  address: null,
  targets: new Map(),
  undoStack: [],
  redoStack: [],
  visited: new Set(),
  forceWeightOnCorrection: true,
  committing: false,
  filterBasis: [],
  charts: [],
  chartsPerRow: 2,
  favourites: new Set(),
  viewMode: "list",
  gridSize: 120,

  loading: false,
  error: null,
  serviceOk: true,

  // -- navigation ---------------------------------------------------------

  boot: async () => {
    set({ loading: true, error: null });
    try {
      const health = await api.health();
      const projects = await api.projects();
      set({ projects, health, serviceOk: true, loading: false });
    } catch (error) {
      set({
        error: error instanceof Error ? error.message : String(error),
        serviceOk: false,
        loading: false,
      });
    }
  },

  openProject: async (name) => {
    const switching = get().loadedProject !== name;
    set({
      loading: true, project: name, error: null,
      ...(switching ? { tables: [], runs: [], imports: [], lineageEdges: [] } : {}),
    });
    try {
      const [tables, runs, lineage, imports] = await Promise.all([
        api.tables(name),
        api.runs(name),
        api.lineage(name),
        api.imports(name).catch(() => [] as ImportSummary[]),
      ]);
      if (get().project !== name) return;
      set({ tables, runs, imports, lineageEdges: lineage.edges, loadedProject: name, loading: false });
    } catch (error) {
      set({ error: error instanceof Error ? error.message : String(error), loading: false });
    }
  },

  refreshProjects: async () => {
    try {
      const [projects, health] = await Promise.all([api.projects(), api.health()]);
      set({ projects, health });
    } catch {
      // the list is refreshed opportunistically
    }
  },

  setPage: (page) => set({ page }),

  refreshProject: async () => {
    const { project } = get();
    if (!project) return;
    try {
      const [tables, runs, lineage, imports] = await Promise.all([
        api.tables(project), api.runs(project), api.lineage(project),
        api.imports(project).catch(() => [] as ImportSummary[]),
      ]);
      set({ tables, runs, imports, lineageEdges: lineage.edges, loadedProject: project });
    } catch {
      // navigation lists are refreshed opportunistically; the open object is what matters
    }
  },

  openTable: async (url, name, options = {}) => {
    set({ loading: true, error: null });
    const token = ++openToken;
    try {
      const [metadata, page] = await Promise.all([
        api.table(url),
        fetchAllRows((offset, limit) => api.rows(url, offset, limit)),
      ]);
      if (token !== openToken) return;
      set(installObject(get(), {
        kind: "table", url, name, run: null, columns: metadata.columns, page,
        sources: [url], keepView: Boolean(options.keepView),
      }));
    } catch (error) {
      if (token !== openToken) return;
      set({ error: error instanceof Error ? error.message : String(error), loading: false });
    }
  },

  openRun: async (url, name, options = {}) => {
    set({ loading: true, error: null });
    const token = ++openToken;
    try {
      const [metadata, page] = await Promise.all([
        api.run(url),
        fetchAllRows((offset, limit) => api.runJoined(url, offset, limit)),
      ]);
      if (token !== openToken) return;
      const first: Record<string, unknown> = page.rows[0] ?? {};
      const columns: ColumnInfo[] = metadata.columns?.length
        ? metadata.columns
        : Object.keys(first)
            .filter((key) => key !== "_row" && key !== "_src")
            .map((key) => ({
              name: key, kind: inferKind(key, first[key]), writable: false,
              default_visible: true, number_role: null, source: "metrics" as const,
            }));
      set(installObject(get(), {
        kind: "run", url, name, run: metadata, columns, page,
        sources: page.sources ?? metadata.sources ?? [], keepView: Boolean(options.keepView),
      }));
    } catch (error) {
      if (token !== openToken) return;
      set({ error: error instanceof Error ? error.message : String(error), loading: false });
    }
  },

  back: () => {
    const { project } = get();
    set({ page: project ? "runs" : "projects", sourceUrl: null, run: null });
  },

  // -- filters -------------------------------------------------------------

  setFilter: (column, next) =>
    set((state) => {
      const current = state.filters[column];
      if (!current) return state;
      return {
        filters: { ...state.filters, [column]: { ...current, ...next } as Filter },
        filterBasis: state.rows,
      };
    }),

  resetFilter: (column) =>
    set((state) => {
      const current = state.filters[column];
      if (current?.kind === "region") {
        return { filters: { ...state.filters, [column]: { ...current, regions: [] } }, filterBasis: state.rows };
      }
      const source = state.columns.find((c) => c.name === column);
      if (!current || !source) return state;
      const fresh = makeFilter(source, state.rows);
      if (!fresh) return state;
      return {
        filters: { ...state.filters, [column]: { ...fresh, locked: current.locked } },
        filterBasis: state.rows,
      };
    }),

  toggleFilterLock: (column) =>
    set((state) => {
      const current = state.filters[column];
      if (!current) return state;
      return {
        filters: { ...state.filters, [column]: { ...current, locked: !current.locked } },
      };
    }),

  clearFilters: () =>
    set((state) => {
      const filters: Record<string, Filter> = {};
      for (const [name, filter] of Object.entries(state.filters)) {
        if (filter.locked) {
          filters[name] = filter;
          continue;
        }
        if (filter.kind === "region") continue; // a cleared selection has no widget to keep
        const source = state.columns.find((c) => c.name === name);
        const fresh = source ? makeFilter(source, state.rows) : null;
        filters[name] = fresh ?? filter;
      }
      return { filters, filterBasis: state.rows };
    }),

  // Turning live back on re-evaluates against the edited rows; turning it off freezes
  // the rows filters read, so an edited row stays put until filters change.
  setLiveFilters: (on) => set((state) => ({ liveFilters: on, filterBasis: state.rows })),

  // -- columns -------------------------------------------------------------

  toggleSort: (column, additive) =>
    set((state) => {
      const existing = state.sort.find((k) => k.column === column);
      const others = additive ? state.sort.filter((k) => k.column !== column) : [];
      if (!existing) return { sort: [...others, { column, direction: "asc" as const }] };
      if (existing.direction === "asc") {
        return { sort: [...others, { column, direction: "desc" as const }] };
      }
      return { sort: others };
    }),

  hideColumns: (columns) =>
    set((state) => {
      const hidden = new Set(state.hidden);
      for (const column of columns) hidden.add(column);
      return { hidden };
    }),

  showColumn: (column) =>
    set((state) => {
      const hidden = new Set(state.hidden);
      hidden.delete(column);
      return { hidden };
    }),

  hideOthers: (keep) =>
    set((state) => {
      const keepSet = new Set(keep);
      const hidden = new Set(state.order.filter((name) => !keepSet.has(name)));
      return { hidden };
    }),

  moveColumn: (column, before) =>
    set((state) => {
      const order = state.order.filter((name) => name !== column);
      const at = before === null ? order.length : order.indexOf(before);
      order.splice(at === -1 ? order.length : at, 0, column);
      return { order };
    }),

  setViewMode: (viewMode) => set({ viewMode }),
  setGridSize: (gridSize) => set({ gridSize }),

  // -- selection -----------------------------------------------------------

  clickRow: (row, modifier) =>
    set((state) => ({
      selection: selectRow(state.selection, row, modifier, get().visibleRows()),
      visited: state.visited.has(row) ? state.visited : new Set(state.visited).add(row),
    })),

  clickColumn: (column, modifier) =>
    set((state) => ({ selection: toggleColumn(state.selection, column, modifier) })),

  selectAllRows: () =>
    set((state) => ({ selection: selectAll(state.selection, get().visibleRows()) })),

  moveCursor: (delta) =>
    set((state) => {
      const selection = moveSelection(state.selection, get().visibleRows(), delta);
      const at = selection.anchor;
      const visited = at === null || state.visited.has(at) ? state.visited : new Set(state.visited).add(at);
      return { selection, visited };
    }),

  clearSelection: () =>
    set((state) =>
      state.focusedInstance
        ? { focusedInstance: null }
        : { selection: escapeSelection(state.selection) },
    ),

  setBoxDisplay: (patch) => set((state) => ({ boxDisplay: { ...state.boxDisplay, ...patch } })),

  focusInstance: (instance) =>
    set((state) => {
      if (!instance) return { focusedInstance: null };
      const selection = state.selection.anchor === instance.row
        ? state.selection
        : selectRow(state.selection, instance.row, "none", get().visibleRows());
      const visited = state.visited.has(instance.row) ? state.visited : new Set(state.visited).add(instance.row);
      return { focusedInstance: instance, selection, visited };
    }),

  // -- charts --------------------------------------------------------------

  addChartFromSelection: () => {
    const { selection, columns } = get();
    const result = chartFromColumns([...selection.columns], columns);
    if (typeof result === "string") return result;
    get().addChart(result);
    return null;
  },

  addChart: (spec) => set((state) => ({ charts: [...state.charts, spec] })),

  updateChart: (id, patch) =>
    set((state) => ({
      charts: state.charts.map((c) => (c.id === id ? ({ ...c, ...patch } as ChartSpec) : c)),
    })),

  removeChart: (id) => set((state) => ({ charts: state.charts.filter((c) => c.id !== id) })),

  cloneChart: (id) =>
    set((state) => {
      const at = state.charts.findIndex((c) => c.id === id);
      if (at === -1) return state;
      const charts = [...state.charts];
      charts.splice(at + 1, 0, { ...charts[at]!, id: newChartId(), locked: false });
      return { charts };
    }),

  toggleFavourite: (id) =>
    set((state) => {
      const spec = state.charts.find((c) => c.id === id);
      if (!spec) return state;
      const saved = toggleStoredFavourite(state.project, state.sourceKind, spec);
      return { favourites: new Set(saved.map(chartSignature)) };
    }),

  setChartsPerRow: (count) => set({ chartsPerRow: Math.min(6, Math.max(1, Math.round(count))) }),

  applyRegion: (x, y, polygons, mode) =>
    set((state) => {
      const key = regionFilterKey(x, y);
      const current = state.filters[key];
      const existing: RegionFilter =
        current?.kind === "region"
          ? current
          : {
              column: key,
              kind: "region",
              scope: "row",
              x,
              y,
              regions: [],
              inverted: false,
              locked: false,
              showFilteredOut: false,
            };
      const strokes: Region[] = polygons
        .filter((p) => p.length >= 3)
        .map((polygon) => ({ mode: mode === "subtract" ? "subtract" : "add", polygon }));
      if (strokes.length === 0) return state;
      const regions = mode === "replace" ? strokes : [...existing.regions, ...strokes];
      return { filters: { ...state.filters, [key]: { ...existing, regions } }, filterBasis: state.rows };
    }),

  removeFilter: (column) =>
    set((state) => {
      if (!(column in state.filters)) return state;
      const filters = { ...state.filters };
      delete filters[column];
      return { filters, filterBasis: state.rows };
    }),

  ...createEditActions(set, get),
  ...createBoxActions(set, get),

  // -- derived -------------------------------------------------------------

  visibleRows: () => {
    const { rows, filterBasis, liveFilters, filters, sort } = get();
    // With live filters off, an edit must not make the row being edited vanish.
    return visibleIndices(liveFilters || filterBasis.length !== rows.length ? rows : filterBasis, filters, sort);
  },

  excludedRows: () => {
    const { rows } = get();
    const visible = new Set(get().visibleRows());
    const out: number[] = [];
    for (let i = 0; i < rows.length; i += 1) if (!visible.has(i)) out.push(i);
    return out;
  },

  activeFilterCount: () => Object.values(get().filters).filter(isActive).length,

  visibleColumns: () => {
    const { columns, order, hidden } = get();
    // Selectors must return a stable reference, or React re-renders forever.
    const hit = columnsCache;
    if (hit && hit.columns === columns && hit.order === order && hit.hidden === hidden) {
      return hit.result;
    }
    const byName = new Map(columns.map((c) => [c.name, c]));
    const result = order
      .filter((name) => !hidden.has(name))
      .map((name) => byName.get(name))
      .filter((c): c is ColumnInfo => Boolean(c));
    columnsCache = { columns, order, hidden, result };
    return result;
  },
}));

interface InstallArgs {
  kind: "table" | "run";
  url: string;
  name: string;
  run: RunMetadata | null;
  columns: ColumnInfo[];
  page: RowPage;
  sources: string[];
  keepView: boolean;
}

/** State for a freshly loaded Table or Run.
 *
 * With `keepView` the user's working context survives: after a commit the object is
 * reloaded from its new revision, and losing every filter, chart and the selection at
 * that moment would punish the user for saving.
 */
function installObject(previous: State, args: InstallArgs): Partial<State> {
  const rows = args.page.rows;
  const dataColumns = args.columns.filter((c) => !isSessionColumn(c.name) && c.name !== BOX_COUNT_COLUMN);
  // How many labelled boxes each image has, derived once at load so it filters and sorts
  // like any number. Crowd/ignore regions are not objects and are not counted.
  const boxSource = dataColumns.find((c) => c.kind === "bounding_boxes_2d" && c.source !== "metrics")
    ?? dataColumns.find((c) => c.kind === "bounding_boxes_2d");
  const derived: ColumnInfo[] = [];
  if (boxSource) {
    for (const row of rows) {
      const value = row[boxSource.name] as { instances?: { iscrowd?: unknown }[] } | null | undefined;
      row[BOX_COUNT_COLUMN] = (value?.instances ?? []).filter((i) => !i.iscrowd).length;
    }
    derived.push({ name: BOX_COUNT_COLUMN, kind: "int32", writable: false, default_visible: true, number_role: null, source: "table" });
  }
  const columns = [...dataColumns, ...derived, ...sessionColumnInfos()];
  const fresh: Record<string, Filter> = {};
  for (const column of columns) {
    const filter = isFilterable(column) ? makeFilter(column, rows) : null;
    if (filter) fresh[column.name] = filter;
    if (column.kind === "bounding_boxes_2d") {
      for (const element of makeElementFilters(column, rows)) fresh[element.column] = element;
    }
  }
  const address: RowAddressing = { kind: args.kind, sources: args.sources };
  const base = {
    focusedInstance: null,
    dismissed: new Set<string>(),
    staged: new Map<string, "accept" | "reject">(),
    sourceUrl: args.url,
    sourceKind: args.kind,
    sourceName: args.name,
    run: args.run,
    columns,
    rows,
    filterBasis: rows,
    total: args.page.total,
    address,
    targets: rowsByTarget(address, rows),
    undoStack: [],
    redoStack: [],
    page: "data" as const,
    loading: false,
  };

  if (!args.keepView) {
    return {
      ...initialView,
      ...chartsFor(previous.project, args.kind, columns),
      ...base,
      filters: fresh,
      selection: emptySelection(),
      visited: new Set(),
      order: columns.map((c) => c.name),
      hidden: new Set(columns.filter((c) => !c.default_visible).map((c) => c.name)),
    };
  }

  const names = new Set(columns.map((c) => c.name));
  const filters: Record<string, Filter> = { ...fresh };
  for (const [key, old] of Object.entries(previous.filters)) {
    const current = fresh[key];
    if (old.kind === "region") {
      if ((names.has(old.x) || old.x === "#") && names.has(old.y)) filters[key] = old;
    } else if (current && current.kind === old.kind) {
      filters[key] = old.kind === "numeric" && current.kind === "numeric"
        ? { ...old, bounds: current.bounds }
        : old.kind === "categorical" && current.kind === "categorical"
          ? { ...old, values: current.values }
          : old;
    }
  }
  const sameRows = previous.rows.length === rows.length;
  return {
    ...base,
    filters,
    sort: previous.sort.filter((k) => names.has(k.column)),
    order: [
      ...previous.order.filter((n) => names.has(n)),
      ...columns.map((c) => c.name).filter((n) => !previous.order.includes(n)),
    ],
    hidden: new Set([...previous.hidden].filter((n) => names.has(n))),
    selection: sameRows ? previous.selection : emptySelection(),
    visited: sameRows ? previous.visited : new Set(),
  };
}

/** Charts for a freshly opened object: its saved favourites, if their columns exist;
 * otherwise the image inspector, since looking at the images is where review starts. */
function chartsFor(project: string | null, kind: "table" | "run", columns: ColumnInfo[]) {
  const available = new Set(columns.map((c) => c.name));
  let charts = restoreFavourites(project, kind, available, chartColumns);
  const image = columns.find((c) => c.kind === "image");
  if (charts.length === 0 && image) {
    const inspector = chartFromColumns([image.name], columns);
    if (typeof inspector !== "string") charts = [inspector];
  }
  return {
    charts,
    favourites: new Set(loadFavourites(project, kind).map(chartSignature)),
  };
}

/** Infer a column kind for a Run view, where the join produces an untyped dict.
 *
 * Arrays must land on "embedding": a feature vector is not a category, and offering a
 * categorical filter over 180 distinct vectors produces an empty, useless widget.
 */
function inferKind(name: string, value: unknown): ColumnInfo["kind"] {
  if (name === "example_id") return "example_id";
  if (name === "epoch" || name === "iteration") return "epoch";
  if (name === "weight") return "sample_weight";
  if (Array.isArray(value)) return "embedding";
  if (typeof value === "boolean") return "bool";
  if (name === "accuracy" || name === "confidence") return "confidence";
  if (typeof value === "number") return Number.isInteger(value) ? "int64" : "float32";
  if (typeof value === "string" && /\.(png|jpe?g|webp|bmp|gif|tiff?)$/i.test(value)) {
    return "image";
  }
  return "string";
}

// Session columns read their values from outside the rows; keep them in step.
useStore.subscribe((state, previous) => {
  if (
    state.selection !== previous.selection ||
    state.visited !== previous.visited ||
    state.undoStack !== previous.undoStack ||
    state.targets !== previous.targets
  ) {
    const edited = new Set<number>();
    for (const change of state.pendingEdits().cells.values()) {
      for (const index of state.targets.get(targetKey(change.table, change.row)) ?? []) edited.add(index);
    }
    setSession({ Selected: state.selection.rows, Visited: state.visited, Edited: edited });
  }
});

// Keep unsaved edits in the browser as they happen, so a reload can recover them.
useStore.subscribe((state, previous) => {
  if (state.undoStack === previous.undoStack) return;
  if (!state.sourceUrl || !state.sourceKind) return;
  // Opening another object replaces the stack; that is not an edit of the new object.
  if (state.sourceUrl !== previous.sourceUrl) return;
  scheduleDraft({
    key: draftKey(state.sourceKind, state.sourceUrl),
    kind: state.sourceKind,
    url: state.sourceUrl,
    name: state.sourceName,
    sources: state.address?.sources ?? [],
    savedAt: new Date().toISOString(),
    batches: state.undoStack,
  });
});

if (typeof window !== "undefined") window.addEventListener("pagehide", flushDrafts);
