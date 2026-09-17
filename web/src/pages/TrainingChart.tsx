/** How a score changed over the rounds of training, one line per run, updating live. */

import { useLayoutEffect, useMemo, useRef, useState } from "react";
import type { ObjectEntry } from "../api/types";
import { CATEGORICAL, OTHER, css } from "../charts/colors";

const METRICS: { key: string; label: string; higherIsBetter: boolean }[] = [
  { key: "map50", label: "mAP50", higherIsBetter: true },
  { key: "map50_95", label: "mAP50-95", higherIsBetter: true },
  { key: "recall", label: "Recall", higherIsBetter: true },
  { key: "precision", label: "Precision", higherIsBetter: true },
  { key: "val_box_loss", label: "Box loss (val)", higherIsBetter: false },
  { key: "train_box_loss", label: "Box loss (train)", higherIsBetter: false },
];

const WIDE_PAD = { top: 16, right: 150, bottom: 34, left: 48 };

/** ``compact`` drops the metric picker and legend (lines are labelled directly) for a dashboard card. */
export function TrainingChart({ runs, compact = false, metricKey: fixedMetric }: { runs: ObjectEntry[]; compact?: boolean; metricKey?: string }) {
  const H = compact ? 196 : 240;
  const PAD = compact ? { top: 12, right: 118, bottom: 30, left: 40 } : WIDE_PAD;
  // Drawn at the container's pixel width, so text stays at its set size on any screen.
  const plot = useRef<HTMLDivElement>(null);
  const [W, setW] = useState(760);
  useLayoutEffect(() => {
    const element = plot.current;
    if (!element) return;
    const observer = new ResizeObserver(([entry]) => entry && setW(Math.max(320, entry.contentRect.width)));
    observer.observe(element);
    return () => observer.disconnect();
  }, []);
  const available = METRICS.filter((m) => runs.some((r) => r.history?.some((h) => typeof h[m.key] === "number")));
  const [metricKey, setMetricKey] = useState(fixedMetric ?? available[0]?.key ?? "map50");
  const [hover, setHover] = useState<number | null>(null);
  const svg = useRef<SVGSVGElement>(null);
  const metric = available.find((m) => m.key === metricKey) ?? available[0];

  // Colour follows the run, in creation order, so a new run never repaints old ones.
  const ordered = useMemo(() => [...runs].sort((a, b) => a.created.localeCompare(b.created)), [runs]);
  const series = ordered
    .map((run, i) => ({
      run,
      color: css(CATEGORICAL[i] ?? OTHER),
      points: (run.history ?? [])
        .map((h, j) => ({ epoch: typeof h.epoch === "number" ? h.epoch + 1 : j + 1, value: metric ? h[metric.key] : undefined }))
        .filter((p): p is { epoch: number; value: number } => typeof p.value === "number"),
    }))
    .filter((s) => s.points.length > 0);

  if (!metric || series.length === 0) return null;

  const maxEpoch = Math.max(...series.flatMap((s) => s.points.map((p) => p.epoch)), ...runs.filter((r) => r.status === "running").map((r) => Number(r.parameters?.epochs) || 0));
  const values = series.flatMap((s) => s.points.map((p) => p.value));
  let lo = Math.min(...values);
  let hi = Math.max(...values);
  if (metric.higherIsBetter && hi <= 1) {
    lo = 0;
    hi = Math.max(hi, 0.05);
  }
  if (hi === lo) hi = lo + 1;
  const x = (epoch: number) => PAD.left + ((epoch - 1) / Math.max(1, maxEpoch - 1)) * (W - PAD.left - PAD.right);
  const y = (value: number) => PAD.top + (1 - (value - lo) / (hi - lo)) * (H - PAD.top - PAD.bottom);
  const ticks = Array.from({ length: 5 }, (_, i) => lo + ((hi - lo) * i) / 4);
  const epochTicks = [...new Set([1, Math.ceil(maxEpoch / 2), maxEpoch])].filter((e) => e >= 1);

  const onMove = (event: React.PointerEvent<SVGSVGElement>) => {
    const box = svg.current?.getBoundingClientRect();
    if (!box) return;
    const px = ((event.clientX - box.left) / box.width) * W;
    const epoch = Math.round(1 + ((px - PAD.left) / (W - PAD.left - PAD.right)) * Math.max(1, maxEpoch - 1));
    setHover(Math.min(maxEpoch, Math.max(1, epoch)));
  };

  return (
    <section className={`panel-card training-chart${compact ? " compact" : ""}`}>
      {compact ? (
        <div className="lab-card-head"><h3>{metric.label}</h3><span>by epoch</span></div>
      ) : (
      <div className="training-chart-head">
        <label className="select-wrap">
          <select value={metric.key} onChange={(e) => setMetricKey(e.target.value)} aria-label="Score to show">
            {available.map((m) => <option key={m.key} value={m.key}>{m.label}</option>)}
          </select>
        </label>
        <span className="muted small">{metric.higherIsBetter ? "Higher is better" : "Lower is better"}, by epoch</span>
        <ul className="chart-legend" aria-label="Runs">
          {series.map((s) => (
            <li key={s.run.url}>
              <span className="legend-line" style={{ background: s.color }} />
              {s.run.name}
            </li>
          ))}
        </ul>
      </div>
      )}
      <div className="training-chart-plot" ref={plot}>
        <svg
          ref={svg}
          viewBox={`0 0 ${W} ${H}`}
          role="img"
          aria-label={`${metric.label} by epoch`}
          style={{ height: H }}
          onPointerMove={onMove}
          onPointerLeave={() => setHover(null)}
        >
          {ticks.map((t) => (
            <g key={t}>
              <line x1={PAD.left} x2={W - PAD.right} y1={y(t)} y2={y(t)} className="chart-grid" />
              <text x={PAD.left - 8} y={y(t) + 4} className="chart-tick" textAnchor="end">{t.toFixed(hi - lo < 0.2 ? 3 : 2)}</text>
            </g>
          ))}
          {epochTicks.map((e) => (
            <text key={e} x={x(e)} y={H - PAD.bottom + 18} className="chart-tick" textAnchor="middle">{e}</text>
          ))}
          <text x={(PAD.left + W - PAD.right) / 2} y={H - 4} className="chart-axis-name" textAnchor="middle">Epoch</text>
          {hover !== null && <line x1={x(hover)} x2={x(hover)} y1={PAD.top} y2={H - PAD.bottom} className="chart-crosshair" />}
          {series.map((s) => {
            const last = s.points[s.points.length - 1]!;
            return (
              <g key={s.run.url}>
                <polyline
                  fill="none" stroke={s.color} strokeWidth={2} strokeLinejoin="round" strokeLinecap="round"
                  points={s.points.map((p) => `${x(p.epoch)},${y(p.value)}`).join(" ")}
                />
                {s.points.length === 1 && <circle cx={x(last.epoch)} cy={y(last.value)} r={4} fill={s.color} />}
                <circle cx={x(last.epoch)} cy={y(last.value)} r={4} fill={s.color} stroke="var(--panel)" strokeWidth={2} />
                <text x={x(last.epoch) + 8} y={y(last.value) + 4} className="chart-direct-label">
                  {s.run.name} {last.value.toFixed(3)}
                </text>
              </g>
            );
          })}
        </svg>
        {hover !== null && (
          <div className="chart-readout" style={{ left: `${(x(hover) / W) * 100}%` }}>
            <div className="muted small">Epoch {hover}</div>
            {series.map((s) => {
              const point = s.points.find((p) => p.epoch === hover);
              return (
                <div key={s.run.url} className="readout-row">
                  <span className="legend-line" style={{ background: s.color }} />
                  <strong>{point ? point.value.toFixed(3) : "—"}</strong>
                  <span className="muted">{s.run.name}</span>
                </div>
              );
            })}
          </div>
        )}
      </div>
    </section>
  );
}
