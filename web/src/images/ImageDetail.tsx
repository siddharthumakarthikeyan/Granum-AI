/** One image, opened full screen from the gallery, laid out like the review inspector.
 *
 * The class list is what this image actually contains. Picking a class isolates it: the
 * rest of the image darkens and only that class's boxes stay lit, which is the quickest
 * way to see whether one class is labelled consistently across a set. Below it every
 * instance is listed; picking one lights that box alone.
 */

import { useEffect, useId, useMemo, useState } from "react";
import { api } from "../api/client";
import type { ImageBoxes, ImageRow, QaEvent, QaState } from "../api/types";
import { Icon, formatNumber, formatWhen, plural } from "../components/ui";
import { ThreadItem } from "../review/ImageInspector";
import { STATUS_LABEL, fileName } from "../review/status";
import { isFlagged } from "./ImagesPage";
import { labelColor } from "./labelColors";

interface Props {
  project: string;
  dataset: string;
  item: ImageRow;
  /** Position in the filtered gallery, for the "9 / 12,429" counter. */
  index: number;
  total: number;
  state: QaState | undefined;
  labels: Record<string, string>;
  boxes: ImageBoxes | undefined;
  /** An object to pick out on opening: the patch this was opened from, if it was one. */
  instance?: number | null;
  hasPrev: boolean;
  hasNext: boolean;
  onStep: (step: number) => void;
  author: string;
  /** Post a comment; the image goes back to unverified. */
  onComment: (text: string) => Promise<boolean>;
  /** Open this image in review, to edit its boxes or comment. */
  onEdit: () => void;
  /** The gallery behind is already compared against this image. */
  like: boolean;
  /** Reorder the gallery by how alike each image is to this one. */
  onLike: () => void;
  onClose: () => void;
}

export function ImageDetail({ project, dataset, item, index: position, total, state, labels, boxes, instance: opening, hasPrev, hasNext, onStep, author, onComment, onEdit, like, onLike, onClose }: Props) {
  const [isolated, setIsolated] = useState<Set<number>>(new Set());
  const [instance, setInstance] = useState<number | null>(null);
  const [hovered, setHovered] = useState<number | null>(null);
  const [busy, setBusy] = useState(false);
  const maskId = useId();

  // A different image starts fresh: its classes are not the ones just isolated. Opened from
  // a patch, it starts on that object -- that object is the reason the viewer was opened.
  useEffect(() => {
    setIsolated(new Set());
    setInstance(opening ?? null);
    setHovered(null);
  }, [item.image, opening]);

  const status = state?.status ?? "unreviewed";

  const [writing, setWriting] = useState(false);
  const [text, setText] = useState("");
  const [thread, setThread] = useState<QaEvent[] | null>(null);

  // The comment thread is fetched per image; the gallery payload carries only counts.
  useEffect(() => {
    let alive = true;
    setThread(null);
    setWriting(false);
    setText("");
    api.qaImage(project, dataset, item.table, item.image)
      .then((detail) => alive && setThread(detail.thread))
      .catch(() => alive && setThread([]));
    return () => {
      alive = false;
    };
  }, [project, dataset, item.table, item.image]);

  const post = async () => {
    const comment = text.trim();
    if (!comment) return;
    setBusy(true);
    const ok = await onComment(comment);
    setBusy(false);
    if (!ok) return;
    setText("");
    setWriting(false);
    setThread((was) => [...(was ?? []), { sample: item.image, status: "unreviewed", comment, author, time: new Date().toISOString() } as QaEvent]);
  };

  useEffect(() => {
    const key = (event: KeyboardEvent) => {
      const target = event.target as HTMLElement | null;
      if (target && (target.tagName === "INPUT" || target.tagName === "TEXTAREA" || target.tagName === "SELECT")) return;
      if (event.ctrlKey || event.metaKey || event.altKey) return;
      if (event.key === "Escape") {
        if (instance !== null) setInstance(null);
        else onClose();
      } else if (event.key === "ArrowLeft" && hasPrev) onStep(-1);
      else if (event.key === "ArrowRight" && hasNext) onStep(1);
      else if ((event.key === "c" || event.key === "C") && !writing) {
        event.preventDefault();
        setWriting(true);
      }
    };
    window.addEventListener("keydown", key);
    return () => window.removeEventListener("keydown", key);
  });

  /** The classes this image uses, most boxes first, with how many boxes each has. */
  const present = useMemo(() => {
    const counts = new Map<number, number>();
    if (boxes) {
      for (const [label] of boxes.b) if (label !== null) counts.set(label, (counts.get(label) ?? 0) + 1);
    } else {
      for (const label of item.classes) counts.set(label, 0);
    }
    return [...counts.entries()].sort((a, b) => b[1] - a[1] || a[0] - b[0]);
  }, [boxes, item.classes]);

  /** Every box with its index in the image, numbered within its class, in class order. */
  const instances = useMemo(() => {
    if (!boxes) return [];
    const rank = new Map(present.map(([label], i) => [label, i]));
    const seen = new Map<number | null, number>();
    const all = boxes.b.map((box, index) => {
      const n = (seen.get(box[0]) ?? 0) + 1;
      seen.set(box[0], n);
      return { index, label: box[0], n, box };
    });
    return all.sort((a, b) => (rank.get(a.label ?? -1) ?? 1e9) - (rank.get(b.label ?? -1) ?? 1e9) || a.index - b.index);
  }, [boxes, present]);

  const listed = isolated.size === 0 ? instances : instances.filter((i) => i.label !== null && isolated.has(i.label));

  const toggleClass = (label: number) => {
    setInstance(null);
    setIsolated((was) => {
      const next = new Set(was);
      if (next.has(label)) next.delete(label);
      else next.add(label);
      return next;
    });
  };

  const lit = (index: number, label: number | null) =>
    instance !== null ? index === instance : isolated.size === 0 || (label !== null && isolated.has(label));
  const shown = boxes?.b.map((box, index) => ({ box, index })).filter(({ box, index }) => lit(index, box[0])) ?? [];
  const masking = instance !== null || isolated.size > 0;
  const labelName = (label: number | null) => (label === null ? "Unlabelled" : labels[String(label)] ?? String(label));

  const aspect = boxes && boxes.h ? boxes.w / boxes.h : 4 / 3;

  return (
    <div className="qa-inspector image-viewer" role="dialog" aria-modal="true" aria-label={fileName(item.image)}>
      <div className="qa-stage">
        <div className="qa-stage-bar">
          <button className="icon-button" disabled={!hasPrev} onClick={() => onStep(-1)} aria-label="Previous image"><Icon name="back" /></button>
          <span className="tabular small">{formatNumber(position + 1)} / {formatNumber(total)}</span>
          <button className="icon-button" disabled={!hasNext} onClick={() => onStep(1)} aria-label="Next image"><Icon name="chevron" /></button>
          <span className="mono small qa-stage-name" title={item.image}>{fileName(item.image)}</span>
          <span className="spacer" />
          {masking && (
            <button className="button subtle" onClick={() => { setIsolated(new Set()); setInstance(null); }}>Show all boxes</button>
          )}
        </div>
        <div className="image-viewer-canvas">
          <div className="image-detail-stage" style={{ aspectRatio: `${aspect}`, width: `min(100%, calc((100vh - 76px) * ${aspect}))` }}>
            <img src={api.mediaUrl(item.image, undefined, project, dataset)} alt="" />
            {boxes && (
              <svg className="box-layer" viewBox="0 0 1 1" preserveAspectRatio="none">
                {masking && (
                  <>
                    <defs>
                      <mask id={maskId} maskUnits="userSpaceOnUse" x="0" y="0" width="1" height="1">
                        {/* White keeps the shade, black cuts a window over each lit box. */}
                        <rect x="0" y="0" width="1" height="1" fill="white" />
                        {shown.map(({ box: [, x0, y0, x1, y1], index }) => (
                          <rect key={index} x={x0} y={y0} width={Math.max(0, x1 - x0)} height={Math.max(0, y1 - y0)} fill="black" />
                        ))}
                      </mask>
                    </defs>
                    <rect x="0" y="0" width="1" height="1" fill="#04060a" opacity="0.84" mask={`url(#${maskId})`} />
                  </>
                )}
                {shown.map(({ box: [label, x0, y0, x1, y1], index }) => (
                  <rect
                    key={index}
                    x={x0}
                    y={y0}
                    width={Math.max(0, x1 - x0)}
                    height={Math.max(0, y1 - y0)}
                    fill={hovered === index ? "rgba(255,255,255,.14)" : "none"}
                    stroke={labelColor(label)}
                    strokeWidth={hovered === index || instance === index ? 2.5 : 1.5}
                    vectorEffect="non-scaling-stroke"
                  />
                ))}
              </svg>
            )}
          </div>
        </div>
      </div>

      <aside className="qa-side">
        <div className="qa-side-head">
          <span className={`qa-chip ${status}`}>{STATUS_LABEL[status]}</span>
          <span className="muted small">{item.set} · {plural(item.objects, "object")}</span>
          <span className="spacer" />
          <button className="icon-button" onClick={onClose} aria-label="Close"><Icon name="close" /></button>
        </div>

        <div className="qa-side-section">
          {writing ? (
            <div className="viewer-comment">
              <textarea
                autoFocus
                rows={3}
                value={text}
                placeholder="What is wrong or worth a note?"
                onChange={(e) => setText(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) void post();
                  if (e.key === "Escape") {
                    e.stopPropagation();
                    setWriting(false);
                  }
                }}
              />
              <div className="viewer-comment-bar">
                <span className="faint small">{author ? `as ${author}` : "Posts unsigned"} · marks it unverified</span>
                <span className="spacer" />
                <button className="button subtle small" onClick={() => setWriting(false)}>Cancel</button>
                <button className="button primary small" disabled={busy || !text.trim()} onClick={() => void post()}>Post</button>
              </div>
            </div>
          ) : (
            <button className="button viewer-verify" onClick={() => setWriting(true)} title="Add a comment; the image goes back to unverified (C)">
              <Icon name="comment" size={14} />Add comment <kbd>C</kbd>
            </button>
          )}
          <p className="faint small viewer-verify-note">
            {state?.time ? `${STATUS_LABEL[status]}${state.author ? ` by ${state.author}` : ""}, ${formatWhen(state.time)}` : "Not reviewed yet"}
            {status === "rework" && state?.note ? ` · ${state.note}` : ""}
          </p>
          {thread && thread.some((e) => e.comment) && (
            <ol className="qa-thread viewer-thread">
              {thread.filter((e) => e.comment).map((event, i) => <ThreadItem key={i} event={event} />)}
            </ol>
          )}
        </div>

        <div className="qa-side-section">
          <h3 className="qa-side-title">Classes <span className="faint">{formatNumber(present.length)}</span></h3>
          {present.length === 0 ? (
            <p className="muted small">No labelled objects.</p>
          ) : (
            <ul className="class-list">
              {present.map(([label, count]) => {
                const on = isolated.has(label);
                return (
                  <li key={label}>
                    <button
                      className={`class-chip${on ? " on" : ""}${isolated.size > 0 && !on ? " dimmed" : ""}`}
                      aria-pressed={on}
                      onClick={() => toggleClass(label)}
                      title={on ? "Show every class again" : "Show only this class"}
                    >
                      <span className="class-swatch" style={{ background: labelColor(label) }} />
                      <span className="truncate">{labelName(label)}</span>
                      {boxes && <span className="faint small tabular">{formatNumber(count)}</span>}
                    </button>
                  </li>
                );
              })}
            </ul>
          )}
        </div>

        {boxes && listed.length > 0 && (
          <div className="qa-side-section viewer-instances">
            <h3 className="qa-side-title">Instances <span className="faint">{formatNumber(listed.length)}</span></h3>
            <ul className="instance-list" onMouseLeave={() => setHovered(null)}>
              {listed.map(({ index, label, n, box: [, x0, y0, x1, y1] }) => {
                const on = instance === index;
                return (
                  <li key={index}>
                    <button
                      // Opened from a patch, the object that was clicked can be anywhere in a
                      // list of a hundred and twenty: bring it to where the reader is looking.
                      ref={(node) => { if (on) node?.scrollIntoView({ block: "nearest" }); }}
                      className={`instance-row${on ? " on" : ""}`}
                      aria-pressed={on}
                      onClick={() => setInstance(on ? null : index)}
                      onMouseEnter={() => setHovered(index)}
                      title={on ? "Show every box again" : "Show only this instance"}
                    >
                      <span className="class-swatch" style={{ background: labelColor(label) }} />
                      <span className="truncate">{labelName(label)} <span className="faint">#{n}</span></span>
                      <span className="faint small tabular">
                        {Math.round((x1 - x0) * boxes.w)} × {Math.round((y1 - y0) * boxes.h)}
                      </span>
                    </button>
                  </li>
                );
              })}
            </ul>
          </div>
        )}

        <div className="qa-side-section viewer-foot">
          <dl className="image-meta">
            {isFlagged(state) && status !== "rework" && (
              <div><dt>Comments</dt><dd>{formatNumber(state?.comments ?? 0)}</dd></div>
            )}
            {boxes && <div><dt>Size</dt><dd className="tabular">{boxes.w} × {boxes.h}</dd></div>}
            <div><dt>Updated</dt><dd>{state?.time ? formatWhen(state.time) : "—"}</dd></div>
          </dl>
          <button
            className="button subtle"
            onClick={onLike}
            disabled={like}
            title={like ? "The gallery behind is already the images most like this one" : "Close this and show the images in the dataset most like this one, most alike first"}
          >
            <Icon name="search" />Find images like this
          </button>
          <button className="button subtle" onClick={onEdit} title="Move, resize, draw and delete boxes, masks and keypoints">
            <Icon name="pencil" />Edit annotations
          </button>
        </div>
      </aside>
    </div>
  );
}
