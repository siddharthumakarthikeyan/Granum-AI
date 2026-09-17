/** Typed wrapper over the Object Service.
 *
 * Every call goes through `request`, so a service that is down produces one clear
 * message rather than a different unhandled shape at each call site.
 */

import type {
  BrowseResult, Health, QaEvent, QaImageDetail, QaOverview, QaState, QaStatus, Shipment, ImageRounds, LearningReport, RemovedImage, VersionRef, ReviewEvent, TrainingResult, TrainingStatus, ImportResult, ImportSource, ImportSummary, Job, LineageGraph,
  ObjectEntry, PreflightReport, ProjectSummary, CommitResult, RowPage, RunMetadata, TableMetadata,
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
      detail = (await response.json()).detail ?? detail;
    } catch {
      /* keep statusText */
    }
    throw new ServiceError(detail, response.status);
  }
  return (await response.json()) as T;
}

export const api = {
  health: () => request<Health>("/api/health"),

  projects: () =>
    request<{ projects: ProjectSummary[] }>("/api/projects").then((r) => r.projects),

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

  ship: (payload: { project: string; dataset: string; author?: string; note?: string }) =>
    request<{ shipment: Shipment }>("/api/qa/ship", undefined, payload),

  trainingStatus: (project: string) =>
    request<TrainingStatus>("/api/training/status", { project }),

  startTraining: (payload: {
    project: string; train_table: string; valid_table: string; rounds: number;
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
    table_name?: string; description?: string;
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
