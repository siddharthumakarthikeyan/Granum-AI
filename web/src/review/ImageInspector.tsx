/** One image under review: its labelled boxes (editable), its status, and its comment thread.
 *
 * Boxes: drag on the image to draw one · click a box to select it · Delete removes it.
 * Edits save as one new version of the set when you leave the image (or press Ctrl+S).
 *
 * Keys: ← → images · A verify (and next) · R rework · U unverify · I isolate ·
 * B show boxes · Delete remove box · Esc deselect, then close.
 */

import { useEffect, useMemo, useRef, useState } from "react";
import { api } from "../api/client";
import type { QaBox, QaEvent, QaImage, QaImageDetail, QaState, QaStatus } from "../api/types";
import { Icon, formatNumber, formatWhen, plural } from "../components/ui";
import { CROWD_COLOR, labelColor } from "../images/labelColors";
import { STATUS_LABEL, statusOf, type MoveAction } from "./status";
/** Drags shorter than this, in image pixels, are clicks rather than new boxes. */
const MIN_SIDE = 3;

interface Props {
  project: string;
  dataset: string;
  /** Each image with the set it is in and that set's version it was loaded from. */
  items: (QaImage & { set: string; table: string })[];
  index: number;
  statuses: Record<string, QaState>;
  author: string;
  isolated: boolean;
  onIndex: (index: number) => void;
  onDecide: (images: string[], status: QaStatus, comment?: string) => Promise<boolean>;
  onMove: (images: string[], action: MoveAction, reason?: string) => Promise<boolean>;
  onSaved: () => Promise<void>;
  onComment: (image: string, comments: number) => void;
  onClose: () => void;
}

interface Edits {
  added: number;
  removed: number;
  relabelled: number;
}

const NO_EDITS: Edits = { added: 0, removed: 0, relabelled: 0 };

function colorFor(box: QaBox): string {
  return box.iscrowd ? CROWD_COLOR : labelColor(box.label ?? 0);
}

export function ImageInspector(props: Props) {
  const { project, dataset, items, index, statuses, author, isolated, onIndex, onDecide, onMove, onSaved, onComment, onClose } = props;
  const item = items[index]!;
  const [detail, setDetail] = useState<QaImageDetail | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [draft, setDraft] = useState("");
  const [needsNote, setNeedsNote] = useState(false);
  const [showBoxes, setShowBoxes] = useState(true);
  const [busy, setBusy] = useState(false);
  const [boxes, setBoxes] = useState<QaBox[]>([]);
  const [edits, setEdits] = useState<Edits>(NO_EDITS);
  const [picked, setPicked] = useState<number | null>(null);
  const [hovered, setHovered] = useState<number | null>(null);
  const [drawLabel, setDrawLabel] = useState<number | null>(null);
  const [dragging, setDragging] = useState<{ x0: number; y0: number; x1: number; y1: number } | null>(null);
  const [confirmDelete, setConfirmDelete] = useState(false);
  const [saveState, setSaveState] = useState<"idle" | "saving" | "saved">("idle");
  const noteRef = useRef<HTMLTextAreaElement>(null);
  const svgRef = useRef<SVGSVGElement>(null);
  const status = statusOf(statuses, item.image);
  const dirty = edits.added + edits.removed + edits.relabelled > 0;

  useEffect(() => {
    let alive = true;
    setError(null);
    setNeedsNote(false);
    setConfirmDelete(false);
    api.qaImage(project, dataset, item.table, item.image)
      .then((next) => {
        if (!alive) return;
        setDetail(next);
        setBoxes(next.boxes);
        setEdits(NO_EDITS);
        setPicked(null);
      })
      .catch((e: Error) => alive && setError(e.message));
    return () => {
      alive = false;
    };
  }, [project, dataset, item.table, item.image]);

  const labels = detail?.labels ?? {};
  const labelIds = useMemo(() => Object.keys(labels).map(Number).sort((a, b) => a - b), [labels]);
  // New boxes default to the most common class in the dataset's current image, else the first.
  useEffect(() => {
    if (!detail || (drawLabel !== null && String(drawLabel) in detail.labels)) return;
    const counts = new Map<number, number>();
    for (const box of detail.boxes) if (box.label !== null && !box.iscrowd) counts.set(box.label, (counts.get(box.label) ?? 0) + 1);
    const common = [...counts.entries()].sort((a, b) => b[1] - a[1])[0]?.[0];
    setDrawLabel(common ?? labelIds[0] ?? null);
  }, [detail, drawLabel, labelIds]);

  const labelName = (label: number | null) => (label === null ? "?" : labels[String(label)] ?? String(label));

  // -- saving ---------------------------------------------------------------
  const save = async (): Promise<boolean> => {
    if (!dirty || !detail?.box_column) return true;
    setBusy(true);
    setSaveState("saving");
    try {
      const width = detail.width ?? 0;
      const height = detail.height ?? 0;
      await api.commit({
        url: detail.table,
        values: { [detail.box_column]: { [String(detail.row)]: { width, height, instances: boxes } } },
        new_columns: {},
        value_maps: {},
        description: `Boxes edited in review: ${item.image.split("/").pop()}`,
      });
      const parts = [
        edits.added && `${edits.added} added`,
        edits.removed && `${edits.removed} removed`,
        edits.relabelled && `${edits.relabelled} relabelled`,
      ].filter(Boolean);
      await api.addQaComment({ project, dataset, sample: item.image, comment: `Edited boxes: ${parts.join(", ")}`, author, table: detail.table })
        .catch(() => undefined);
      setEdits(NO_EDITS);
      setSaveState("saved");
      window.setTimeout(() => setSaveState("idle"), 2500);
      await onSaved();
      return true;
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
      setSaveState("idle");
      return false;
    } finally {
      setBusy(false);
    }
  };

  const go = async (next: number) => {
    if (next < 0 || next >= items.length) return;
    if (await save()) onIndex(next);
  };

  const close = async () => {
    if (await save()) onClose();
  };

  // -- review actions ---------------------------------------------------------
  const reloadThread = async () => {
    const next = await api.qaImage(project, dataset, item.table, item.image);
    setDetail((was) => (was ? { ...was, thread: next.thread } : next));
    onComment(item.image, next.thread.filter((e) => e.comment).length);
  };

  const decide = async (next: QaStatus) => {
    const note = draft.trim();
    if (next === "rework" && !note) {
      setNeedsNote(true);
      noteRef.current?.focus();
      return;
    }
    if (!(await save())) return;
    setBusy(true);
    const ok = await onDecide([item.image], next, note);
    setBusy(false);
    if (!ok) return;
    setDraft("");
    setNeedsNote(false);
    if (next === "reviewed" && index < items.length - 1) onIndex(index + 1);
    else void reloadThread().catch(() => undefined);
  };

  const moveImage = async (action: MoveAction) => {
    if (action !== "delete" && !(await save())) return;
    await onMove([item.image], action, draft.trim());
    setDraft("");
    setConfirmDelete(false);
  };

  const comment = async () => {
    const text = draft.trim();
    if (!text) return;
    setBusy(true);
    try {
      const done = await api.addQaComment({ project, dataset, sample: item.image, comment: text, author, table: item.table });
      setDetail((was) => was && { ...was, thread: done.thread });
      onComment(item.image, done.thread.filter((e) => e.comment).length);
      setDraft("");
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };

  // -- box editing ------------------------------------------------------------
  const editable = Boolean(detail?.editable && detail.box_column);
  const width = detail?.width ?? 0;
  const height = detail?.height ?? 0;

  const toImage = (event: React.PointerEvent): { x: number; y: number } | null => {
    const svg = svgRef.current;
    const matrix = svg?.getScreenCTM();
    if (!svg || !matrix) return null;
    const point = new DOMPoint(event.clientX, event.clientY).matrixTransform(matrix.inverse());
    return { x: Math.min(width, Math.max(0, point.x)), y: Math.min(height, Math.max(0, point.y)) };
  };

  const removeBox = (at: number) => {
    setBoxes((was) => was.filter((_, i) => i !== at));
    setEdits((was) => ({ ...was, removed: was.removed + 1 }));
    setPicked(null);
    setHovered(null);
  };

  const relabel = (at: number, label: number) => {
    setBoxes((was) => was.map((box, i) => (i === at ? { ...box, label } : box)));
    setEdits((was) => ({ ...was, relabelled: was.relabelled + 1 }));
  };

  const onPointerDown = (event: React.PointerEvent<SVGSVGElement>) => {
    if (!editable || !showBoxes || event.button !== 0) return;
    const point = toImage(event);
    if (!point) return;
    event.currentTarget.setPointerCapture(event.pointerId);
    setPicked(null);
    setDragging({ x0: point.x, y0: point.y, x1: point.x, y1: point.y });
  };

  const onPointerMove = (event: React.PointerEvent<SVGSVGElement>) => {
    if (!dragging) return;
    const point = toImage(event);
    if (point) setDragging({ ...dragging, x1: point.x, y1: point.y });
  };

  const onPointerUp = () => {
    if (!dragging) return;
    const x0 = Math.min(dragging.x0, dragging.x1);
    const x1 = Math.max(dragging.x0, dragging.x1);
    const y0 = Math.min(dragging.y0, dragging.y1);
    const y1 = Math.max(dragging.y0, dragging.y1);
    setDragging(null);
    if (x1 - x0 < MIN_SIDE || y1 - y0 < MIN_SIDE || drawLabel === null) return;
    const round = (v: number) => Math.round(v * 10) / 10;
    const box: QaBox = {
      vertices: [round(x0), round(y0), round(x1), round(y1)],
      label: drawLabel,
      iscrowd: false,
      area: round((x1 - x0) * (y1 - y0)),
    };
    setBoxes((was) => [...was, box]);
    setEdits((was) => ({ ...was, added: was.added + 1 }));
    setPicked(boxes.length);
  };

  // -- keys -------------------------------------------------------------------
  // The latest handlers, for a key listener registered once.
  const keys = useRef({ decide, go, close, index, picked, removeBox, save, moveImage, isolated, editable });
  keys.current = { decide, go, close, index, picked, removeBox, save, moveImage, isolated, editable };
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      const target = event.target as HTMLElement;
      if (target.tagName === "TEXTAREA" || target.tagName === "INPUT" || target.tagName === "SELECT") {
        if (event.key === "Escape") target.blur();
        return;
      }
      const k = keys.current;
      if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "s") void k.save();
      else if (event.ctrlKey || event.metaKey || event.altKey) return;
      else if (event.key === "Escape") {
        if (k.picked !== null) setPicked(null);
        else void k.close();
      } else if ((event.key === "Delete" || event.key === "Backspace") && k.picked !== null && k.editable) k.removeBox(k.picked);
      else if (event.key === "ArrowRight") void k.go(k.index + 1);
      else if (event.key === "ArrowLeft") void k.go(k.index - 1);
      else if (event.key === "a" || event.key === "A") void k.decide("reviewed");
      else if (event.key === "r" || event.key === "R") void k.decide("rework");
      else if (event.key === "u" || event.key === "U") void k.decide("unreviewed");
      else if ((event.key === "i" || event.key === "I") && !k.isolated) void k.moveImage("isolate");
      else if (event.key === "b" || event.key === "B") setShowBoxes((v) => !v);
      else return;
      event.preventDefault();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  // Leaving the page with unsaved box edits would lose them.
  useEffect(() => {
    if (!dirty) return;
    const warn = (event: BeforeUnloadEvent) => {
      event.preventDefault();
      event.returnValue = "";
    };
    window.addEventListener("beforeunload", warn);
    return () => window.removeEventListener("beforeunload", warn);
  }, [dirty]);

  const name = item.image.split("/").pop() ?? item.image;
  const classCounts = new Map<string, number>();
  for (const box of boxes) {
    const label = labelName(box.label);
    classCounts.set(label, (classCounts.get(label) ?? 0) + 1);
  }
  const pickedBox = picked !== null ? boxes[picked] : undefined;
  // Label size in image pixels, so text reads the same on small and large images.
  const fontSize = Math.max(10, Math.round(Math.max(width, height) / 70));

  return (
    <div className="qa-inspector" role="dialog" aria-modal="true" aria-label={name}>
      <div className="qa-stage">
        <div className="qa-stage-bar">
          <button className="icon-button" onClick={() => void go(index - 1)} disabled={index === 0 || busy} aria-label="Previous image"><Icon name="back" /></button>
          <span className="tabular small">{formatNumber(index + 1)} / {formatNumber(items.length)}</span>
          <button className="icon-button" onClick={() => void go(index + 1)} disabled={index >= items.length - 1 || busy} aria-label="Next image"><Icon name="chevron" /></button>
          <span className="mono small qa-stage-name" title={item.image}>{name}</span>
          <span className="spacer" />
          {editable && (
            <>
              <span className="muted small">Draw as</span>
              <div className="select-wrap qa-draw-class">
                <select value={drawLabel ?? ""} onChange={(e) => setDrawLabel(Number(e.target.value))} aria-label="Class for new boxes">
                  {labelIds.map((id) => <option key={id} value={id}>{labels[String(id)]}</option>)}
                </select>
              </div>
            </>
          )}
          {dirty ? (
            <button className="button primary" onClick={() => void save()} disabled={busy} title="Save box edits as a new version (Ctrl+S)">
              {saveState === "saving" ? "Saving" : `Save ${plural(edits.added + edits.removed + edits.relabelled, "edit")}`}
            </button>
          ) : saveState === "saved" ? (
            <span className="qa-saved small"><Icon name="check" size={13} />Saved</span>
          ) : null}
          <label className="check-row small">
            <input type="checkbox" checked={showBoxes} onChange={(e) => setShowBoxes(e.target.checked)} />
            Boxes <kbd>B</kbd>
          </label>
        </div>
        <div className="qa-canvas">
          {width > 0 && height > 0 ? (
            <svg
              ref={svgRef}
              viewBox={`0 0 ${width} ${height}`}
              preserveAspectRatio="xMidYMid meet"
              className={editable && showBoxes ? "drawable" : ""}
              onPointerDown={onPointerDown}
              onPointerMove={onPointerMove}
              onPointerUp={onPointerUp}
              onPointerCancel={() => setDragging(null)}
            >
              <image href={api.mediaUrl(item.image, undefined, project, dataset)} width={width} height={height} />
              {showBoxes && boxes.map((box, i) => {
                const [x0 = 0, y0 = 0, x1 = 0, y1 = 0] = box.vertices;
                const color = colorFor(box);
                const active = picked === i || hovered === i;
                return (
                  <g
                    key={i}
                    className="qa-box"
                    onPointerDown={(e) => {
                      if (!editable) return;
                      e.stopPropagation();
                      setPicked(i);
                    }}
                    onPointerEnter={() => setHovered(i)}
                    onPointerLeave={() => setHovered((h) => (h === i ? null : h))}
                  >
                    <rect
                      x={x0} y={y0} width={Math.max(0, x1 - x0)} height={Math.max(0, y1 - y0)}
                      fill={picked === i ? "rgba(255,255,255,.12)" : "rgba(0,0,0,0)"}
                      stroke={picked === i ? "#ffffff" : color}
                      strokeWidth={active ? 2.6 : 1.6}
                      strokeDasharray={box.iscrowd ? "3 3" : undefined}
                      vectorEffect="non-scaling-stroke"
                    />
                    {active && (
                      <text x={x0} y={Math.max(fontSize, y0 - 3)} fontSize={fontSize} className="qa-box-label" fill={picked === i ? "#ffffff" : color}>
                        {labelName(box.label)}
                      </text>
                    )}
                  </g>
                );
              })}
              {dragging && (
                <rect
                  x={Math.min(dragging.x0, dragging.x1)} y={Math.min(dragging.y0, dragging.y1)}
                  width={Math.abs(dragging.x1 - dragging.x0)} height={Math.abs(dragging.y1 - dragging.y0)}
                  fill="rgba(34,211,238,.10)" stroke="#22d3ee" strokeWidth={1.6} strokeDasharray="5 3" vectorEffect="non-scaling-stroke"
                  pointerEvents="none"
                />
              )}
            </svg>
          ) : detail ? (
            <img src={api.mediaUrl(item.image, undefined, project, dataset)} alt="" />
          ) : (
            <span className="muted">{error ?? "Loading"}</span>
          )}
        </div>
      </div>

      <aside className="qa-side">
        <div className="qa-side-head">
          <span className={`qa-chip ${status}`}>{STATUS_LABEL[status]}</span>
          <span className="muted small">{isolated ? `isolated from ${item.from ?? "?"}` : item.set} · row {formatNumber(item.row)}</span>
          <span className="spacer" />
          <button className="icon-button" onClick={() => void close()} aria-label="Close"><Icon name="close" /></button>
        </div>

        <div className="qa-side-section">
          <div className="qa-status-buttons">
            <button className={`button${status === "reviewed" ? " on-reviewed" : ""}`} onClick={() => void decide("reviewed")} disabled={busy}>
              <Icon name="check" />Verify <kbd>A</kbd>
            </button>
            <button className={`button${status === "rework" ? " on-rework" : ""}`} onClick={() => void decide("rework")} disabled={busy}>
              <Icon name="pencil" />Rework <kbd>R</kbd>
            </button>
            <button className="button subtle" onClick={() => void decide("unreviewed")} disabled={busy || status === "unreviewed"} title="Back to unverified, e.g. after fixing the labels">
              Unverify <kbd>U</kbd>
            </button>
          </div>
          {statuses[item.image]?.author && status !== "unreviewed" && (
            <p className="faint small">{STATUS_LABEL[status]} by {statuses[item.image]!.author}, {formatWhen(statuses[item.image]!.time)}</p>
          )}
          <div className="qa-move-buttons">
            {isolated ? (
              <button className="button" onClick={() => void moveImage("return")} disabled={busy} title={`Put back into ${item.from ?? "its set"}`}>
                <Icon name="back" />Return to {item.from ?? "set"}
              </button>
            ) : (
              <button className="button" onClick={() => void moveImage("isolate")} disabled={busy} title="Set aside, out of new dataset versions; return it later">
                <Icon name="isolate" />Isolate <kbd>I</kbd>
              </button>
            )}
            {confirmDelete ? (
              <button className="button danger-button" onClick={() => void moveImage("delete")} disabled={busy}>Confirm delete</button>
            ) : (
              <button className="button danger-button" onClick={() => setConfirmDelete(true)} disabled={busy} title="Move to the removed set; recoverable from Removed on the Images tab">
                <Icon name="trash" />Delete
              </button>
            )}
          </div>
          {item.reason && isolated && <p className="faint small">Isolated: {item.reason}</p>}
        </div>

        <div className="qa-side-section">
          <h3 className="qa-side-title">
            Boxes <span className="faint">{formatNumber(boxes.length)}</span>
            {editable && <span className="faint qa-hint">drag to draw · click to select · Del removes</span>}
          </h3>
          {pickedBox && editable && (
            <div className="qa-picked">
              <span className="qa-swatch" style={{ background: colorFor(pickedBox) }} />
              <div className="select-wrap">
                <select value={pickedBox.label ?? ""} onChange={(e) => relabel(picked!, Number(e.target.value))} aria-label="Class of the selected box">
                  {labelIds.map((id) => <option key={id} value={id}>{labels[String(id)]}</option>)}
                </select>
              </div>
              <span className="faint small tabular">
                {Math.round((pickedBox.vertices[2] ?? 0) - (pickedBox.vertices[0] ?? 0))}×{Math.round((pickedBox.vertices[3] ?? 0) - (pickedBox.vertices[1] ?? 0))}
              </span>
              <button className="icon-button" onClick={() => removeBox(picked!)} aria-label="Delete box" title="Delete box (Del)"><Icon name="trash" size={14} /></button>
            </div>
          )}
          <ul className="qa-classes">
            {[...classCounts.entries()].sort((a, b) => b[1] - a[1]).map(([label, n]) => (
              <li key={label}><span>{label}</span><span className="tabular muted">{formatNumber(n)}</span></li>
            ))}
            {detail && classCounts.size === 0 && <li className="faint">No boxes</li>}
          </ul>
        </div>

        <div className="qa-side-section qa-thread-section">
          <h3 className="qa-side-title">Activity</h3>
          <ol className="qa-thread">
            {(detail?.thread ?? []).map((event, i) => <ThreadItem key={i} event={event} />)}
            {detail && detail.thread.length === 0 && <li className="faint small">No comments</li>}
          </ol>
        </div>

        <div className="qa-compose">
          <textarea
            ref={noteRef}
            value={draft}
            onChange={(e) => {
              setDraft(e.target.value);
              if (e.target.value.trim()) setNeedsNote(false);
            }}
            onKeyDown={(e) => {
              if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) void comment();
            }}
            placeholder={needsNote ? "Describe what needs rework, then press Rework" : "Comment, or the reason for rework / isolate / delete"}
            className={needsNote ? "needs-note" : ""}
            rows={3}
            maxLength={4000}
          />
          <div className="qa-compose-bar">
            <span className="faint small">{author ? `as ${author}` : "Set your name under Review in the ribbon"}</span>
            <span className="spacer" />
            <button className="button" onClick={() => void comment()} disabled={busy || !draft.trim()}>Comment</button>
          </div>
        </div>
        {error && detail && <p className="form-error qa-side-error">{error}</p>}
      </aside>
    </div>
  );
}

export function ThreadItem({ event }: { event: QaEvent }) {
  return (
    <li className={`qa-event${event.status ? ` status-${event.status}` : ""}`}>
      <div className="qa-event-head small">
        <span className="strong">{event.author || "Someone"}</span>
        {event.status && <span className={`qa-chip ${event.status}`}>{STATUS_LABEL[event.status]}</span>}
        <span className="faint">{formatWhen(event.time)}</span>
      </div>
      {event.comment && <p className="qa-event-body">{event.comment}</p>}
    </li>
  );
}
