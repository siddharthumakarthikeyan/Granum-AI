/** How findings are named and explained. One place, so the page, the reviewer and the
 * reasons saved with decisions use the same words. */

import type { Finding, FindingRule } from "../api/types";

export const RULES: { id: FindingRule; label: string; short: string; color: string; action: string }[] = [
  { id: "missing_label", label: "Possible missing label", short: "Missing label", color: "var(--amber)", action: "Add a box if the object should be labelled." },
  { id: "wrong_class", label: "Possible wrong class", short: "Wrong class", color: "var(--pink)", action: "Change the class if the label is wrong." },
  { id: "loose_box", label: "Box may not fit", short: "Loose box", color: "var(--cyan)", action: "Tighten the box if it does not fit the object." },
  { id: "missed", label: "Model does not find this label", short: "Not found", color: "var(--learn-insufficient)", action: "Check the label; keep it if it is a valid hard case." },
];
export const RULE = new Map(RULES.map((r) => [r.id, r]));

const range = (c: [number, number] | null) => (c ? (c[0] === c[1] ? c[0].toFixed(2) : `${c[0].toFixed(2)}–${c[1].toFixed(2)}`) : "");

/** One sentence of evidence, in the reviewer's terms. */
export function evidence(f: Finding, classes: Record<string, string>): string {
  const name = (label: number | null | undefined) => (label === null || label === undefined ? "object" : classes[String(label)] ?? `class ${label}`);
  const seen = `${f.rounds} of ${f.window} epochs`;
  switch (f.rule) {
    case "missing_label":
      return `The model predicts ${name(f.predicted_label)} here in ${seen} (confidence ${range(f.confidence)}), and nothing is labelled here.`;
    case "wrong_class":
      return `Labelled ${name(f.label)}; the model predicts ${name(f.predicted_label)} on this box in ${seen} (confidence ${range(f.confidence)}).`;
    case "loose_box":
      return `The model's ${name(f.label)} box overlaps this label at IoU ${(f.iou ?? 0).toFixed(2)}, too little to match, in ${seen}.`;
    case "missed":
      return `The model does not find this ${name(f.label)} in ${seen}.`;
  }
}

/** Whether the model stopped showing it: it may have learned the label as it is. */
export function faded(f: Finding): string | null {
  return f.in_last_round ? null : `Last seen in epoch ${f.last_epoch + 1}.`;
}

/** What is saved with a decision, so the log says which finding it answered. */
export function decisionReason(version: string, f: Finding | undefined, note: string): string {
  const what = f ? `${RULE.get(f.rule)!.label} (${f.rounds}/${f.window} epochs)` : "finding";
  return `${version}: ${what}. ${note}`.trim();
}

/** Rough review effort, stated as an estimate: a fixed time per finding. */
export const SECONDS_PER_FINDING = 20;

/** How each review status reads on a finding. */
export const STATUS_LABEL: Record<string, string> = {
  correct: "Label is right",
  corrected: "Fixing",
  ambiguous: "Ambiguous",
  deferred: "Later",
  excluded: "Excluded",
};

/** An xyxy box as SVG rect attributes. */
export const rectOf = ([x0, y0, x1, y1]: [number, number, number, number]) => ({ x: x0, y: y0, width: Math.max(0, x1 - x0), height: Math.max(0, y1 - y0) });

/** A view around a box: ``context`` times its size at ``aspect``, kept inside the image. */
export function cropView(box: [number, number, number, number], W: number, H: number, context: number, aspect: number, min = 64): string {
  const [x0, y0, x1, y1] = box;
  let h = Math.max(min, ((x1 - x0) * context) / aspect, (y1 - y0) * context);
  let w = h * aspect;
  if (w > W) { w = W; h = w / aspect; }
  if (h > H) { h = H; w = Math.min(W, h * aspect); }
  const clamp = (v: number, hi: number) => Math.min(Math.max(0, v), Math.max(0, hi));
  return `${clamp((x0 + x1) / 2 - w / 2, W - w)} ${clamp((y0 + y1) / 2 - h / 2, H - h)} ${w} ${h}`;
}
