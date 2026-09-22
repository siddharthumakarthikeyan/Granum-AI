/** One run read for what it gets wrong, rather than for how good it is.
 *
 * Three readings of the same stored predictions, on one page because they answer one
 * question between them: the confusion matrix says which class is mistaken for which, the
 * per-class table says what that costs, and the threshold sweep says whether the operating
 * point the model ships at is the one it should.
 *
 * Every cell of the matrix is a button, and picking one shows the objects behind it, cropped
 * to the box: a matrix nobody can look through is a decoration. The label is drawn solid and
 * the model's box dashed over it, which is the whole disagreement in one picture.
 */

import { useCallback, useEffect, useMemo, useState } from "react";
import { api } from "../api/client";
import type { EvaluationExample, EvaluationReport } from "../api/types";
import { EmptyState, Icon, PageHeader, formatNumber, plural } from "../components/ui";
import { navigate, routeHref } from "../router";
import { useStore } from "../store/store";

/** What a cell stands for: a pair of classes, a label nothing found, or a box over nothing. */
interface Cell {
  truth: number | null;
  predicted: number | null;
  count: number;
}

const percent = (value: number) => `${(value * 100).toFixed(1)}%`;

export function EvaluationPage({ project, url }: { project: string; url?: string }) {
  const runs = useStore((s) => s.runs);
  const scored = useMemo(
    () => [...runs].filter((r) => r.parameters?.kind !== "screening" && r.status !== "running")
      .sort((a, b) => b.created.localeCompare(a.created)),
    [runs],
  );
  const runUrl = url ?? scored[0]?.url;
  const run = runs.find((r) => r.url === runUrl);

  const [report, setReport] = useState<EvaluationReport | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [split, setSplit] = useState<string | null>(null);
  const [confidence, setConfidence] = useState(0.25);
  const [cell, setCell] = useState<Cell | null>(null);
  const [examples, setExamples] = useState<EvaluationExample[] | null>(null);

  const load = useCallback(async () => {
    if (!runUrl) return;
    try {
      const next = await api.evaluation(runUrl, split ?? undefined, confidence);
      setReport(next);
      setError(null);
      if (split === null && next.split) setSplit(next.split);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }, [runUrl, split, confidence]);

  useEffect(() => {
    setReport(null);
    setCell(null);
    void load();
  }, [load]);

  useEffect(() => {
    if (!cell || !runUrl) {
      setExamples(null);
      return;
    }
    let alive = true;
    setExamples(null);
    api.evaluationExamples({
      url: runUrl,
      split: split ?? undefined,
      confidence,
      ...(cell.truth === null ? {} : { truth: cell.truth }),
      ...(cell.predicted === null ? {} : { predicted: cell.predicted }),
    })
      .then((next) => alive && setExamples(next.examples))
      .catch(() => alive && setExamples([]));
    return () => {
      alive = false;
    };
  }, [cell, runUrl, split, confidence]);

  const classes = report?.classes ?? {};
  const name = (label: number | null) => (label === null ? "—" : classes[String(label)] ?? `class ${label}`);

  const header = (
    <PageHeader
      title="Evaluation"
      context={run?.name}
      subtitle={report?.headline
        ? `${plural(report.images ?? 0, "image")} of ${report.set ?? "a set"} at confidence ${percent(confidence)} · ${formatNumber(report.headline.labels)} labels`
        : "What a run gets wrong, class by class"}
      actions={scored.length > 1 ? (
        <label className="inline-field small">
          <span className="muted">Run</span>
          <select value={runUrl} onChange={(e) => { setSplit(null); navigate({ name: "evaluation", project, url: e.target.value }); }}>
            {scored.map((r) => <option key={r.url} value={r.url}>{r.name}</option>)}
          </select>
        </label>
      ) : undefined}
    />
  );

  if (!runUrl) {
    return (
      <div className="page">
        {header}
        <EmptyState title="No run to read yet" action={<a className="button" href={routeHref({ name: "runs", project })}>Go to runs</a>}>
          <p>A run that stored the model's boxes can be read here class by class.</p>
        </EmptyState>
      </div>
    );
  }
  if (error) return <div className="page">{header}<p className="form-error">{error}</p></div>;
  if (report && !report.stores_boxes) {
    return (
      <div className="page">
        {header}
        <EmptyState title="This run did not save the model's boxes">
          <p>A confusion matrix is built from the boxes themselves. Train again with “Record per-sample metrics and predictions every epoch” on.</p>
        </EmptyState>
      </div>
    );
  }

  return (
    <div className="page evaluation-page">
      {header}
      {!report && <p className="muted"><span className="spinner" /> Reading every prediction</p>}

      {report?.headline && (
        <>
          {report.splits.length > 1 && (
            <div className="tabs" role="tablist" aria-label="Set">
              {report.splits.map((s) => (
                <button key={s} role="tab" aria-selected={s === report.split} className={`tab${s === report.split ? " on" : ""}`}
                  onClick={() => { setCell(null); setSplit(s); }}>
                  {s}
                </button>
              ))}
            </div>
          )}

          <div className="panel eval-headline">
            <Figure label="mAP50" value={report.headline.map50 === null ? "—" : report.headline.map50.toFixed(3)}
              note="over the whole ranking, whatever the threshold" />
            <Figure label="Precision" value={percent(report.headline.precision)} note={`${formatNumber(report.headline.fp)} boxes over nothing`} />
            <Figure label="Recall" value={percent(report.headline.recall)} note={`${formatNumber(report.headline.fn)} labels not found`} />
            <Figure label="F1" value={percent(report.headline.f1)} note={`${formatNumber(report.headline.tp)} found of ${formatNumber(report.headline.labels)}`} />
            <span className="spacer" />
            <Threshold
              value={confidence}
              best={report.best_confidence ?? null}
              onChange={(next) => { setCell(null); setConfidence(next); }}
            />
          </div>

          <section className="eval-section">
            <h3 className="card-title">What it mistakes for what</h3>
            <p className="muted small">
              Rows are what the labels say, columns what the model says, matched by overlap
              alone so a box in the right place with the wrong class lands in a cell rather
              than counting twice as two separate mistakes. Pick a cell to see the objects.
            </p>
            <Matrix report={report} chosen={cell} onPick={setCell} />
          </section>

          {cell && (
            <section className="eval-section">
              <h3 className="card-title">
                {cell.truth !== null && cell.predicted !== null
                  ? `Labelled ${name(cell.truth)}, predicted ${name(cell.predicted)}`
                  : cell.predicted === null
                    ? `Labelled ${name(cell.truth)}, nothing predicted`
                    : `Predicted ${name(cell.predicted)} over nothing labelled`}
                <span className="muted"> · {formatNumber(cell.count)}</span>
                <button className="button subtle small eval-close" onClick={() => setCell(null)}><Icon name="close" size={13} />Close</button>
              </h3>
              <Examples examples={examples} report={report} project={project} />
            </section>
          )}

          <section className="eval-section">
            <h3 className="card-title">Every class</h3>
            <ClassTable report={report} onPick={(label) => setCell({ truth: label, predicted: null, count: report.confusion?.missed[String(label)] ?? 0 })} />
          </section>

          <section className="eval-section">
            <h3 className="card-title">Precision and recall as the threshold moves</h3>
            <Curve report={report} confidence={confidence} onPick={(next) => { setCell(null); setConfidence(next); }} />
          </section>
        </>
      )}
    </div>
  );
}

function Figure({ label, value, note }: { label: string; value: string; note: string }) {
  return (
    <div className="eval-figure">
      <span className="eval-figure-value tabular">{value}</span>
      <span className="muted small">{label}</span>
      <span className="faint small">{note}</span>
    </div>
  );
}

/** The operating point, and where the sweep says it should be. */
function Threshold({ value, best, onChange }: { value: number; best: number | null; onChange: (next: number) => void }) {
  return (
    <div className="eval-threshold">
      <label className="field">
        <span className="field-label">Confidence {Math.round(value * 100)}%</span>
        <input type="range" min={5} max={95} step={5} value={Math.round(value * 100)}
          onChange={(e) => onChange(Number(e.target.value) / 100)} />
      </label>
      {best !== null && Math.abs(best - value) > 0.001 && (
        <button className="button subtle small" onClick={() => onChange(best)} title="Where the pooled F1 peaks on this set">
          Best is {Math.round(best * 100)}%
        </button>
      )}
    </div>
  );
}

/** The matrix itself: labelled classes down, predicted across, with the two edges. */
function Matrix({ report, chosen, onPick }: {
  report: EvaluationReport;
  chosen: Cell | null;
  onPick: (cell: Cell | null) => void;
}) {
  const confusion = report.confusion!;
  const classes = report.classes ?? {};
  const rows = (report.per_class ?? []).filter((row) => row.support > 0).map((row) => row.label);
  const columns = useMemo(() => {
    const seen = new Set<number>();
    for (const key of Object.keys(confusion.cells)) seen.add(Number(key.split(":")[1]));
    for (const key of Object.keys(confusion.background)) seen.add(Number(key));
    return [...seen].sort((a, b) => a - b);
  }, [confusion]);
  const at = (truth: number, predicted: number) => confusion.cells[`${truth}:${predicted}`] ?? 0;
  const top = Math.max(1, ...Object.values(confusion.cells));
  const name = (label: number) => classes[String(label)] ?? `class ${label}`;
  const picked = (truth: number | null, predicted: number | null) =>
    chosen?.truth === truth && chosen?.predicted === predicted;

  if (rows.length === 0) return <p className="muted">No labels in this set.</p>;

  return (
    <div className="data-table-wrap">
      <table className="data-table matrix-table">
        <thead>
          <tr>
            <th className="matrix-corner">labelled ＼ predicted</th>
            {columns.map((column) => <th key={column} className="num">{name(column)}</th>)}
            <th className="num matrix-edge" title="Labels no confident box covered">not found</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={row}>
              <th className="matrix-head">{name(row)}</th>
              {columns.map((column) => {
                const count = at(row, column);
                const right = row === column;
                return (
                  <td key={column} className="num">
                    {count > 0 ? (
                      <button
                        className={`matrix-cell${right ? " right" : ""}${picked(row, column) ? " on" : ""}`}
                        style={{ opacity: right ? 1 : 0.35 + 0.65 * (count / top) }}
                        onClick={() => onPick(picked(row, column) ? null : { truth: row, predicted: column, count })}
                        title={`${count} ${name(row)} labels the model called ${name(column)}`}
                      >
                        {formatNumber(count)}
                      </button>
                    ) : <span className="faint">·</span>}
                  </td>
                );
              })}
              <td className="num matrix-edge">
                {(() => {
                  const count = confusion.missed[String(row)] ?? 0;
                  return count > 0 ? (
                    <button className={`matrix-cell missed${picked(row, null) ? " on" : ""}`}
                      onClick={() => onPick(picked(row, null) ? null : { truth: row, predicted: null, count })}
                      title={`${count} ${name(row)} labels nothing covered`}>
                      {formatNumber(count)}
                    </button>
                  ) : <span className="faint">·</span>;
                })()}
              </td>
            </tr>
          ))}
          <tr>
            <th className="matrix-head matrix-edge" title="Confident boxes with no label under them">over nothing</th>
            {columns.map((column) => {
              const count = confusion.background[String(column)] ?? 0;
              return (
                <td key={column} className="num matrix-edge">
                  {count > 0 ? (
                    <button className={`matrix-cell spurious${picked(null, column) ? " on" : ""}`}
                      onClick={() => onPick(picked(null, column) ? null : { truth: null, predicted: column, count })}
                      title={`${count} ${name(column)} boxes with nothing labelled under them`}>
                      {formatNumber(count)}
                    </button>
                  ) : <span className="faint">·</span>}
                </td>
              );
            })}
            <td className="num matrix-edge"><span className="faint">·</span></td>
          </tr>
        </tbody>
      </table>
    </div>
  );
}

/** The objects behind a cell, cropped to the box with a little of the picture around it. */
function Examples({ examples, report, project }: {
  examples: EvaluationExample[] | null;
  report: EvaluationReport;
  project: string;
}) {
  if (examples === null) return <p className="muted"><span className="spinner" /> Finding them</p>;
  if (examples.length === 0) return <p className="muted">Nothing to show for this cell.</p>;
  return (
    <div className="eval-examples">
      {examples.map((example, i) => (
        <a
          key={`${example.image}-${i}`}
          className="eval-example"
          href={routeHref({ name: "images", project, dataset: report.dataset ?? undefined, open: example.image ?? undefined })}
          title={`${example.image ?? ""}${example.confidence !== null ? `\nconfidence ${example.confidence.toFixed(2)}` : ""}`}
        >
          <Crop example={example} project={project} dataset={report.dataset ?? null} />
          <span className="eval-example-foot">
            {example.confidence !== null ? `${Math.round(example.confidence * 100)}%` : "not found"}
          </span>
        </a>
      ))}
    </div>
  );
}

function Crop({ example, project, dataset }: { example: EvaluationExample; project: string; dataset: string | null }) {
  const [x0, y0, x1, y1] = example.box;
  const width = Math.max(x1 - x0, 1);
  const height = Math.max(y1 - y0, 1);
  const size = Math.max(width, height) * 3;
  const view = [
    Math.max(0, Math.min((x0 + x1) / 2 - size / 2, Math.max(0, example.width - size))),
    Math.max(0, Math.min((y0 + y1) / 2 - size / 2, Math.max(0, example.height - size))),
    size, size,
  ].join(" ");
  const stroke = size / 90;
  return (
    <svg viewBox={view} preserveAspectRatio="xMidYMid slice" aria-hidden="true">
      {example.image && (
        <image href={api.mediaUrl(example.image, 640, project, dataset ?? undefined)}
          x={0} y={0} width={example.width} height={example.height} preserveAspectRatio="none" />
      )}
      {example.label !== null && (
        <rect x={x0} y={y0} width={width} height={height} fill="none" stroke="var(--pass)" strokeWidth={stroke} />
      )}
      {example.predicted_box && (
        <rect x={example.predicted_box[0]} y={example.predicted_box[1]}
          width={Math.max(example.predicted_box[2] - example.predicted_box[0], 1)}
          height={Math.max(example.predicted_box[3] - example.predicted_box[1], 1)}
          fill="none" stroke="var(--accent)" strokeWidth={stroke} strokeDasharray={`${stroke * 3} ${stroke * 2}`} />
      )}
      {example.label === null && (
        <rect x={x0} y={y0} width={width} height={height} fill="none" stroke="var(--accent)"
          strokeWidth={stroke} strokeDasharray={`${stroke * 3} ${stroke * 2}`} />
      )}
    </svg>
  );
}

function ClassTable({ report, onPick }: { report: EvaluationReport; onPick: (label: number) => void }) {
  const rows = report.per_class ?? [];
  if (rows.length === 0) return <p className="muted">No classes in this set.</p>;
  return (
    <div className="data-table-wrap">
      <table className="data-table">
        <thead>
          <tr>
            <th>Class</th>
            <th className="num" title="Labels of this class in the set">Support</th>
            <th className="num">Found</th>
            <th className="num" title="Boxes of this class with no label of it under them">Over nothing</th>
            <th className="num" title="Labels of this class nothing found">Not found</th>
            <th className="num">Precision</th>
            <th className="num">Recall</th>
            <th className="num">F1</th>
            <th className="num" title="Average precision over the whole ranking">AP</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={row.label} className="clickable" onClick={() => onPick(row.label)}>
              <td><span className="cell-title">{row.name}</span></td>
              <td className="num tabular">{formatNumber(row.support)}</td>
              <td className="num tabular">{formatNumber(row.tp)}</td>
              <td className="num tabular">{formatNumber(row.fp)}</td>
              <td className="num tabular">{formatNumber(row.fn)}</td>
              <td className="num tabular">{percent(row.precision)}</td>
              <td className="num tabular">{percent(row.recall)}</td>
              <td className="num tabular">{percent(row.f1)}</td>
              <td className="num tabular">{row.ap === null ? "—" : row.ap.toFixed(3)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

/** The sweep, drawn as two lines against the threshold, with the current point marked. */
function Curve({ report, confidence, onPick }: {
  report: EvaluationReport;
  confidence: number;
  onPick: (next: number) => void;
}) {
  const curve = report.curve ?? [];
  if (curve.length === 0) return <p className="muted">Nothing to sweep.</p>;
  const W = 640, H = 200, pad = 28;
  const x = (value: number) => pad + (value - curve[0]!.confidence) / (curve[curve.length - 1]!.confidence - curve[0]!.confidence) * (W - pad * 2);
  const y = (value: number) => H - pad - value * (H - pad * 2);
  const line = (key: "precision" | "recall" | "f1") =>
    curve.map((point, i) => `${i === 0 ? "M" : "L"}${x(point.confidence).toFixed(1)},${y(point[key]).toFixed(1)}`).join(" ");
  const nearest = curve.reduce((best, point) =>
    Math.abs(point.confidence - confidence) < Math.abs(best.confidence - confidence) ? point : best, curve[0]!);
  return (
    <div className="eval-curve">
      <svg viewBox={`0 0 ${W} ${H}`} role="img" aria-label="Precision and recall against confidence">
        <line x1={pad} y1={y(0)} x2={W - pad} y2={y(0)} stroke="var(--border-2)" />
        <line x1={pad} y1={y(0)} x2={pad} y2={y(1)} stroke="var(--border-2)" />
        {[0, 0.5, 1].map((value) => (
          <text key={value} x={pad - 6} y={y(value) + 4} textAnchor="end" className="eval-axis">{value * 100}</text>
        ))}
        {curve.map((point) => (
          <line key={point.confidence} x1={x(point.confidence)} y1={y(0)} x2={x(point.confidence)} y2={y(0) + 4} stroke="var(--border-2)" />
        ))}
        <path d={line("precision")} fill="none" stroke="var(--info)" strokeWidth={2} />
        <path d={line("recall")} fill="none" stroke="var(--warn)" strokeWidth={2} />
        <path d={line("f1")} fill="none" stroke="var(--pass)" strokeWidth={2} strokeDasharray="4 3" />
        <line x1={x(nearest.confidence)} y1={y(0)} x2={x(nearest.confidence)} y2={y(1)} stroke="var(--accent)" strokeWidth={1} />
        {curve.map((point) => (
          <circle key={point.confidence} cx={x(point.confidence)} cy={y(point.f1)} r={7} fill="transparent"
            onClick={() => onPick(point.confidence)} style={{ cursor: "pointer" }}>
            <title>{`${Math.round(point.confidence * 100)}%: precision ${percent(point.precision)}, recall ${percent(point.recall)}, F1 ${percent(point.f1)}`}</title>
          </circle>
        ))}
        <text x={W - pad} y={H - 6} textAnchor="end" className="eval-axis">confidence %</text>
      </svg>
      <div className="eval-legend">
        <span><span className="swatch" style={{ background: "var(--info)" }} />Precision</span>
        <span><span className="swatch" style={{ background: "var(--warn)" }} />Recall</span>
        <span><span className="swatch" style={{ background: "var(--pass)" }} />F1</span>
        <span className="faint small">
          At {Math.round(nearest.confidence * 100)}%: {formatNumber(nearest.tp)} found,
          {" "}{formatNumber(nearest.fp)} over nothing, {formatNumber(nearest.fn)} missed.
        </span>
      </div>
    </div>
  );
}
