/** One stable colour per class index, shared by every screen that draws boxes.
 *
 * The colour follows the class, not its position in a list, so the same class keeps its
 * colour between the gallery, the detail panel and the review inspector.
 */

export const CLASS_HUES = [
  "#22d3ee", // cyan
  "#f472b6", // pink
  "#fbbf24", // amber
  "#a78bfa", // violet
  "#5fc7a0", // green
  "#fb923c", // orange
  "#60a5fa", // blue
  "#e879f9", // magenta
  "#f87171", // red
  "#34d399", // emerald
  "#c4b5fd", // lilac
  "#facc15", // yellow
];

/** Crowd and ignore regions are deliberately colourless: they are not a class. */
export const CROWD_COLOR = "#6b7786";

export function labelColor(label: number | null | undefined): string {
  if (label === null || label === undefined) return CROWD_COLOR;
  return CLASS_HUES[Math.abs(label) % CLASS_HUES.length]!;
}
