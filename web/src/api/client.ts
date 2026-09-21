/** Typed wrapper over the Object Service.
 *
 * Every call goes through `request`, so a service that is down produces one clear
 * message rather than a different unhandled shape at each call site.
 */

import type { AugmentExample, AugmentRecipe, LicenceStatus,
  BrowseResult, ComparisonReport, EmbeddingReport, EmbeddingStatus, ExampleDataset, FindingsReport, Health, QaEvent, QaVersionCounts, QaImageDetail, QaOverview, QaState, QaStatus, Release, TaskId, LibraryClass, LibraryProject, PullResult, ImageBoxes, ImageRounds, ImagesOverview, LearningReport, RemovedImage, VersionRef, ReviewEvent, TrainingResult, TrainingStatus, ImportResult, ImportSource, ImportSummary, Job, LineageGraph,
  ObjectEntry, PreflightReport, ProjectCard, ProjectSummary, CommitResult, RowPage, RunMetadata, TableMetadata,
} from "./types";
import type { CommitPayload } from "../store/editing";

export class ServiceError extends Error {
  constructor(message: string, readonly status: number) {
    super(message);
    this.name = "ServiceError";
  }
}

const BASE = "";

async function request<T>(
  path: string,
  params?: Record<string, string | number>,
  body?: unknown,
): Promise<T> {
  const url = new URL(`${BASE}${path}`, window.location.origin);
  for (const [key, value] of Object.entries(params ?? {})) {
    url.searchParams.set(key, String(value));
  }

  let response: Response;
  try {
    response = await fetch(
      url.toString(),
      body === undefined
        ? undefined
        : { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) },
    );
  } catch {
    throw new ServiceError(
      "Cannot reach the Granum service. Start it with `granum service`.",
      0,
    );
  }

  if (!response.ok) {
    let detail = response.statusText;
    try {
      const body = (await response.json()).detail ?? detail;
      // Some answers carry {message, code}: the message is what people read.
      detail = typeof body === "object" && body !== null && "message" in body ? String(body.message) : body;
    } catch {
      /* keep statusText */
    }
    // Refused by the licence: say so wherever the user is, and show the licence's new state.
    if (response.status === 402) window.dispatchEvent(new CustomEvent("granum:licence", { detail }));
    throw new ServiceError(detail, response.status);
  }
  return (await response.json()) as T;
}

export const api = {
  health: () => request<Health>("/api/health"),

  licence: () => request<LicenceStatus>("/api/licence"),
  installLicence: (key: string) => request<LicenceStatus>("/api/licence/install", undefined, { key }),
  removeLicence: () => request<LicenceStatus>("/api/licence/remove", undefined, {}),
  licenceCode: (email: string) => request<{ sent: boolean; minutes: number; dev_code?: string }>("/api/licence/code", undefined, { email }),
  licenceActivate: (email: string, code: string) => request<LicenceStatus>("/api/licence/activate", undefined, { email, code }),
  licenceRenew: () => request<LicenceStatus>("/api/licence/renew", undefined, {}),
  licenceSignOut: () => request<LicenceStatus>("/api/licence/sign-out", undefined, {}),

  renameProject: (name: string, newName: string) =>
    request<{ name: string; files_updated: number }>(`/api/projects/${encodeURIComponent(name)}/rename`, undefined, { new_name: newName }),

  deleteProject: (name: string, confirm: string) =>
    request<{ deleted: string; tables: number; runs: number }>(`/api/projects/${encodeURIComponent(name)}/delete`, undefined, { confirm }),

  projects: () =>
    request<{ projects: ProjectSummary[] }>("/api/projects").then((r) => r.projects),

  projectCards: () =>
    request<{ projects: ProjectCard[] }>("/api/projects/summary").then((r) => r.projects),

  tables: (project: string) =>
    request<{ tables: ObjectEntry[] }>(`/api/projects/${encodeURIComponent(project)}/tables`)
      .then((r) => r.tables),

  runs: (project: string) =>
    request<{ runs: ObjectEntry[] }>(`/api/projects/${encodeURIComponent(project)}/runs`)
      .then((r) => r.runs),

  lineage: (project: string) =>
    request<LineageGraph>(`/api/projects/${encodeURIComponent(project)}/lineage`),

  table: (url: string) => request<TableMetadata>("/api/table", { url }),

  rows: (url: string, offset: number, limit: number) =>
    request<RowPage>("/api/table/rows", { url, offset, limit }),

  run: (url: string) => request<RunMetadata>("/api/run", { url }),

  runJoined: (url: string, offset: number, limit: number) =>
    request<RowPage>("/api/run/joined", { url, offset, limit }),

  /** Write an editing session to a new revision. Only changed cells are sent. */
  commit: (payload: CommitPayload & { name?: string; description?: string }) =>
    request<CommitResult>("/api/table/commit", undefined, payload),

  reindex: () => request<{ objects: number }>("/api/reindex", undefined, {}),

  imports: (project: string) =>
    request<{ imports: ImportSummary[] }>(`/api/projects/${encodeURIComponent(project)}/imports`)
      .then((r) => r.imports),

  importReport: (project: string, id: string) =>
    request<{ report: PreflightReport; import: ImportResult }>(
      `/api/projects/${encodeURIComponent(project)}/imports/${encodeURIComponent(id)}`,
    ),

  reviews: (project: string, dataset: string) =>
    request<{ statuses: Record<string, ReviewEvent>; counts: Record<string, number> }>("/api/reviews", { project, dataset }),

  recordReview: (payload: { project: string; dataset: string; samples: string[]; status: string; reason: string; table?: string | null }) =>
    request<{ recorded: number; counts: Record<string, number> }>("/api/reviews", undefined, payload),

  qa: (project: string, dataset: string) => request<QaOverview>("/api/qa", { project, dataset }),

  images: (project: string, dataset: string) => request<ImagesOverview>("/api/images", { project, dataset }),

  /** Box geometry for the images on screen, addressed by table and row. */
  imageBoxes: (project: string, dataset: string, items: { table: string; row: number }[]) =>
    request<{ boxes: Record<string, ImageBoxes> }>("/api/images/boxes", undefined, { project, dataset, items })
      .then((r) => r.boxes),

  qaImage: (project: string, dataset: string, table: string, image: string) =>
    request<QaImageDetail>("/api/qa/image", { project, dataset, table, image }),

  setQaStatus: (payload: { project: string; dataset: string; samples: string[]; status: QaStatus; comment?: string; author?: string; table?: string }) =>
    request<{ recorded: number; statuses: Record<string, QaState> }>("/api/qa/status", undefined, payload),

  addQaComment: (payload: { project: string; dataset: string; sample: string; comment: string; author?: string; table?: string }) =>
    request<{ event: QaEvent; thread: QaEvent[] }>("/api/qa/comment", undefined, payload),

  isolate: (payload: { project: string; dataset: string; table: string; samples: string[]; reason?: string; author?: string }) =>
    request<{ count: number; version: VersionRef }>("/api/qa/isolate", undefined, payload),

  deleteImages: (payload: { project: string; dataset: string; table: string; samples: string[]; reason?: string; author?: string }) =>
    request<{ count: number; version: VersionRef }>("/api/qa/delete", undefined, payload),

  returnIsolated: (payload: { project: string; dataset: string; samples: string[]; author?: string }) =>
    request<{ count: number; versions: VersionRef[] }>("/api/qa/return", undefined, payload),

  qaVersion: (project: string, dataset: string, table: string) =>
    request<QaVersionCounts>("/api/qa/version", { project, dataset, table }),

  /** Without augmentation the version is made at once; with it, a job whose result is `{ release }`. */
  createRelease: (payload: {
    project: string; dataset: string; name: string; description: string; mode: "all" | "verified"; author?: string;
    augmentation?: AugmentRecipe | null;
  }) => request<{ release: Release; job?: undefined } | { job: Job<{ release: Release }>; release?: undefined }>("/api/qa/release", undefined, payload),

  releaseUsage: (project: string, dataset: string, releaseId: string) =>
    request<{ files: number; bytes: number; runs: string[] }>("/api/releases/usage", { project, dataset, release_id: releaseId }),

  deleteRelease: (payload: { project: string; dataset: string; release_id: string; author?: string }) =>
    request<{ deleted: string; name: string; files: number; bytes: number; runs: string[] }>("/api/releases/delete", undefined, payload),

  augmentExamples: (payload: {
    project: string; dataset: string; items: Record<string, { recipe: Partial<AugmentRecipe>; at: "min" | "max" }>;
    row?: number | null; size?: number;
  }) => request<{ set: string; row: number; source: string; original: AugmentExample; items: Record<string, AugmentExample>; bytes_per_image: number }>(
    "/api/augment/examples", undefined, payload,
  ),


  runFindings: (url: string) => request<FindingsReport>("/api/run/findings", { url }),

  /** Two runs side by side. Refused reports come back with `interpretation.kind === "blocked"`. */
  compareRuns: (baseline: string, candidate: string, split?: string, limit = 400) =>
    request<ComparisonReport>("/api/runs/compare", { baseline, candidate, limit, ...(split ? { split } : {}) }),

  /** The same report as a file, with every image in it. Followed by the browser, not fetched here. */
  comparisonFileUrl: (baseline: string, candidate: string, split?: string): string => {
    const params = new URLSearchParams({ baseline, candidate, download: "true" });
    if (split) params.set("split", split);
    return `/api/runs/compare?${params.toString()}`;
  },
  exampleDataset: () => request<ExampleDataset>("/api/examples/shapes", undefined, {}),
  library: () => request<{ projects: LibraryProject[]; classes: LibraryClass[] }>("/api/library"),

  pullFromProjects: (payload: { selection: Record<string, string[]>; keep_other_labels: boolean }) =>
    request<PullResult>("/api/library/pull", undefined, payload),

  releases: (project: string) => request<{ releases: Release[] }>("/api/releases", { project }),

  embeddings: (project: string, dataset: string) =>
    request<EmbeddingStatus>("/api/embeddings", { project, dataset }),

  /** Embedding a set is a job: seconds on a small dataset, minutes on a large one. */
  computeEmbeddings: (payload: { project: string; dataset: string; embedder?: string }) =>
    request<Job<{ status: EmbeddingStatus["status"]; unreadable: number }>>("/api/embeddings", undefined, payload),

  /** The neighbour graph: a second or so the first time, then served from the service's cache. */
  embeddingReport: (project: string, dataset: string, limit = 5000) =>
    request<EmbeddingReport>("/api/embeddings/report", { project, dataset, limit }),

  installTraining: () => request<Job<{ installed: string }>>("/api/training/install", undefined, {}),

  trainingStatus: (project: string) =>
    request<TrainingStatus>("/api/training/status", { project }),

  startTraining: (payload: {
    project: string; train_table: string; valid_table: string; test_table?: string | null; rounds: number;
    family: string; version: string; image_size: number; track_learning: boolean;
    compare_with?: string | null;
  }) => request<Job<TrainingResult>>("/api/training", undefined, payload),

  imageRounds: (url: string, table: string, example: number, good?: number) =>
    request<ImageRounds>("/api/run/image-rounds", { url, table, example, ...(good === undefined ? {} : { good }) }),

  removeImages: (payload: { project: string; table: string; samples: string[]; reason: string; reasons?: Record<string, string> }) =>
    request<{ count: number; missing: string[]; version: VersionRef; removed: VersionRef }>("/api/datasets/remove", undefined, payload),

  removedImages: (project: string, dataset: string) =>
    request<{ table: VersionRef | null; images: RemovedImage[] }>("/api/datasets/removed", { project, dataset }),

  restoreImages: (payload: { project: string; dataset: string; samples: string[] }) =>
    request<{ count: number; versions: VersionRef[]; removed: VersionRef }>("/api/datasets/restore", undefined, payload),

  tableSample: (url: string, n = 12) =>
    request<{ images: { row: number; image: string }[] }>("/api/table/sample", { url, n }),

  runLearning: (url: string, good?: number) =>
    request<LearningReport>("/api/run/learning", good === undefined ? { url } : { url, good: String(good) }),

  browse: (path?: string) => request<BrowseResult>("/api/import/browse", path ? { path } : undefined),

  preflight: (sources: ImportSource[], media: string) =>
    request<Job<PreflightReport>>("/api/import/preflight", undefined, { sources, media }),

  commitImport: (payload: {
    preflight_job: string; project_name: string; resolutions: Record<string, string>;
    table_name?: string; description?: string; split_plan?: Record<string, number> | null; tasks?: TaskId[];
  }) => request<Job<ImportResult>>("/api/import/commit", undefined, payload),

  job: <T>(id: string) => request<Job<T>>(`/api/jobs/${encodeURIComponent(id)}`),

  cancelJob: (id: string) => request<Job<unknown>>(`/api/jobs/${encodeURIComponent(id)}/cancel`, undefined, {}),

  /** Media URL for an <img src>. Not fetched here -- the browser does that. */
  mediaUrl: (url: string, size?: number, project?: string, dataset?: string): string => {
    const params = new URLSearchParams({ url });
    if (size) params.set("size", String(size));
    if (project) params.set("project", project);
    if (dataset) params.set("dataset", dataset);
    return `/api/media?${params.toString()}`;
  },
};
