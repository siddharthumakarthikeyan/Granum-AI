/** Training runs side by side: model, data, scores, status. */

import { useEffect, useState } from "react";
import type { ObjectEntry } from "../api/types";
import { EmptyState, Icon, PageHeader, RunStatus, formatWhen, plural } from "../components/ui";
import { navigate, routeHref } from "../router";
import { useStore } from "../store/store";
import { Comparison, TrainDialog, TrainingProgressCard, useTrainingJob } from "../training/Training";
import { TrainingChart } from "./TrainingChart";

const SCORES = [
  { key: "map50", label: "mAP50" },
  { key: "map50_95", label: "mAP50-95" },
  { key: "precision", label: "Precision" },
  { key: "recall", label: "Recall" },
];

const score = (run: ObjectEntry, key: string): number | null => {
  const value = run.last_metrics?.[key];
  return typeof value === "number" && Number.isFinite(value) ? value : null;
};

const FAMILY: Record<string, string> = { yolo: "YOLO", rtdetr: "RT-DETR", rfdetr: "RF-DETR" };

export function RunsPage({ project }: { project: string }) {
  const runs = useStore((s) => s.runs);
  const loading = useStore((s) => s.loading);
  const refreshProject = useStore((s) => s.refreshProject);
  const { job, setJob, dismiss, cancel } = useTrainingJob(project);
  const [dialogOpen, setDialogOpen] = useState(false);
  const training = runs.some((r) => r.status === "running") || job?.status === "running";
  const ordered = [...runs].sort((a, b) => b.created.localeCompare(a.created));
  const latestCompared = ordered.find((r) => r.parameters?.compare_map50_this !== undefined);
  const testScore = (run: ObjectEntry): number | null => {
    const value = run.parameters?.test_map50;
    return typeof value === "number" && Number.isFinite(value) ? value : null;
  };
  const tested = runs.some((r) => testScore(r) !== null);
  const bestTest = Math.max(...runs.map((r) => testScore(r) ?? -Infinity));

  useEffect(() => {
    if (!training) return;
    const timer = window.setInterval(() => void refreshProject(), 4000);
    return () => window.clearInterval(timer);
  }, [training, refreshProject]);

  // The best value of each score is marked, so the leading run reads at a glance.
  const best = Object.fromEntries(SCORES.map(({ key }) => [key, Math.max(...runs.map((r) => score(r, key) ?? -Infinity))]));

  return (
    <div className="page">
      <PageHeader
        title="Runs"
        context={project}
        subtitle={plural(runs.length, "run")}
        actions={
          <>
            {runs.length > 1 && (
              <a className="button" href={routeHref({ name: "compare", project })}>
                <Icon name="swap" />Compare runs
              </a>
            )}
            <button className="button primary" onClick={() => setDialogOpen(true)} disabled={job?.status === "running"}>
              <Icon name="runs" />Train model
            </button>
          </>
        }
      />
      {job && <TrainingProgressCard project={project} job={job} onCancel={() => void cancel()} onDismiss={dismiss} />}
      {dialogOpen && <TrainDialog project={project} onClose={() => setDialogOpen(false)} onStarted={setJob} />}

      {runs.length === 0 && !loading ? (
        <EmptyState
          title="No runs"
          action={<button className="button primary" onClick={() => setDialogOpen(true)}><Icon name="runs" />Train model</button>}
        >
          <p>Train YOLO, RT-DETR or RF-DETR here, or log runs from your own training script:</p>
          <pre className="code-block">{`run = granum.init("${project}", "baseline")
granum.collect_metrics(table, collectors, predictor=predictor,
                       constants={"epoch": epoch})`}</pre>
        </EmptyState>
      ) : (
        <>
          {latestCompared && <Comparison run={latestCompared} project={project} />}
          <TrainingChart runs={runs} />
          <div className="data-table-wrap">
            <table className="data-table">
              <thead>
                <tr>
                  <th>Run</th>
                  <th>Status</th>
                  <th>Model</th>
                  <th>Train / validation{tested ? " / test" : ""} data</th>
                  <th className="num">Epochs</th>
                  {SCORES.map((s) => <th key={s.key} className="num">{s.label}</th>)}
                  {tested && <th className="num" title="mAP50 of the finished model on the held-out test set">Test mAP50</th>}
                  <th>Created</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                {ordered.map((run) => {
                  const p = run.parameters ?? {};
                  return (
                    <tr key={run.url} className="clickable" onClick={() => navigate({ name: "run", project, url: run.url })}>
                      <td><span className="cell-title">{run.name}</span></td>
                      <td><RunStatus status={run.status} epochs={run.epochs} total={p.epochs} /></td>
                      <td>
                        <span>{FAMILY[String(p.framework)] ?? String(p.framework ?? "—")}</span>
                        <span className="cell-sub">{String(p.version ?? p.model ?? "")}{p.imgsz ? `, ${String(p.imgsz)} px` : ""}</span>
                      </td>
                      <td className="cell-mono data-versions">
                        {p.train_version ? String(p.train_version) : "—"}
                        {p.valid_version ? <span className="cell-sub">{String(p.valid_version)}</span> : null}
                        {p.test_version ? <span className="cell-sub">{String(p.test_version)}</span> : null}
                      </td>
                      <td className="num">{run.epochs ?? "—"}</td>
                      {SCORES.map(({ key }) => {
                        const value = score(run, key);
                        return (
                          <td key={key} className={`num${value !== null && value === best[key] && runs.length > 1 ? " value-best" : ""}`}>
                            {value !== null ? value.toFixed(3) : "—"}
                          </td>
                        );
                      })}
                      {tested && (() => {
                        const value = testScore(run);
                        return (
                          <td className={`num${value !== null && value === bestTest && runs.length > 1 ? " value-best" : ""}`}>
                            {value !== null ? value.toFixed(3) : "—"}
                          </td>
                        );
                      })()}
                      <td className="muted">{formatWhen(run.created)}</td>
                      <td className="actions" onClick={(event) => event.stopPropagation()}>
                        {(() => {
                          // Against the run before it: the question a new run raises.
                          const earlier = ordered[ordered.indexOf(run) + 1];
                          return earlier ? (
                            <a className="button" href={routeHref({ name: "compare", project, baseline: earlier.url, candidate: run.url })}
                               title={`Compare with ${earlier.name}`}>
                              Compare
                            </a>
                          ) : null;
                        })()}
                        {p.tracks_learning === true && (
                          <a className="button" href={routeHref({ name: "learning", project, url: run.url })} title="How each image was learned, epoch by epoch">
                            Samples
                          </a>
                        )}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </>
      )}
    </div>
  );
}
