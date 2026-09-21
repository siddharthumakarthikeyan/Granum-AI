/** Shapes returned by the Granum Object Service. */

export type ColumnKind =
  | "bool" | "int32" | "int64" | "float32" | "string" | "url"
  | "image" | "video_url"
  | "categorical_label" | "categorical_label_list"
  | "embedding"
  | "bounding_boxes_2d" | "geometry_2d" | "int32_list"
  | "confidence" | "fraction" | "probability" | "iou"
  | "sample_weight" | "example_id" | "epoch" | "foreign_table_id";

export interface ValueMapEntry {
  internal_name: string;
  display_name: string;
  color: string;
}

/** Class index (as a string key) -> class. */
export type ValueMap = Record<string, ValueMapEntry>;

export interface ColumnInfo {
  name: string;
  kind: ColumnKind;
  writable: boolean;
  default_visible: boolean;
  number_role: string | null;
  /** "table" columns can be edited; "metrics" never; "session" exist only in the browser. */
  source?: "table" | "metrics" | "session";
  /** Run views: this column holds the value of `collected_of` when metrics were collected. */
  collected_of?: string;
  value_map?: ValueMap;
  /** Geometry columns: per-instance property name -> type. */
  instance_properties?: Record<string, string>;
}

export interface ProjectSummary {
  name: string;
  tables: number;
  runs: number;
}

/** One project as the projects page shows it (GET /api/projects/summary). */
export interface ProjectCard {
  name: string;
  tasks: TaskId[];
  datasets: number;
  sets: string[];
  images: number;
  verified: number;
  boxes: number;
  classes: number;
  versions: number;
  runs: number;
  last_run: { name: string; created: string; status?: string } | null;
  updated: string | null;
  covers: { image: string; dataset: string }[];
  /** Imported from the generated example; does not count against the plan. */
  example?: boolean;
}

export interface ExampleDataset {
  sources: ImportSource[];
  images: number;
  description: string;
  project_name: string;
  tasks: TaskId[];
}

export interface ObjectEntry {
  url: string;
  type: "table" | "metrics_table" | "run";
  name: string;
  project_name: string;
  dataset_name: string;
  created: string;
  row_count: number;
  parents: string[];
  description: string;
  /** Runs only. */
  parameters?: Record<string, unknown>;
  last_metrics?: Record<string, unknown>;
  status?: string;
  epochs?: number;
  inputs?: string[];
  history?: Record<string, number>[];
  /** Tables only. */
  op?: string;
  /** Tables only: the tasks chosen when the dataset was imported. */
  tasks?: TaskId[];
  /** Tables only: the set this version belongs to (train, valid, test). */
  split?: string;
  box_column?: string | null;
  box_count?: number;
  class_count?: number;
  preflight?: {
    import_id: string;
    verdict: Verdict;
    created: string;
    warnings: number;
    resolutions: Record<string, string>;
  };
}

export type Severity = "block" | "warn" | "info";
export type Verdict = "block" | "warn" | "pass";

export interface FindingOption {
  id: string;
  label: string;
  effect: string;
}

export interface FindingExample {
  split?: string;
  image?: string;
  file_name?: string;
  width?: number;
  height?: number;
  annotation_id?: number;
  bbox?: number[];
  category?: string | number;
  [key: string]: unknown;
}

export interface Finding {
  code: string;
  severity: Severity;
  title: string;
  detail: string;
  count: number;
  unit: string;
  splits: Record<string, number>;
  examples: FindingExample[];
  options: FindingOption[];
  default: string | null;
}

export interface SplitSummary {
  split: string;
  images: number;
  boxes: number;
  boxes_per_image: { mean: number; median: number; p90: number; max: number };
  box_side_histogram: { from: number; to: number | null; boxes: number }[];
  median_box_side: number;
  image_sizes: { width: number; height: number; images: number }[];
  distinct_image_sizes: number;
  media_checked: number;
  media_bytes: number;
}

export interface PreflightReport {
  version: number;
  format: string;
  created: string;
  verdict: Verdict;
  media_mode: "full" | "sample" | "none";
  sources: { split: string; annotations: string; images: string }[];
  summary: {
    images: number;
    boxes: number;
    splits: SplitSummary[];
    classes: { id: number; name: string; boxes: Record<string, number> }[];
    /** The task the labels look like they are for, and the counts behind the guess. */
    task?: { detected: TaskId; reason: string; counts: Record<string, number> };
  };
  findings: Finding[];
}

export type TaskId =
  | "object_detection" | "instance_segmentation" | "semantic_segmentation"
  | "panoptic_segmentation" | "keypoint_detection" | "classification";

export interface LibraryClass {
  /** Classes match across projects by this key: the name, case and spacing ignored. */
  key: string;
  name: string;
  images: number;
  boxes: number;
  /** Library-wide classes only: the projects that have it. */
  projects?: string[];
}

export interface LibraryProject {
  name: string;
  images: number;
  tasks: TaskId[];
  sets: string[];
  classes: LibraryClass[];
}

export interface PullResult {
  sources: { split: string; annotations: string; images: string; count: number; boxes: number }[];
  images: number;
  boxes: number;
  duplicates: number;
  projects: string[];
}

export interface ImportResult {
  id: string;
  tasks?: TaskId[];
  project_name: string;
  tables: { split: string; url: string; name: string; dataset_name: string; rows: number; boxes: number }[];
  resolutions: Record<string, string>;
  effects: Record<string, number>;
  report_url: string;
  verdict: Verdict;
  warnings_accepted: string[];
}

export interface Job<T> {
  id: string;
  kind: "preflight" | "import" | "training" | "training-install" | "release" | "embeddings";
  status: "running" | "done" | "failed" | "cancelled";
  phase: string;
  done: number;
  total: number;
  elapsed: number;
  error: string | null;
  result: T | null;
  log?: string[];
  /** Training only: progress within the current round, and seconds left in it. */
  step?: number;
  steps?: number;
  round_eta?: number | null;
}

export interface ImportSource {
  split: string;
  annotations: string;
  images?: string | null;
}

export interface BrowseResult {
  path: string | null;
  parent: string | null;
  entries: { name: string; path: string; type: "dir" | "annotations" }[];
  images?: number;
  detected?: ImportSource[];
}

export interface ImportSummary {
  id: string;
  created: string;
  verdict: Verdict;
  sources: { split: string; annotations: string; images: string }[];
  tables: ImportResult["tables"];
  findings: Pick<Finding, "code" | "severity" | "title" | "count" | "unit">[];
  resolutions: Record<string, string>;
  effects: Record<string, number>;
}

export interface TableMetadata {
  url: string;
  name: string;
  project_name: string;
  dataset_name: string;
  description: string;
  created: string;
  row_count: number;
  parents: string[];
  columns: ColumnInfo[];
  latest_revision: string;
}

export interface RunMetricsTable {
  url: string;
  name: string;
  rows: number;
  columns: string[];
  foreign_table_url: string | null;
  constants: Record<string, unknown>;
}

export interface RunMetadata {
  url: string;
  name: string;
  project_name: string;
  description: string;
  created: string;
  status: string;
  parameters: Record<string, unknown>;
  metrics_tables: RunMetricsTable[];
  aggregate_metrics: Record<string, unknown>[];
  /** Joined-view columns with editability, from the service. */
  columns?: ColumnInfo[];
  /** Per metrics table: the Table collected on, and the revision joined now. */
  inputs?: {
    metrics_table: string;
    collected_on: string;
    joined: string;
    changed_columns?: string[];
    newer_revision_skipped?: string | null;
  }[];
  sources?: string[];
}

export type Row = Record<string, unknown> & { _row: number };

export interface RowPage {
  url: string;
  offset: number;
  limit: number;
  total: number;
  rows: Row[];
  /** Run views: input Table urls, indexed by each row's `_src`. */
  sources?: string[];
}

export interface LineageGraph {
  nodes: ObjectEntry[];
  edges: { from: string; to: string }[];
}

export interface CommitResult {
  url: string;
  name: string;
  parents: string[];
  row_count: number;
  summary: { cells?: Record<string, number>; columns_added?: string[]; value_maps?: string[] };
}

/** What this computer's licence allows (GET /api/licence). */
export interface LicenceStatus {
  mode: "full" | "read_only";
  state: "active" | "unrestricted" | "missing" | "invalid" | "wrong_machine" | "clock" | "expired" | "lease_expired";
  reason: string | null;
  machine: string;
  lid?: string;
  email?: string;
  customer?: string | null;
  plan?: string | null;
  kind?: "online" | "offline";
  machines?: number;
  issued?: string;
  expires?: string | null;
  lease_until?: string | null;
  max_projects?: number | null;
  days_left?: number | null;
  offline_days_left?: number;
  projects_used: number;
  lease_days: number;
  /** A licence server is set up: sign-in and renewal are available. */
  server: boolean;
  /** The server's last word when it refused a renewal. */
  server_message: string | null;
}

export interface Health {
  status: string;
  version: string;
  roots: string[];
  data_roots: string[];
  objects: number;
  scans: number;
  dashboard_bundled: boolean;
}

export interface ReviewEvent {
  status: "correct" | "corrected" | "ambiguous" | "deferred" | "excluded" | "unreviewed";
  reason: string;
  time: string;
  table: string | null;
  reviewer: string;
}

export type LearningCategory = "early" | "steady" | "late" | "forgotten" | "never" | "insufficient" | "empty";

export interface LearnedImage {
  example_id: number;
  image: string | null;
  objects: number;
  width: number | null;
  height: number | null;
  category: LearningCategory;
  first_good_epoch: number | null;
  learned_epoch: number | null;
  forgetting_events: number;
  observations: number;
  final_score: number;
  mean_score: number;
  best_score: number;
  /** One score per entry of the split's epochs; null where that round was not recorded. */
  scores: (number | null)[];
}

export interface LearningSplit {
  split: string;
  table: string;
  table_name: string | null;
  dataset: string | null;
  epochs: number[];
  counts: Partial<Record<LearningCategory, number>>;
  early_before: number | null;
  late_after: number | null;
  images: LearnedImage[];
}

export interface LearningReport {
  url: string;
  name: string;
  good: number;
  tracks_learning: boolean;
  splits: LearningSplit[];
}

export interface RoundBox {
  vertices: number[];
  label: number | null;
  confidence?: number;
  iou?: number;
  matched?: boolean;
  ignored?: boolean;
}

export interface ImageRound {
  epoch: number;
  tp: number;
  fp: number;
  fn: number;
  precision: number;
  recall: number;
  f1: number;
  /** Null when this round's boxes were not saved (only scores). */
  boxes: RoundBox[] | null;
  gt_match: number[] | null;
}

export interface ImageRounds {
  image: string;
  table: string;
  table_name: string;
  set: string;
  dataset: string;
  example: number;
  width: number;
  height: number;
  labels: Record<string, string>;
  truth: (RoundBox & { iscrowd?: boolean })[];
  rounds: ImageRound[];
  good: number;
  learned_from: number | null;
  perfect_from: number | null;
}

export type QaStatus = "unreviewed" | "reviewed" | "rework";

export interface QaImage {
  row: number;
  image: string;
  objects: number;
  /** Isolated images: the set each came from, and why it was set aside. */
  from?: string | null;
  reason?: string;
}

export interface QaVersion {
  url: string;
  name: string;
  row_count: number;
  created: string;
  change: string | null;
  description: string;
  shipped: boolean;
  images: number;
  reviewed: number;
  ready: boolean;
}

export interface QaSet extends VersionRef {
  images: QaImage[];
  counts: Record<QaStatus, number>;
  /** Present for train/valid/test sets, not for the isolated set. */
  ready?: boolean;
  shipped?: boolean;
  versions?: QaVersion[];
}

export interface QaVersionCounts extends VersionRef {
  images: number;
  counts: Record<QaStatus, number>;
  ready: boolean;
  shipped: boolean;
}

export interface QaState {
  status: QaStatus;
  comments: number;
  author?: string;
  time?: string;
  note?: string;
}

export interface QaEvent {
  sample: string;
  status: QaStatus | null;
  comment: string;
  author: string;
  time: string;
  table: string | null;
}

export interface Shipment {
  id: string;
  time: string;
  author: string;
  note: string;
  sets: Record<string, {
    url: string; name: string; images: number; verified?: number;
    /** On an augmented set: the images it was made from, and the copies added. */
    originals?: number; augmented?: number; dropped_boxes?: number; dropped_masks?: number;
  }>;
}

/** Augmented copies of the train set (granum.core.augment); each key present is one augmentation. */
export interface AugmentRecipe {
  copies: number;
  flip?: { horizontal?: boolean; vertical?: boolean };
  rotate90?: { clockwise?: boolean; counterclockwise?: boolean; upside_down?: boolean };
  crop?: { min: number; max: number };
  rotation?: { min: number; max: number };
  shear?: { horizontal: number; vertical: number };
  grayscale?: { percent: number };
  hue?: { min: number; max: number };
  saturation?: { min: number; max: number };
  brightness?: { min: number; max: number };
  exposure?: { min: number; max: number };
  blur?: { max: number };
  noise?: { max: number };
  cutout?: { count: number; size: number };
}

/** One image rendered small (a data URL) with its boxes, in its own pixel coordinates. */
export interface AugmentExample {
  image: string;
  width: number;
  height: number;
  boxes: { box: number[]; label: number | null; crowd: boolean }[];
}

/** A dataset version: one frozen version of each set, the only data training accepts. */
export interface Release extends Shipment {
  dataset: string;
  name: string;
  version: number;
  /** "verified": unverified images were left out; "all": every image, verified or not. */
  mode: "all" | "verified";
  tasks?: TaskId[];
  augmentation?: AugmentRecipe;
}

export interface QaBox {
  vertices: number[];
  label: number | null;
  iscrowd?: number | boolean | null;
  [property: string]: unknown;
}

export interface QaOverview {
  sets: QaSet[];
  isolated: QaSet | null;
  statuses: Record<string, QaState>;
  shipments: Shipment[];
  ready: boolean;
  up_to_date: boolean;
}

export interface QaImageDetail {
  image: string;
  row: number;
  table: string;
  box_column: string | null;
  editable: boolean;
  /** Properties the dataset's instances carry, name -> kind (segmentation, coco_extra, ...). */
  instance_properties?: Record<string, string>;
  width: number | null;
  height: number | null;
  labels: Record<string, string>;
  boxes: QaBox[];
  thread: QaEvent[];
}

export interface VersionRef {
  url: string;
  name: string;
  set: string;
  row_count: number;
}

export interface RemovedImage {
  row: number;
  image: string;
  objects: number;
  removed_from: string;
  removed_from_version: string;
  removed_reason: string;
  removed_at: string;
}

export interface TrainingResult {
  run_name: string;
  exit_code?: number;
  cancelled?: boolean;
}

export interface ModelVersion {
  id: string;
  name: string;
  size: string;
  note: string;
}

export interface ModelFamily {
  id: "yolo" | "rtdetr" | "rfdetr" | string;
  name: string;
  maker: string;
  package: string;
  summary: string;
  detail: string;
  supports_closer: boolean;
  versions: ModelVersion[];
  installed: boolean;
  install_hint: string | null;
}

export interface TrainingStatus {
  available: boolean;
  gpu: string | null;
  reason: string | null;
  families?: ModelFamily[];
  running_job: Job<TrainingResult> | null;
  busy_elsewhere: boolean;
  /** Set versions that are part of a dataset version: the only ones training accepts. */
  shipped?: string[];
  /** Training packages are missing and Granum can install them into its own folder. */
  installable?: boolean;
  install_size?: string;
  install_job?: Job<{ installed: string }> | null;
}

/** One image of a set, as the Images tab lists it. */
export interface ImageRow {
  row: number;
  image: string;
  objects: number;
  /** Class indices used by this image's boxes, ignoring crowd/ignore regions. */
  classes: number[];
  set: string;
  table: string;
  added: string;
  /** Isolated images: the set each came from, and why it was set aside. */
  from?: string | null;
  reason?: string;
}

export interface ImageSet extends VersionRef {
  created: string;
  images: number;
}

export interface ImagesOverview {
  sets: ImageSet[];
  /** Class index (as a string key) -> display name, merged across the dataset's sets. */
  labels: Record<string, string>;
  images: ImageRow[];
  statuses: Record<string, QaState>;
}

/** Box geometry for drawing: coordinates are fractions of the image. */
export interface ImageBoxes {
  w: number;
  h: number;
  /** [label, x0, y0, x1, y1] per box. */
  b: [number | null, number, number, number, number][];
}

// -- embeddings: copies, leaks and what is unlike the rest ----------------------

/** What made a dataset's vectors, and what that lets them see. */
export interface Embedder {
  id: string;
  name: string;
  dimensions: number;
  /** What it needs installed, or null when it needs nothing. */
  needs: string | null;
  detail: string;
  /** False for the plain descriptor: it finds copies, it does not read content. */
  semantic: boolean;
}

export interface EmbeddingStatus {
  project: string;
  dataset: string;
  status: {
    version: string;
    embedder: Embedder;
    images: number;
    unreadable: number;
    created: string;
    sets: string[];
    /** Made by an older rule set: the numbers would not compare. */
    stale: boolean;
  } | null;
  /** Images in the dataset now, and how many of them have no vector yet. */
  images: number;
  missing: number;
  /** The best embedder installed on this machine, which a new run would use. */
  available: Embedder;
}

/** A pair of near-identical images sitting in different sets. */
export interface LeakPair {
  a: string;
  b: string;
  sets: [string, string];
  distance: number;
  /** Under the duplicate threshold: the same photograph, not merely a close frame. */
  same_image: boolean;
  /** Both sides are the exporter's copies of one picture: the split was cut through it. */
  same_source: boolean;
}

/** One source picture the exporter wrote out more than once, usually augmented. */
export interface ExportGroup {
  /** What the copies have in common: the source name, or the image they were made from. */
  source: string;
  images: string[];
  sets: string[];
}

/** The thresholds every distance in a report is measured against. */
export interface NeighbourPolicy {
  k: number;
  duplicate: number;
  leak: number;
  outlier: number;
  max_group: number;
  batch: number;
}

export interface EmbeddingReport {
  version: string;
  /** Images with a vector that the dataset still holds: what the graph was built over. */
  images: number;
  /** The median distance between two random images: the unit every threshold is a share of. */
  scale: number;
  policy: NeighbourPolicy;
  embedder: Embedder | null;
  duplicates: {
    /** Image keys, one list per group of copies. Capped by the request's limit. */
    groups: string[][];
    /** Per group, in the same order: how far apart its least alike pair is, as a share
     *  of the typical distance. Near zero is one photograph re-exported. */
    spreads: number[];
    /** Per group, one number per image: which of the group's source pictures it came from.
     *  Two images sharing a number are one picture, not a repetition of it. */
    families: number[][];
    images: number;
    /** Source pictures that repeat another source picture: what there is to remove. */
    redundant: number;
    shown: number;
    total: number;
  };
  /** The exporter's own copies: one picture written out more than once, augmented or not.
   *  Never counted as duplicates — deleting them undoes an augmentation somebody asked for. */
  exports: {
    sources: number;
    repeated: number;
    images: number;
    groups: ExportGroup[];
    shown: number;
  };
  /** Runs of images each close to the next -- a burst, a pan, a video. Not copies. */
  chains: { images: number; example: string; sets: string[] }[];
  leaks: LeakPair[];
  leaks_total: number;
  outliers: { image: string; score: number; set: string }[];
  /** Images added since the vectors were made, and vectors for images since deleted. */
  missing: number;
  dropped: number;
}

// -- findings: labels worth a reviewer's time -----------------------------------

export type FindingRule = "missing_label" | "wrong_class" | "loose_box" | "missed";

export interface Finding {
  rule: FindingRule;
  rounds: number;
  window: number;
  share: number;
  first_epoch: number;
  last_epoch: number;
  in_last_round: boolean;
  /** [min, max] confidence of the model's predictions behind it; null for a missed label. */
  confidence: [number, number] | null;
  truth_index: number | null;
  annotation_id?: number | null;
  /** The label's box, or for a missing label the place the model keeps predicting. */
  box: [number, number, number, number];
  label: number | null;
  predicted_label?: number;
  predicted_box?: [number, number, number, number];
  iou?: number;
  score: number;
}

export interface FlaggedImage {
  example_id: number;
  image: string | null;
  width: number | null;
  height: number | null;
  labels: number;
  score: number;
  findings: Finding[];
  review: { status: string; reason: string; time: string; reviewer: string } | null;
}

export interface FindingsSplit {
  split: string;
  table: string;
  table_name: string;
  dataset: string | null;
  project: string;
  held_out: boolean;
  images_total: number;
  competent_from: number | null;
  observed: number;
  window: number;
  classes: Record<string, string>;
  counts: Record<FindingRule, number>;
  images: FlaggedImage[];
}

export interface FindingsReport {
  url: string;
  name: string;
  rules_version: string;
  policy: Record<string, number>;
  stores_boxes: boolean;
  splits: FindingsSplit[];
}

// -- comparing two runs (EV06/EV11) ------------------------------------------

export type CheckStatus = "ok" | "warn" | "blocked";

export interface CompatibilityCheck {
  check: string;
  status: CheckStatus;
  detail: string;
  fields?: string[];
  baseline?: unknown;
  candidate?: unknown;
}

export interface Counted {
  tp: number;
  fp: number;
  fn: number;
  images: number;
  labels: number;
  precision: number;
  recall: number;
  f1: number;
}

export type SampleOutcome = "improved" | "regressed" | "unchanged";

export interface SampleChange {
  image: string;
  outcome: SampleOutcome;
  baseline: { tp: number; fp: number; fn: number; example_id: number | null; precision: number; recall: number; f1: number };
  candidate: { tp: number; fp: number; fn: number; example_id: number | null; precision: number; recall: number; f1: number };
  delta_f1: number;
}

export interface SliceRow {
  key: string | number;
  name: string;
  metric: "f1" | "recall";
  support: number;
  /** False when the slice holds too few labels to read anything into its change. */
  conclusive: boolean;
  baseline: Counted & { labels: number };
  candidate: Counted & { labels: number };
  delta: number;
}

/** How one set's labels differ between the versions two runs used. */
export interface DataChange {
  known: boolean;
  reason?: string;
  identical?: boolean;
  baseline?: string;
  candidate?: string;
  images_baseline?: number;
  images_candidate?: number;
  images_added?: number;
  images_removed?: number;
  images_edited?: number;
  added?: string[];
  removed?: string[];
  boxes_baseline?: number;
  boxes_candidate?: number;
  boxes_added?: number;
  boxes_removed?: number;
  boxes_relabelled?: number;
  boxes_moved?: number;
  boxes_with_added_images?: number;
  boxes_with_removed_images?: number;
  edited?: { image: string; added: number; removed: number; relabelled: number; moved: number; before: number; after: number }[];
  truncated?: boolean;
}

export interface ComparedRun {
  url: string;
  name: string;
  created: string;
  status: string;
  set: string | null;
  table: string | null;
  table_name: string | null;
  dataset: string | null;
  epoch: number | null;
  stores_boxes: boolean;
  classes: Record<string, string>;
  evaluator: Record<string, unknown>;
  seed: number | null;
  recipe: Record<string, unknown>;
  train_table: string | null;
  train_version: string | null;
  score_labels: string | null;
  map50: number | null;
  splits: string[];
}

export interface ComparisonReport {
  report_version: string;
  generated: string;
  project: string;
  policy: Record<string, number>;
  split: string | null;
  shared_splits: string[];
  runs: { baseline: ComparedRun; candidate: ComparedRun };
  checks: CompatibilityCheck[];
  interpretation: { kind: "controlled" | "observational" | "blocked"; blocked: string[]; warnings: string[]; summary: string };
  training_data: DataChange;
  /** Everything below is absent when the comparison was refused. */
  headline?: {
    metric: string;
    baseline: number | null;
    candidate: number | null;
    delta: number | null;
    tolerance?: number;
    verdict: string;
    scored_on: { baseline: string | null; candidate: string | null };
    same_labels: boolean;
    source: string;
  };
  samples?: {
    counts: Record<"improved" | "regressed" | "unchanged" | "only_baseline" | "only_candidate", number>;
    baseline: Counted;
    candidate: Counted;
    shared: { baseline: Counted; candidate: Counted };
    images: SampleChange[];
    shown: number;
    only_baseline: string[];
    only_candidate: string[];
  };
  slices?: { known: boolean; images: number; reason: string | null; classes: SliceRow[]; sizes: SliceRow[] };
  evaluation_data?: DataChange;
  cost?: {
    baseline: RunCost;
    candidate: RunCost;
    review: {
      known: boolean;
      reason?: string;
      dataset?: string;
      observed?: { decisions: number; images: number; reviewers: string[]; by_status: Record<string, number>; from: string | null; to: string | null };
      estimated?: { minutes: number; basis: string };
    };
  };
}

export interface RunCost {
  created: string;
  rounds_logged: number;
  wall_clock_seconds: number | null;
  wall_clock_covers: string | null;
  recipe: Record<string, unknown>;
}
