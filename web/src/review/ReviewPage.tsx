/** Annotation review: every image starts unreviewed; reviewers mark it reviewed or send it
 * back for rework with a comment; when a whole dataset is reviewed it can be shipped, and
 * only shipped versions can be trained on (see granum.core.qa).
 */

import { useCallback, useEffect, useMemo, useState } from "react";
import { api } from "../api/client";
import type { QaImage, QaOverview, QaSet, QaState, QaStatus } from "../api/types";
import { EmptyState, Icon, PageHeader, formatNumber, formatWhen, plural } from "../components/ui";
import { groupDatasets, REMOVED_SET } from "../pages/datasets";
import { navigate, routeHref } from "../router";
import { useStore } from "../store/store";
import { ImageInspector } from "./ImageInspector";
import { ShipDialog } from "./ShipDialog";

const PAGE = 120;
const ISOLATED_TAB = "__isolated";
export type MoveAction = "isolate" | "delete" | "return";
type TrayMode = "rework" | "isolate" | "delete" | null;
const NAME_KEY = "granum.reviewer";

export const STATUS_LABEL: Record<QaStatus, string> = { unreviewed: "Unreviewed", reviewed: "Reviewed", rework: "Rework" };
type Filter = "all" | QaStatus | "commented";

export function statusOf(statuses: Record<string, QaState>, image: string): QaStatus {
  return statuses[image]?.status ?? "unreviewed";
}

export function countStatuses(set: QaSet, statuses: Record<string, QaState>): Record<QaStatus, number> {
  const counts: Record<QaStatus, number> = { unreviewed: 0, reviewed: 0, rework: 0 };
  for (const item of set.images) counts[statusOf(statuses, item.image)] += 1;
  return counts;
}

function readName(): string {
  try {
    return window.localStorage.getItem(NAME_KEY) ?? "";
  } catch {
    return "";
  }
}

export function ReviewPage({ project, dataset }: { project: string; dataset?: string }) {
  const tables = useStore((s) => s.tables);
  const refreshProject = useStore((s) => s.refreshProject);
  const loading = useStore((s) => s.loading);
  const datasets = useMemo(
    () => groupDatasets(tables).filter((d) => d.splits.some((s) => s.name !== REMOVED_SET)),
    [tables],
  );
  const active = dataset ?? datasets[0]?.name;

  const [data, setData] = useState<QaOverview | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [setName, setSetName] = useState<string | null>(null);
  const [filter, setFilter] = useState<Filter>("all");
  const [shown, setShown] = useState(PAGE);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [open, setOpen] = useState<number | null>(null);
  const [shipping, setShipping] = useState(false);
  const [trayMode, setTrayMode] = useState<TrayMode>(null);
  const [trayNote, setTrayNote] = useState("");
  const [busy, setBusy] = useState(false);
  const [toast, setToast] = useState<string | null>(null);
  const [author, setAuthorState] = useState(readName);

  const setAuthor = (name: string) => {
    setAuthorState(name);
    try {
      window.localStorage.setItem(NAME_KEY, name);
    } catch {
      /* the name is a convenience; without storage it lasts the session */
    }
  };

  const load = useCallback(async () => {
    if (!active) return;
    try {
      setData(await api.qa(project, active));
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }, [project, active]);

  useEffect(() => {
    setData(null);
    setSelected(new Set());
    setOpen(null);
    void load();
  }, [load]);

  const sets = data?.sets ?? [];
  const isolated = data?.isolated ?? null;
  const onIsolated = setName === ISOLATED_TAB && isolated !== null;
  const current = onIsolated ? isolated : sets.find((s) => s.set === setName) ?? sets[0];
  const statuses = data?.statuses ?? {};
  const items = useMemo(() => {
    if (!current) return [];
    return current.images.filter((item) => {
      if (filter === "all") return true;
      if (filter === "commented") return (statuses[item.image]?.comments ?? 0) > 0;
      return statusOf(statuses, item.image) === filter;
    });
  }, [current, statuses, filter]);

  useEffect(() => {
    setShown(PAGE);
    setSelected(new Set());
  }, [current?.set, filter]);

  // Isolating or deleting the open image shortens the list; stay at the same position.
  useEffect(() => {
    if (open !== null && open >= items.length) setOpen(items.length ? items.length - 1 : null);
  }, [open, items.length]);

  const visibleCount = Math.min(shown, items.length);
  const allVisibleSelected = items.slice(0, shown).every((i) => selected.has(i.image));
  const allSelected = items.length > 0 && items.every((i) => selected.has(i.image));

  const flash = (message: string) => {
    setToast(message);
    window.setTimeout(() => setToast(null), 4000);
  };

  /** Apply a status at once; the service call follows and a failure reloads the truth. */
  const decide = useCallback(async (images: string[], status: QaStatus, comment = "") => {
    if (!active || !current || images.length === 0) return false;
    setData((before) => {
      if (!before) return before;
      const next = { ...before.statuses };
      for (const image of images) {
        const was = next[image] ?? { status: "unreviewed", comments: 0 };
        next[image] = { ...was, status, author, note: comment, comments: was.comments + (comment ? 1 : 0), time: new Date().toISOString() };
      }
      return { ...before, statuses: next };
    });
    try {
      const done = await api.setQaStatus({ project, dataset: active, samples: images, status, comment, author, table: current.url });
      setData((before) => before && { ...before, statuses: { ...before.statuses, ...done.statuses } });
      return true;
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
      void load();
      return false;
    }
  }, [project, active, current, author, load]);

  const closeTray = () => {
    setTrayMode(null);
    setTrayNote("");
  };

  const bulk = async (status: QaStatus, comment = "") => {
    setBusy(true);
    const images = [...selected];
    if (await decide(images, status, comment)) {
      flash(`${plural(images.length, "image")} marked ${STATUS_LABEL[status].toLowerCase()}`);
      setSelected(new Set());
      closeTray();
    }
    setBusy(false);
  };

  /** Isolate, delete or return images; each writes new set versions, so reload after. */
  const move = useCallback(async (images: string[], action: MoveAction, reason = "") => {
    if (!active || !current || images.length === 0) return false;
    setBusy(true);
    try {
      const payload = { project, dataset: active, samples: images, reason, author };
      if (action === "isolate") await api.isolate({ ...payload, table: current.url });
      else if (action === "delete") await api.deleteImages({ ...payload, table: current.url });
      else await api.returnIsolated(payload);
      const verb = action === "isolate" ? "isolated" : action === "delete" ? "deleted" : "returned to their sets";
      flash(`${plural(images.length, "image")} ${verb}`);
      setSelected((was) => new Set([...was].filter((i) => !images.includes(i))));
      await Promise.all([load(), refreshProject()]);
      return true;
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
      return false;
    } finally {
      setBusy(false);
    }
  }, [project, active, current, author, load, refreshProject]);

  const runTray = async () => {
    const note = trayNote.trim();
    if (trayMode === "rework") {
      if (note) await bulk("rework", note);
    } else if (trayMode) {
      if (await move([...selected], trayMode, note)) closeTray();
    }
  };

  if (datasets.length === 0 && !loading) {
    return (
      <div className="page">
        <PageHeader title="Review" context={project} />
        <EmptyState title="No datasets" action={<a className="button primary" href={routeHref({ name: "import", project })}><Icon name="import" />Import a dataset</a>}>
          <p>Imported datasets are reviewed here before they can be shipped for training.</p>
        </EmptyState>
      </div>
    );
  }

  const totals = sets.reduce(
    (acc, s) => {
      const c = countStatuses(s, statuses);
      return { unreviewed: acc.unreviewed + c.unreviewed, reviewed: acc.reviewed + c.reviewed, rework: acc.rework + c.rework };
    },
    { unreviewed: 0, reviewed: 0, rework: 0 } as Record<QaStatus, number>,
  );
  const total = totals.unreviewed + totals.reviewed + totals.rework;
  const latest = data?.shipments[0];
  // Shipping works per set: a set can ship once its (newest) version is fully reviewed.
  const setState = sets.map((s) => {
    const c = countStatuses(s, statuses);
    return { set: s, ready: s.images.length > 0 && c.reviewed === s.images.length, shipped: Boolean(s.shipped) };
  });
  const shippedSets = setState.filter((s) => s.shipped).length;
  const upToDate = sets.length > 0 && shippedSets === sets.length;
  // Something can ship: a set's newest version (counted live here) or any earlier fully reviewed version.
  const shippable = setState.some((s) => s.ready && !s.shipped)
    || sets.some((s) => (s.versions ?? []).slice(1).some((v) => v.ready && !v.shipped));

  return (
    <div className="page review-page">
      <PageHeader
        title="Review"
        context={project}
        subtitle={data ? `${formatNumber(total)} images across ${plural(sets.length, "set")}` : undefined}
        actions={
          <>
            {datasets.length > 1 && (
              <div className="select-wrap">
                <select aria-label="Dataset" value={active} onChange={(e) => navigate({ name: "review", project, dataset: e.target.value })}>
                  {datasets.map((d) => <option key={d.name} value={d.name}>{d.name}</option>)}
                </select>
              </div>
            )}
            <label className="inline-field small reviewer-field">
              <span className="muted">Reviewer</span>
              <input type="text" value={author} onChange={(e) => setAuthor(e.target.value)} placeholder="Your name" maxLength={80} />
            </label>
            <button
              className="button primary"
              onClick={() => {
                // Version counts are computed by the service; refresh them so the dialog matches
                // the decisions just made on this page.
                void load().then(() => setShipping(true));
              }}
              disabled={!data || !shippable}
              title={upToDate ? "The newest version of every set is already shipped"
                : shippable ? "Ship reviewed sets for training"
                  : "A set can ship once every image in it is reviewed"}
            >
              <Icon name="ship" />Ship
            </button>
          </>
        }
      />
      {error && <p className="form-error">{error}</p>}

      {data && (
        <>
          <div className="qa-summary">
            <div className="qa-ship-state">
              {upToDate ? (
                <span className="qa-pill shipped"><Icon name="check" size={13} />Shipped</span>
              ) : shippedSets > 0 ? (
                <span className="qa-pill changed"><Icon name="ship" size={13} />Partly shipped</span>
              ) : latest ? (
                <span className="qa-pill changed"><Icon name="warn" size={13} />Changed since shipped</span>
              ) : (
                <span className="qa-pill draft">Not shipped</span>
              )}
              <span className="muted small">
                {setState.map((s) => `${s.set.set} ${s.shipped ? "shipped" : s.ready ? "ready" : "in review"}`).join(" · ")}
                {latest ? ` · last shipped ${formatWhen(latest.time)}${latest.author ? ` by ${latest.author}` : ""}` : ""}
                {isolated && isolated.images.length > 0 && ` · ${formatNumber(isolated.images.length)} isolated, not shipped`}
              </span>
            </div>
            <div className="qa-bar" aria-label={`${totals.reviewed} of ${total} reviewed`}>
              {(["reviewed", "rework", "unreviewed"] as QaStatus[]).map((status) => (
                <span key={status} className={`qa-bar-${status}`} style={{ width: `${total ? (totals[status] / total) * 100 : 0}%` }} />
              ))}
            </div>
            <dl className="qa-counts">
              {(["reviewed", "rework", "unreviewed"] as QaStatus[]).map((status) => (
                <div key={status}>
                  <dt><span className={`qa-dot ${status}`} />{STATUS_LABEL[status]}</dt>
                  <dd className="tabular">{formatNumber(totals[status])}</dd>
                </div>
              ))}
              <div>
                <dt>Progress</dt>
                <dd className="tabular">{total ? `${Math.floor((totals.reviewed / total) * 100)}%` : "—"}</dd>
              </div>
            </dl>
          </div>

          <div className="qa-toolbar">
            <div className="segmented" role="tablist" aria-label="Set">
              {sets.map((s) => {
                const c = countStatuses(s, statuses);
                return (
                  <button key={s.set} role="tab" aria-selected={s === current} className={s === current ? "on" : ""} onClick={() => setSetName(s.set)}>
                    {s.set}
                    {s.shipped && <Icon name="check" size={12} className="tab-shipped" />}
                    <span className="split-toggle-count">{formatNumber(c.reviewed)}/{formatNumber(s.images.length)}</span>
                  </button>
                );
              })}
              {isolated && isolated.images.length > 0 && (
                <button role="tab" aria-selected={onIsolated} className={`isolated-tab${onIsolated ? " on" : ""}`} onClick={() => setSetName(ISOLATED_TAB)}>
                  isolated
                  <span className="split-toggle-count">{formatNumber(isolated.images.length)}</span>
                </button>
              )}
            </div>
            {current && <span className="cell-mono muted small">{current.name}</span>}
            {onIsolated && <span className="muted small">Not shipped. Fix or review, then return each image to its set.</span>}
            <span className="spacer" />
            <div className="segmented" role="group" aria-label="Status filter">
              {(["all", "unreviewed", "rework", "reviewed", "commented"] as Filter[]).map((f) => {
                const count = !current ? 0 : f === "all" ? current.images.length
                  : f === "commented" ? current.images.filter((i) => (statuses[i.image]?.comments ?? 0) > 0).length
                    : countStatuses(current, statuses)[f];
                return (
                  <button key={f} className={filter === f ? "on" : ""} onClick={() => setFilter(f)}>
                    {f === "all" ? "All" : f === "commented" ? "Commented" : STATUS_LABEL[f]}
                    <span className="split-toggle-count">{formatNumber(count)}</span>
                  </button>
                );
              })}
            </div>
            <div className="qa-select" role="group" aria-label="Selection">
              <button
                className="button subtle"
                onClick={() => setSelected(new Set(items.slice(0, shown).map((i) => i.image)))}
                disabled={items.length === 0 || (selected.size === visibleCount && allVisibleSelected)}
                title="Select the images loaded on this page"
              >
                Select shown <span className="split-toggle-count">{formatNumber(visibleCount)}</span>
              </button>
              <button
                className="button subtle"
                onClick={() => setSelected(new Set(items.map((i) => i.image)))}
                disabled={items.length === 0 || (selected.size === items.length && allSelected)}
                title="Select every image matching the current set and filter, including those not loaded yet"
              >
                Select all <span className="split-toggle-count">{formatNumber(items.length)}</span>
              </button>
              {selected.size > 0 && (
                <button className="button subtle" onClick={() => setSelected(new Set())}>Select none</button>
              )}
            </div>
          </div>

          {items.length === 0 ? (
            <p className="muted qa-empty">{filter === "all" ? "This set has no images." : `No ${filter === "commented" ? "commented" : STATUS_LABEL[filter].toLowerCase()} images in ${current?.set}.`}</p>
          ) : (
            <div className="qa-grid">
              {items.slice(0, shown).map((item, i) => (
                <QaCard
                  key={item.image}
                  item={item}
                  state={statuses[item.image]}
                  project={project}
                  dataset={active!}
                  isolated={onIsolated}
                  checked={selected.has(item.image)}
                  onToggle={() => setSelected((was) => {
                    const next = new Set(was);
                    if (next.has(item.image)) next.delete(item.image);
                    else next.add(item.image);
                    return next;
                  })}
                  onOpen={() => setOpen(i)}
                />
              ))}
            </div>
          )}
          {items.length > shown && (
            <div className="qa-more">
              <button className="button" onClick={() => setShown(shown + PAGE)}>
                Show {formatNumber(Math.min(PAGE, items.length - shown))} more
              </button>
              <span className="muted small">{formatNumber(shown)} of {formatNumber(items.length)}</span>
            </div>
          )}

          {latest && (
            <section className="qa-history">
              <h2 className="section-title">Shipments</h2>
              <div className="data-table-wrap">
                <table className="data-table">
                  <thead>
                    <tr><th>Shipped</th><th>By</th><th>Sets</th><th className="num">Images</th><th>Note</th></tr>
                  </thead>
                  <tbody>
                    {data.shipments.map((s, i) => (
                      <tr key={s.id}>
                        <td>{formatWhen(s.time)}{i === 0 && <span className="tag">latest</span>}</td>
                        <td>{s.author || "—"}</td>
                        <td className="cell-mono small">{Object.entries(s.sets).map(([name, v]) => `${name}: ${v.name}`).join(", ")}</td>
                        <td className="num">{formatNumber(Object.values(s.sets).reduce((n, v) => n + v.images, 0))}</td>
                        <td className="muted">{s.note || "—"}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </section>
          )}
        </>
      )}

      {selected.size > 0 && (
        <div className="decision-tray" role="region" aria-label="Selected images">
          <span className="strong">{plural(selected.size, "image")} selected</span>
          {trayMode === null && !allSelected && items.length > selected.size && (
            <button className="button subtle qa-select-all-link" onClick={() => setSelected(new Set(items.map((i) => i.image)))}>
              Select all {formatNumber(items.length)}
            </button>
          )}
          {trayMode !== null ? (
            <>
              <input
                type="text"
                className="qa-tray-note"
                autoFocus
                value={trayNote}
                onChange={(e) => setTrayNote(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Enter") void runTray();
                  if (e.key === "Escape") closeTray();
                }}
                placeholder={trayMode === "rework" ? "What needs rework?" : trayMode === "isolate" ? "Why set aside? (optional)" : "Why delete? (optional)"}
              />
              {trayMode === "delete" && <span className="muted small">Moves to the removed set; recoverable from Datasets.</span>}
              <button className="button subtle" onClick={closeTray}>Cancel</button>
              <button
                className={`button ${trayMode === "isolate" ? "primary" : "danger-button"}`}
                disabled={busy || (trayMode === "rework" && !trayNote.trim())}
                onClick={() => void runTray()}
              >
                {trayMode === "rework" ? "Send to rework" : trayMode === "isolate" ? `Isolate ${formatNumber(selected.size)}` : `Delete ${formatNumber(selected.size)}`}
              </button>
            </>
          ) : (
            <>
              <span className="spacer" />
              <button className="button subtle" onClick={() => setSelected(new Set())}>Clear</button>
              <button className="button danger-button" disabled={busy} onClick={() => setTrayMode("delete")}><Icon name="trash" />Delete…</button>
              {onIsolated ? (
                <button className="button" disabled={busy} onClick={() => void move([...selected], "return")}><Icon name="back" />Return to set</button>
              ) : (
                <button className="button" disabled={busy} onClick={() => setTrayMode("isolate")}><Icon name="isolate" />Isolate…</button>
              )}
              <button className="button" disabled={busy} onClick={() => void bulk("unreviewed")}>Reset</button>
              <button className="button" disabled={busy} onClick={() => setTrayMode("rework")}>Rework…</button>
              <button className="button primary" disabled={busy} onClick={() => void bulk("reviewed")}><Icon name="check" />Mark reviewed</button>
            </>
          )}
        </div>
      )}
      {toast && <div className="toast" role="status">{toast}</div>}

      {open !== null && current && items[open] && (
        <ImageInspector
          project={project}
          dataset={active!}
          set={current}
          items={items}
          index={open}
          statuses={statuses}
          author={author}
          isolated={onIsolated}
          onMove={move}
          onSaved={load}
          onIndex={(i) => {
            setOpen(i);
            if (i >= shown) setShown(i + 1);
          }}
          onDecide={decide}
          onComment={(image, comments) =>
            setData((before) => before && {
              ...before,
              statuses: { ...before.statuses, [image]: { ...(before.statuses[image] ?? { status: "unreviewed" }), comments } },
            })}
          onClose={() => setOpen(null)}
        />
      )}

      {shipping && data && active && (
        <ShipDialog
          project={project}
          dataset={active}
          sets={sets}
          statuses={statuses}
          author={author}
          onClose={() => setShipping(false)}
          onShipped={(message) => {
            setShipping(false);
            flash(message);
            void load();
          }}
        />
      )}
    </div>
  );
}

function QaCard({ item, state, project, dataset, isolated, checked, onToggle, onOpen }: {
  item: QaImage;
  isolated: boolean;
  state: QaState | undefined;
  project: string;
  dataset: string;
  checked: boolean;
  onToggle: () => void;
  onOpen: () => void;
}) {
  const status = state?.status ?? "unreviewed";
  const name = item.image.split("/").pop() ?? item.image;
  return (
    <div className={`qa-card status-${status}${checked ? " selected" : ""}`}>
      <button className="qa-thumb" onClick={onOpen} title={name}>
        <img loading="lazy" src={api.mediaUrl(item.image, 320, project, dataset)} alt="" />
        <span className={`qa-chip ${status}`}>{STATUS_LABEL[status]}</span>
        {isolated && item.from && <span className="qa-origin" title={item.reason || undefined}>from {item.from}</span>}
      </button>
      <div className="qa-card-body">
        <input type="checkbox" checked={checked} onChange={onToggle} aria-label={`Select ${name}`} />
        <span className="qa-card-name mono small" title={item.image}>{name}</span>
        <span className="faint small tabular" title="Labelled objects">{item.objects}</span>
        {(state?.comments ?? 0) > 0 && (
          <span className="qa-comments small" title={plural(state!.comments, "comment")}><Icon name="comment" size={12} />{state!.comments}</span>
        )}
      </div>
    </div>
  );
}
