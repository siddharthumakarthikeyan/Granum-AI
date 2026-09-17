/** A health-check report: what the data looks like, what could go wrong, and what to do. */

import { useMemo, useState } from "react";
import { api } from "../api/client";
import type { Finding, FindingExample, PreflightReport, Severity } from "../api/types";
import { CATEGORICAL, OTHER, css } from "../charts/colors";
import { FINDINGS, effectLabel, optionEffect, optionLabel } from "../copy/plain";
import { HelpTip, Icon, SeverityLabel, Term, formatBytes, formatNumber, plural } from "../components/ui";

const SEVERITY_ORDER: Severity[] = ["block", "warn", "info"];
const GROUP_TITLES: Record<Severity, string> = {
  block: "Must fix before importing",
  warn: "Please check",
  info: "Good to know",
};
const GROUP_HELP: Record<Severity, string> = {
  block: "The import can't go ahead as the data is. The recommended fix is already selected; change it if you prefer another.",
  warn: "The data can be imported, but these could make a model learn the wrong thing or look better than it really is.",
  info: "Nothing is wrong. These are worth knowing when you review the data.",
};

export function splitColor(index: number): string {
  return css(CATEGORICAL[index] ?? OTHER);
}

interface Props {
  report: PreflightReport;
  choices?: Record<string, string>;
  onChoose?: (code: string, option: string) => void;
  /** Saved reports: what was applied, and what it changed. */
  effects?: Record<string, number>;
}

function unitWord(unit: string, count: number): string {
  const words: Record<string, [string, string]> = {
    boxes: ["box", "boxes"],
    images: ["image", "images"],
    categories: ["label", "labels"],
    files: ["file", "files"],
  };
  const [one, many] = words[unit] ?? [unit.replace(/s$/, ""), unit];
  return plural(count, one, many);
}

export function ReportView({ report, choices, onChoose, effects }: Props) {
  const [filter, setFilter] = useState<Severity | "all">("all");
  const counts = useMemo(() => {
    const out: Record<Severity, number> = { block: 0, warn: 0, info: 0 };
    for (const finding of report.findings) out[finding.severity] += 1;
    return out;
  }, [report]);
  const splits = report.summary.splits.map((s) => s.split);

  return (
    <div className="report">
      <Summary report={report} />

      {effects && Object.keys(effects).length > 0 && (
        <section className="section">
          <h2 className="section-title">Applied resolutions</h2>
          <ul className="effects">
            {Object.entries(effects).sort().map(([effect, count]) => (
              <li key={effect}>
                <span className="effect-count">{formatNumber(count)}</span>
                <span>{effectLabel(effect)}</span>
              </li>
            ))}
          </ul>
        </section>
      )}

      <section className="section">
        <div className="section-head">
          <h2 className="section-title">What we found</h2>
          <div className="segmented" role="tablist" aria-label="Show findings">
            <button role="tab" aria-selected={filter === "all"} className={filter === "all" ? "on" : ""} onClick={() => setFilter("all")}>
              All <span className="muted">{report.findings.length}</span>
            </button>
            {SEVERITY_ORDER.filter((s) => counts[s] > 0).map((severity) => (
              <button key={severity} role="tab" aria-selected={filter === severity} className={filter === severity ? "on" : ""} onClick={() => setFilter(severity)}>
                {GROUP_TITLES[severity].replace(" before importing", "")} <span className="muted">{counts[severity]}</span>
              </button>
            ))}
          </div>
        </div>
        {report.findings.length === 0 && (
          <p className="muted">No problems found. {report.media_mode === "none" ? "Image files were not checked." : ""}</p>
        )}
        {SEVERITY_ORDER.filter((s) => (filter === "all" || filter === s) && counts[s] > 0).map((severity) => (
          <div key={severity} className="finding-group">
            <div className="finding-group-head">
              <h3 className={`finding-group-title severity-${severity}`}>{GROUP_TITLES[severity]}</h3>
              <p className="muted small">{GROUP_HELP[severity]}</p>
            </div>
            {report.findings.filter((f) => f.severity === severity).map((finding) => (
              <FindingCard
                key={finding.code}
                finding={finding}
                splits={splits}
                choice={choices?.[finding.code] ?? finding.default}
                onChoose={onChoose}
              />
            ))}
          </div>
        ))}
      </section>
    </div>
  );
}

function Summary({ report }: { report: PreflightReport }) {
  const { summary } = report;
  const splits = summary.splits;
  const maxClass = Math.max(1, ...summary.classes.flatMap((c) => Object.values(c.boxes)));

  return (
    <section className="section summary">
      <h2 className="section-title">Summary</h2>
      <p className="summary-sentence">
        {splits.map((split, i) => (
          <span key={split.split}>
            {i > 0 && (i === splits.length - 1 ? " and " : ", ")}
            <span className="swatch" style={{ background: splitColor(i) }} />
            <strong>{formatNumber(split.images)}</strong> images in <strong>{split.split}</strong>

          </span>
        ))}
        , with <strong>{formatNumber(summary.boxes)}</strong> labelled objects across <strong>{summary.classes.length}</strong> labels.{" "}
        <HelpTip>
          Each file you picked is a <b>set</b>. The training set teaches the model; the validation or test set checks how well it learned.
          The two should never share images or scenes.
        </HelpTip>
      </p>

      <div className="summary-splits">
        <table className="data-table compact">
          <thead>
            <tr>
              <th><Term term="split">Set</Term></th>
              <th className="num">Images</th>
              <th className="num"><Term term="box">Labelled objects</Term></th>
              <th className="num">Objects per image</th>
              <th className="num">Typical object size</th>
              {report.media_mode !== "none" && <th className="num">Images opened</th>}
            </tr>
          </thead>
          <tbody>
            {splits.map((split, i) => (
              <tr key={split.split}>
                <td><span className="swatch" style={{ background: splitColor(i) }} />{split.split}</td>
                <td className="num">{formatNumber(split.images)}</td>
                <td className="num">{formatNumber(split.boxes)}</td>
                <td className="num">about {formatNumber(split.boxes_per_image.median)} <span className="muted">(up to {formatNumber(split.boxes_per_image.max)})</span></td>
                <td className="num">{split.median_box_side} pixels across</td>
                {report.media_mode !== "none" && (
                  <td className="num">{formatNumber(split.media_checked)} <span className="muted">({formatBytes(split.media_bytes)})</span></td>
                )}
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <div className="summary-charts">
        <div className="panel-card">
          <h3 className="card-title">Boxes per class</h3>
          <table className="bar-table">
            <tbody>
              {summary.classes.map((category) => (
                <tr key={category.id}>
                  <th scope="row"><span className="class-name">{category.name}</span></th>
                  <td>
                    {splits.map((split, i) => {
                      const value = category.boxes[split.split] ?? 0;
                      return (
                        <div key={split.split} className="bar-line" title={`${split.split}: ${formatNumber(value)} objects`}>
                          <span className="bar" style={{ width: `${(value / maxClass) * 100}%`, background: splitColor(i) }} />
                          <span className="bar-value">{value === 0 ? <span className="muted">none</span> : formatNumber(value)}</span>
                        </div>
                      );
                    })}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <div className="panel-card">
          <h3 className="card-title">Box width</h3>
          <p className="faint small card-intro">Share of boxes by width, px</p>
          <table className="bar-table">
            <tbody>
              {(splits[0]?.box_side_histogram ?? []).map((bin, b) => (
                <tr key={bin.from}>
                  <th scope="row" className="small">
                    {bin.from === 0 ? `under ${bin.to} px` : bin.to === null ? `${bin.from} px or more` : `${bin.from} to ${bin.to} px`}
                  </th>
                  <td>
                    {splits.map((split, i) => {
                      const total = split.boxes || 1;
                      const share = (split.box_side_histogram[b]?.boxes ?? 0) / total;
                      return (
                        <div key={split.split} className="bar-line" title={`${split.split}: ${formatNumber(split.box_side_histogram[b]?.boxes ?? 0)} objects`}>
                          <span className="bar" style={{ width: `${share * 100}%`, background: splitColor(i) }} />
                          <span className="bar-value">{(share * 100).toFixed(share < 0.01 && share > 0 ? 1 : 0)}%</span>
                        </div>
                      );
                    })}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </section>
  );
}

function FindingCard({ finding, splits, choice, onChoose }: {
  finding: Finding;
  splits: string[];
  choice: string | null;
  onChoose?: (code: string, option: string) => void;
}) {
  const [open, setOpen] = useState(finding.severity !== "info");
  const [technical, setTechnical] = useState(true);
  const copy = FINDINGS[finding.code];
  const imageExamples = finding.examples.filter((e) => typeof e.image === "string");
  const otherExamples = finding.examples.filter((e) => typeof e.image !== "string");
  const chosen = finding.options.find((o) => o.id === choice);
  const changedFromRecommended = Boolean(onChoose && finding.default && choice !== finding.default);

  return (
    <article className={`finding finding-${finding.severity}${open ? " open" : ""}`}>
      <button className="finding-head" onClick={() => setOpen(!open)} aria-expanded={open}>
        <SeverityLabel severity={finding.severity} />
        <span className="finding-title">{finding.title}</span>
        <span className="finding-count">{unitWord(finding.unit, finding.count)}</span>
        {!open && chosen && (
          <span className="finding-choice small">
            <Icon name="check" size={13} /> {optionLabel(finding.code, chosen.id, chosen.label)}
          </span>
        )}
        <Icon name="chevron" className="finding-chevron" />
      </button>
      {open && (
        <div className="finding-body">
          <div className="finding-explain">
            <div>
              <h4>What this means</h4>
              <p>{copy?.meaning ?? finding.detail}</p>
            </div>
            {copy && (
              <div>
                <h4>What we recommend</h4>
                <p>{copy.recommendation}</p>
              </div>
            )}
          </div>

          {Object.keys(finding.splits).length > 0 && (
            <p className="finding-splits">
              <span className="muted">Where:</span>
              {splits.filter((s) => finding.splits[s]).map((split) => (
                <span key={split} className="split-count">
                  <span className="swatch" style={{ background: splitColor(splits.indexOf(split)) }} />
                  {unitWord(finding.unit, finding.splits[split]!)} in {split}
                </span>
              ))}
            </p>
          )}

          {imageExamples.length > 0 && (
            <div>
              <h4 className="examples-title">
                Examples{imageExamples.some((e) => e.bbox) ? ", zoomed in on the object (outlined in orange)" : ""}
              </h4>
              <div className="examples">
                {imageExamples.map((example, i) => <ExampleTile key={i} example={example} />)}
                {finding.count > imageExamples.length && (
                  <span className="examples-more muted small">and {formatNumber(finding.count - imageExamples.length)} more</span>
                )}
              </div>
            </div>
          )}
          {otherExamples.length > 0 && <ExampleList examples={otherExamples} />}

          {finding.options.length > 0 && (
            <fieldset className="options" disabled={!onChoose}>
              <legend>{onChoose ? "What should the import do?" : "What the import did"}</legend>
              {finding.options.map((option) => {
                if (!onChoose && option.id !== choice) return null;
                return (
                  <label key={option.id} className={`option${option.id === choice ? " checked" : ""}`}>
                    <input
                      type="radio"
                      name={`option-${finding.code}`}
                      checked={option.id === choice}
                      onChange={() => onChoose?.(finding.code, option.id)}
                    />
                    <span>
                      <span className="strong">{optionLabel(finding.code, option.id, option.label)}</span>
                      {option.id === finding.default && onChoose && <span className="tag tag-recommended">Recommended</span>}
                      <span className="muted small block">{optionEffect(finding.code, option.id, option.effect)}</span>
                    </span>
                  </label>
                );
              })}
              {changedFromRecommended && (
                <p className="small changed-note">
                  You changed this from the recommended choice. That's fine; it's recorded with the import.
                </p>
              )}
            </fieldset>
          )}
          {finding.options.length === 0 && finding.severity !== "block" && (
            <p className="muted small">No decision needed.</p>
          )}

          <div className="technical">
            <button className="technical-toggle small" onClick={() => setTechnical(!technical)} aria-expanded={technical}>
              <Icon name="chevron" size={12} className={technical ? "rotated" : ""} />
              Technical details
            </button>
            {technical && (
              <div className="technical-body small">
                <p>{finding.title}. {finding.detail}</p>
                <p className="muted">Check ID <code>{finding.code}</code></p>
              </div>
            )}
          </div>
        </div>
      )}
    </article>
  );
}

/** An example image, cropped around its box so an 8-pixel object is visible at all. */
function ExampleTile({ example }: { example: FindingExample }) {
  const [failed, setFailed] = useState(false);
  const W = 176;
  const H = 132;
  const width = Number(example.width) || 0;
  const height = Number(example.height) || 0;
  const box = Array.isArray(example.bbox) && example.bbox.length === 4 ? example.bbox.map(Number) : null;

  let view = { x: 0, y: 0, w: width || W, h: height || H };
  if (box && width && height) {
    const [bx, by, bw, bh] = box as [number, number, number, number];
    const side = Math.max(bw, bh, 12) * 3.5;
    let w = Math.max(side, 96);
    let h = w * (H / W);
    if (h < bh * 1.6) {
      h = bh * 1.6;
      w = h * (W / H);
    }
    w = Math.min(w, width);
    h = Math.min(h, height);
    const x = Math.min(Math.max(0, bx + bw / 2 - w / 2), Math.max(0, width - w));
    const y = Math.min(Math.max(0, by + bh / 2 - h / 2), Math.max(0, height - h));
    view = { x, y, w, h };
  }
  const scale = Math.min(W / view.w, H / view.h);
  const needed = Math.max(width, height) * scale * (window.devicePixelRatio || 1);
  const size = [256, 512, 1024, 2048].find((s) => s >= needed) ?? 2048;
  const src = api.mediaUrl(String(example.image), size);
  const offsetX = (W - view.w * scale) / 2;
  const offsetY = (H - view.h * scale) / 2;

  return (
    <figure className="example" title={String(example.file_name ?? "")}>
      <div className="example-frame" style={{ width: W, height: H }}>
        {failed ? (
          <span className="example-missing small">Image not available</span>
        ) : width && height ? (
          <svg width={W} height={H} viewBox={`0 0 ${W} ${H}`} role="img" aria-label={`Example from ${example.file_name ?? "an image"}`}>
            <g transform={`translate(${offsetX} ${offsetY}) scale(${scale}) translate(${-view.x} ${-view.y})`}>
              <image href={src} x={0} y={0} width={width} height={height} preserveAspectRatio="none" onError={() => setFailed(true)} />
              {box && (
                <rect
                  x={box[0]} y={box[1]} width={Math.max(box[2]!, 0.5)} height={Math.max(box[3]!, 0.5)}
                  fill="none" stroke="#fbbf24" strokeWidth={2 / scale} vectorEffect="non-scaling-stroke"
                />
              )}
            </g>
          </svg>
        ) : (
          <img src={src} alt="" onError={() => setFailed(true)} />
        )}
      </div>
      <figcaption className="small">
        <span className="example-caption">{example.category !== undefined ? String(example.category) : `from ${example.split}`}</span>
        {typeof example.boxes === "number" && <span className="muted"> {formatNumber(example.boxes)} objects</span>}
        {typeof example.sequence === "string" && <span className="muted"> scene {example.sequence}</span>}
        {typeof example.reason === "string" && <span className="muted block">{example.reason}</span>}
      </figcaption>
    </figure>
  );
}

const EXAMPLE_COLUMNS: Record<string, string> = {
  name: "Label name",
  ids: "Label numbers",
  boxes: "Objects per number",
  category_id: "Label number",
  split: "Set",
  elsewhere: "Name in another set",
  image_id: "Image number",
  file_name: "File",
};

function ExampleList({ examples }: { examples: FindingExample[] }) {
  const keys = [...new Set(examples.flatMap((e) => Object.keys(e)))];
  const show = (value: unknown) => {
    if (Array.isArray(value)) return value.join(", ");
    if (value && typeof value === "object") {
      return Object.entries(value as Record<string, unknown>).map(([k, v]) => `number ${k}: ${formatNumber(Number(v))}`).join(", ");
    }
    return String(value ?? "");
  };
  return (
    <div className="data-table-wrap">
      <table className="data-table compact">
        <thead>
          <tr>{keys.map((key) => <th key={key}>{EXAMPLE_COLUMNS[key] ?? key.replace(/_/g, " ")}</th>)}</tr>
        </thead>
        <tbody>
          {examples.map((example, i) => (
            <tr key={i}>
              {keys.map((key) => <td key={key}>{show(example[key])}</td>)}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
