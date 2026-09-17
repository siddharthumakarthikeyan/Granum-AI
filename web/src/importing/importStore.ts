/** State of the import flow, kept outside the page so leaving and coming back resumes it. */

import { create } from "zustand";
import { api, ServiceError } from "../api/client";
import type { ImportResult, ImportSource, Job, PreflightReport } from "../api/types";

export type Step = "choose" | "checking" | "review" | "importing" | "done";
export type MediaMode = "full" | "sample" | "none";

const POLL_MS = 400;

interface ImportState {
  step: Step;
  sources: ImportSource[];
  media: MediaMode;
  job: Job<PreflightReport> | null;
  report: PreflightReport | null;
  choices: Record<string, string>;
  projectName: string;
  tableName: string;
  importJob: Job<ImportResult> | null;
  result: ImportResult | null;
  error: string | null;

  setSources: (sources: ImportSource[]) => void;
  setMedia: (media: MediaMode) => void;
  choose: (code: string, option: string) => void;
  setProjectName: (name: string) => void;
  setTableName: (name: string) => void;
  runPreflight: () => Promise<void>;
  cancel: () => Promise<void>;
  backToChoose: () => void;
  runImport: () => Promise<void>;
  reset: (projectName?: string) => void;
}

const sleep = (ms: number) => new Promise((resolve) => window.setTimeout(resolve, ms));
const message = (error: unknown) => (error instanceof ServiceError || error instanceof Error ? error.message : String(error));

/** A project name from the dataset's folder: /data/human_aerial/train/x.json -> human_aerial. */
export function suggestProjectName(sources: ImportSource[]): string {
  const first = sources[0];
  if (!first) return "";
  const parts = first.annotations.split("/").filter(Boolean);
  const folder = parts.length >= 3 && sources.some((s) => parts.at(-2) === s.split) ? parts.at(-3) : parts.at(-2);
  return (folder ?? "").replace(/[^A-Za-z0-9._ -]+/g, "-");
}

export const useImport = create<ImportState>((set, get) => ({
  step: "choose",
  sources: [],
  media: "full",
  job: null,
  report: null,
  choices: {},
  projectName: "",
  tableName: "initial",
  importJob: null,
  result: null,
  error: null,

  setSources: (sources) => set({ sources, error: null }),
  setMedia: (media) => set({ media }),
  choose: (code, option) => set((state) => ({ choices: { ...state.choices, [code]: option } })),
  setProjectName: (projectName) => set({ projectName }),
  setTableName: (tableName) => set({ tableName }),

  runPreflight: async () => {
    const { sources, media } = get();
    set({ step: "checking", error: null, report: null, job: null, choices: {} });
    try {
      let job = await api.preflight(sources, media);
      set({ job });
      while (job.status === "running") {
        await sleep(POLL_MS);
        if (get().job?.id !== job.id) return;
        job = await api.job<PreflightReport>(job.id);
        set({ job });
      }
      if (job.status !== "done" || !job.result) {
        set({ step: "choose", error: job.status === "cancelled" ? null : job.error ?? `Preflight ${job.status}` });
        return;
      }
      const report = job.result;
      const choices: Record<string, string> = {};
      for (const finding of report.findings) if (finding.default) choices[finding.code] = finding.default;
      set({
        step: "review",
        report,
        choices,
        projectName: get().projectName || suggestProjectName(sources),
      });
    } catch (error) {
      set({ step: "choose", error: message(error) });
    }
  },

  cancel: async () => {
    const job = get().job;
    if (job) await api.cancelJob(job.id).catch(() => undefined);
    set({ step: "choose", job: null });
  },

  backToChoose: () => set({ step: "choose", report: null, job: null, error: null }),

  runImport: async () => {
    const { job, choices, projectName, tableName } = get();
    if (!job) return;
    set({ step: "importing", error: null, importJob: null });
    try {
      let importJob = await api.commitImport({
        preflight_job: job.id,
        project_name: projectName.trim(),
        table_name: tableName.trim() || "initial",
        resolutions: choices,
      });
      set({ importJob });
      while (importJob.status === "running") {
        await sleep(POLL_MS);
        importJob = await api.job<ImportResult>(importJob.id);
        set({ importJob });
      }
      if (importJob.status !== "done" || !importJob.result) {
        set({ step: "review", error: importJob.error ?? `Import ${importJob.status}` });
        return;
      }
      set({ step: "done", result: importJob.result });
    } catch (error) {
      set({ step: "review", error: message(error) });
    }
  },

  reset: (projectName = "") =>
    set({
      step: "choose", sources: [], job: null, report: null, choices: {}, projectName,
      tableName: "initial", importJob: null, result: null, error: null,
    }),
}));
