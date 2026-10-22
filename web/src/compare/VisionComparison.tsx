import { useEffect, useState } from "react";
import type { ObjectEntry } from "../api/types";
import { api } from "../api/client";
import { PageHeader } from "../components/ui";

export interface VisionReport {
  task: string; metric: string; split: string; shared_splits: string[]; images: number;
  baseline: { name: string; score: number }; candidate: { name: string; score: number };
  delta: number; bootstrap_95: number[]; uncertainty: string; held_out: boolean; recipe_matches: boolean | null;
  outcomes: Record<string, number>;
  rows: { row: number; image: string; baseline: number; candidate: number; delta: number; outcome: string }[];
}

export function VisionComparison({ project, baseline, candidate, split, runs }: {
  project: string; baseline?: string; candidate?: string; split?: string; runs: ObjectEntry[];
}) {
  const [right, setRight] = useState(candidate ?? runs[0]?.url ?? "");
  const [left, setLeft] = useState(baseline ?? runs.find(r => r.url !== right)?.url ?? "");
  const [chosenSplit, setSplit] = useState(split ?? "");
  const [report, setReport] = useState<VisionReport | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [outcome, setOutcome] = useState("all");
  useEffect(() => {
    let alive = true;
    setReport(null); setError(null);
    if (left && right) api.compareVision(left, right, chosenSplit || undefined)
      .then(result => { if (alive) setReport(result); }).catch((e: Error) => { if (alive) setError(e.message); });
    return () => { alive = false; };
  }, [left, right, chosenSplit]);
  const download = () => {
    if (!report) return;
    const url = URL.createObjectURL(new Blob([JSON.stringify(report, null, 2)], { type: "application/json" }));
    const a = document.createElement("a"); a.href = url; a.download = "granum-comparison.json"; a.click(); URL.revokeObjectURL(url);
  };
  const rows = report?.rows.filter(r => outcome === "all" || r.outcome === outcome) ?? [];
  return <div className="page">
    <PageHeader title="Compare runs" context={project} actions={<button className="button" disabled={!report} onClick={download}>Download report</button>} />
    <div className="field-pair">
      <label className="field"><span>Baseline</span><select value={left} onChange={e => setLeft(e.target.value)}>{runs.map(r => <option key={r.url} value={r.url}>{r.name}</option>)}</select></label>
      <label className="field"><span>Candidate</span><select value={right} onChange={e => setRight(e.target.value)}>{runs.map(r => <option key={r.url} value={r.url}>{r.name}</option>)}</select></label>
    </div>
    {error && <p className="form-error">{error}</p>}
    {!left && <p>Train two models to compare their results.</p>}
    {report && <>
      <label className="field"><span>Evaluation split</span><select value={report.split} onChange={e => setSplit(e.target.value)}>{report.shared_splits.map(s => <option key={s}>{s}</option>)}</select></label>
      <p>{report.images.toLocaleString()} matched images on the same frozen labels. {report.held_out ? "Held out from training." : "Held-out status is not verified."} {report.recipe_matches === null ? "Training recipe details are incomplete." : report.recipe_matches ? "Training recipes match." : "Training recipes differ."}</p>
      <table className="data-table" aria-label="Comparison scores"><thead><tr><th>Metric</th><th>{report.baseline.name}</th><th>{report.candidate.name}</th><th>Change</th><th>95% interval</th></tr></thead><tbody><tr>
        <td>{report.metric === "accuracy" ? "Accuracy" : "Dataset mean IoU"}</td><td>{report.baseline.score.toFixed(4)}</td><td>{report.candidate.score.toFixed(4)}</td><td>{report.delta >= 0 ? "+" : ""}{report.delta.toFixed(4)}</td><td>{report.bootstrap_95.map(x => x.toFixed(4)).join(" to ")}</td>
      </tr></tbody></table>
      <p className="muted small">{report.uncertainty}</p>
      <label className="field"><span>Images</span><select value={outcome} onChange={e => setOutcome(e.target.value)}><option value="all">All outcomes</option>{Object.entries(report.outcomes).map(([key, count]) => <option key={key} value={key}>{key}: {count}</option>)}</select></label>
      <table className="data-table" aria-label="Per-image changes"><thead><tr><th>Image</th><th>Baseline</th><th>Candidate</th><th>Outcome</th></tr></thead><tbody>{rows.slice(0, 200).map(row => <tr key={row.row}><td>{row.image.split("/").pop()}</td><td>{row.baseline.toFixed(4)}</td><td>{row.candidate.toFixed(4)}</td><td>{row.outcome}</td></tr>)}</tbody></table>
      {rows.length > 200 && <p>Showing the first 200 images. The downloaded report includes all {rows.length.toLocaleString()}.</p>}
    </>}
  </div>;
}
