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

/** One of several ranges of an augmentation, held as `<key>_min` and `<key>_max`. */
interface RangeField extends Field {
  /** After the number where both ends are shown in one line: "+10% h". */
  short: string;
  signed?: boolean;
}

interface Option { key: string; label: string }

/** Settings of each augmentation, with the values used when it is first added. */
type Spec =
  | { kind: "options"; options: Option[]; initial: Record<string, boolean> }
  | { kind: "range"; unit: string; low: number; high: number; step: number; initial: Range; /** No "+" before positive values. */ unsigned?: boolean }
  | { kind: "ranges"; ranges: RangeField[]; initial: Record<string, number> }
  /** `kinds` are ways of doing it to choose between; each copy gets one of those chosen. */
  | { kind: "values"; fields: Field[]; kinds?: Option[]; initial: Record<string, number | boolean> };

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

/** The chosen kinds by name; the first kind is what a setting saved without any gets. */
function kindSummary(value: Record<string, unknown>, kinds: Option[]): string {
  const on = kinds.filter((k) => value[k.key] === true);
  return (on.length ? on : kinds.slice(0, 1)).map((k) => k.label).join(", ");
}

/** One end of every range of a setting: "+10% h, −5% v". */
function endSummary(ranges: RangeField[], value: Record<string, number>, at: "min" | "max"): string {
  return ranges.map((r) => {
    const n = value[`${r.key}_${at}`]!;
    return `${r.signed ? signed(n) : n}${r.unit}${r.short ? ` ${r.short}` : ""}`;
  }).join(", ");
}

const BLUR_KINDS: Option[] = [
  { key: "gaussian", label: "Gaussian" }, { key: "median", label: "Median" },
  { key: "average", label: "Average" }, { key: "box", label: "Box" },
];
const NOISE_KINDS: Option[] = [
  { key: "gaussian", label: "Gaussian" }, { key: "salt_pepper", label: "Salt & pepper" }, { key: "iso", label: "ISO" },
];
const TRANSLATION: RangeField[] = [
  { key: "horizontal", label: "Horizontal", unit: "%", short: "h", low: -100, high: 100, step: 1, signed: true },
  { key: "vertical", label: "Vertical", unit: "%", short: "v", low: -100, high: 100, step: 1, signed: true },
];
const GRID: RangeField[] = [
  { key: "size", label: "Grid spacing", unit: "px", short: "grid", low: 2, high: 200, step: 1 },
  { key: "ratio", label: "Hole, as a share of the spacing", unit: "", short: "holes", low: 0, high: 0.9, step: 0.05 },
];

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
  {
    id: "translation", label: "Translation", geometric: true,
    description: "Shifts the image by a random share of its width and height. The part left uncovered is filled black.",
    spec: { kind: "ranges", ranges: TRANSLATION, initial: { horizontal_min: -10, horizontal_max: 10, vertical_min: -10, vertical_max: 10 } },
    demo: { horizontal_min: -20, horizontal_max: 20, vertical_min: -15, vertical_max: 15 },
    summary: (v: Record<string, number>) =>
      `${signed(v.horizontal_min!)} to ${signed(v.horizontal_max!)}% h, ${signed(v.vertical_min!)} to ${signed(v.vertical_max!)}% v`,
  },
  {
    id: "zoom", label: "Zoom", geometric: true,
    description: "Scales the image about its centre, in the same frame. Above 100% magnifies and cuts the edges away; below shrinks it and leaves a black border.",
    spec: { kind: "range", unit: "%", low: 10, high: 400, step: 1, initial: { min: 80, max: 120 }, unsigned: true },
    demo: { min: 60, max: 160 },
    summary: (v: Range) => `${v.min}% to ${v.max}%`,
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
    id: "gamma", label: "Gamma", geometric: false,
    description: "Gamma correction: below 1 darkens the mid-tones, above 1 lifts them. Black and white stay put.",
    spec: { kind: "range", unit: "", low: 0.1, high: 5, step: 0.1, initial: { min: 0.8, max: 1.2 }, unsigned: true },
    demo: { min: 0.5, max: 2 },
    summary: (v: Range) => `${v.min} to ${v.max}`,
  },
  {
    id: "blur", label: "Blur", geometric: false,
    description: "Blurs with a random strength up to the limit. Each copy gets one of the chosen kinds.",
    spec: {
      kind: "values", kinds: BLUR_KINDS,
      fields: [{ key: "max", label: "Up to", unit: "px", low: 0, high: 20, step: 0.5 }],
      initial: { max: 1.5, gaussian: true },
    },
    demo: { max: 4, gaussian: true },
    summary: (v: Record<string, number | boolean>) => `Up to ${v.max} px · ${kindSummary(v, BLUR_KINDS)}`,
  },
  {
    id: "noise", label: "Noise", geometric: false,
    description: "Adds noise with a random strength up to the limit. Each copy gets one of the chosen kinds: Gaussian grain, black and white specks, or the grain of a camera at high ISO.",
    spec: {
      kind: "values", kinds: NOISE_KINDS,
      fields: [{ key: "max", label: "Up to", unit: "%", low: 0, high: 50, step: 0.5 }],
      initial: { max: 2, gaussian: true },
    },
    demo: { max: 8, gaussian: true },
    summary: (v: Record<string, number | boolean>) => `Up to ${v.max}% · ${kindSummary(v, NOISE_KINDS)}`,
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
  {
    id: "gridmask", label: "Grid mask", geometric: false,
    description: "Blacks out a regular grid of squares, shifted at random on each copy. Labels are kept.",
    spec: { kind: "ranges", ranges: GRID, initial: { size_min: 32, size_max: 96, ratio_min: 0.3, ratio_max: 0.5 } },
    demo: { size_min: 32, size_max: 64, ratio_min: 0.5, ratio_max: 0.5 },
    summary: (v: Record<string, number>) => `${v.size_min} to ${v.size_max} px, ${v.ratio_min} to ${v.ratio_max} holes`,
  },
];

const ALL = [...GEOMETRY, ...PIXELS];
const COPIES = [1, 2, 3, 4, 5];

const summarize = (a: Augmentation, value: unknown) => (a.summary as (v: unknown) => string)(value);

/** Why a setting's numbers cannot be used, if they cannot. */
function numberProblem(item: Augmentation, value: unknown): string | null {
  const spec = item.spec;
  if (spec.kind === "options") return null;
  if (spec.kind === "range") {
    const v = value as Range;
    if (![v.min, v.max].every((n) => Number.isFinite(n) && n >= spec.low && n <= spec.high)) return `Use values from ${spec.low} to ${spec.high}.`;
    return v.min > v.max ? "Minimum is above maximum." : null;
  }
  const v = value as Record<string, number>;
  const within = (n: number | undefined, f: Field) => Number.isFinite(n) && n! >= f.low && n! <= f.high;
  if (spec.kind === "ranges") {
    for (const r of spec.ranges) {
      const min = v[`${r.key}_min`], max = v[`${r.key}_max`];
      if (!within(min, r) || !within(max, r)) return `${r.label}: use ${r.low} to ${r.high}.`;
      if (min! > max!) return `${r.label}: minimum is above maximum.`;
    }
    return null;
  }
  const bad = spec.fields.find((f) => !within(v[f.key], f));
  return bad ? `${bad.label.replace(" ±", "")}: use ${bad.low} to ${bad.high}.` : null;
}

/** Why a setting cannot be used, if it cannot. */
function problemOf(item: Augmentation, value: unknown): string | null {
  const spec = item.spec;
  const chosen = value as Record<string, unknown>;
  if (spec.kind === "options") return Object.values(chosen).some(Boolean) ? null : "Choose at least one.";
  const problem = numberProblem(item, value);
  if (problem) return problem;
  return spec.kind === "values" && spec.kinds && !spec.kinds.some((k) => chosen[k.key] === true) ? "Choose at least one kind." : null;
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
  const spec = item.spec;
  const [draft, setDraft] = useState<unknown>(() => {
    const start = structuredClone(value ?? spec.initial) as Record<string, unknown>;
    // A setting saved before kinds existed has none ticked; it gets the first, as the service gives it.
    if (spec.kind === "values" && spec.kinds && !spec.kinds.some((k) => start[k.key] === true)) start[spec.kinds[0]!.key] = true;
    return start;
  });
  const problem = problemOf(item, draft);
  const kinds = spec.kind === "values" ? spec.kinds : undefined;

  // What each preview shows: every option or kind on its own, or both ends of the range.
  const views = useMemo<View[]>(() => {
    if (spec.kind === "options") {
      return spec.options.map((o) => ({ key: o.key, label: o.label, detail: "", at: "max", recipe: { [o.key]: true }, option: o.key }));
    }
    if (spec.kind === "range") {
      const v = draft as Range;
      const show = spec.unsigned ? String : signed;
      return [
        { key: "min", label: "Minimum", detail: `${show(v.min)}${spec.unit}`, at: "min", recipe: v },
        { key: "max", label: "Maximum", detail: `${show(v.max)}${spec.unit}`, at: "max", recipe: v },
      ];
    }
    const v = draft as Record<string, number>;
    if (spec.kind === "ranges") {
      return [
        { key: "min", label: "Minimum", detail: endSummary(spec.ranges, v, "min"), at: "min", recipe: v },
        { key: "max", label: "Maximum", detail: endSummary(spec.ranges, v, "max"), at: "max", recipe: v },
      ];
    }
    if (spec.kinds) {
      // Each kind alone at the limit, whatever is ticked.
      const numbers = Object.fromEntries(spec.fields.map((f) => [f.key, v[f.key]]));
      return spec.kinds.map((k) => ({ key: k.key, label: k.label, detail: "", at: "max", recipe: { ...numbers, [k.key]: true }, option: k.key }));
    }
    if (item.id === "shear") {
      return [
        { key: "min", label: "One way", detail: `−${v.horizontal}° h, −${v.vertical}° v`, at: "min", recipe: v },
        { key: "max", label: "The other way", detail: `+${v.horizontal}° h, +${v.vertical}° v`, at: "max", recipe: v },
      ];
    }
    return [{ key: "max", label: item.id === "grayscale" ? "Grayscale copy" : "At the limit", detail: summarize(item, v), at: "max", recipe: v }];
  }, [spec, draft, item]);

  // Options and kinds preview each one alone, whatever is ticked; numbers must be valid first.
  const unusable = numberProblem(item, draft);
  const items = useMemo<Items | null>(() => {
    if (unusable) return null;
    return Object.fromEntries(views.map((v) => [v.key, { recipe: { [item.id]: v.recipe } as Partial<AugmentRecipe>, at: v.at }]));
  }, [views, unusable, item.id]);
  const shown = useExamples(project, dataset, items, row, 480);

  const chosen = value !== undefined;
  const options = spec.kind === "options" || kinds ? (draft as Record<string, boolean>) : null;
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
      width={views.length > 3 ? 920 : 780}
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
  if (spec.kind === "ranges") {
    const v = value as Record<string, number>;
    return (
      <div className="aug-ranges">
        {spec.ranges.map((r) => (
          <div key={r.key} className="aug-range" role="group" aria-label={r.label}>
            <span className="aug-range-name">{r.label}</span>
            <NumberBox label="Minimum" value={v[`${r.key}_min`]!} unit={r.unit} low={r.low} high={r.high} step={r.step} onChange={(n) => onChange({ ...v, [`${r.key}_min`]: n })} />
            <span className="aug-to">to</span>
            <NumberBox label="Maximum" value={v[`${r.key}_max`]!} unit={r.unit} low={r.low} high={r.high} step={r.step} onChange={(n) => onChange({ ...v, [`${r.key}_max`]: n })} />
            <span className="aug-bounds faint small">Allowed {r.low}{r.unit} to {r.high}{r.unit}</span>
          </div>
        ))}
      </div>
    );
  }
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
