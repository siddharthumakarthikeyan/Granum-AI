import { useEffect, useRef, useState } from "react";
import { Modal } from "../components/Modal";
import { deleteEditorDraft, loadEditorDraft, saveEditorDraft, type EditorDraft } from "./editorDrafts";

type Session<T> = { key: string; token: string | null; pending: EditorDraft<T> | null; ready: boolean; queue: Promise<void>; last: string };

/** Keep pending annotations and schema edits until an acknowledged server commit. */
export function useEditorDraft<T>(key: string, base: string | null, data: T, dirty: boolean, restore: (data: T) => void) {
  const session = useRef<Session<T> | null>(null);
  const [pending, setPending] = useState<EditorDraft<T> | null>(null);
  const [error, setError] = useState("");
  const [status, setStatus] = useState("");
  const restoreRef = useRef(restore);
  restoreRef.current = restore;
  const serialized = JSON.stringify(data);

  useEffect(() => {
    if (!base) return;
    let alive = true;
    const s: Session<T> = { key, token: null, pending: null, ready: false, queue: Promise.resolve(), last: "" };
    session.current = s;
    setPending(null); setError(""); setStatus("Checking recovery…");
    s.queue = loadEditorDraft<T>(key).then((draft) => {
      s.token = draft?.token ?? null; s.pending = draft; s.ready = true;
      if (alive) { setPending(draft); setStatus(""); }
    }).catch((e: Error) => { s.ready = true; if (alive) { setError(e.message); setStatus(""); } });
    return () => { alive = false; };
  }, [key, base]);

  useEffect(() => {
    const s = session.current;
    if (!base || !dirty || !s?.ready || s.key !== key || s.pending || serialized === s.last) return;
    s.last = serialized;
    setStatus("Saving recovery copy…");
    s.queue = s.queue.then(async () => {
      const draft: EditorDraft<T> = { key, base, data: JSON.parse(serialized) as T, version: 1, savedAt: new Date().toISOString(), token: crypto.randomUUID() };
      await saveEditorDraft(draft, s.token);
      s.token = draft.token;
      if (session.current === s) { setError(""); setStatus("Recovery copy saved in this browser"); }
    }).catch((e: Error) => { if (session.current === s) { setError(e.message); setStatus(""); } });
  }, [key, base, dirty, serialized, pending, status]);

  const clear = async () => {
    const s = session.current;
    if (!s || s.key !== key) return;
    await s.queue;
    if (s.token !== null) await deleteEditorDraft(key, s.token);
    s.token = null; s.pending = null; s.last = serialized;
    setPending(null); setStatus("");
  };
  const download = () => {
    const record = pending ?? { key, base, version: 1, data, savedAt: new Date().toISOString() };
    const url = URL.createObjectURL(new Blob([JSON.stringify(record, null, 2)], { type: "application/json" }));
    const a = document.createElement("a"); a.href = url; a.download = "granum-annotation-draft.json"; a.click();
    window.setTimeout(() => URL.revokeObjectURL(url), 1000);
  };
  const stale = pending && (pending.base !== base || pending.version !== 1);
  const banner = <>
    {(status || error) && <div className={error ? "form-error" : "notice small"} role={error ? "alert" : "status"}>
      {error || status}. Drafts are private to this browser profile, not a server backup.
      {(error || dirty) && <button className="button subtle small" onClick={download}>Export edits</button>}
    </div>}
    {pending && <Modal title={stale ? "Draft from a different revision" : "Recover unsaved annotations"} onClose={() => undefined} footer={<>
      <button onClick={download}>Export draft</button>
      <button onClick={() => void clear().catch((e: Error) => setError(e.message))}>Discard draft</button>
      <button className="primary" disabled={Boolean(stale)} onClick={() => {
        if (!session.current || stale) return;
        session.current.pending = null;
        restoreRef.current(pending.data); setPending(null);
      }}>Recover edits</button>
    </>}>
      <p>Unsaved work from {new Date(pending.savedAt).toLocaleString()} was found.</p>
      <p>{stale ? "The source revision changed. Automatic replay is blocked to avoid overwriting newer labels. Export the draft for comparison or discard it." : "Recover the annotations, class changes and pending work, or explicitly discard them."}</p>
      {error && <p className="form-error" role="alert">{error}</p>}
    </Modal>}
  </>;
  return { clear, banner, blocked: Boolean(pending) || !session.current?.ready };
}