/** Sample dynamics: when each image was learned during training, and which never were.
 *
 * Built on per-image F1 recorded after every epoch (granum.metrics.dynamics.image_learning).
 * An image is learned from the epoch its F1 reached the threshold and stayed there.
 */

import { useEffect, useMemo, useState } from "react";
import { api } from "../api/client";
import type { LearnedImage, LearningCategory, LearningReport, LearningSplit } from "../api/types";
import { Modal } from "../components/Modal";
import { EmptyState, Icon, PageHeader, formatNumber, plural } from "../components/ui";
import { routeHref } from "../router";
import { useStore } from "../store/store";
import { useDecisions, type Decision } from "../viewer/decisions";
import { ImageViewer } from "../viewer/ImageViewer";
import { groupDatasets, splitOfTable } from "./datasets";

interface CategoryInfo {
  id: LearningCategory;
  label: string;
  explain: (split: LearningSplit) => string;
  color: string;
}

const epochOf = (epoch: number | null | undefined) => (epoch === null || epoch === undefined ? "?" : String(Math.round(epoch) + 1));

const CATEGORIES: CategoryInfo[] = [
  { id: "early", label: "Early", color: "var(--learn-early)", explain: (s) => `Learned by epoch ${epochOf(s.early_before)} and stable after.` },
  { id: "steady", label: "Mid", color: "var(--learn-steady)", explain: (s) => `Learned between epochs ${epochOf(s.early_before)} and ${epochOf(s.late_after)}.` },
  { id: "late", label: "Late", color: "var(--learn-late)", explain: (s) => `Learned from epoch ${epochOf(s.late_after)} onward. Hard samples or label noise.` },
  { id: "forgotten", label: "Unstable", color: "var(--warn)", explain: () => "Reached the threshold, then dropped below it again. Often inconsistent labels." },
  { id: "never", label: "Not learned", color: "var(--block)", explain: () => "Never reached the threshold. Check for missing or wrong labels first." },
  { id: "empty", label: "Empty", color: "var(--learn-empty)", explain: () => "No labels and no predictions." },
];
const INFO = new Map(CATEGORIES.map((c) => [c.id, c]));

type Sort = "learned" | "final" | "objects";
type DecisionFilter = "all" | "undecided" | Decision;

const DECISION_LABEL: Record<Decision, string> = { keep: "Keep", remove: "Remove", removed: "Removed" };
const PAGE = 60;

export function LearningPage({ project, url }: { project: string; url: string }) {
  const runs = useStore((s) => s.runs);
  const tables = useStore((s) => s.tables);
  const refreshProject = useStore((s) => s.refreshProject);
  const [report, setReport] = useState<LearningReport | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [splitName, setSplitName] = useState<string | null>(null);
  const [category, setCategory] = useState<LearningCategory | null>(null);
  const [sort, setSort] = useState<Sort>("learned");
  const [shown, setShown] = useState(PAGE);
  const [good, setGood] = useState(0.5);
  const [decisionFilter, setDecisionFilter] = useState<DecisionFilter>("all");
  // The list is fixed while the viewer is open, so deciding never shifts what comes next.
  const [viewing, setViewing] = useState<{ index: number; items: LearnedImage[] } | null>(null);
  const [confirming, setConfirming] = useState(false);
  const [applying, setApplying] = useState(false);
  const [applyError, setApplyError] = useState<string | null>(null);
  const [toast, setToast] = useState<string | null>(null);

  // While the run trains, new epochs keep arriving: reload them, and the run's status.
  const [tick, setTick] = useState(0);
  const isRunning = runs.find((r) => r.url === url)?.status === "running";
  useEffect(() => {
    if (!isRunning) return;
    const timer = window.setInterval(() => {
      setTick((t) => t + 1);
      void refreshProject();
    }, 20000);
    return () => window.clearInterval(timer);
  }, [isRunning, refreshProject]);

  useEffect(() => {
    let alive = true;
    setError(null);
    api.runLearning(url, good)
      .then((next) => {
        if (!alive) return;
        setReport(next);
        setSplitName((current) => (next.splits.some((s) => s.split === current) ? current : (next.splits.find((s) => s.split === "train") ?? next.splits[0])?.split ?? null));
      })
      .catch((e: Error) => alive && setError(e.message));
    return () => {
      alive = false;
    };
  }, [url, good, tick]);

  const split = report?.splits.find((s) => s.split === splitName) ?? null;
  const decisions = useDecisions(project, split?.dataset ?? null);
  const run = runs.find((r) => r.url === url);
  const name = report?.name ?? run?.name ?? "Run";

  useEffect(() => {
    // Open on the hardest samples when there are any.
    if (!split) return;
    const first = (["never", "forgotten", "late"] as LearningCategory[]).find((c) => (split.counts[c] ?? 0) > 0);
    setCategory(first ?? null);
    setShown(PAGE);
  }, [split]);

  const images = useMemo(() => {
    if (!split) return [];
    const decisionOf = (i: LearnedImage) => (i.image ? decisions.byImage.get(i.image) : undefined);
    const chosen = split.images.filter((i) =>
      (category === null || i.category === category)
      && (decisionFilter === "all" || (decisionFilter === "undecided" ? !decisionOf(i) : decisionOf(i) === decisionFilter)));
    const key: Record<Sort, (i: LearnedImage) => number> = {
      learned: (i) => (i.learned_epoch ?? 1e6) * 10 - i.best_score,
      final: (i) => i.final_score,
      objects: (i) => -i.objects,
    };
    return [...chosen].sort((a, b) => key[sort](a) - key[sort](b) || a.example_id - b.example_id);
  }, [split, category, sort, decisionFilter, decisions.byImage]);

  const marked = split ? split.images.filter((i) => i.image && decisions.byImage.get(i.image) === "remove") : [];
  const target = split ? splitOfTable(groupDatasets(tables), split.table)?.split ?? null : null;

  const applyRemovals = async () => {
    if (!split || !target) return;
    setApplying(true);
    setApplyError(null);
    try {
      const done = await api.removeImages({
        project, table: target.latest.url, samples: marked.map((i) => i.image!), reason: `Removed after reviewing ${name}`,
        reasons: Object.fromEntries(marked.map((i) => [i.image!, decisions.reasons.get(i.image!) ?? ""]).filter(([, r]) => r)),
      });
      setConfirming(false);
      setToast(`Removed ${plural(done.count, "image")} from ${split.split}. New version ${done.version.name}.`);
      window.setTimeout(() => setToast(null), 6000);
      await Promise.all([decisions.refresh(), refreshProject()]);
    } catch (e) {
      setApplyError(e instanceof Error ? e.message : String(e));
    } finally {
      setApplying(false);
    }
  };

  const params = run?.parameters ?? {};
  const header = (
    <PageHeader
      back={{ href: routeHref({ name: "runs", project }), label: "Runs" }}
      title={`${name}: sample dynamics`}
      subtitle={report ? `Per-image F1 by epoch, ${String(params.model ?? params.framework ?? "")}. Learned means F1 ≥ ${report.good} through the last epoch.` : "Loading"}
      actions={
        <>
          <label className="inline-field small">
            <span className="muted">Threshold</span>
            <select value={good} onChange={(e) => setGood(Number(e.target.value))} aria-label="F1 threshold">
              <option value={0.3}>F1 0.3</option>
              <option value={0.5}>F1 0.5</option>
              <option value={0.7}>F1 0.7</option>
            </select>
          </label>
          <a className="button" href={routeHref({ name: "run", project, url })}>Open run</a>
        </>
      }
    />
  );

  if (error) return <div className="page">{header}<p className="form-error">{error}</p></div>;
  if (report && report.splits.length === 0) {
    return (
      <div className="page">
        {header}
        {run?.status === "running" ? (
          <EmptyState title="Waiting for the first epoch to finish">
            <p>
              Per-image results are recorded at the end of every epoch, after the model has been run on each image.
              They appear here automatically; on a large dataset the first epoch can take several minutes.
            </p>
          </EmptyState>
        ) : (
          <EmptyState title="No per-epoch sample metrics in this run">
            <p>
              {run?.status === "interrupted" || run?.status === "cancelled" || run?.status === "failed"
                ? "The run stopped before its first epoch finished, so no per-image results were recorded."
                : "Train with “Record per-sample metrics and predictions every epoch” enabled."}
            </p>
          </EmptyState>
        )}
      </div>
    );
  }

  return (
    <div className="page learning-page">
      {header}
      {report && (
        <div className="tabs" role="tablist" aria-label="Set">
          {report.splits.map((s) => (
            <button key={s.split} role="tab" aria-selected={s.split === splitName} className={`tab${s.split === splitName ? " on" : ""}`} onClick={() => setSplitName(s.split)}>
              {s.split}
              <span className="small">{formatNumber(s.images.length)} images, {s.epochs.length} epochs</span>
            </button>
          ))}
        </div>
      )}

      {split && split.epochs.length < 3 && (
        <p className="notice">Only {plural(split.epochs.length, "epoch")} recorded; early and late categories need more epochs to mean much.</p>
      )}

      {split && (
        <div className="dynamics-summary">
          <CategoryTable split={split} selected={category} onSelect={setCategory} />
          <LearnedByEpoch split={split} />
        </div>
      )}

      {split && (
        <section className="section">
          <div className="grid-toolbar">
            <h2 className="section-title">
              {category ? INFO.get(category)!.label : "All samples"} <span className="muted">{formatNumber(images.length)}</span>
            </h2>
            {category && <span className="faint small">{INFO.get(category)!.explain(split)}</span>}
            <span className="spacer" />
            {category && <button className="button subtle" onClick={() => setCategory(null)}>Clear category</button>}
            <label className="inline-field small">
              <span className="muted">Decision</span>
              <select value={decisionFilter} onChange={(e) => setDecisionFilter(e.target.value as DecisionFilter)}>
                <option value="all">Any</option>
                <option value="undecided">Undecided</option>
                <option value="keep">Keep</option>
                <option value="remove">Remove</option>
                <option value="removed">Removed</option>
              </select>
            </label>
            <label className="inline-field small">
              <span className="muted">Sort</span>
              <select value={sort} onChange={(e) => setSort(e.target.value as Sort)}>
                <option value="learned">Learned epoch</option>
                <option value="final">Final F1, lowest first</option>
                <option value="objects">Objects, most first</option>
              </select>
            </label>
          </div>
          <div className="sample-grid">
            {images.slice(0, shown).map((image, i) => (
              <SampleCard
                key={image.example_id}
                image={image}
                split={split}
                project={project}
                good={report!.good}
                decision={image.image ? decisions.byImage.get(image.image) : undefined}
                onOpen={() => setViewing({ index: i, items: images })}
              />
            ))}
          </div>
          {images.length > shown && (
            <div className="learning-more">
              <button className="button" onClick={() => setShown(shown + PAGE * 2)}>Show {formatNumber(Math.min(PAGE * 2, images.length - shown))} more</button>
            </div>
          )}
        </section>
      )}

      {split && marked.length > 0 && (
        <div className="decision-tray" role="region" aria-label="Pending removals">
          <span className="strong">{plural(marked.length, "image")} marked for removal</span>
          <span className="muted">{split.dataset} / {split.split}</span>
          <span className="spacer" />
          <button className="button subtle" onClick={() => setDecisionFilter("remove")}>Show</button>
          <button className="button danger-button" onClick={() => setConfirming(true)} disabled={!target}>Remove from {split.split}</button>
        </div>
      )}
      {toast && <div className="toast" role="status">{toast}</div>}
      {decisions.error && <p className="form-error">{decisions.error}</p>}

      {confirming && split && target && (
        <Modal
          title={`Remove ${plural(marked.length, "image")} from ${split.split}`}
          onClose={() => !applying && setConfirming(false)}
          width={500}
          footer={
            <>
              <span className="spacer" />
              <button onClick={() => setConfirming(false)} disabled={applying}>Cancel</button>
              <button className="primary" onClick={() => void applyRemovals()} disabled={applying}>
                {applying ? "Removing" : "Remove"}
              </button>
            </>
          }
        >
          <p>Creates a new version of <span className="strong">{split.split}</span> from <span className="mono">{target.latest.name}</span> ({formatNumber(target.latest.row_count)} images) without these images. They move to the <span className="strong">removed</span> set with their reasons and can be restored.</p>
          {applyError && <p className="form-error">{applyError}</p>}
        </Modal>
      )}

      {viewing !== null && split && report && (
        <ImageViewer
          project={project}
          runUrl={url}
          table={split.table}
          dataset={split.dataset ?? ""}
          setName={split.split}
          items={viewing.items}
          index={viewing.index}
          onIndex={(i) => {
            setViewing({ ...viewing, index: i });
            if (i >= shown) setShown(i + PAGE);
          }}
          decisions={decisions}
          good={report.good}
          onClose={() => setViewing(null)}
        />
      )}
    </div>
  );
}

/** Categories as a compact table, with a stacked bar; rows filter the samples. */
function CategoryTable({ split, selected, onSelect }: {
  split: LearningSplit;
  selected: LearningCategory | null;
  onSelect: (c: LearningCategory | null) => void;
}) {
  const total = split.images.length || 1;
  const present = CATEGORIES.filter((c) => (split.counts[c.id] ?? 0) > 0);
  return (
    <div className="panel-card category-panel">
      <div className="category-bar" role="img" aria-label={present.map((c) => `${c.label}: ${split.counts[c.id]}`).join(", ")}>
        {present.map((c) => (
          <span
            key={c.id}
            className={`category-segment${selected !== null && selected !== c.id ? " dim" : ""}`}
            style={{ flexGrow: split.counts[c.id] ?? 0, background: c.color }}
            title={`${c.label}: ${formatNumber(split.counts[c.id] ?? 0)}`}
          />
        ))}
      </div>
      <table className="category-table">
        <tbody>
          {CATEGORIES.map((c) => {
            const count = split.counts[c.id] ?? 0;
            return (
              <tr
                key={c.id}
                className={`${selected === c.id ? "on" : ""}${count ? "" : " zero"}`}
                onClick={() => count && onSelect(selected === c.id ? null : c.id)}
                tabIndex={count ? 0 : -1}
                onKeyDown={(e) => (e.key === "Enter" || e.key === " ") && count && onSelect(selected === c.id ? null : c.id)}
                aria-pressed={selected === c.id}
              >
                <td><span className="swatch" style={{ background: c.color }} />{c.label}</td>
                <td className="num">{formatNumber(count)}</td>
                <td className="num faint">{count ? `${((count / total) * 100).toFixed(1)}%` : ""}</td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

/** Share of samples learned for good by each epoch. */
function LearnedByEpoch({ split }: { split: LearningSplit }) {
  const [at, setAt] = useState<number | null>(null);
  const epochs = split.epochs;
  if (epochs.length < 2) return null;
  const total = split.images.filter((i) => i.category !== "empty").length || 1;
  const values = epochs.map((e) => split.images.filter((i) => i.learned_epoch !== null && i.learned_epoch <= e && i.category !== "forgotten").length);
  // The axis follows the data: a weak run's curve stays readable instead of hugging zero.
  const top = Math.min(1, Math.max(0.1, Math.ceil(((Math.max(...values) / total) * 1.15) * 10) / 10));
  const W = 640, H = 168, L = 40, R = 12, T = 12, B = 24;
  const x = (i: number) => L + (i / (epochs.length - 1)) * (W - L - R);
  const y = (v: number) => T + (1 - v / total / top) * (H - T - B);
  const path = values.map((v, i) => `${i ? "L" : "M"}${x(i).toFixed(1)},${y(v).toFixed(1)}`).join("");
  const area = `${path}L${x(epochs.length - 1).toFixed(1)},${y(0)}L${x(0)},${y(0)}Z`;

  return (
    <figure className="panel-card learned-by-epoch">
      <figcaption>
        <span className="strong">Learned by epoch</span>
        <span className="faint small">{at !== null ? `Epoch ${epochs[at]! + 1}: ${formatNumber(values[at]!)} of ${formatNumber(total)} (${((values[at]! / total) * 100).toFixed(1)}%)` : `Share of ${formatNumber(total)} non-empty samples, axis 0–${Math.round(top * 100)}%`}</span>
      </figcaption>
      <svg
        viewBox={`0 0 ${W} ${H}`}
        preserveAspectRatio="none"
        role="img"
        aria-label={`Learned by epoch: ${values.map((v, i) => `epoch ${epochs[i]! + 1} ${v}`).join(", ")}`}
        onMouseLeave={() => setAt(null)}
        onMouseMove={(event) => {
          const box = event.currentTarget.getBoundingClientRect();
          const px = ((event.clientX - box.left) / box.width) * W;
          setAt(Math.max(0, Math.min(epochs.length - 1, Math.round(((px - L) / (W - L - R)) * (epochs.length - 1)))));
        }}
      >
        {[0, 0.5, 1].map((t) => (
          <line key={t} className="chart-grid" x1={L} x2={W - R} y1={y(t * top * total)} y2={y(t * top * total)} vectorEffect="non-scaling-stroke" />
        ))}
        <path d={area} className="learned-area" />
        <path d={path} className="learned-line" vectorEffect="non-scaling-stroke" />
        {at !== null && <line className="chart-crosshair" x1={x(at)} x2={x(at)} y1={T} y2={H - B} vectorEffect="non-scaling-stroke" />}
      </svg>
      <div className="learned-axis faint small" style={{ paddingLeft: `${(L / W) * 100}%`, paddingRight: `${(R / W) * 100}%` }}>
        <span>Epoch {epochs[0]! + 1}</span>
        <span>Epoch {epochs[epochs.length - 1]! + 1}</span>
      </div>
    </figure>
  );
}

function Sparkline({ scores, good }: { scores: (number | null)[]; good: number }) {
  const W = 120, H = 22;
  const n = Math.max(scores.length - 1, 1);
  const points = scores
    .map((s, i) => (s === null ? null : `${((i / n) * W).toFixed(1)},${(H - 2 - s * (H - 4)).toFixed(1)}`))
    .filter(Boolean);
  const goodY = H - 2 - good * (H - 4);
  return (
    <svg className="sparkline" viewBox={`0 0 ${W} ${H}`} preserveAspectRatio="none" aria-hidden="true">
      <line x1={0} x2={W} y1={goodY} y2={goodY} className="sparkline-good" />
      <polyline points={points.join(" ")} className="sparkline-line" />
    </svg>
  );
}

function SampleCard({ image, split, project, good, decision, onOpen }: {
  image: LearnedImage;
  split: LearningSplit;
  project: string;
  good: number;
  decision: Decision | undefined;
  onOpen: () => void;
}) {
  const info = INFO.get(image.category)!;
  const file = image.image?.split("/").pop() ?? `image ${image.example_id}`;
  const when = image.learned_epoch !== null ? `Learned epoch ${epochOf(image.learned_epoch)}` : `Best ${image.best_score.toFixed(2)}`;
  return (
    <button className={`sample-card${decision ? ` decided-${decision}` : ""}`} onClick={onOpen} title={file}>
      <span className="sample-thumb">
        {image.image ? <img loading="lazy" src={api.mediaUrl(image.image, 320, project, split.dataset ?? undefined)} alt="" /> : <Icon name="file" />}
        <span className="sample-category" style={{ borderLeftColor: info.color }}>{info.label}</span>
        {decision && <span className={`decision-tag tag-${decision}`}>{DECISION_LABEL[decision]}</span>}
      </span>
      <span className="sample-meta">
        <span className="sample-f1"><span className="faint">F1</span> {image.final_score.toFixed(2)}</span>
        <Sparkline scores={image.scores} good={good} />
      </span>
      <span className="sample-foot">
        <span>{when}</span>
        <span>{plural(image.objects, "object")}</span>
      </span>
    </button>
  );
}
