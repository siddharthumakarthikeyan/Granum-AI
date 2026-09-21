/** One image, full screen: zoom into the boxes, step through training round by round, and
 * decide whether the image stays in the dataset.
 *
 * Keys: ← → images · [ ] rounds · space plays the rounds · K keep · R remove · U undo ·
 * L labels · G model's boxes · M only mistakes · F fit · + − zoom · Esc close.
 */

import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import { api } from "../api/client";
import type { ImageRound, ImageRounds, LearningCategory } from "../api/types";
import { BoxShapes } from "../boxes/BoxOverlay";
import { ROLE_NAMES, ROLE_STYLE, type BoxRole, type DrawnBox } from "../boxes/model";
import { Icon, formatNumber, plural } from "../components/ui";
import { REMOVE_REASONS, type Decisions } from "./decisions";

export interface ViewerItem {
  example_id: number;
  image: string | null;
  /** The run-wide learning category, when known; "insufficient" withholds a verdict. */
  category?: LearningCategory;
}

interface Props {
  project: string;
  runUrl: string;
  table: string;
  dataset: string;
  setName: string;
  items: ViewerItem[];
  index: number;
  onIndex: (index: number) => void;
  decisions: Decisions;
  good: number;
  onClose: () => void;
}

const MIN_ZOOM = 1;
const MAX_ZOOM = 16;
const PLAY_MS = 700;

const roundName = (epoch: number) => `epoch ${epoch + 1}`;

function isPerfect(round: ImageRound, labelled: number): boolean {
  return round.fp === 0 && round.fn === 0 && round.tp === labelled;
}

export function ImageViewer({ project, runUrl, table, dataset, setName, items, index, onIndex, decisions, good, onClose }: Props) {
  const item = items[index];
  const [data, setData] = useState<ImageRounds | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [roundAt, setRoundAt] = useState<number | null>(null);
  const [showLabels, setShowLabels] = useState(true);
  const [showGuesses, setShowGuesses] = useState(true);
  const [mistakesOnly, setMistakesOnly] = useState(false);
  const [playing, setPlaying] = useState(false);
  const [advance, setAdvance] = useState(true);
  const [reason, setReason] = useState(REMOVE_REASONS[0]!);
  const [hovered, setHovered] = useState<DrawnBox | null>(null);

  // -- data ---------------------------------------------------------------
  useEffect(() => {
    if (!item) return;
    let alive = true;
    setLoading(true);
    setError(null);
    setPlaying(false);
    api.imageRounds(runUrl, table, item.example_id, good)
      .then((next) => {
        if (!alive) return;
        setData(next);
        // Open on the last round: how the finished model sees the image.
        setRoundAt(next.rounds.length ? next.rounds.length - 1 : null);
      })
      .catch((e: Error) => alive && setError(e.message))
      .finally(() => alive && setLoading(false));
    return () => {
      alive = false;
    };
  }, [runUrl, table, item, good]);

  const rounds = data?.rounds ?? [];
  const round = roundAt !== null ? rounds[roundAt] ?? null : null;
  const labelled = data ? data.truth.filter((t) => !t.iscrowd).length : 0;

  // -- zoom and pan ---------------------------------------------------------
  const stageRef = useRef<HTMLDivElement>(null);
  const [stage, setStage] = useState({ width: 800, height: 600 });
  const [view, setView] = useState({ zoom: 1, x: 0, y: 0 });
  const drag = useRef<{ x: number; y: number; vx: number; vy: number } | null>(null);
  const imageWidth = data?.width || 1;
  const imageHeight = data?.height || 1;
  const fit = Math.min(stage.width / imageWidth, stage.height / imageHeight) || 1;

  useLayoutEffect(() => {
    const element = stageRef.current;
    if (!element) return;
    const observer = new ResizeObserver(([entry]) => {
      if (entry) setStage({ width: entry.contentRect.width, height: entry.contentRect.height });
    });
    observer.observe(element);
    return () => observer.disconnect();
  }, []);

  const fitView = useCallback(() => {
    setView({ zoom: 1, x: (stage.width - imageWidth * fit) / 2, y: (stage.height - imageHeight * fit) / 2 });
  }, [stage.width, stage.height, imageWidth, imageHeight, fit]);

  // A new image, or a resized window, starts from the whole image.
  useEffect(() => fitView(), [fitView, data?.image]);

  const zoomAt = useCallback((factor: number, cx: number, cy: number) => {
    setView((v) => {
      const zoom = Math.min(MAX_ZOOM, Math.max(MIN_ZOOM, v.zoom * factor));
      if (zoom === MIN_ZOOM) {
        return { zoom, x: (stage.width - imageWidth * fit) / 2, y: (stage.height - imageHeight * fit) / 2 };
      }
      const ratio = zoom / v.zoom;
      return { zoom, x: cx - (cx - v.x) * ratio, y: cy - (cy - v.y) * ratio };
    });
  }, [stage.width, stage.height, imageWidth, imageHeight, fit]);

  const onWheel = (event: React.WheelEvent) => {
    const box = stageRef.current!.getBoundingClientRect();
    zoomAt(event.deltaY < 0 ? 1.2 : 1 / 1.2, event.clientX - box.left, event.clientY - box.top);
  };

  // React's wheel listener is passive; stop the page from scrolling behind the viewer.
  useEffect(() => {
    const element = stageRef.current;
    if (!element) return;
    const prevent = (event: WheelEvent) => event.preventDefault();
    element.addEventListener("wheel", prevent, { passive: false });
    return () => element.removeEventListener("wheel", prevent);
  }, []);

  // -- boxes --------------------------------------------------------------
  const boxes = useMemo<DrawnBox[]>(() => {
    if (!data) return [];
    const out: DrawnBox[] = [];
    const name = (label: number | null) => (label === null ? "object" : data.labels[String(label)] ?? `class ${label}`);
    const push = (column: string, i: number, vertices: number[], label: number | null, role: BoxRole, confidence: number | null) => {
      const [x0 = 0, y0 = 0, x1 = 0, y1 = 0] = vertices;
      const style = ROLE_STYLE[role];
      out.push({
        column, index: i, role, x0, y0, x1, y1, label,
        text: `${name(label)}${confidence !== null ? ` ${confidence.toFixed(2)}` : ""} · ${ROLE_NAMES[role].toLowerCase()}`,
        color: style.color, dash: style.dash, opacity: 1, confidence, iou: null,
      });
    };
    const guesses = showGuesses && round?.boxes ? round.boxes : null;
    if (showLabels) {
      data.truth.forEach((t, i) => {
        const match = round?.gt_match?.[i];
        const role: BoxRole = t.iscrowd || match === -2 ? "skip" : guesses && match === -1 ? "missed" : "truth";
        if (mistakesOnly && role !== "missed") return;
        push("truth", i, t.vertices, t.label, role, null);
      });
    }
    guesses?.forEach((b, i) => {
      const role: BoxRole = b.matched ? "matched" : b.ignored ? "skipped" : "unmatched";
      if (mistakesOnly && role !== "unmatched") return;
      push("guess", i, b.vertices, b.label, role, typeof b.confidence === "number" ? b.confidence : null);
    });
    return out;
  }, [data, round, showLabels, showGuesses, mistakesOnly]);

  // -- decisions ------------------------------------------------------------
  const image = data?.image ?? item?.image ?? null;
  const decision = image ? decisions.byImage.get(image) : undefined;
  const next = useCallback(() => index < items.length - 1 && onIndex(index + 1), [index, items.length, onIndex]);
  const previous = useCallback(() => index > 0 && onIndex(index - 1), [index, onIndex]);

  const decide = useCallback((choice: "keep" | "remove" | "clear") => {
    if (!image || decision === "removed") return;
    void decisions.decide([image], choice, choice === "remove" ? reason : "");
    if (advance && choice !== "clear") next();
  }, [image, decision, decisions, reason, advance, next]);

  // -- playback and keys ------------------------------------------------------
  useEffect(() => {
    if (!playing || rounds.length === 0) return;
    const timer = window.setInterval(() => {
      setRoundAt((at) => {
        const nextAt = (at ?? -1) + 1;
        if (nextAt >= rounds.length) {
          setPlaying(false);
          return rounds.length - 1;
        }
        return nextAt;
      });
    }, PLAY_MS);
    return () => window.clearInterval(timer);
  }, [playing, rounds.length]);

  const stepRound = useCallback((delta: number) => {
    setPlaying(false);
    setRoundAt((at) => (rounds.length ? Math.min(rounds.length - 1, Math.max(0, (at ?? 0) + delta)) : null));
  }, [rounds.length]);

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      const target = event.target as HTMLElement | null;
      if (target && /^(INPUT|TEXTAREA|SELECT)$/.test(target.tagName)) return;
      if (event.ctrlKey || event.metaKey || event.altKey) return;
      const key = event.key;
      const handled = true;
      if (key === "Escape") onClose();
      else if (key === "ArrowRight") next();
      else if (key === "ArrowLeft") previous();
      else if (key === "]" || key === ".") stepRound(1);
      else if (key === "[" || key === ",") stepRound(-1);
      else if (key === "Home") setRoundAt(rounds.length ? 0 : null);
      else if (key === "End") setRoundAt(rounds.length ? rounds.length - 1 : null);
      else if (key === " ") {
        if (roundAt === rounds.length - 1) setRoundAt(0);
        setPlaying((p) => !p);
      } else if (key === "k" || key === "K") decide("keep");
      else if (key === "r" || key === "R") decide("remove");
      else if (key === "u" || key === "U") decide("clear");
      else if (key === "l" || key === "L") setShowLabels((v) => !v);
      else if (key === "g" || key === "G") setShowGuesses((v) => !v);
      else if (key === "m" || key === "M") setMistakesOnly((v) => !v);
      else if (key === "f" || key === "F" || key === "0") fitView();
      else if (key === "+" || key === "=") zoomAt(1.5, stage.width / 2, stage.height / 2);
      else if (key === "-") zoomAt(1 / 1.5, stage.width / 2, stage.height / 2);
      else return;
      if (handled) {
        event.preventDefault();
        event.stopImmediatePropagation();
      }
    };
    window.addEventListener("keydown", onKey, true);
    return () => window.removeEventListener("keydown", onKey, true);
  }, [onClose, next, previous, stepRound, rounds.length, roundAt, decide, fitView, zoomAt, stage.width, stage.height]);

  // -- the story of this image ------------------------------------------------
  const verdict = useMemo(() => {
    if (!data) return null;
    const last = rounds[rounds.length - 1];
    const best = rounds.reduce<ImageRound | null>((b, r) => (!b || r.f1 > b.f1 ? r : b), null);
    if (labelled === 0 && last && last.fp === 0) {
      return { tone: "pass", title: "Empty, correctly", detail: "No labels and no predictions in the last epoch." };
    }
    if (item?.category === "insufficient" || rounds.length < 3) {
      return {
        tone: "neutral",
        title: "Too few observations",
        detail: `Seen in ${plural(rounds.length, "epoch")}. An image needs at least 3 observations, in at least half the recorded epochs, before it is called learned or not learned.`,
      };
    }
    // The page's category is run-wide; the verdict must not contradict it.
    const drops = rounds.filter((r, i) => i > 0 && rounds[i - 1]!.f1 >= good && r.f1 < good).length;
    if (item?.category === "forgotten") {
      return {
        tone: "warn",
        title: "Unstable",
        detail: data.learned_from !== null
          ? `Dropped below F1 ${good} ${plural(drops, "time")} before holding from ${roundName(data.learned_from)}.`
          : `Dropped below F1 ${good} ${plural(drops, "time")}; ended at ${last?.f1.toFixed(2)}.`,
      };
    }
    if (data.perfect_from !== null) {
      return {
        tone: "pass",
        title: `Perfect from ${roundName(data.perfect_from)}`,
        detail: `All ${plural(labelled, "label")} matched with no false positives in every epoch since.`,
      };
    }
    if (data.learned_from !== null && last) {
      return {
        tone: "good",
        title: `Learned from ${roundName(data.learned_from)}`,
        detail: `F1 ≥ ${good} since then. Last epoch: ${last.fn} missed, ${last.fp} false positives.`,
      };
    }
    if (best && best.f1 >= good) {
      return {
        tone: "warn",
        title: "Unstable",
        detail: `Peaked at F1 ${best.f1.toFixed(2)} in ${roundName(best.epoch)}, ended at ${last?.f1.toFixed(2)}.`,
      };
    }
    return {
      tone: "block",
      title: `Not learned in ${plural(rounds.length, "epoch")}`,
      detail: best
        ? `Best F1 ${(Math.floor(best.f1 * 100) / 100).toFixed(2)} in ${roundName(best.epoch)}, threshold ${good}.`
        : "No epochs recorded for this image.",
    };
  }, [data, rounds, labelled, good, item?.category]);

  // Keep the selected round visible in a long strip (60 epochs do not fit).
  const stripRef = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const cell = stripRef.current?.querySelector<HTMLElement>(".round-cell.on");
    cell?.scrollIntoView({ block: "nearest", inline: "nearest" });
  }, [roundAt, data]);

  const hasAnyBoxes = rounds.some((r) => r.boxes !== null);
  const scale = fit * view.zoom;
  const file = (image ?? "").split("/").pop();

  return (
    <div className="viewer" role="dialog" aria-modal="true" aria-label={`Image ${index + 1} of ${items.length}`}>
      <header className="viewer-bar">
        <button className="icon-button" onClick={previous} disabled={index === 0} aria-label="Previous image (←)" title="Previous image (←)">
          <Icon name="back" />
        </button>
        <span className="viewer-count">
          <span className="strong">{formatNumber(index + 1)}</span>
          <span className="muted"> of {formatNumber(items.length)}</span>
        </span>
        <button className="icon-button" onClick={next} disabled={index >= items.length - 1} aria-label="Next image (→)" title="Next image (→)">
          <Icon name="chevron" />
        </button>
        <span className="viewer-file muted" title={image ?? ""}>{dataset} / {setName} / {file}</span>
        <span className="spacer" />
        {loading && <span className="muted small"><span className="spinner" /> Loading</span>}
        <button className="icon-button" onClick={onClose} aria-label="Close (Esc)" title="Close (Esc)"><Icon name="close" /></button>
      </header>

      <div className="viewer-body">
        <div className="viewer-stage-wrap">
          <div className="viewer-layers">
            <button className={`chip${showLabels ? " on" : ""}`} onClick={() => setShowLabels(!showLabels)} aria-pressed={showLabels} title="L">
              Labels
            </button>
            <button
              className={`chip${showGuesses ? " on" : ""}`}
              onClick={() => setShowGuesses(!showGuesses)}
              aria-pressed={showGuesses}
              disabled={!hasAnyBoxes}
              title={hasAnyBoxes ? "G" : "This run did not save the model's boxes"}
            >
              Predictions{round ? `, ${roundName(round.epoch)}` : ""}
            </button>
            <button className={`chip${mistakesOnly ? " on" : ""}`} onClick={() => setMistakesOnly(!mistakesOnly)} aria-pressed={mistakesOnly} title="M">
              Errors only
            </button>
          </div>

          <div
            ref={stageRef}
            className={`viewer-stage${loading ? " loading" : ""}`}
            onWheel={onWheel}
            onPointerDown={(event) => {
              (event.target as Element).setPointerCapture?.(event.pointerId);
              drag.current = { x: event.clientX, y: event.clientY, vx: view.x, vy: view.y };
            }}
            onPointerMove={(event) => {
              if (!drag.current || view.zoom === MIN_ZOOM) return;
              const d = drag.current;
              setView((v) => ({ ...v, x: d.vx + event.clientX - d.x, y: d.vy + event.clientY - d.y }));
            }}
            onPointerUp={() => { drag.current = null; }}
            onDoubleClick={(event) => {
              const box = stageRef.current!.getBoundingClientRect();
              if (view.zoom > 1.01) fitView();
              else zoomAt(4, event.clientX - box.left, event.clientY - box.top);
            }}
          >
            {data && image && (
              <div
                className="viewer-canvas"
                style={{ width: imageWidth * scale, height: imageHeight * scale, transform: `translate(${view.x}px, ${view.y}px)` }}
              >
                <img src={api.mediaUrl(image, undefined, project, dataset)} alt="" draggable={false} />
                <svg viewBox={`0 0 ${imageWidth} ${imageHeight}`} preserveAspectRatio="none">
                  <BoxShapes
                    boxes={boxes}
                    annotate="selected"
                    hovered={hovered}
                    stroke={view.zoom > 3 ? 2 : 1.5}
                    fontSize={13 / scale}
                    onBoxHover={setHovered}
                  />
                </svg>
              </div>
            )}
            {error && <p className="form-error viewer-error">{error}</p>}
          </div>

          <div className="viewer-zoom">
            <button className="icon-button" onClick={() => zoomAt(1 / 1.5, stage.width / 2, stage.height / 2)} aria-label="Zoom out (−)" title="Zoom out (−)">−</button>
            <span className="small">{Math.round(view.zoom * 100)}%</span>
            <button className="icon-button" onClick={() => zoomAt(1.5, stage.width / 2, stage.height / 2)} aria-label="Zoom in (+)" title="Zoom in (+)">+</button>
            <button className="button subtle small-button" onClick={fitView} title="F">Whole image</button>
            <span className="faint small viewer-hint">Scroll to zoom, drag to pan</span>
          </div>

          <ul className="viewer-legend small" aria-label="What the boxes mean">
            {(["truth", "missed", "matched", "unmatched"] as BoxRole[]).map((role) => (
              <li key={role}>
                <svg width="18" height="12" aria-hidden="true">
                  <rect x="1" y="1" width="16" height="10" fill="none" stroke={ROLE_STYLE[role].color} strokeWidth="2" strokeDasharray={ROLE_STYLE[role].dash ?? undefined} />
                </svg>
                {ROLE_NAMES[role]}
              </li>
            ))}
          </ul>
        </div>

        <aside className="viewer-side">
          {verdict && (
            <section className={`viewer-verdict tone-${verdict.tone}`}>
              <h2>{verdict.title}</h2>
              <p className="small">{verdict.detail}</p>
            </section>
          )}

          {rounds.length > 0 && (
            <section className="viewer-section">
              <div className="viewer-section-head">
                <h3>Epochs</h3>
                <span className="spacer" />
                <button className="icon-button" onClick={() => stepRound(-1)} disabled={!roundAt} aria-label="Previous round ([)" title="Previous round ([)">‹</button>
                <button
                  className="button subtle small-button"
                  onClick={() => {
                    if (roundAt === rounds.length - 1) setRoundAt(0);
                    setPlaying(!playing);
                  }}
                  title="Space"
                >
                  {playing ? "Pause" : "Play"}
                </button>
                <button className="icon-button" onClick={() => stepRound(1)} disabled={roundAt === rounds.length - 1} aria-label="Next round (])" title="Next round (])">›</button>
              </div>
              <div ref={stripRef} className="round-strip" role="listbox" aria-label="Rounds" style={{ "--good": good } as React.CSSProperties}>
                {rounds.map((r, i) => {
                  const perfect = isPerfect(r, labelled);
                  // Forgotten: at or above the threshold in the previous observation, below it now.
                  const dropped = i > 0 && rounds[i - 1]!.f1 >= good && r.f1 < good;
                  return (
                    <button
                      key={r.epoch}
                      role="option"
                      aria-selected={i === roundAt}
                      className={`round-cell${i === roundAt ? " on" : ""}${perfect ? " perfect" : r.f1 >= good ? " good" : ""}${dropped ? " dropped" : ""}`}
                      onClick={() => { setPlaying(false); setRoundAt(i); }}
                      title={`Round ${r.epoch + 1}: score ${r.f1.toFixed(2)}, found ${r.tp} of ${labelled}, ${r.fp} extra${perfect ? ", perfect" : ""}${dropped ? ", dropped below the threshold" : ""}`}
                    >
                      <span className="round-bar"><span style={{ height: `${Math.max(4, r.f1 * 100)}%` }} /></span>
                      <span className="round-number">{perfect ? <Icon name="check" size={11} /> : r.epoch + 1}</span>
                    </button>
                  );
                })}
              </div>
              <p className="round-key faint small">
                <span className="key-threshold" /> F1 threshold {good}
                {rounds.some((r, i) => i > 0 && rounds[i - 1]!.f1 >= good && r.f1 < good) && <><span className="key-dropped" /> dropped below it</>}
              </p>
              {round && (
                <dl className="round-stats">
                  <div><dt>F1, {roundName(round.epoch)}</dt><dd>{round.f1.toFixed(2)}</dd></div>
                  <div><dt>True positives</dt><dd>{formatNumber(round.tp)}<span className="faint"> / {formatNumber(labelled)}</span></dd></div>
                  <div><dt>False negatives</dt><dd>{formatNumber(round.fn)}</dd></div>
                  <div><dt>False positives</dt><dd>{formatNumber(round.fp)}</dd></div>
                </dl>
              )}
              {round && round.boxes === null && (
                <p className="notice small">
                  Predictions were not stored for this epoch.
                </p>
              )}
            </section>
          )}

          <section className="viewer-section viewer-decide">
            <h3>Decision</h3>
            {decision === "removed" ? (
              <p className="small">
                <span className="decision-tag tag-removed">Removed</span> from {setName}
                {decisions.reasons.get(image ?? "") ? `: ${decisions.reasons.get(image ?? "")}` : ""}. Restore it from the removed set.
              </p>
            ) : (
              <>
                <div className="decide-buttons">
                  <button className={`decide keep${decision === "keep" ? " on" : ""}`} onClick={() => decide("keep")}>
                    <Icon name="check" /> Keep <kbd>K</kbd>
                  </button>
                  <button className={`decide remove${decision === "remove" ? " on" : ""}`} onClick={() => decide("remove")}>
                    <Icon name="close" /> Remove <kbd>R</kbd>
                  </button>
                </div>
                <label className="field">
                  <span className="small">Removal reason</span>
                  <div className="select-wrap">
                    <select value={reason} onChange={(e) => setReason(e.target.value)}>
                      {REMOVE_REASONS.map((r) => <option key={r}>{r}</option>)}
                    </select>
                  </div>
                </label>
                <p className="small muted">
                  {decision === "keep" && "Marked keep. "}
                  {decision === "remove" && "Marked for removal; applied from the samples page. "}
                  {decision && <button className="link-button" onClick={() => decide("clear")}>Undo <kbd>U</kbd></button>}
                </p>
                <label className="check-row small">
                  <input type="checkbox" checked={advance} onChange={(e) => setAdvance(e.target.checked)} />
                  Advance after deciding
                </label>
              </>
            )}
          </section>

          <details className="viewer-keys small muted">
            <summary>Keyboard shortcuts</summary>
            <p>← → images · [ ] rounds · Space play · K keep · R remove · U undo · L labels · G model's boxes · M only mistakes · + − zoom · F whole image · Esc close</p>
          </details>
        </aside>
      </div>
    </div>
  );
}
