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
  };
  findings: Finding[];
}

export interface ImportResult {
  id: string;
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
  kind: "preflight" | "import" | "training" | "training-install";
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

export type LearningCategory = "early" | "steady" | "late" | "forgotten" | "never" | "empty";

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
  sets: Record<string, { url: string; name: string; images: number }>;
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
  /** Dataset versions that have been shipped: the only ones training accepts. */
  shipped?: string[];
  /** Training packages are missing and Granum can install them into its own folder. */
  installable?: boolean;
  install_size?: string;
  install_job?: Job<{ installed: string }> | null;
}
