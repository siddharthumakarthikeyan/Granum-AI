/** Review one flagged image full screen: its findings with their evidence, every label for
 * context, and a decision recorded in the dataset's review log.
 *
 * Keys: ← → images · ↑ ↓ findings · Z close-up / whole image · C label is right ·
 * F fix in the editor · A ambiguous · L later · X exclude · U undo · Esc close.
 */

import { useCallback, useEffect, useState } from "react";
import { api } from "../api/client";
import type { FindingsSplit, FlaggedImage, ImageRounds } from "../api/types";
import { Icon, formatNumber } from "../components/ui";
import { navigate } from "../router";
import { RULE, STATUS_LABEL, cropView, decisionReason, evidence, faded, rectOf } from "./text";

interface Props {
  project: string;
  runUrl: string;
  version: string;
  split: FindingsSplit;
  items: FlaggedImage[];
  index: number;
  onIndex: (index: number) => void;
  onDecided: () => Promise<void> | void;
  onClose: () => void;
}

type Status = "correct" | "corrected" | "ambiguous" | "deferred" | "excluded" | "unreviewed";

const DECISIONS: { status: Status; label: string; key: string; note: string }[] = [
  { status: "correct", label: "Label is right", key: "C", note: "Label checked and right, a valid hard case." },
  { status: "ambiguous", label: "Ambiguous", key: "A", note: "Cannot tell what the right label is." },
  { status: "deferred", label: "Later", key: "L", note: "Needs another look." },
  { status: "excluded", label: "Exclude image", key: "X", note: "Should not be used for training." },
];

export function FindingReview({ project, runUrl, version, split, items, index, onIndex, onDecided, onClose }: Props) {
  const item = items[index]!;
  const [selected, setSelected] = useState(0);
  const [closeUp, setCloseUp] = useState(true);
  const [labels, setLabels] = useState<ImageRounds | null>(null);
  const [status, setStatus] = useState<string | null>(item.review?.status ?? null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [advance, setAdvance] = useState(true);

  useEffect(() => {
    setSelected(0);
    setStatus(item.review?.status ?? null);
    setError(null);
    setLabels(null);
    let alive = true;
    // Every label of the image, for context around the findings.
    api.imageRounds(runUrl, split.table, item.example_id).then((r) => alive && setLabels(r)).catch(() => undefined);
    return () => {
      alive = false;
    };
  }, [item, runUrl, split.table]);

  const finding = item.findings[selected] ?? item.findings[0]!;
  const next = useCallback(() => index < items.length - 1 && onIndex(index + 1), [index, items.length, onIndex]);
  const previous = useCallback(() => index > 0 && onIndex(index - 1), [index, onIndex]);

  const decide = useCallback(async (to: Status, note: string, then?: () => void) => {
    if (!item.image || !split.dataset || busy) return;
    setBusy(true);
    setError(null);
    try {
      await api.recordReview({
        project, dataset: split.dataset, samples: [item.image], status: to, table: split.table,
        reason: to === "unreviewed" ? `${version}: decision undone` : decisionReason(version, finding, note),
      });
      setStatus(to === "unreviewed" ? null : to);
      void onDecided();
      if (then) then();
      else if (to !== "unreviewed" && advance) next();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }, [item.image, split.dataset, split.table, busy, project, version, finding, onDecided, advance, next]);

  // Fixing happens in the editor; the decision is recorded first, as "will be fixed".
  const fix = useCallback(() => {
    void decide("corrected", "Label is wrong; fixing it in the editor.", () =>
      navigate({ name: "images", project, dataset: split.dataset ?? undefined, edit: true, open: item.image ?? undefined }));
  }, [decide, project, split.dataset, item.image]);

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.target instanceof HTMLInputElement || event.target instanceof HTMLSelectElement) return;
      const key = event.key.toLowerCase();
      if (key === "escape") onClose();
      else if (key === "arrowright") next();
      else if (key === "arrowleft") previous();
      else if (key === "arrowdown") setSelected((s) => Math.min(item.findings.length - 1, s + 1));
      else if (key === "arrowup") setSelected((s) => Math.max(0, s - 1));
      else if (key === "z") setCloseUp((c) => !c);
      else if (key === "f") fix();
      else if (key === "u" && status) void decide("unreviewed", "");
      else {
        const choice = DECISIONS.find((d) => d.key.toLowerCase() === key);
        if (!choice) return;
        void decide(choice.status, choice.note);
      }
      event.preventDefault();
      event.stopImmediatePropagation();
    };
    window.addEventListener("keydown", onKey, true);
    return () => window.removeEventListener("keydown", onKey, true);
  }, [onClose, next, previous, item.findings.length, fix, decide, status]);

  const W = item.width ?? 1, H = item.height ?? 1;
  const view = closeUp ? cropView(finding.box, W, H, 5, 1.6, 96) : `0 0 ${W} ${H}`;
  const stroke = Math.max(Number(view.split(" ")[2]), Number(view.split(" ")[3])) / 320;
  const info = RULE.get(finding.rule)!;
  const file = item.image?.split("/").pop();
  const className = (label: number | null | undefined) => (label === null || label === undefined ? "" : split.classes[String(label)] ?? String(label));

  return (
    <div className="viewer finding-review" role="dialog" aria-modal="true" aria-label={`Finding ${index + 1} of ${items.length}`}>
      <header className="viewer-bar">
        <button className="icon-button" onClick={previous} disabled={index === 0} aria-label="Previous image (←)" title="Previous image (←)"><Icon name="back" /></button>
        <span className="viewer-count"><span className="strong">{formatNumber(index + 1)}</span><span className="muted"> of {formatNumber(items.length)}</span></span>
        <button className="icon-button" onClick={next} disabled={index >= items.length - 1} aria-label="Next image (→)" title="Next image (→)"><Icon name="chevron" /></button>
        <span className="viewer-file muted" title={item.image ?? ""}>{split.dataset} / {split.split} / {file}</span>
        <span className="spacer" />
        <button className="icon-button" onClick={onClose} aria-label="Close (Esc)" title="Close (Esc)"><Icon name="close" /></button>
      </header>

      <div className="viewer-body">
        <div className="viewer-stage-wrap">
          <div className="viewer-layers">
            <button className={`chip${closeUp ? " on" : ""}`} onClick={() => setCloseUp(true)} aria-pressed={closeUp} title="Z">Close-up</button>
            <button className={`chip${!closeUp ? " on" : ""}`} onClick={() => setCloseUp(false)} aria-pressed={!closeUp} title="Z">Whole image</button>
          </div>
          <div className="viewer-stage finding-stage">
            {item.image && (
              <svg viewBox={view} preserveAspectRatio="xMidYMid meet" role="img" aria-label={`${info.label} on ${file}`}>
                <image href={api.mediaUrl(item.image, undefined, project, split.dataset ?? undefined)} x={0} y={0} width={W} height={H} preserveAspectRatio="none" />
                {(labels?.truth ?? []).map((t, i) => (
                  <g key={`t${i}`} className="context-label">
                    <rect {...rectOf(t.vertices.slice(0, 4) as [number, number, number, number])} fill="none" strokeWidth={stroke} />
                  </g>
                ))}
                {item.findings.map((f, i) => {
                  const color = RULE.get(f.rule)!.color;
                  const on = i === selected;
                  return (
                    <g key={`f${i}`} opacity={on ? 1 : 0.45} onClick={() => setSelected(i)} className="finding-shape">
                      {f.predicted_box && <rect {...rectOf(f.predicted_box)} fill="none" stroke={color} strokeWidth={stroke * (on ? 1.6 : 1)} strokeDasharray={`${stroke * 4} ${stroke * 3}`} />}
                      <rect {...rectOf(f.box)} fill={on ? "rgba(255,255,255,.04)" : "none"} stroke={color} strokeWidth={stroke * (on ? 2.4 : 1.4)}
                        strokeDasharray={f.rule === "missing_label" ? `${stroke * 4} ${stroke * 3}` : undefined} />
                    </g>
                  );
                })}
              </svg>
            )}
          </div>
          <ul className="viewer-legend small" aria-label="What the boxes mean">
            <li><svg width="18" height="12" aria-hidden="true"><rect x="1" y="1" width="16" height="10" fill="none" stroke="var(--text-3)" strokeWidth="1.5" /></svg>Label</li>
            <li><svg width="18" height="12" aria-hidden="true"><rect x="1" y="1" width="16" height="10" fill="none" stroke={info.color} strokeWidth="2" /></svg>Finding</li>
            <li><svg width="18" height="12" aria-hidden="true"><rect x="1" y="1" width="16" height="10" fill="none" stroke={info.color} strokeWidth="1.5" strokeDasharray="3 2" /></svg>Model's box</li>
          </ul>
        </div>

        <aside className="viewer-side">
          <section className="viewer-verdict finding-verdict" style={{ borderLeftColor: info.color }}>
            <h2>{info.label}</h2>
            <p className="small">{evidence(finding, split.classes)}{faded(finding) ? ` ${faded(finding)}` : ""}</p>
            <p className="small muted">{info.action}</p>
          </section>

          {item.findings.length > 1 && (
            <section className="viewer-section">
              <h3>In this image <span className="muted">{item.findings.length}</span></h3>
              <ul className="finding-list">
                {item.findings.map((f, i) => (
                  <li key={i}>
                    <button className={i === selected ? "on" : ""} onClick={() => setSelected(i)}>
                      <span className="rule-dot" style={{ background: RULE.get(f.rule)!.color }} />
                      <span className="truncate">{RULE.get(f.rule)!.short}{f.label !== null ? `, ${className(f.label)}` : f.predicted_label !== undefined ? `, ${className(f.predicted_label)}` : ""}</span>
                      <span className="faint">{f.rounds}/{f.window}</span>
                    </button>
                  </li>
                ))}
              </ul>
            </section>
          )}

          <section className="viewer-section viewer-decide">
            <h3>Decision {status && <span className={`decision-tag finding-status-${status}`}>{STATUS_LABEL[status] ?? status}</span>}</h3>
            <button className="button primary finding-fix" onClick={fix} disabled={busy || !split.dataset}>
              <Icon name="pencil" /> Fix in the editor <kbd>F</kbd>
            </button>
            <div className="finding-decisions">
              {DECISIONS.map((d) => (
                <button key={d.status} className={`decide${status === d.status ? " on" : ""}`} onClick={() => void decide(d.status, d.note)} disabled={busy} title={d.note}>
                  {d.label} <kbd>{d.key}</kbd>
                </button>
              ))}
            </div>
            {error && <p className="form-error small">{error}</p>}
            <p className="small muted">
              Saved to the review log of {split.dataset}.{" "}
              {status && <button className="link-button" onClick={() => void decide("unreviewed", "")}>Undo <kbd>U</kbd></button>}
            </p>
            <label className="check-row small">
              <input type="checkbox" checked={advance} onChange={(e) => setAdvance(e.target.checked)} />
              Next image after deciding
            </label>
          </section>

          <details className="viewer-keys small muted">
            <summary>Keyboard shortcuts</summary>
            <p>← → images · ↑ ↓ findings · Z close-up · F fix · C right · A ambiguous · L later · X exclude · U undo · Esc close</p>
          </details>
        </aside>
      </div>
    </div>
  );
}
