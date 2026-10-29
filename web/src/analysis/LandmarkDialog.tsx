import { useMemo, useState } from "react";
import { Modal } from "../components/Modal";
import { elementFilterKey, filterRows } from "../store/filtering";
import { useStore } from "../store/store";
import { landmarkIndices, summarizeLandmarks } from "./landmarks";

export function LandmarkDialog({ onClose }: { onClose: () => void }) {
  const columns = useStore(s => s.columns);
  const rows = useStore(s => s.rows);
  const filters = useStore(s => s.filters);
  const setFilter = useStore(s => s.setFilter);
  const candidates = columns.filter(c => landmarkIndices(c).length > 0);
  const [columnName, setColumn] = useState(candidates[0]?.name ?? "");
  const [classId, setClassId] = useState("");
  const [scope, setScope] = useState("all");
  const [cutoff, setCutoff] = useState(.5);
  const column = candidates.find(c => c.name === columnName);
  const layouts = column?.pose_categories ?? {};
  const layoutId = classId in layouts ? classId : Object.keys(layouts)[0] ?? "";
  const layout = layouts[layoutId];
  const summaries = useMemo(() => column ? summarizeLandmarks(column, rows,
    scope === "filtered" ? filterRows(rows, Object.values(filters)) : rows.map((_, i) => i),
    scope === "filtered" ? Object.values(filters) : [], layoutId ? Number(layoutId) : undefined,
  ) : [], [column, rows, filters, scope, layoutId]);
  const showLow = (index: number, metric: "oks" | "confidence") => {
    const key = elementFilterKey(columnName, `keypoint_${index}_${metric}`);
    const filter = filters[key];
    if (filter?.kind !== "numeric") return;
    // Inverting the upper interval keeps the filter active even if all scores are low.
    // Numeric filters always exclude unavailable values, including when inverted.
    setFilter(key, { range: [cutoff, Math.max(cutoff, filter.bounds[1])], inverted: true });
    if (layoutId) {
      const labelKey = elementFilterKey(columnName, "label");
      const labels = filters[labelKey];
      if (labels?.kind === "categorical") setFilter(labelKey, { excluded: labels.values.filter(v => Number(v) !== Number(layoutId)), inverted: false });
    }
    onClose();
  };
  const number = (value: number | null) => value === null ? "—" : value.toFixed(3);
  return <Modal title="Landmark analysis" onClose={onClose} width={800} footer={<>
    <span className="spacer" /><button onClick={onClose}>Close</button>
  </>}>
    <p className="muted">Compare accuracy and confidence for each keypoint slot in the dataset's order (starting at 0). OKS measures location agreement; 1 is a perfect match. Unmatched or unlabelled keypoints have no OKS and are excluded from its mean.</p>
    <label className="field"><span>Predictions</span><select value={columnName} onChange={e => setColumn(e.target.value)}>{candidates.map(c => <option key={c.name}>{c.name}</option>)}</select></label>
    {Object.keys(layouts).length > 0 && <label className="field"><span>Class layout</span><select value={layoutId} onChange={e => setClassId(e.target.value)}>{Object.entries(layouts).map(([id, item]) => <option key={id} value={id}>{item.name}</option>)}</select></label>}
    {layout?.ambiguous && <p className="notice">This class has different landmark layouts in the source datasets. Names are unavailable; inspect each source separately.</p>}
    <label className="field"><span>Summarize</span><select value={scope} onChange={e => setScope(e.target.value)}><option value="all">All loaded observations</option><option value="filtered">Current filtered view</option></select></label>
    <label className="field"><span>Low-score threshold</span><input type="number" min={0} max={1} step={.05} value={cutoff} onChange={e => setCutoff(Number(e.target.value))} /></label>
    <p className="muted">Show below applies an object filter and retains your other filters. Unavailable values are excluded. Repeated epochs count as separate observations.</p>
    <table className="grid" aria-label="Landmark metrics"><thead><tr>
      <th>Keypoint</th><th>Scored</th><th>Unavailable</th><th>Mean OKS</th><th>Mean confidence</th><th>Inspect</th>
    </tr></thead><tbody>{summaries.map(summary => <tr key={summary.index}>
      <td>{layout?.names[summary.index] ? `${layout.names[summary.index]} (Keypoint ${summary.index})` : `Keypoint ${summary.index}`}</td><td>{summary.scored}</td><td>{summary.unavailable}</td>
      <td>{number(summary.meanOks)}</td><td>{number(summary.meanConfidence)}</td>
      <td><button disabled={!summary.scored || !Number.isFinite(cutoff) || cutoff < 0 || cutoff > 1}
        aria-label={`Show keypoint ${summary.index} OKS below threshold`} onClick={() => showLow(summary.index, "oks")}>OKS below {cutoff}</button>{" "}
      <button disabled={!summary.confidenceCount || !Number.isFinite(cutoff) || cutoff < 0 || cutoff > 1}
        aria-label={`Show keypoint ${summary.index} confidence below threshold`} onClick={() => showLow(summary.index, "confidence")}>Confidence below {cutoff}</button></td>
    </tr>)}</tbody></table>
  </Modal>;
}
