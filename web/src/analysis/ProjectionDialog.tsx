import { useEffect, useState } from "react";
import { api } from "../api/client";
import type { Job } from "../api/types";
import { scatterSpec } from "../charts/spec";
import { Modal } from "../components/Modal";
import { navigate } from "../router";
import { useStore } from "../store/store";

interface Result { url: string; name: string; kind: "table" | "run"; project: string; axes: string[] }
export interface SavedProjection {
  id: string; name: string; method: string; dimensions: number; features: number;
  reference_samples: number; column: string; created_at: string;
}

export function ProjectionDialog({ onClose }: { onClose: () => void }) {
  const columns = useStore(s => s.columns);
  const sourceUrl = useStore(s => s.sourceUrl);
  const sourceKind = useStore(s => s.sourceKind);
  const embeddings = columns.filter(c => c.kind === "embedding");
  const [column, setColumn] = useState(embeddings[0]?.name ?? "");
  const [method, setMethod] = useState("pca");
  const [dimensions, setDimensions] = useState(2);
  const [neighbours, setNeighbours] = useState(15);
  const [seed, setSeed] = useState(0);
  const [prefix, setPrefix] = useState("projection");
  const [methods, setMethods] = useState<{ id: string; installed: boolean; install: string | null }[]>([]);
  const [saved, setSaved] = useState<SavedProjection[]>([]);
  const [reducerId, setReducerId] = useState("");
  const [remember, setRemember] = useState(false);
  const [savedName, setSavedName] = useState("");
  const [job, setJob] = useState<Job<Result> | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    let alive = true;
    void Promise.all([
      api.reductionMethods(),
      sourceUrl && sourceKind ? api.savedProjections(sourceUrl, sourceKind) : Promise.resolve([]),
    ]).then(([value, records]) => { if (alive) { setMethods(value); setSaved(records); } })
      .catch(e => { if (alive) setError(String(e)); });
    return () => { alive = false; };
  }, [sourceUrl, sourceKind]);
  useEffect(() => {
    if (!job || job.status !== "running") return;
    let alive = true;
    const timer = window.setTimeout(() => {
      void api.job<Result>(job.id).then(next => { if (alive) { setJob(next); setError(null); } }).catch(e => {
        if (alive) { setError(String(e)); setJob(current => current ? { ...current } : current); }
      });
    }, 1000);
    return () => { alive = false; window.clearTimeout(timer); };
  }, [job]);
  const start = async () => {
    const state = useStore.getState();
    if (!state.sourceUrl || !state.sourceKind) return;
    setBusy(true); setError(null);
    try {
      setJob(await api.projectEmbeddings({ url: state.sourceUrl, kind: state.sourceKind, column, method, dimensions, neighbours, seed, prefix,
        reducer_id: reducerId || undefined, save_reducer_as: !reducerId && remember ? savedName.trim() : undefined }));
    } catch (e) { setError(e instanceof Error ? e.message : String(e)); }
    finally { setBusy(false); }
  };
  const open = async () => {
    const result = job?.result;
    if (!result) return;
    setBusy(true); setError(null);
    try {
      await useStore.getState().refreshProject();
      const store = useStore.getState();
      if (store.undoStack.length) throw new Error("Save your current edits before opening the projection. The projection is already saved.");
      await (result.kind === "run" ? store.openRun(result.url, result.name) : store.openTable(result.url, result.name));
      const loaded = useStore.getState();
      if (loaded.sourceUrl !== result.url || loaded.error) throw new Error(loaded.error ?? "Could not open the projection");
      loaded.addChart({ ...scatterSpec(result.axes[0]!, result.axes[1]!), z: result.axes[2] ?? null });
      navigate({ name: result.kind, project: result.project, url: result.url });
      onClose();
    } catch (e) { setError(e instanceof Error ? e.message : String(e)); }
    finally { setBusy(false); }
  };
  const running = job?.status === "running";
  const selected = saved.find(item => item.id === reducerId);
  const canStart = column && (selected || methods.find(m => m.id === method)?.installed) && (reducerId || !remember || savedName.trim());
  return <Modal title="Project embeddings" onClose={onClose} width={520} footer={<>
    {running && <button onClick={() => void api.cancelJob(job.id).then(() => setJob({ ...job })).catch(e => setError(String(e)))}>Stop after current calculation</button>}
    <span className="spacer" /><button onClick={onClose}>Close</button>
    {job?.status === "done" ? <button className="primary" disabled={busy} onClick={() => void open()}>Open projection</button>
      : <button className="primary" disabled={busy || running || !canStart} onClick={() => void start()}>Create projection</button>}
  </>}>
    <p className="muted">Create a dataset version or a separate analysis run. Run projections fit the last available embedding table and reuse that coordinate system for every epoch.</p>
    <label className="field"><span>Embedding column</span><select value={column} onChange={e => setColumn(e.target.value)}>{embeddings.map(c => <option key={c.name}>{c.name}</option>)}</select></label>
    <label className="field"><span>Coordinate system</span><select value={reducerId} onChange={e => setReducerId(e.target.value)}>
      <option value="">Fit a new projection</option>{saved.map(item => <option key={item.id} value={item.id}>{item.name} · {item.method.toUpperCase()} {item.dimensions}D</option>)}
    </select></label>
    {selected ? <p className="muted">Reuse {selected.features}-component embeddings in the saved {selected.dimensions}D coordinate system. Use the same embedding model and preprocessing as the reference dataset ({selected.reference_samples} samples).</p> : <>
    <label className="field"><span>Method</span><select value={method} onChange={e => setMethod(e.target.value)}>{methods.map(m => <option key={m.id} value={m.id} disabled={!m.installed}>{m.id.toUpperCase()}{m.installed ? "" : " — add-on required"}</option>)}</select></label>
    <label className="field"><span>Dimensions</span><select value={dimensions} onChange={e => setDimensions(Number(e.target.value))}><option value={2}>2D</option><option value={3}>3D</option></select></label>
    <label className="field"><span>Neighbours</span><input type="number" min={2} max={200} value={neighbours} onChange={e => setNeighbours(Number(e.target.value))} /></label>
    <label className="field"><span>Random seed</span><input type="number" min={0} max={2147483647} value={seed} onChange={e => setSeed(Number(e.target.value))} /></label>
    <label className="checkbox"><input type="checkbox" checked={remember} onChange={e => setRemember(e.target.checked)} />Save this coordinate system for reuse</label>
    {remember && <label className="field"><span>Saved projection name</span><input value={savedName} maxLength={80} onChange={e => setSavedName(e.target.value)} /></label>}
    </>}
    <label className="field"><span>Output column prefix</span><input value={prefix} onChange={e => setPrefix(e.target.value)} /></label>
    {job && <p role="status">{job.phase} · {job.done}/{job.total} · {job.status}</p>}
    {(error || job?.error) && <p className="form-error" role="alert">{error ?? job?.error}</p>}
  </Modal>;
}
