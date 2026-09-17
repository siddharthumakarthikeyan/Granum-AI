/** The images taken out of a dataset's sets: where each came from, why, and a way back. */

import { useCallback, useEffect, useMemo, useState } from "react";
import { api } from "../api/client";
import type { RemovedImage, VersionRef } from "../api/types";
import { EmptyState, Icon, PageHeader, formatNumber, formatWhen, plural } from "../components/ui";
import { routeHref } from "../router";
import { useStore } from "../store/store";

export function RemovedPage({ project, dataset }: { project: string; dataset: string }) {
  const refreshProject = useStore((s) => s.refreshProject);
  const [images, setImages] = useState<RemovedImage[] | null>(null);
  const [table, setTable] = useState<VersionRef | null>(null);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [from, setFrom] = useState<string>("all");
  const [large, setLarge] = useState<RemovedImage | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [toast, setToast] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const result = await api.removedImages(project, dataset);
      setImages(result.images);
      setTable(result.table);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }, [project, dataset]);

  useEffect(() => {
    void load();
  }, [load]);

  const sets = useMemo(() => [...new Set((images ?? []).map((i) => i.removed_from))].sort(), [images]);
  const shown = (images ?? []).filter((i) => from === "all" || i.removed_from === from);

  const putBack = async (samples: string[]) => {
    setBusy(true);
    setError(null);
    try {
      const done = await api.restoreImages({ project, dataset, samples });
      setSelected(new Set());
      setLarge(null);
      setToast(`${plural(done.count, "image")} put back${done.versions.length ? ` (new version ${done.versions.map((v) => `${v.set}: ${v.name}`).join(", ")})` : ""}.`);
      window.setTimeout(() => setToast(null), 6000);
      await Promise.all([load(), refreshProject()]);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };

  const toggle = (image: string) => {
    setSelected((current) => {
      const next = new Set(current);
      if (next.has(image)) next.delete(image);
      else next.add(image);
      return next;
    });
  };

  return (
    <div className="page">
      <PageHeader
        back={{ href: routeHref({ name: "datasets", project }), label: "Datasets" }}
        title={`Removed from ${dataset}`}
        subtitle="Images taken out of the training or checking sets. Nothing here is deleted: put any image back and it returns to the newest version of the set it came from."
        actions={
          sets.length > 1 ? (
            <label className="inline-field small">
              <span className="muted">From</span>
              <select value={from} onChange={(e) => setFrom(e.target.value)}>
                <option value="all">Every set</option>
                {sets.map((s) => <option key={s} value={s}>{s}</option>)}
              </select>
            </label>
          ) : undefined
        }
      />
      {error && <p className="form-error">{error}</p>}
      {images !== null && images.length === 0 && (
        <EmptyState title="Nothing has been removed">
          <p>Open a training run's "which images were easy or hard" page, click an image, and choose Remove.</p>
        </EmptyState>
      )}

      {shown.length > 0 && (
        <>
          <div className="section-head">
            <h2 className="section-title">{plural(shown.length, "image")}<span className="muted">{table ? ` · version ${table.name}` : ""}</span></h2>
            <span className="spacer" />
            <button className="button subtle" onClick={() => setSelected(selected.size === shown.length ? new Set() : new Set(shown.map((i) => i.image)))}>
              {selected.size === shown.length ? "Select none" : "Select all"}
            </button>
          </div>
          <div className="learning-grid">
            {shown.map((item) => {
              const checked = selected.has(item.image);
              return (
                <div key={item.image} className={`learning-card removed-card${checked ? " selected" : ""}`}>
                  <button className="learning-thumb" onClick={() => setLarge(item)} title="See it large">
                    <img loading="lazy" src={api.mediaUrl(item.image, 320, project, dataset)} alt="" />
                    <span className="learning-zoom" aria-hidden="true"><Icon name="open" size={14} /></span>
                  </button>
                  <div className="learning-card-body">
                    <label className="check-row small">
                      <input type="checkbox" checked={checked} onChange={() => toggle(item.image)} />
                      <span className="strong">From {item.removed_from}</span>
                    </label>
                    <span className="small">{item.removed_reason || "No reason given"}</span>
                    <span className="muted small">{plural(item.objects, "object")} · {formatWhen(item.removed_at)}</span>
                  </div>
                </div>
              );
            })}
          </div>
        </>
      )}

      {selected.size > 0 && (
        <div className="decision-tray" role="region" aria-label="Selected images">
          <span className="strong">{plural(selected.size, "image")} selected</span>
          <span className="spacer" />
          <button className="button subtle" onClick={() => setSelected(new Set())}>Clear</button>
          <button className="button primary" onClick={() => void putBack([...selected])} disabled={busy}>
            {busy ? "Putting back" : "Put back"}
          </button>
        </div>
      )}
      {toast && <div className="toast" role="status">{toast}</div>}

      {large && (
        <div className="lightbox" role="dialog" aria-modal="true" onMouseDown={(e) => e.target === e.currentTarget && setLarge(null)}>
          <div className="lightbox-frame">
            <img src={api.mediaUrl(large.image, undefined, project, dataset)} alt="" />
            <div className="lightbox-bar">
              <span className="small">
                <span className="strong">From {large.removed_from}</span>
                <span className="muted"> · {large.removed_reason || "No reason given"} · {formatNumber(large.objects)} objects</span>
              </span>
              <span className="spacer" />
              <button className="button" onClick={() => setLarge(null)}>Close</button>
              <button className="button primary" onClick={() => void putBack([large.image])} disabled={busy}>Put back into {large.removed_from}</button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
