/** A project at a glance: the data as a mosaic, the headline numbers, the hardest sample,
 * training progress, sample dynamics, and what needs attention. */

import { useEffect, useState } from "react";
import { api } from "../api/client";
import type { ImageRounds, LearningReport, LearningSplit, ObjectEntry } from "../api/types";
import { ROLE_NAMES, ROLE_STYLE, type BoxRole } from "../boxes/model";
import { ActionMenu } from "../components/ActionMenu";
import { DashboardMetric } from "../components/DashboardMetric";
import { EmptyState, Icon, PageHeader, RunStatus, SeverityLabel, formatNumber, formatWhen, plural } from "../components/ui";
import { navigate, routeHref } from "../router";
import { useStore } from "../store/store";
import { DeleteProjectDialog } from "../components/DeleteProjectDialog";
import { RenameProjectDialog } from "../components/RenameProjectDialog";
import { TrainDialog, TrainingProgressCard, useTrainingJob, type TrainPreset } from "../training/Training";
import { HOLDING_SETS, groupDatasets, splitOfTable } from "./datasets";
import { TrainingChart } from "./TrainingChart";

const metric = (run: ObjectEntry, key: string): number | null => {
  const value = run.last_metrics?.[key];
  return typeof value === "number" && Number.isFinite(value) ? value : null;
};

const DYNAMICS = [
  { id: "early", label: "Early", color: "var(--learn-early)" },
  { id: "steady", label: "Mid", color: "var(--learn-steady)" },
  { id: "late", label: "Late", color: "var(--learn-late)" },
  { id: "forgotten", label: "Unstable", color: "var(--amber)" },
  { id: "never", label: "Not learned", color: "var(--pink)" },
  { id: "insufficient", label: "Too few observations", color: "var(--learn-insufficient)" },
] as const;

export function ProjectOverview({ project }: { project: string }) {
  const tables = useStore((s) => s.tables);
  const runs = useStore((s) => s.runs);
  const imports = useStore((s) => s.imports);
  const loading = useStore((s) => s.loading);
  const loadedProject = useStore((s) => s.loadedProject);
  const refreshProject = useStore((s) => s.refreshProject);
  const { job, setJob, dismiss, cancel } = useTrainingJob(project);
  const [trainPreset, setTrainPreset] = useState<TrainPreset | null>(null);
  const [deleting, setDeleting] = useState(false);
  const [renaming, setRenaming] = useState(false);
  const training = runs.some((r) => r.status === "running") || job?.status === "running";

  useEffect(() => {
    if (!training) return;
    const timer = window.setInterval(() => void refreshProject(), 4000);
    return () => window.clearInterval(timer);
  }, [training, refreshProject]);

  // The newest run that recorded per-sample dynamics feeds the hardest-sample and dynamics cards.
  const tracked = [...runs].filter((r) => r.parameters?.tracks_learning === true && r.status !== "running")
    .sort((a, b) => b.created.localeCompare(a.created))[0];
  const [learningResult, setLearningResult] = useState<{ url: string; report: LearningReport } | null>(null);
  const learning = learningResult?.url === tracked?.url ? learningResult?.report : null;
  useEffect(() => {
    if (!tracked) return;
    let alive = true;
    api.runLearning(tracked.url).then((report) => alive && setLearningResult({ url: tracked.url, report })).catch(() => undefined);
    return () => {
      alive = false;
    };
  }, [tracked?.url]);

  if (loadedProject !== project) {
    return <div className="page project-dashboard"><PageHeader title={project} subtitle={loading ? "Loading your project…" : "Project data is unavailable."} />
      <div className="dashboard-loading" role="status">{loading ? <><span className="spinner" />Loading datasets and runs</> :
        <button className="button" onClick={() => void useStore.getState().openProject(project)}><Icon name="refresh" />Retry loading project</button>}</div></div>;
  }

  const datasets = groupDatasets(tables);
  const sets = datasets.flatMap((dataset) => dataset.splits.map((split) => ({ dataset, split })));
  const live = sets.filter((s) => !HOLDING_SETS.includes(s.split.name));
  const images = live.reduce((n, s) => n + s.split.latest.row_count, 0);
  const boxes = live.reduce((n, s) => n + (s.split.latest.box_count ?? 0), 0);
  const classes = Math.max(0, ...live.map((s) => s.split.latest.class_count ?? 0));
  const byRecent = [...runs].sort((a, b) => b.created.localeCompare(a.created));
  const score = [{ key: "map50", label: "mAP50" }, { key: "mean_iou", label: "Mean IoU" },
    { key: "accuracy", label: "Accuracy" }, { key: "macro_f1", label: "Macro F1" }]
    .find((candidate) => runs.some((run) => metric(run, candidate.key) !== null)) ?? { key: "map50", label: "mAP50" };
  const ranked = [...runs].sort((a, b) => (metric(b, score.key) ?? -1) - (metric(a, score.key) ?? -1));
  const best = ranked[0] && metric(ranked[0], score.key) !== null ? ranked[0] : null;
  const hasHistory = runs.some((run) => run.history?.some((epoch) =>
    ["accuracy", "macro_f1", "mean_iou", "pixel_accuracy", "train_loss", "map50", "map50_95", "recall", "precision", "val_box_loss", "train_box_loss"]
      .some((key) => typeof epoch[key] === "number")));

  const tableByUrl = new Map(tables.map((t) => [t.url, t]));
  const staleBySet = new Map<string, { label: string; latest: ObjectEntry; runs: ObjectEntry[] }>();
  for (const run of runs) {
    const input = run.inputs?.[0];
    const found = input && tableByUrl.has(input) ? splitOfTable(datasets, input) : null;
    if (!found || found.split.latest.url === input) continue;
    if (runs.some((other) => other.inputs?.includes(found.split.latest.url))) continue;
    const key = `${found.dataset.name}/${found.split.name}`;
    const entry = staleBySet.get(key) ?? { label: key, latest: found.split.latest, runs: [] };
    entry.runs.push(run);
    staleBySet.set(key, entry);
  }
  const warnings = imports.flatMap((item) => item.findings.filter((f) => f.severity !== "info").map((finding) => ({ item, finding })));
  const mosaicSet = live.find((s) => /^train/i.test(s.split.name)) ?? live[0];
  const dynamicsSplit = learning?.splits.find((s) => s.split === "train") ?? learning?.splits[0];

  return (
    <div className="overview page project-dashboard">
      <PageHeader
        title={<span className="project-title">{project}</span>}
        subtitle={`${plural(datasets.length, "source dataset")} · ${plural(classes, "class", "classes")} · ${plural(tables.length, "table version")}`}
        actions={<>
          <a className="button" href={routeHref({ name: "import", project })}><Icon name="import" />Add data</a>
          <button className="button primary" onClick={() => setTrainPreset({})} disabled={job?.status === "running" || live.length === 0}><Icon name="runs" />Train model</button>
          <ActionMenu label="Project actions" actions={[
            { label: "Rename project", icon: "pencil", onSelect: () => setRenaming(true) },
            { label: "Delete project", icon: "trash", danger: true, disabled: job?.status === "running", onSelect: () => setDeleting(true) },
          ]} />
        </>}
      />
      <dl className="dashboard-metrics" aria-label="Project statistics">
        <DashboardMetric label="Images" value={formatNumber(images)} detail={`Across ${plural(live.length, "active split")}`} icon="images" />
        <DashboardMetric label="Annotated objects" value={formatNumber(boxes)} detail={plural(classes, "class", "classes")} icon="target" />
        <DashboardMetric label="Runs" value={formatNumber(runs.length)} detail={training ? "Training in progress" : "Recorded experiments"} icon="runs" />
        <DashboardMetric label={`Best ${score.label}`} value={best ? metric(best, score.key)!.toFixed(3) : "—"}
          detail={best ? best.name : "Available after evaluation"} icon="target" accent />
      </dl>
      {datasets.length > 0 && <nav className="project-workflow" aria-label="Project workflow">
        <a href={routeHref({ name: "images", project, review: true })}><span className="workflow-icon"><Icon name="review" size={19} /></span><span><strong>Review images</strong><span>Inspect and refine labels</span></span><Icon name="chevron" size={15} /></a>
        <a href={routeHref({ name: "datasets", project })}><span className="workflow-icon"><Icon name="datasets" size={19} /></span><span><strong>Dataset versions</strong><span>Prepare your training data</span></span><Icon name="chevron" size={15} /></a>
        <a href={routeHref({ name: "runs", project })}><span className="workflow-icon"><Icon name="runs" size={19} /></span><span><strong>Explore runs</strong><span>Follow model performance</span></span><Icon name="chevron" size={15} /></a>
      </nav>}

      <div className="overview-content">
        {datasets.length === 0 && runs.length === 0 && !loading && (
          <EmptyState
            title="No data yet"
            action={<a className="button primary" href={routeHref({ name: "import", project })}><Icon name="import" />Add data</a>}
          >
            <p>Import annotations and images to start. Preflight validates everything before it is written.</p>
          </EmptyState>
        )}

        {job && <TrainingProgressCard project={project} job={job} onCancel={() => void cancel()} onDismiss={dismiss} />}
        {trainPreset && <TrainDialog project={project} preset={trainPreset} onClose={() => setTrainPreset(null)} onStarted={setJob} />}
        {renaming && <RenameProjectDialog project={project} onClose={() => setRenaming(false)} />}
        {deleting && (
          <DeleteProjectDialog project={{ name: project, tables: tables.length, runs: runs.length }} onClose={() => setDeleting(false)} />
        )}

        {(datasets.length > 0 || runs.length > 0) && (
          <div className="overview-insights">
            <section className="performance-panel">
              <div className="performance-heading"><div><h2>Model performance</h2><p>Follow your experiments, epoch by epoch.</p></div><a className="section-link" href={routeHref({ name: "runs", project })}>All runs<Icon name="chevron" size={14} /></a></div>
              {hasHistory ? <TrainingChart runs={runs} metricKey={score.key} /> :
                <div className="insight-empty-body"><span className="empty-state-icon"><Icon name="runs" size={25} /></span><strong>{training ? "Your model is learning" : "See your progress take shape"}</strong><p>{training ? "Scores appear as training rounds finish." : "Train a model or record metrics from your pipeline to compare performance here."}</p>
                  {!training && <button className="button" disabled={live.length === 0} onClick={() => setTrainPreset({})}>Train a model<Icon name="chevron" size={14} /></button>}
                </div>}
              <div className="performance-foot"><span className={`status-dot${training ? " ok" : ""}`} />{training ? "Training in progress · updates automatically" : `${plural(runs.length, "recorded experiment")} in this project`}</div>
            </section>
            {tracked && dynamicsSplit ? <HardestSample key={`${tracked.url}/${dynamicsSplit.table}`} project={project} run={tracked} split={dynamicsSplit} /> :
              <a className="lab-card dataset-preview" href={routeHref({ name: "images", project })}>
                <div className="lab-card-head"><h3>Dataset preview</h3><Icon name="chevron" size={14} /></div>
                <div className="dataset-preview-frame">{mosaicSet ? <Mosaic url={mosaicSet.split.latest.url} project={project} dataset={mosaicSet.dataset.name} /> : <Icon name="images" size={28} />}</div>
                <p className="dataset-preview-foot"><span>{plural(images, "image")} to explore</span><span>View images<Icon name="chevron" size={13} /></span></p>
              </a>}
          </div>
        )}
        {tracked && dynamicsSplit && <DynamicsCard project={project} run={tracked} split={dynamicsSplit} />}

        {(staleBySet.size > 0 || warnings.length > 0) && (
          <section className="section">
            <div className="section-head"><h2 className="section-title"><Icon name="warn" size={17} />Needs attention <span className="dashboard-count">{staleBySet.size + warnings.length}</span></h2></div>
            <div className="data-table-wrap">
              <table className="data-table">
                <tbody>
                  {[...staleBySet.values()].map((stale) => (
                    <tr key={stale.label}>
                      <td style={{ width: 110 }}><span className="severity severity-info"><Icon name="refresh" size={14} />Retrain</span></td>
                      <td>
                        <span className="cell-title">{plural(stale.runs.length, "run")} trained on an older {stale.label}</span>
                        <span className="cell-sub">{stale.runs.map((r) => r.name).join(", ")}. Newest version {stale.latest.name}, {formatNumber(stale.latest.row_count)} images.</span>
                      </td>
                      <td className="actions">
                        <button
                          className="button"
                          disabled={job?.status === "running"}
                          onClick={() => setTrainPreset({ trainUrl: stale.latest.url, compareWith: stale.runs[stale.runs.length - 1]!.name })}
                        >
                          Retrain on {stale.latest.name}
                        </button>
                      </td>
                    </tr>
                  ))}
                  {warnings.slice(0, 6).map(({ item, finding }) => (
                    <tr key={`${item.id}-${finding.code}`} className="clickable" onClick={() => navigate({ name: "report", project, id: item.id })}>
                      <td style={{ width: 110 }}><SeverityLabel severity={finding.severity} /></td>
                      <td>
                        <span className="cell-title">{finding.title}</span>
                        <span className="cell-sub">Preflight, {formatWhen(item.created)}</span>
                      </td>
                      <td className="num muted">{formatNumber(finding.count)} {finding.unit}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </section>
        )}

        <div className="overview-columns">
          {datasets.length > 0 && (
            <section className="section">
              <div className="section-head">
                <h2 className="section-title">Datasets</h2>
                <a href={routeHref({ name: "datasets", project })} className="section-link">Dataset versions</a>
              </div>
              <div className="data-table-wrap">
                <table className="data-table">
                  <thead>
                    <tr>
                      <th>Dataset</th>
                      <th>Sets</th>
                      <th className="num">Images</th>
                      <th className="num">Boxes</th>
                      <th className="num">Versions</th>
                      <th>Updated</th>
                    </tr>
                  </thead>
                  <tbody>
                    {datasets.map((dataset) => {
                      const liveSets = dataset.splits.filter((s) => !HOLDING_SETS.includes(s.name));
                      const newest = dataset.revisions.map((r) => r.entry.created).sort().at(-1);
                      return (
                        <tr key={dataset.name} className="clickable" onClick={() => navigate({ name: "images", project, dataset: dataset.name })}>
                          <td><a className="cell-title" href={routeHref({ name: "images", project, dataset: dataset.name })}>{dataset.name}</a></td>
                          <td>
                            <span className="set-pills">
                              {liveSets.map((s) => (
                                <a
                                  key={s.name}
                                  className="set-pill"
                                  href={routeHref({ name: "table", project, url: s.latest.url })}
                                  onClick={(e) => e.stopPropagation()}
                                  title={`Open ${s.name} (${s.latest.name})`}
                                >
                                  {s.name}<span>{formatNumber(s.latest.row_count)}</span>
                                </a>
                              ))}
                            </span>
                          </td>
                          <td className="num">{formatNumber(liveSets.reduce((n, s) => n + s.latest.row_count, 0))}</td>
                          <td className="num">{formatNumber(liveSets.reduce((n, s) => n + (s.latest.box_count ?? 0), 0))}</td>
                          <td className="num">{dataset.revisions.length}</td>
                          <td className="muted">{formatWhen(newest)}</td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            </section>
          )}

          {runs.length > 0 && (
            <section className="section">
              <div className="section-head">
                <h2 className="section-title">Runs</h2>
                <span className="faint small">ranked by {score.label}</span>
                <a href={routeHref({ name: "runs", project })} className="section-link">All runs</a>
              </div>
              <div className="data-table-wrap">
                <table className="data-table">
                  <thead>
                    <tr>
                      <th>Run</th>
                      <th>Status</th>
                      <th className="num">{score.label}</th>
                    </tr>
                  </thead>
                  <tbody>
                    {(ranked.length ? ranked : byRecent).slice(0, 6).map((run) => {
                      const map50 = metric(run, score.key);
                      return (
                        <tr key={run.url} className="clickable" onClick={() => navigate({ name: "run", project, url: run.url })}>
                          <td>
                            <a className="cell-title" href={routeHref({ name: "run", project, url: run.url })}>{run.name}</a>
                            <span className="cell-sub">{[String(run.parameters?.model ?? run.parameters?.framework ?? ""), formatWhen(run.created)].filter(Boolean).join(" · ")}</span>
                          </td>
                          <td><RunStatus status={run.status} epochs={run.epochs} total={run.parameters?.epochs} /></td>
                          <td className={`num strong${run === best ? " value-best" : ""}`}>{map50 !== null ? map50.toFixed(3) : "—"}</td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            </section>
          )}
        </div>
      </div>
    </div>
  );
}

/** Two rows of thumbnails spread through the newest training version. */
function Mosaic({ url, project, dataset }: { url: string; project: string; dataset: string }) {
  const [images, setImages] = useState<string[] | null>(null);
  useEffect(() => {
    let alive = true;
    setImages(null);
    api.tableSample(url, 6).then((r) => alive && setImages(r.images.map((i) => i.image).filter(Boolean))).catch(() => alive && setImages([]));
    return () => {
      alive = false;
    };
  }, [url]);
  if (!images?.length) return <div className="preview-placeholder"><Icon name="images" size={27} /><span>{images === null ? "Loading image previews…" : "No image previews in this dataset"}</span></div>;
  return (
    <div className="lab-mosaic" aria-hidden="true">
      {images.map((image) => <img key={image} src={api.mediaUrl(image, 256, project, dataset)} alt="" loading="lazy" />)}
    </div>
  );
}

/** The labelled sample the tracked run did worst on, with its last-epoch boxes drawn. */
function HardestSample({ project, run, split }: { project: string; run: ObjectEntry; split: LearningSplit }) {
  const [data, setData] = useState<ImageRounds | null>(null);
  const [failed, setFailed] = useState(false);
  // Include sparse images and complete misses: they can be the most useful examples.
  const candidate = split.images.filter((image) => image.image && Number.isFinite(image.final_score))
    .sort((a, b) => a.final_score - b.final_score)[0];

  useEffect(() => {
    if (!candidate) return;
    let alive = true;
    setData(null);
    setFailed(false);
    api.imageRounds(run.url, split.table, candidate.example_id).then((r) => alive && setData(r)).catch(() => alive && setFailed(true));
    return () => {
      alive = false;
    };
  }, [run.url, split.table, candidate?.example_id]);

  if (!candidate) {
    return <a className="lab-card insight-empty" href={routeHref({ name: "learning", project, url: run.url })}>
      <div className="lab-card-head"><h3>Hardest sample</h3><Icon name="chevron" size={14} /></div>
      <div className="insight-empty-body"><span className="insight-empty-icon"><Icon name="images" size={26} /></span><strong>No scored images yet</strong><p>Samples with image references and recorded scores will appear here.</p></div>
    </a>;
  }

  const last = data?.rounds[data.rounds.length - 1];
  const counts: Partial<Record<BoxRole, number>> = {};
  const shapes: { role: BoxRole; v: number[] }[] = [];
  if (data && last) {
    data.truth.forEach((t, i) => {
      if (t.iscrowd) return;
      const role: BoxRole = last.gt_match && last.gt_match[i] === -1 ? "missed" : "truth";
      shapes.push({ role, v: t.vertices });
      counts[role] = (counts[role] ?? 0) + 1;
    });
    const matchedPredictions = new Set(last.gt_match?.filter((index) => index >= 0));
    (last.boxes ?? []).forEach((b, index) => {
      // Some collectors store the ground-truth mapping without per-prediction flags.
      const matched = b.matched ?? (last.gt_match ? matchedPredictions.has(index) : undefined);
      if (matched !== false || b.ignored) return;
      shapes.push({ role: "unmatched", v: b.vertices });
      counts.unmatched = (counts.unmatched ?? 0) + 1;
    });
  }

  return (
    <a className="lab-card hardest" href={routeHref({ name: "learning", project, url: run.url })}>
      <div className="lab-card-head">
        <h3>Hardest sample</h3>
        <span title={run.name}>F1 {candidate.final_score.toFixed(2)} · {plural(candidate.objects, "object")}</span>
      </div>
      <div className="hardest-frame" style={{ aspectRatio: data ? `${data.width} / ${data.height}` : "16 / 9", maxWidth: data ? `${280 * data.width / data.height}px` : undefined }}>
        {candidate.image && <img src={api.mediaUrl(candidate.image, 640, project, split.dataset ?? undefined)} alt={`Lowest-scoring sample in ${split.split}, final F1 ${candidate.final_score.toFixed(2)}`} />}
        {data && (
          <svg viewBox={`0 0 ${data.width} ${data.height}`} preserveAspectRatio="none" aria-hidden="true">
            {shapes.map((s, i) => {
              const [x0 = 0, y0 = 0, x1 = 0, y1 = 0] = s.v;
              return (
                <rect key={i} x={x0} y={y0} width={x1 - x0} height={y1 - y0} fill="none"
                  stroke={ROLE_STYLE[s.role].color} strokeWidth={2} vectorEffect="non-scaling-stroke"
                  strokeDasharray={s.role === "unmatched" ? "4 3" : undefined} />
              );
            })}
          </svg>
        )}
      </div>
      {last ? <div className="box-legend">
        {((last.gt_match ? ["truth", "missed", "unmatched"] : ["truth"]) as BoxRole[]).map((role) => (
          <span key={role}>
            <i style={{ borderColor: ROLE_STYLE[role].color, borderStyle: role === "unmatched" ? "dashed" : "solid" }} />
            {role === "truth" ? last.gt_match ? "Found" : "Ground truth" : ROLE_NAMES[role]} {counts[role] ?? 0}
          </span>
        ))}
      </div> : <p className="muted small sample-detail-status">{failed ? "Annotation details unavailable. Open the run to inspect." : data ? "No annotation rounds recorded." : "Loading annotation details…"}</p>}
    </a>
  );
}

function DynamicsCard({ project, run, split }: { project: string; run: ObjectEntry; split: LearningSplit }) {
  const total = split.images.length || 1;
  const never = split.counts.never ?? 0;
  return <a className="dynamics-summary" href={routeHref({ name: "learning", project, url: run.url })}>
    <div className="dynamics-heading"><span className="dynamics-symbol"><Icon name="target" size={21} /></span><div><h3>Learning dynamics</h3><p>{split.split} · {run.name}</p></div></div>
    <div className="dynamics-distribution"><div className="dynamics-track" aria-hidden="true">{DYNAMICS.map((category) => <span key={category.id} style={{ width: `${((split.counts[category.id] ?? 0) / total) * 100}%`, background: category.color }} />)}</div>
      <div className="dynamics-legend">{DYNAMICS.map((category) => { const n = split.counts[category.id] ?? 0; return n > 0 ? <span key={category.id}><i style={{ background: category.color }} />{category.label}<strong>{formatNumber(n)}</strong></span> : null; })}</div>
    </div>
    <div className="dynamics-score"><strong>{Math.round((never / total) * 100)}%</strong><span>not learned</span></div><Icon name="chevron" size={17} />
  </a>;
}
