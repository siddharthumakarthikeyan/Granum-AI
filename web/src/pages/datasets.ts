/** Tables grouped into datasets, each with its revision history in order. */

import type { ObjectEntry } from "../api/types";

export interface Revision {
  entry: ObjectEntry;
  depth: number;
  parent: ObjectEntry | null;
}

export interface Dataset {
  name: string;
  splits: Split[];
  /** Every version of every set. */
  revisions: Revision[];
  /** The newest version of the first set, for places that show one. */
  latest: ObjectEntry;
  root: ObjectEntry;
}

const OP_LABELS: Record<string, string> = {
  from_coco: "Imported",
  from_yolo: "Imported",
  from_image_folder: "Imported from a folder of images",
  create: "Created",
  edit: "Changes saved",
  set_values: "Values changed",
  add_column: "Column added",
  delete_columns: "Columns removed",
  delete_rows: "Images removed",
  remove_images: "Images taken out",
  restore_images: "Images put back",
  filter: "Filtered",
  subset: "Part of the data taken",
  join_tables: "Combined with other data",
  squash: "History flattened",
  release: "Frozen for a dataset version",
  set_value_map: "Labels changed",
  add_value_map_item: "Label added",
  set_value_map_item: "Label renamed",
  delete_value_map_item: "Label removed",
};

export function describeOp(op: string | undefined): string {
  if (!op) return "Version";
  return OP_LABELS[op] ?? op.replace(/_/g, " ");
}

const SPLIT_ORDER = ["train", "valid", "val", "validation", "test", "isolated", "removed"];

/** The set holding images taken out of the others: never trained or checked on. */
export const REMOVED_SET = "removed";
/** Images set aside during review, left out of new dataset versions until returned. */
export const ISOLATED_SET = "isolated";
/** Producer op of a set copy frozen for a dataset version (granum.core.curation.RELEASE_OP). */
export const RELEASE_OP = "release";
/** Sets holding images taken out of the others. */
export const HOLDING_SETS: readonly string[] = [REMOVED_SET, ISOLATED_SET];

/** Sets in the usual order: train, then validation, then test, then anything else. */
function splitRank(name: string): number {
  const at = SPLIT_ORDER.indexOf(name.toLowerCase());
  return at === -1 ? SPLIT_ORDER.length : at;
}

export interface Split {
  name: string;
  revisions: Revision[];
  latest: ObjectEntry;
  root: ObjectEntry;
}

/** One dataset: its sets (train, valid, test), each a chain of versions. */
export function groupDatasets(all: ObjectEntry[]): Dataset[] {
  // Frozen copies made for a dataset version are not versions of their set.
  const tables = all.filter((t) => t.op !== RELEASE_OP);
  const byUrl = new Map(tables.map((t) => [t.url, t]));
  const depth = new Map<string, number>();
  const depthOf = (entry: ObjectEntry, guard = 0): number => {
    const known = depth.get(entry.url);
    if (known !== undefined) return known;
    const parent = entry.parents[0] ? byUrl.get(entry.parents[0]) : undefined;
    const value = parent && guard < 64 ? depthOf(parent, guard + 1) + 1 : 0;
    depth.set(entry.url, value);
    return value;
  };
  /** The set a version belongs to: its recorded split, else its root's name. */
  const splitOf = (entry: ObjectEntry, guard = 0): string => {
    if (entry.split) return entry.split;
    const parent = entry.parents[0] ? byUrl.get(entry.parents[0]) : undefined;
    return parent && guard < 64 ? splitOf(parent, guard + 1) : entry.name;
  };

  const groups = new Map<string, ObjectEntry[]>();
  for (const table of tables) {
    if (table.type !== "table") continue;
    const list = groups.get(table.dataset_name) ?? [];
    list.push(table);
    groups.set(table.dataset_name, list);
  }

  const datasets: Dataset[] = [];
  for (const [name, entries] of groups) {
    const bySplit = new Map<string, Revision[]>();
    for (const entry of entries) {
      const revision = { entry, depth: depthOf(entry), parent: entry.parents[0] ? byUrl.get(entry.parents[0]) ?? null : null };
      const key = splitOf(entry);
      bySplit.set(key, [...(bySplit.get(key) ?? []), revision]);
    }
    const splits: Split[] = [...bySplit.entries()]
      .map(([split, revisions]) => {
        revisions.sort((a, b) => a.depth - b.depth || a.entry.created.localeCompare(b.entry.created));
        const latest = [...revisions].sort(
          (a, b) => b.depth - a.depth || b.entry.created.localeCompare(a.entry.created),
        )[0]!.entry;
        return { name: split, revisions, latest, root: revisions[0]!.entry };
      })
      .sort((a, b) => splitRank(a.name) - splitRank(b.name) || a.name.localeCompare(b.name));
    const revisions = splits.flatMap((s) => s.revisions);
    datasets.push({ name, splits, revisions, latest: splits[0]!.latest, root: splits[0]!.root });
  }
  return datasets.sort((a, b) => a.name.localeCompare(b.name));
}

/** The newest version of the set a table belongs to, and that set. */
export function splitOfTable(datasets: Dataset[], url: string): { dataset: Dataset; split: Split } | null {
  for (const dataset of datasets) {
    for (const split of dataset.splits) {
      if (split.revisions.some((r) => r.entry.url === url)) return { dataset, split };
    }
  }
  return null;
}

export function pickSplit(dataset: Dataset | undefined, pattern: RegExp): Split | undefined {
  return dataset?.splits.find((s) => pattern.test(s.name));
}
