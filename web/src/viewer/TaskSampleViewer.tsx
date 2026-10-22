import { useEffect, useState } from "react";
import { api } from "../api/client";
import { Modal } from "../components/Modal";
import { MaskOverlay } from "../images/MaskOverlay";

interface Mask { label: number; segmentation: string }
export interface TaskRounds {
  task: "classify" | "semantic"; metric: "accuracy" | "mean_iou"; image: string;
  width: number | null; height: number | null; labels: Record<string, string>; label: number | null;
  truth: Mask[]; rounds: { epoch: number; score: number; predicted: number | null; confidence: number | null; masks: Mask[] }[];
}

export function TaskSampleViewer({ project, dataset, run, table, example, onClose }: {
  project: string; dataset: string; run: string; table: string; example: number; onClose: () => void;
}) {
  const [data, setData] = useState<TaskRounds | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [at, setAt] = useState(0);
  useEffect(() => {
    let alive = true;
    api.taskImageRounds(run, table, example).then(result => { if (alive) { setData(result); setAt(result.rounds.length - 1); } }).catch((e: Error) => { if (alive) setError(e.message); });
    return () => { alive = false; };
  }, [run, table, example]);
  const round = data?.rounds[at];
  const colors = ["#14b8a6", "#f59e0b", "#ec4899", "#6366f1"];
  const color = (label: number) => colors[Object.keys(data?.labels ?? {}).indexOf(String(label)) % colors.length] ?? colors[0]!;
  const region = (mask: Mask, index: number) => {
    const value = JSON.parse(mask.segmentation) as unknown;
    return Array.isArray(value)
      ? <g key={index} fill={color(mask.label)} opacity={.4}>
        {(value as number[][]).map((points, polygon) => <polygon key={polygon} points={points.join(" ")} />)}
      </g>
      : <MaskOverlay key={`${at}:${index}`} value={value} at={index} selected color={color(mask.label)} />;
  };
  const overlay = (masks: Mask[]) => data && <svg viewBox={`0 0 ${data.width} ${data.height}`} style={{ width: "100%", maxHeight: 420 }}>
    <image href={api.mediaUrl(data.image, undefined, project, dataset)} width={data.width!} height={data.height!} />
    {masks.map(region)}
  </svg>;
  return <Modal title="Sample across epochs" width={900} onClose={onClose} footer={<button onClick={onClose}>Close</button>}>
    {error && <p className="form-error">{error}</p>}
    {data && round && <>
      <label className="field"><span>Epoch</span><select value={at} onChange={e => setAt(Number(e.target.value))}>{data.rounds.map((r, i) => <option key={r.epoch} value={i}>{r.epoch + 1}</option>)}</select></label>
      <p>{data.metric === "accuracy" ? "Accuracy" : "Image mean IoU"}: {round.score.toFixed(3)}</p>
      {data.task === "classify" ? <>
        <p>Label: {data.labels[String(data.label)]} · Prediction: {data.labels[String(round.predicted)]} · Confidence: {round.confidence?.toFixed(3) ?? "—"}</p>
        <img src={api.mediaUrl(data.image, 900, project, dataset)} alt="Selected sample" style={{ maxWidth: "100%", maxHeight: 500 }} />
      </> : <>
        <div className="field-pair"><div><p>Ground truth</p>{overlay(data.truth)}</div><div><p>Prediction</p>{overlay(round.masks)}</div></div>
        <p>{Object.entries(data.labels).map(([id, name]) => <span key={id} style={{ color: color(Number(id)), marginRight: 16 }}>{name}</span>)}</p>
      </>}
    </>}
  </Modal>;
}
