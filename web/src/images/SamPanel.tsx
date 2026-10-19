import { useEffect, useRef, useState } from "react";
import { api } from "../api/client";
import type { Job } from "../api/types";

export interface SamPoint { point: [number, number]; label: 0 | 1 }
type Proposal = { model: string; width: number; height: number; cancelled?: boolean; candidates: { mask: unknown; quality: number }[] };

export function SamPanel({ project, dataset, table, image, box, points, onPointTool, onClear, onPreview, onApply, onRestore }: {
  project: string; dataset: string; table: string; image: string; box: number[] | null; points: SamPoint[];
  onPointTool: (label: 0 | 1) => void; onClear: () => void; onPreview: (mask: unknown) => void;
  onApply: (mask: unknown, model: string) => boolean;
  onRestore: (box: number[] | null, points: SamPoint[]) => boolean;
}) {
  const [catalogue, setCatalogue] = useState<Awaited<ReturnType<typeof api.samModels>> | null>(null);
  const [model, setModel] = useState("sam2.1_t.pt");
  const [job, setJob] = useState<Job<Proposal> | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [candidate, setCandidate] = useState(0);
  const alive = useRef(true);
  const requestKey = JSON.stringify({ table, image, box, points });
  const currentKey = useRef(requestKey); currentKey.current = requestKey;
  const submittedKey = useRef("");
  const preview = useRef(onPreview); preview.current = onPreview;
  const storageKey = `granum:sam:${JSON.stringify([project, dataset, table, image])}`;
  const restore = useRef(onRestore); restore.current = onRestore;
  const clearSaved = () => { try { localStorage.removeItem(storageKey); } catch { /* proposal remains usable in this tab */ } };

  useEffect(() => {
    let disposed = false;
    try {
      const raw = localStorage.getItem(storageKey);
      if (raw) {
        const saved = JSON.parse(raw) as { id: string; model: string; requestKey: string };
        const prompts = JSON.parse(saved.requestKey) as { table: string; image: string; box: number[] | null; points: SamPoint[] };
        const validBox = prompts.box === null || (Array.isArray(prompts.box) && prompts.box.length === 4 && prompts.box.every(Number.isFinite));
        const validPoints = Array.isArray(prompts.points) && prompts.points.every(p => p && Array.isArray(p.point) && p.point.length === 2 && p.point.every(Number.isFinite) && (p.label === 0 || p.label === 1));
        if (typeof saved.id !== "string" || prompts.table !== table || prompts.image !== image || !validBox || !validPoints) throw new Error("The saved SAM request is invalid.");
        if (!restore.current(prompts.box, prompts.points)) throw new Error("The object changed. Generate a new SAM proposal.");
        submittedKey.current = saved.requestKey;
        setModel(saved.model);
        api.job<Proposal>(saved.id).then(next => {
          if (disposed) return;
          setJob(next);
          if (next.status === "done" && next.result && !next.result.cancelled) preview.current(next.result.candidates[0]?.mask ?? null);
          if (next.status === "failed") setError(next.error ?? "SAM stopped.");
        }).catch((e: Error) => { if (!disposed) setError(`The saved SAM request could not be recovered: ${e.message}`); });
      }
    } catch (e) { setError(e instanceof Error ? e.message : String(e)); }
    return () => { disposed = true; };
  }, [storageKey, table, image]);

  useEffect(() => {
    alive.current = true;
    api.samModels().then((data) => alive.current && setCatalogue(data)).catch((e: Error) => alive.current && setError(e.message));
    return () => { alive.current = false; preview.current(null); };
  }, []);
  useEffect(() => { preview.current(null); setCandidate(0); }, [requestKey]);

  useEffect(() => {
    if (!job || job.status !== "running") return;
    let disposed = false;
    const timer = window.setTimeout(() => {
      api.job<Proposal>(job.id).then((next) => {
        if (disposed) return;
        setJob(next);
        if (next.status === "failed") setError(next.error ?? "SAM stopped.");
        if (next.status === "done" && next.result && !next.result.cancelled) {
          if (submittedKey.current !== currentKey.current) setError("The prompts changed while SAM was running. Generate a new proposal.");
          else { setCandidate(0); preview.current(next.result.candidates[0]?.mask ?? null); }
        }
      }).catch((e: Error) => {
        if (!disposed) { setError(e.message); setJob((current) => current ? { ...current } : current); }
      });
    }, 1000);
    return () => { disposed = true; window.clearTimeout(timer); };
  }, [job]);

  const start = async () => {
    setBusy(true); setError(null); preview.current(null); submittedKey.current = requestKey;
    try {
      const next = await api.proposeMask({ project, dataset, table, image, model, box, points: points.map((p) => p.point), labels: points.map((p) => p.label) });
      if (!alive.current) return;
      setJob(next);
      if (next.status === "done" && next.result && !next.result.cancelled && currentKey.current === submittedKey.current) preview.current(next.result.candidates[0]?.mask ?? null);
      try { localStorage.setItem(storageKey, JSON.stringify({ id: next.id, model, requestKey })); }
      catch { setError("SAM is running, but this browser could not save its recovery information. Keep this tab open."); }
    }
    catch (e) { setError(e instanceof Error ? e.message : String(e)); }
    finally { if (alive.current) setBusy(false); }
  };

  const install = async () => {
    setBusy(true); setError(null);
    try {
      let installation = await api.installTraining();
      while (installation.status === "running" && alive.current) {
        await new Promise((resolve) => window.setTimeout(resolve, 1000));
        installation = await api.job<{ installed: string }>(installation.id);
      }
      if (installation.status === "failed") throw new Error(installation.error ?? "Installation failed.");
      if (alive.current) setCatalogue(await api.samModels());
    } catch (e) { if (alive.current) setError(e instanceof Error ? e.message : String(e)); }
    finally { if (alive.current) setBusy(false); }
  };

  const running = job?.status === "running";
  const proposed = job?.status === "done" && !job.result?.cancelled && submittedKey.current === requestKey ? job.result : null;
  return <div className="qa-side-section">
    <h3 className="qa-side-title">Segment Anything</h3>
    <p className="faint small">Use the selected box, or mark foreground and background points. Review the proposed mask before applying it.</p>
    {catalogue && !catalogue.available ? <>
      <p className="small muted">Requires local model support (about 3 GB). Model weights download on first use.</p>
      <button className="button small" disabled={busy} onClick={() => void install()}>{busy ? "Installing model support…" : "Install model support"}</button>
    </> : <>
      <label className="field">Model<select value={model} onChange={(e) => setModel(e.target.value)} disabled={busy || running}>
        {(catalogue?.models ?? [{ id: "sam2.1_t.pt", name: "SAM 2.1 tiny" }]).map((entry) => <option key={entry.id} value={entry.id}>{entry.name}</option>)}
      </select></label>
      <div className="editor-actions">
        <button className="button small" onClick={() => onPointTool(1)}>Foreground point</button>
        <button className="button small" onClick={() => onPointTool(0)}>Background point</button>
        <button className="button small subtle" onClick={onClear} disabled={!points.length}>Clear {points.length} points</button>
      </div>
      <button className="button small" disabled={busy || running || !catalogue?.available || (!box && !points.some((p) => p.label))} onClick={() => void start()}>{busy || running ? job?.phase ?? "Starting SAM…" : "Propose mask"}</button>
      {running && <button className="button small subtle" onClick={() => void api.cancelJob(job.id).catch((e: Error) => setError(e.message))}>Cancel</button>}
      <p className="faint small">Runs on this machine. First use downloads the selected model's weights.</p>
    </>}
    {proposed && proposed.candidates.length > 0 && <>
      {proposed.candidates.length > 1 && <label className="field">Proposal<select value={candidate} onChange={(e) => { const at = Number(e.target.value); setCandidate(at); onPreview(proposed.candidates[at]!.mask); }}>
        {proposed.candidates.map((c, i) => <option key={i} value={i}>Mask {i + 1} · model quality {c.quality.toFixed(2)}</option>)}
      </select></label>}
      <div className="editor-actions">
        <button className="button small primary" onClick={() => { if (onApply(proposed.candidates[candidate]!.mask, proposed.model)) { onPreview(null); setJob(null); clearSaved(); } }}>Apply mask</button>
        <button className="button small subtle" onClick={() => { onPreview(null); setJob(null); clearSaved(); }}>Discard</button>
      </div>
    </>}
    {error && <p className="form-error">{error}</p>}
  </div>;
}
