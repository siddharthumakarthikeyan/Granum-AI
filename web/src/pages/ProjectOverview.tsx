/** A project at a glance: the data as a mosaic, the headline numbers, the hardest sample,
 * training progress, sample dynamics, and what needs attention. */

import { useEffect, useState } from "react";
import { api } from "../api/client";
import type { ImageRounds, LearningReport, LearningSplit, ObjectEntry } from "../api/types";
import { ROLE_NAMES, ROLE_STYLE, type BoxRole } from "../boxes/model";
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
  const [learning, setLearning] = useState<LearningReport | null>(null);
  useEffect(() => {
    if (!tracked) return;
    let alive = true;
    api.runLearning(tracked.url).then((r) => alive && setLearning(r)).catch(() => undefined);
    return () => {
      alive = false;
    };
  }, [tracked?.url]);

  if (loadedProject !== project && loading) {
    return <div className="page"><PageHeader title={project} subtitle="Loading" /></div>;
  }

  const datasets = groupDatasets(tables);
  const sets = datasets.flatMap((dataset) => dataset.splits.map((split) => ({ dataset, split })));
  const live = sets.filter((s) => !HOLDING_SETS.includes(s.split.name));
  const images = live.reduce((n, s) => n + s.split.latest.row_count, 0);
  const boxes = live.reduce((n, s) => n + (s.split.latest.box_count ?? 0), 0);
  const classes = Math.max(0, ...live.map((s) => s.split.latest.class_count ?? 0));
  const byRecent = [...runs].sort((a, b) => b.created.localeCompare(a.created));
  const ranked = [...runs].sort((a, b) => (metric(b, "map50") ?? -1) - (metric(a, "map50") ?? -1));
  const best = ranked[0] && metric(ranked[0], "map50") !== null ? ranked[0] : null;

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
    <div className="overview">
      <section className="lab-banner">
        {mosaicSet && <Mosaic url={mosaicSet.split.latest.url} project={project} dataset={mosaicSet.dataset.name} />}
        <div className="lab-banner-shade" />
        <div className="lab-banner-content">
          <div className="lab-banner-title">
            <span className="page-context">Project</span>
            <h1 className="project-title">
              {project}
              <button className="icon-button title-rename" title="Rename project" aria-label="Rename project" onClick={() => setRenaming(true)}>
                <Icon name="pencil" size={15} />
              </button>
            </h1>
            <span className="muted">
              {datasets.map((d) => d.name).join(", ") || "No datasets"}{classes ? `, ${plural(classes, "class", "classes")}` : ""}, {plural(tables.length, "version")}
            </span>
          </div>
          <span className="spacer" />
          <BigNumber value={formatNumber(images)} label="images" />
          <BigNumber value={formatNumber(boxes)} label="boxes" />
          <BigNumber value={best ? (metric(best, "map50") ?? 0).toFixed(3) : "—"} label="best mAP50" accent />
          <div className="lab-banner-actions">
            <a className="button" href={routeHref({ name: "import", project })}><Icon name="import" />Import</a>
            <button className="button primary" onClick={() => setTrainPreset({})} disabled={job?.status === "running" || live.length === 0}>
              <Icon name="runs" />Train model
            </button>
            <button
              className="icon-button banner-delete"
              title="Delete project"
              aria-label="Delete project"
              onClick={() => setDeleting(true)}
              disabled={job?.status === "running"}
            >
              <Icon name="trash" size={16} />
            </button>
          </div>
        </div>
      </section>

      <div className="page">
        {datasets.length === 0 && runs.length === 0 && !loading && (
          <EmptyState
            title="No data yet"
            action={<a className="button primary" href={routeHref({ name: "import", project })}><Icon name="import" />Import a COCO dataset</a>}
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

        {(tracked || runs.length > 0) && (
          <div className="lab-grid-3">
            {tracked && dynamicsSplit ? (
              <HardestSample project={project} run={tracked} split={dynamicsSplit} />
            ) : (
              <div className="lab-card"><div className="lab-card-head"><h3>Hardest sample</h3></div><p className="faint small">Train with per-sample metrics to surface hard samples.</p></div>
            )}
            {runs.some((r) => (r.history?.length ?? 0) > 1) ? <TrainingChart runs={runs} compact metricKey="map50" /> : <div className="lab-card"><div className="lab-card-head"><h3>mAP50</h3></div><p className="faint small">{runs.some((r) => r.status === "running") ? "Training is in its first round. Scores are plotted when each round finishes." : "No epochs logged yet."}</p></div>}
            <DynamicsCard project={project} run={tracked} split={dynamicsSplit} />
          </div>
        )}

        {(staleBySet.size > 0 || warnings.length > 0) && (
          <section className="section">
            <div className="section-head"><h2 className="section-title">Attention</h2></div>
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
                <a href={routeHref({ name: "datasets", project })} className="section-link">All versions</a>
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
                        <tr key={dataset.name} className="clickable" onClick={() => navigate({ name: "datasets", project })}>
                          <td><span className="cell-title">{dataset.name}</span></td>
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
                <span className="faint small">ranked by mAP50</span>
                <a href={routeHref({ name: "runs", project })} className="section-link">All runs</a>
              </div>
              <div className="data-table-wrap">
                <table className="data-table">
                  <thead>
                    <tr>
                      <th>Run</th>
                      <th>Status</th>
                      <th className="num">mAP50</th>
                    </tr>
                  </thead>
                  <tbody>
                    {(ranked.length ? ranked : byRecent).slice(0, 6).map((run) => {
                      const map50 = metric(run, "map50");
                      return (
                        <tr key={run.url} className="clickable" onClick={() => navigate({ name: "run", project, url: run.url })}>
                          <td>
                            <span className="cell-title">{run.name}</span>
                            <span className="cell-sub">{String(run.parameters?.model ?? run.parameters?.framework ?? "")}, {formatWhen(run.created)}</span>
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

function BigNumber({ value, label, accent = false }: { value: string; label: string; accent?: boolean }) {
  return (
    <div className="big-number">
      <span className={`big-number-value${accent ? " accent" : ""}`}>{value}</span>
      <span className="big-number-label">{label}</span>
    </div>
  );
}

/** Two rows of thumbnails spread through the newest training version. */
function Mosaic({ url, project, dataset }: { url: string; project: string; dataset: string }) {
  const [images, setImages] = useState<string[]>([]);
  useEffect(() => {
    let alive = true;
    api.tableSample(url, 20).then((r) => alive && setImages(r.images.map((i) => i.image))).catch(() => undefined);
    return () => {
      alive = false;
    };
  }, [url]);
  return (
    <div className="lab-mosaic" aria-hidden="true">
      {images.map((image) => <img key={image} src={api.mediaUrl(image, 256, project, dataset)} alt="" loading="lazy" />)}
    </div>
  );
}

/** The labelled sample the tracked run did worst on, with its last-epoch boxes drawn. */
function HardestSample({ project, run, split }: { project: string; run: ObjectEntry; split: LearningSplit }) {
  const [data, setData] = useState<ImageRounds | null>(null);
  // Worst final F1 among images the model partly got: an image with nothing found shows
  // nothing, while a partial miss shows found, missed and false boxes side by side.
  const labelled = split.images.filter((i) => i.objects >= 15 && i.objects <= 90 && i.image);
  const candidate = [...labelled].filter((i) => i.final_score >= 0.15).sort((a, b) => a.final_score - b.final_score)[0]
    ?? [...labelled].sort((a, b) => a.final_score - b.final_score)[0];

  useEffect(() => {
    if (!candidate) return;
    let alive = true;
    api.imageRounds(run.url, split.table, candidate.example_id).then((r) => alive && setData(r)).catch(() => undefined);
    return () => {
      alive = false;
    };
  }, [run.url, split.table, candidate?.example_id]);

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
    (last.boxes ?? []).forEach((b) => {
      if (b.matched || b.ignored) return;
      shapes.push({ role: "unmatched", v: b.vertices });
      counts.unmatched = (counts.unmatched ?? 0) + 1;
    });
  }

  return (
    <a className="lab-card hardest" href={routeHref({ name: "learning", project, url: run.url })}>
      <div className="lab-card-head">
        <h3>Hardest sample</h3>
        <span>{candidate ? `F1 ${candidate.final_score.toFixed(2)}, ${plural(candidate.objects, "object")}, ${run.name}` : "none"}</span>
      </div>
      <div className="hardest-frame" style={{ aspectRatio: data ? `${data.width} / ${data.height}` : "16 / 9" }}>
        {candidate?.image && <img src={api.mediaUrl(candidate.image, 640, project, split.dataset ?? undefined)} alt="" />}
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
      <div className="box-legend">
        {(["truth", "missed", "unmatched"] as BoxRole[]).map((role) => (
          <span key={role}>
            <i style={{ borderColor: ROLE_STYLE[role].color, borderStyle: role === "unmatched" ? "dashed" : "solid" }} />
            {role === "truth" ? "Found" : ROLE_NAMES[role]} {counts[role] ?? 0}
          </span>
        ))}
      </div>
    </a>
  );
}

function DynamicsCard({ project, run, split }: { project: string; run?: ObjectEntry; split?: LearningSplit }) {
  if (!run || !split) {
    return <div className="lab-card"><div className="lab-card-head"><h3>Sample dynamics</h3></div><p className="faint small">No run with per-sample metrics yet.</p></div>;
  }
  const total = split.images.length || 1;
  const never = split.counts.never ?? 0;
  return (
    <a className="lab-card" href={routeHref({ name: "learning", project, url: run.url })}>
      <div className="lab-card-head">
        <h3>Sample dynamics</h3>
        <span>{split.split}, {run.name}</span>
      </div>
      <div className="dyn-headline">{Math.round((never / total) * 100)}%</div>
      <div className="muted small dyn-sub">never learned, {plural(never, "sample")}</div>
      <div className="dyn-bars">
        {DYNAMICS.map((c) => {
          const n = split.counts[c.id] ?? 0;
          return (
            <div key={c.id} className="dyn-row">
              <span>{c.label}</span>
              <span className="dyn-track"><span style={{ width: `${(n / total) * 100}%`, background: c.color }} /></span>
              <span className="num">{formatNumber(n)}</span>
            </div>
          );
        })}
      </div>
    </a>
  );
}
