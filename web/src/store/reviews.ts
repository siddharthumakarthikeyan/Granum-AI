/** Review decisions shown beside the data, and recorded from a selection.
 *
 * Decisions live on the service, per dataset, keyed by image. Here they become an
 * ordinary filterable "Review" column, so "show me everything marked Unclear" is the same
 * gesture as any other filter. The column is never committed with edits.
 */

import { api } from "../api/client";
import type { ColumnInfo, ReviewEvent, Row } from "../api/types";
import { makeFilter } from "./filtering";
import { isSessionColumn } from "./session";
import { useStore } from "./store";
import type { CategoricalFilter } from "./types";

export const REVIEW_COLUMN = "Review";
export const NOT_REVIEWED = "Not reviewed";
const GROUP_SEPARATOR = String.fromCharCode(31);

export const REVIEW_STATUSES: { id: ReviewEvent["status"]; label: string; help: string }[] = [
  { id: "correct", label: "Correct", help: "The label is correct, even if the image is hard." },
  { id: "corrected", label: "Corrected", help: "The label was wrong and you corrected it." },
  { id: "ambiguous", label: "Ambiguous", help: "You can't tell what the right label should be." },
  { id: "deferred", label: "Deferred", help: "Come back to this one." },
  { id: "excluded", label: "Excluded", help: "The image is unusable, for example blurry or irrelevant." },
];

const LABELS = new Map<string, string>(REVIEW_STATUSES.map((s) => [s.id, s.label]));

/** Decisions for the object currently open: dataset name -> image -> decision. */
let cache: { url: string; byDataset: Map<string, Record<string, ReviewEvent>> } | null = null;

const reviewColumn: ColumnInfo = {
  name: REVIEW_COLUMN, kind: "string", writable: false, default_visible: true, number_role: null, source: "session",
};

interface RowAddress {
  dataset: string;
  table: string;
  sample: string;
}

/** Which dataset, table revision and image a dashboard row refers to. */
function addressOf(): ((row: Row) => RowAddress | null) | null {
  const state = useStore.getState();
  const image = state.columns.find((c) => c.kind === "image");
  if (!image || !state.sourceUrl) return null;
  const datasetOf = new Map(state.tables.map((t) => [t.url, t.dataset_name]));
  const sources = state.address?.sources ?? [];
  const sourceUrl = state.sourceUrl;
  return (row) => {
    const table = state.sourceKind === "run" ? sources[Number(row._src ?? 0)] : sourceUrl;
    const dataset = table ? datasetOf.get(table) : undefined;
    const sample = row[image.name];
    return dataset && table && typeof sample === "string" ? { dataset, table, sample } : null;
  };
}

function apply(): void {
  const state = useStore.getState();
  if (!cache || cache.url !== state.sourceUrl) return;
  const locate = addressOf();
  if (!locate) return;
  const decisions = cache.byDataset;
  const rows = state.rows.map((row) => {
    const at = locate(row);
    const event = at ? decisions.get(at.dataset)?.[at.sample] : undefined;
    const label = event ? LABELS.get(event.status) ?? NOT_REVIEWED : NOT_REVIEWED;
    return row[REVIEW_COLUMN] === label ? row : { ...row, [REVIEW_COLUMN]: label };
  });

  let columns = state.columns;
  if (!columns.some((c) => c.name === REVIEW_COLUMN)) {
    const at = columns.findIndex((c) => isSessionColumn(c.name));
    columns = [...columns];
    columns.splice(at === -1 ? columns.length : at, 0, reviewColumn);
  }
  const order = state.order.includes(REVIEW_COLUMN)
    ? state.order
    : [...state.order.slice(0, 1), REVIEW_COLUMN, ...state.order.slice(1)];

  const fresh = makeFilter(reviewColumn, rows) as CategoricalFilter;
  const previous = state.filters[REVIEW_COLUMN] as CategoricalFilter | undefined;
  const filter = previous ? { ...previous, values: fresh.values } : fresh;

  useStore.setState({
    rows,
    filterBasis: state.filterBasis.length === state.rows.length ? rows : state.filterBasis,
    columns,
    order,
    filters: { ...state.filters, [REVIEW_COLUMN]: filter },
  });
}

/** Fetch decisions for every dataset behind the open object and show them. */
export async function loadReviews(): Promise<void> {
  const state = useStore.getState();
  const project = state.project;
  const url = state.sourceUrl;
  if (!project || !url || !addressOf()) return;
  const datasetOf = new Map(state.tables.map((t) => [t.url, t.dataset_name]));
  const datasets = new Set<string>();
  for (const table of state.sourceKind === "run" ? state.address?.sources ?? [] : [url]) {
    const name = datasetOf.get(table);
    if (name) datasets.add(name);
  }
  const byDataset = new Map<string, Record<string, ReviewEvent>>();
  await Promise.all(
    [...datasets].map(async (dataset) => {
      try {
        byDataset.set(dataset, (await api.reviews(project, dataset)).statuses);
      } catch {
        byDataset.set(dataset, {});
      }
    }),
  );
  if (useStore.getState().sourceUrl !== url) return;
  cache = { url, byDataset };
  apply();
}

/** Record a decision for rows, then show it. Returns an error message or null. */
export async function markReview(indices: number[], status: ReviewEvent["status"], reason: string): Promise<string | null> {
  const state = useStore.getState();
  const project = state.project;
  const locate = addressOf();
  if (!project || !locate || !cache) return "Review decisions need images and a project";
  const groups = new Map<string, { dataset: string; table: string; samples: Set<string> }>();
  for (const index of indices) {
    const row = state.rows[index];
    const at = row ? locate(row) : null;
    if (!at) continue;
    const key = `${at.dataset}${GROUP_SEPARATOR}${at.table}`;
    const group = groups.get(key) ?? { dataset: at.dataset, table: at.table, samples: new Set<string>() };
    group.samples.add(at.sample);
    groups.set(key, group);
  }
  if (groups.size === 0) return "None of the selected rows can be reviewed";
  try {
    for (const group of groups.values()) {
      await api.recordReview({
        project, dataset: group.dataset, table: group.table, samples: [...group.samples], status, reason,
      });
      const decisions = { ...(cache.byDataset.get(group.dataset) ?? {}) };
      const time = new Date().toISOString();
      for (const sample of group.samples) {
        if (status === "unreviewed") delete decisions[sample];
        else decisions[sample] = { status, reason, time, table: group.table, reviewer: "" };
      }
      cache.byDataset.set(group.dataset, decisions);
    }
  } catch (error) {
    return error instanceof Error ? error.message : String(error);
  }
  apply();
  return null;
}

/** How many distinct images have a decision, out of how many are loaded. */
export function reviewProgress(rows: Row[]): { reviewed: number; total: number } {
  const image = useStore.getState().columns.find((c) => c.kind === "image");
  const seen = new Map<unknown, boolean>();
  for (const row of rows) {
    const key = image ? row[image.name] : row._row;
    const reviewed = row[REVIEW_COLUMN] !== undefined && row[REVIEW_COLUMN] !== NOT_REVIEWED;
    seen.set(key, (seen.get(key) ?? false) || reviewed);
  }
  let reviewed = 0;
  for (const value of seen.values()) if (value) reviewed += 1;
  return { reviewed, total: seen.size };
}

// Reloading the object (after saving changes, say) replaces the rows; show decisions again.
useStore.subscribe((state, previous) => {
  if (state.rows === previous.rows || state.rows.length === 0) return;
  if (!cache || cache.url !== state.sourceUrl) return;
  if (REVIEW_COLUMN in state.rows[0]!) return;
  apply();
});
