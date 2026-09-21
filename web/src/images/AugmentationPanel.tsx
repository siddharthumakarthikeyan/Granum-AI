/** Augmentation for a new dataset version: first a yes/no, then the recipe.
 *
 * Every augmentation is a card showing what it does to one of the dataset's own train
 * images. Clicking a card opens its settings with the image at both ends of the range;
 * applying adds it to the recipe. The recipe goes to POST /api/qa/release as
 * `augmentation`, where the train set gets `copies` augmented copies of each image
 * (granum.core.augment).
 */

import { useEffect, useMemo, useState } from "react";
import { api } from "../api/client";
import type { AugmentRecipe, TaskId } from "../api/types";
import { Modal } from "../components/Modal";
import { Icon, formatBytes, formatNumber } from "../components/ui";
import { CROWD_COLOR, labelColor } from "./labelColors";

type Kind = keyof Omit<AugmentRecipe, "copies">;

interface Range { min: number; max: number }

interface Field { key: string; label: string; unit: string; low: number; high: number; step: number }

/** Settings of each augmentation, with the values used when it is first added. */
type Spec =
  | { kind: "options"; options: { key: string; label: string }[]; initial: Record<string, boolean> }
  | { kind: "range"; unit: string; low: number; high: number; step: number; initial: Range }
  | { kind: "values"; fields: Field[]; initial: Record<string, number> };

interface Augmentation {
  id: Kind;
  label: string;
  description: string;
  geometric: boolean;
  spec: Spec;
  /** Shown on its card before it is chosen: strong enough to see at a glance. */
  demo: unknown;
  summary: (value: never) => string;
}

const signed = (n: number) => (n > 0 ? `+${n}` : String(n));
const range = (unit: string) => (v: Range) => `${signed(v.min)}${unit} to ${signed(v.max)}${unit}`;

function optionSummary(value: Record<string, boolean>, names: Record<string, string>): string {
  const on = Object.keys(names).filter((k) => value[k]);
  return on.length ? on.map((k) => names[k]).join(", ") : "Nothing chosen";
}

const GEOMETRY: Augmentation[] = [
  {
    id: "flip", label: "Flip", geometric: true,
    description: "Mirrors the image. Each chosen direction is applied to about half of the copies.",
    spec: { kind: "options", options: [{ key: "horizontal", label: "Horizontal" }, { key: "vertical", label: "Vertical" }], initial: { horizontal: true } },
    demo: { horizontal: true },
    summary: (v: Record<string, boolean>) => optionSummary(v, { horizontal: "Horizontal", vertical: "Vertical" }),
  },
  {
    id: "rotate90", label: "90° Rotate", geometric: true,
    description: "Turns the image by a quarter or half turn. Each copy gets one of the chosen turns, or none.",
    spec: {
      kind: "options",
      options: [{ key: "clockwise", label: "Clockwise" }, { key: "counterclockwise", label: "Counter-clockwise" }, { key: "upside_down", label: "Upside down" }],
      initial: { clockwise: true, counterclockwise: true },
    },
    demo: { clockwise: true },
    summary: (v: Record<string, boolean>) => optionSummary(v, { clockwise: "Clockwise", counterclockwise: "Counter-clockwise", upside_down: "Upside down" }),
  },
  {
    id: "crop", label: "Crop", geometric: true,
    description: "Zooms into a random region. At 20%, a fifth of the width and height is cut away.",
    spec: { kind: "range", unit: "%", low: 0, high: 90, step: 1, initial: { min: 0, max: 20 } },
    demo: { min: 0, max: 35 },
    summary: (v: Range) => `${v.min}% to ${v.max}% zoom`,
  },
  {
    id: "rotation", label: "Rotation", geometric: true,
    description: "Rotates by a random angle in the range. Corners left uncovered are filled black.",
    spec: { kind: "range", unit: "°", low: -180, high: 180, step: 1, initial: { min: -15, max: 15 } },
    demo: { min: -20, max: 20 },
    summary: range("°"),
  },
  {
    id: "shear", label: "Shear", geometric: true,
    description: "Slants the image by a random angle up to the limit, horizontally and vertically.",
    spec: {
      kind: "values",
      fields: [
        { key: "horizontal", label: "Horizontal ±", unit: "°", low: 0, high: 45, step: 1 },
        { key: "vertical", label: "Vertical ±", unit: "°", low: 0, high: 45, step: 1 },
      ],
      initial: { horizontal: 10, vertical: 10 },
    },
    demo: { horizontal: 15, vertical: 15 },
    summary: (v: { horizontal: number; vertical: number }) => `±${v.horizontal}° h, ±${v.vertical}° v`,
  },
];

const PIXELS: Augmentation[] = [
  {
    id: "grayscale", label: "Grayscale", geometric: false,
    description: "Removes colour from a share of the copies.",
    spec: { kind: "values", fields: [{ key: "percent", label: "Share of copies", unit: "%", low: 0, high: 100, step: 1 }], initial: { percent: 15 } },
    demo: { percent: 100 },
    summary: (v: { percent: number }) => `${v.percent}% of copies`,
  },
  {
    id: "hue", label: "Hue", geometric: false,
    description: "Shifts every colour around the colour wheel by a random angle.",
    spec: { kind: "range", unit: "°", low: -180, high: 180, step: 1, initial: { min: -15, max: 15 } },
    demo: { min: -60, max: 60 },
    summary: range("°"),
  },
  {
    id: "saturation", label: "Saturation", geometric: false,
    description: "Makes colours more muted (negative) or more vivid (positive).",
    spec: { kind: "range", unit: "%", low: -100, high: 100, step: 1, initial: { min: -25, max: 25 } },
    demo: { min: -80, max: 80 },
    summary: range("%"),
  },
  {
    id: "brightness", label: "Brightness", geometric: false,
    description: "Darkens (negative) or brightens (positive) the whole image evenly.",
    spec: { kind: "range", unit: "%", low: -90, high: 90, step: 1, initial: { min: -20, max: 20 } },
    demo: { min: -40, max: 40 },
    summary: range("%"),
  },
  {
    id: "exposure", label: "Exposure", geometric: false,
    description: "Bends the tone curve: shadows change most, highlights stay put.",
    spec: { kind: "range", unit: "%", low: -90, high: 90, step: 1, initial: { min: -10, max: 10 } },
    demo: { min: -60, max: 60 },
    summary: range("%"),
  },
  {
    id: "blur", label: "Blur", geometric: false,
    description: "Gaussian blur with a random radius up to the limit.",
    spec: { kind: "values", fields: [{ key: "max", label: "Up to", unit: "px", low: 0, high: 20, step: 0.5 }], initial: { max: 1.5 } },
    demo: { max: 4 },
    summary: (v: { max: number }) => `Up to ${v.max} px`,
  },
  {
    id: "noise", label: "Noise", geometric: false,
    description: "Replaces up to this share of pixels with random colours.",
    spec: { kind: "values", fields: [{ key: "max", label: "Up to", unit: "% of pixels", low: 0, high: 50, step: 0.5 }], initial: { max: 2 } },
    demo: { max: 10 },
    summary: (v: { max: number }) => `Up to ${v.max}%`,
  },
  {
    id: "cutout", label: "Cutout", geometric: false,
    description: "Blacks out square regions. Labels are kept, so the model learns partly hidden objects.",
    spec: {
      kind: "values",
      fields: [
        { key: "count", label: "Squares", unit: "", low: 1, high: 20, step: 1 },
        { key: "size", label: "Size", unit: "%", low: 1, high: 50, step: 1 },
      ],
      initial: { count: 3, size: 10 },
    },
    demo: { count: 4, size: 15 },
    summary: (v: { count: number; size: number }) => `${v.count} × ${v.size}%`,
  },
];

const ALL = [...GEOMETRY, ...PIXELS];
const COPIES = [1, 2, 3, 4, 5];

const summarize = (a: Augmentation, value: unknown) => (a.summary as (v: unknown) => string)(value);

/** Why a setting cannot be used, if it cannot. */
function problemOf(item: Augmentation, value: unknown): string | null {
  const spec = item.spec;
  if (spec.kind === "options") {
    return Object.values(value as Record<string, boolean>).some(Boolean) ? null : "Choose at least one.";
  }
  if (spec.kind === "range") {
    const v = value as Range;
    if (![v.min, v.max].every((n) => Number.isFinite(n) && n >= spec.low && n <= spec.high)) return `Use values from ${spec.low} to ${spec.high}.`;
    return v.min > v.max ? "Minimum is above maximum." : null;
  }
  const v = value as Record<string, number>;
  const bad = spec.fields.find((f) => !Number.isFinite(v[f.key]) || v[f.key]! < f.low || v[f.key]! > f.high);
  return bad ? `${bad.label.replace(" ±", "")}: use ${bad.low} to ${bad.high}.` : null;
}

export interface AugmentationState {
  enabled: boolean;
  copies: number;
  settings: Partial<Record<Kind, unknown>>;
}

export const NO_AUGMENTATION: AugmentationState = { enabled: false, copies: 3, settings: {} };

/** The recipe to send, or null when augmentation is off, empty or has a mistake. */
export function recipeOf(state: AugmentationState): AugmentRecipe | null {
  if (!state.enabled) return null;
  const chosen = ALL.filter((a) => state.settings[a.id] !== undefined);
  if (!chosen.length || chosen.some((a) => problemOf(a, state.settings[a.id]))) return null;
  const recipe: AugmentRecipe = { copies: state.copies };
  for (const a of chosen) (recipe as unknown as Record<string, unknown>)[a.id] = state.settings[a.id];
  return recipe;
}

/** What stands in the way of creating with this state, if anything. */
export function augmentationProblem(state: AugmentationState): string | null {
  if (!state.enabled) return null;
  const chosen = ALL.filter((a) => state.settings[a.id] !== undefined);
  if (!chosen.length) return "Choose at least one augmentation, or answer No.";
  const bad = chosen.find((a) => problemOf(a, state.settings[a.id]));
  return bad ? `${bad.label}: ${problemOf(bad, state.settings[bad.id])}` : null;
}

/** "Flip, Rotation, Brightness", and the full settings one per line, for a saved recipe. */
export function recipeSummary(recipe: AugmentRecipe): { names: string; detail: string } {
  const chosen = ALL.filter((a) => recipe[a.id] !== undefined);
  return {
    names: chosen.map((a) => a.label).join(", "),
    detail: [`${recipe.copies} copies per train image`, ...chosen.map((a) => `${a.label}: ${summarize(a, recipe[a.id])}`)].join("\n"),
  };
}

// -- examples ---------------------------------------------------------------------

interface Example { image: string; width: number; height: number; boxes: { box: number[]; label: number | null; crowd: boolean }[] }

interface Examples { row: number; original: Example; items: Record<string, Example>; bytes_per_image: number }

type Items = Record<string, { recipe: Partial<AugmentRecipe>; at: "min" | "max" }>;

/** One train image rendered under each item, fetched again a moment after the items change. */
function useExamples(project: string, dataset: string, items: Items | null, row: number | null, size: number) {
  const [result, setResult] = useState<Examples | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const key = JSON.stringify(items);
  useEffect(() => {
    if (!items) return;
    let alive = true;
    setLoading(true);
    const timer = window.setTimeout(() => {
      api.augmentExamples({ project, dataset, items, row, size })
        .then((r) => alive && (setResult(r), setError(null)))
        .catch((e: Error) => alive && setError(e.message))
        .finally(() => alive && setLoading(false));
    }, 250);
    return () => {
      alive = false;
      window.clearTimeout(timer);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps -- `key` is the items' content
  }, [key, project, dataset, row, size]);
  return { result, error, loading };
}

/** An example drawn to fit its frame; `fill` covers the frame instead, unless that would cut a portrait result. */
function Picture({ example, boxes, labels, fill }: { example: Example | undefined; boxes?: boolean; labels?: Record<string, string>; fill?: boolean }) {
  if (!example) return <div className="aug-picture empty" />;
  const cover = fill && example.width >= example.height;
  return (
    <svg className="aug-picture" viewBox={`0 0 ${example.width} ${example.height}`} preserveAspectRatio={`xMidYMid ${cover ? "slice" : "meet"}`} role="img">
      <image href={example.image} x="0" y="0" width={example.width} height={example.height} />
      {boxes && example.boxes.map((b, j) => (
        <rect key={j} x={b.box[0]} y={b.box[1]} width={b.box[2]! - b.box[0]!} height={b.box[3]! - b.box[1]!}
          fill="none" stroke={b.crowd ? CROWD_COLOR : labelColor(b.label)} strokeWidth={1.25} vectorEffect="non-scaling-stroke">
          <title>{labels?.[String(b.label)] ?? b.label}</title>
        </rect>
      ))}
    </svg>
  );
}

// -- the panel ----------------------------------------------------------------------

export function AugmentationPanel({ project, dataset, state, onChange, trainImages, trainSet, labels, tasks, disabled }: {
  project: string;
  dataset: string;
  state: AugmentationState;
  onChange: (next: AugmentationState) => void;
  /** Train images going into the version, before augmentation. */
  trainImages: number;
  trainSet: string | null;
  labels: Record<string, string>;
  tasks?: TaskId[];
  disabled?: boolean;
}) {
  const [editing, setEditing] = useState<Augmentation | null>(null);

  // Each card shows the image at the strong end of its setting: the chosen one, else a demo.
  const cardItems = useMemo<Items | null>(() => {
    if (!state.enabled || !trainSet) return null;
    const items: Items = {};
    for (const a of ALL) {
      const chosen = state.settings[a.id];
      const value = chosen !== undefined && !problemOf(a, chosen) ? chosen : a.demo;
      items[a.id] = { recipe: { [a.id]: value } as Partial<AugmentRecipe>, at: "max" };
    }
    return items;
  }, [state.enabled, state.settings, trainSet]);
  const cards = useExamples(project, dataset, cardItems, null, 240);
  const row = cards.result?.row ?? null;

  const apply = (item: Augmentation, value: unknown | undefined) => {
    const settings = { ...state.settings };
    if (value === undefined) delete settings[item.id];
    else settings[item.id] = value;
    onChange({ ...state, settings });
    setEditing(null);
  };

  const added = trainImages * state.copies;
  const bytes = cards.result?.bytes_per_image ? cards.result.bytes_per_image * added : 0;
  const keypoints = tasks?.includes("keypoint_detection");
  const flips = Boolean(state.settings.flip || state.settings.rotate90);

  return (
    <section className="aug">
      <div className="aug-ask">
        <div className="aug-ask-text">
          <h3>Augmentation</h3>
          <p className="faint small">
            {trainSet ? <>Adds transformed copies of <span className="mono">{trainSet}</span> images. Validation and test sets are not changed.</> : "This dataset has no train set to augment."}
          </p>
        </div>
        <div className="segmented" role="radiogroup" aria-label="Augment the train set">
          <button role="radio" aria-checked={!state.enabled} className={state.enabled ? "" : "on"} disabled={disabled} onClick={() => onChange({ ...state, enabled: false })}>No</button>
          <button role="radio" aria-checked={state.enabled} className={state.enabled ? "on" : ""} disabled={disabled || !trainSet} onClick={() => onChange({ ...state, enabled: true })}>Yes</button>
        </div>
      </div>

      {state.enabled && trainSet && (
        <>
          <div className="aug-output">
            <div className="aug-output-field">
              <span>Copies per image</span>
              <div className="segmented" role="radiogroup" aria-label="Copies per train image">
                {COPIES.map((n) => (
                  <button key={n} role="radio" aria-checked={state.copies === n} className={state.copies === n ? "on" : ""} disabled={disabled}
                    onClick={() => onChange({ ...state, copies: n })}>{n}×</button>
                ))}
              </div>
            </div>
            <dl className="aug-output-facts">
              <div><dt>{trainSet}</dt><dd className="tabular">{formatNumber(trainImages)} → {formatNumber(trainImages + added)}</dd></div>
              <div><dt>New files</dt><dd className="tabular">{bytes ? `≈ ${formatBytes(bytes)}` : "—"}</dd></div>
            </dl>
          </div>

          {([["Geometry", GEOMETRY], ["Color and noise", PIXELS]] as const).map(([title, items]) => (
            <div key={title} className="aug-group">
              <div className="aug-group-head">
                <h4>{title}</h4>
                {title === "Geometry" && <span className="faint small">Boxes, masks and keypoints move with the image.</span>}
              </div>
              <div className="aug-cards">
                {items.map((item) => {
                  const value = state.settings[item.id];
                  const on = value !== undefined;
                  return (
                    <button key={item.id} type="button" className={`aug-card${on ? " on" : ""}`} disabled={disabled}
                      onClick={() => setEditing(item)} aria-pressed={on} title={item.description}>
                      <span className={`aug-card-media${cards.loading ? " loading" : ""}`}>
                        <Picture example={cards.result?.items[item.id]} fill />
                        {on && <span className="aug-card-check" aria-hidden="true"><Icon name="check" size={12} /></span>}
                      </span>
                      <span className="aug-card-body">
                        <span className="aug-card-name">{item.label}</span>
                        <span className="aug-card-detail">{on ? summarize(item, value) : "Add"}</span>
                      </span>
                    </button>
                  );
                })}
              </div>
            </div>
          ))}
          {cards.error && <p className="form-error">{cards.error}</p>}

          {keypoints && flips && (
            <p className="aug-note small"><Icon name="info" size={14} />Flips and turns move keypoints but keep their names: a left eye flipped horizontally is still labelled left.</p>
          )}
        </>
      )}

      {editing && (
        <AugmentationEditor
          project={project}
          dataset={dataset}
          item={editing}
          value={state.settings[editing.id]}
          row={row}
          labels={labels}
          onApply={(value) => apply(editing, value)}
          onRemove={() => apply(editing, undefined)}
          onClose={() => setEditing(null)}
        />
      )}
    </section>
  );
}

// -- one augmentation's settings -------------------------------------------------------

interface View { key: string; label: string; detail: string; at: "min" | "max"; recipe: unknown; option?: string }

function AugmentationEditor({ project, dataset, item, value, row, labels, onApply, onRemove, onClose }: {
  project: string;
  dataset: string;
  item: Augmentation;
  /** The current setting; undefined when the augmentation is not chosen yet. */
  value: unknown;
  row: number | null;
  labels: Record<string, string>;
  onApply: (value: unknown) => void;
  onRemove: () => void;
  onClose: () => void;
}) {
  const [draft, setDraft] = useState<unknown>(() => structuredClone(value ?? item.spec.initial));
  const problem = problemOf(item, draft);
  const spec = item.spec;

  // What each preview shows: every option on its own, or both ends of the range.
  const views = useMemo<View[]>(() => {
    if (spec.kind === "options") {
      return spec.options.map((o) => ({ key: o.key, label: o.label, detail: "", at: "max", recipe: { [o.key]: true }, option: o.key }));
    }
    if (spec.kind === "range") {
      const v = draft as Range;
      return [
        { key: "min", label: "Minimum", detail: `${signed(v.min)}${spec.unit}`, at: "min", recipe: v },
        { key: "max", label: "Maximum", detail: `${signed(v.max)}${spec.unit}`, at: "max", recipe: v },
      ];
    }
    const v = draft as Record<string, number>;
    if (item.id === "shear") {
      return [
        { key: "min", label: "One way", detail: `−${v.horizontal}° h, −${v.vertical}° v`, at: "min", recipe: v },
        { key: "max", label: "The other way", detail: `+${v.horizontal}° h, +${v.vertical}° v`, at: "max", recipe: v },
      ];
    }
    return [{ key: "max", label: item.id === "grayscale" ? "Grayscale copy" : "At the limit", detail: summarize(item, v), at: "max", recipe: v }];
  }, [spec, draft, item]);

  // Options preview each one alone, whatever is ticked; ranges wait for valid numbers.
  const items = useMemo<Items | null>(() => {
    if (spec.kind !== "options" && problem) return null;
    return Object.fromEntries(views.map((v) => [v.key, { recipe: { [item.id]: v.recipe } as Partial<AugmentRecipe>, at: v.at }]));
  }, [views, problem, item.id, spec.kind]);
  const shown = useExamples(project, dataset, items, row, 480);

  const chosen = value !== undefined;
  const options = spec.kind === "options" ? (draft as Record<string, boolean>) : null;
  // Frames take the image's own shape, so a rotation's corners are not hidden in letterboxing.
  const original = shown.result?.original;
  const aspect = original ? `${original.width} / ${original.height}` : "4 / 3";
  const media = (example: Example | undefined) => (
    <span className={`aug-view-media${shown.loading ? " loading" : ""}`} style={{ aspectRatio: aspect }}><Picture example={example} boxes labels={labels} /></span>
  );

  return (
    <Modal
      title={item.label}
      onClose={onClose}
      width={780}
      className="aug-editor"
      footer={
        <>
          {chosen && <button className="aug-remove" onClick={onRemove}><Icon name="trash" size={13} />Remove</button>}
          <span className="spacer" />
          <button onClick={onClose}>Cancel</button>
          <button className="primary" disabled={Boolean(problem)} onClick={() => onApply(draft)}>{chosen ? "Update" : "Add augmentation"}</button>
        </>
      }
    >
      <p className="aug-editor-lead">
        {item.description}
        {item.geometric && <span className="faint"> Boxes, masks and keypoints are transformed with the image.</span>}
      </p>

      <div className="aug-views" style={{ gridTemplateColumns: `repeat(${views.length + 1}, minmax(0, 1fr))` }}>
        <figure className="aug-view">
          {media(shown.result?.original)}
          <figcaption><span>Original</span></figcaption>
        </figure>
        {views.map((view) => {
          const example = shown.result?.items[view.key];
          if (options && view.option) {
            const on = Boolean(options[view.option]);
            return (
              <button key={view.key} type="button" className={`aug-view selectable${on ? " on" : ""}`} aria-pressed={on}
                onClick={() => setDraft({ ...options, [view.option!]: !on })}>
                {media(example)}
                <span className="aug-view-check" aria-hidden="true">{on && <Icon name="check" size={12} />}</span>
                <span className="aug-view-caption"><span>{view.label}</span><span className="faint">{on ? "Included" : "Not included"}</span></span>
              </button>
            );
          }
          return (
            <figure key={view.key} className="aug-view">
              {media(example)}
              <figcaption><span>{view.label}</span><span className="mono faint">{view.detail}</span></figcaption>
            </figure>
          );
        })}
      </div>

      {spec.kind !== "options" && (
        <div className="aug-editor-controls">
          <Controls spec={spec} value={draft} onChange={setDraft} />
        </div>
      )}
      {problem && <p className="aug-problem">{problem}</p>}
      {shown.error && <p className="form-error">{shown.error}</p>}
    </Modal>
  );
}

function Controls({ spec, value, onChange }: { spec: Exclude<Spec, { kind: "options" }>; value: unknown; onChange: (v: unknown) => void }) {
  if (spec.kind === "range") {
    const v = value as Range;
    return (
      <div className="aug-range">
        <NumberBox label="Minimum" value={v.min} unit={spec.unit} low={spec.low} high={spec.high} step={spec.step} onChange={(n) => onChange({ ...v, min: n })} />
        <span className="aug-to">to</span>
        <NumberBox label="Maximum" value={v.max} unit={spec.unit} low={spec.low} high={spec.high} step={spec.step} onChange={(n) => onChange({ ...v, max: n })} />
        <span className="aug-bounds faint small">Allowed {spec.low}{spec.unit} to {spec.high}{spec.unit}</span>
      </div>
    );
  }
  const v = value as Record<string, number>;
  return (
    <div className="aug-range">
      {spec.fields.map((f) => (
        <NumberBox key={f.key} label={f.label} value={v[f.key]!} unit={f.unit} low={f.low} high={f.high} step={f.step}
          onChange={(n) => onChange({ ...v, [f.key]: n })} />
      ))}
    </div>
  );
}

function NumberBox({ label, value, unit, low, high, step, onChange }: {
  label: string; value: number; unit: string; low: number; high: number; step: number; onChange: (n: number) => void;
}) {
  // Kept as typed, so clearing the box to type a new number does not snap back.
  const [text, setText] = useState(String(value));
  useEffect(() => {
    if (Number(text) !== value) setText(String(value));
    // eslint-disable-next-line react-hooks/exhaustive-deps -- only outside changes reset the text
  }, [value]);
  return (
    <label className="aug-number">
      <span className="aug-number-label">{label}</span>
      <span className="aug-number-box">
        <input type="number" inputMode="decimal" value={text} min={low} max={high} step={step}
          onChange={(e) => {
            setText(e.target.value);
            onChange(e.target.value === "" || e.target.value === "-" ? Number.NaN : Number(e.target.value));
          }} />
        {unit && <span className="aug-unit">{unit}</span>}
      </span>
    </label>
  );
}
