/** What the images in front of you are made of, counted rather than sampled.
 *
 * Everything here is computed over the rows the ribbon leaves, so the numbers are of the
 * selection and not of the dataset: filter to the validation set and the counts are the
 * validation set's. That is the point of putting them beside the gallery rather than on an
 * overview page — a distribution is only useful next to the thing it describes.
 *
 * Counts come from the image rows, which carry how many objects each image has and which
 * classes are in it, so they cover every image of the selection. Box *sizes* need geometry,
 * which the Images tab fetches a screenful at a time, so that one is counted over the images
 * read so far and says as much rather than implying it covers the rest.
 */

import type { ImageBoxes, ImageRow, QaState } from "../api/types";

/** One bar: what it counts, how many, and what picking it would filter to. */
export interface Bar {
  key: string;
  label: string;
  count: number;
  /** Colour for a class swatch; other distributions have none. */
  colour?: string;
}

/** Buckets for a count per image, chosen so that a busy aerial frame and an empty one both
 *  land somewhere useful. Open-ended at the top: some exports have hundreds in one image. */
const OBJECT_BUCKETS: [string, number, number][] = [
  ["none", 0, 0],
  ["1", 1, 1],
  ["2–3", 2, 3],
  ["4–7", 4, 7],
  ["8–15", 8, 15],
  ["16–31", 16, 31],
  ["32–63", 32, 63],
  ["64+", 64, Number.POSITIVE_INFINITY],
];

/** A bucket index, or the last bucket when nothing matched: a box cannot be off the end. */
function orLast(found: number, last: number): number {
  return found < 0 ? last : found;
}

/** How many images the selection holds per set. */
export function bySet(items: ImageRow[]): Bar[] {
  const counts = new Map<string, number>();
  for (const item of items) counts.set(item.set, (counts.get(item.set) ?? 0) + 1);
  return [...counts].sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0]))
    .map(([set, count]) => ({ key: set, label: set, count }));
}

/** Where the selection stands in review. Every image is in exactly one of these.
 *
 * "Not reviewed" rather than the ribbon's "Unverified" on purpose: the ribbon's filter means
 * anything not verified, rework included, and two numbers under one word would not agree.
 */
export function byStatus(items: ImageRow[], statuses: Record<string, QaState>): Bar[] {
  const order = [
    ["reviewed", "Verified"],
    ["rework", "Rework"],
    ["unreviewed", "Not reviewed"],
  ] as const;
  const counts = new Map<string, number>(order.map(([key]) => [key, 0]));
  for (const item of items) {
    const status = statuses[item.image]?.status ?? "unreviewed";
    counts.set(status, (counts.get(status) ?? 0) + 1);
  }
  return order.map(([key, label]) => ({ key, label, count: counts.get(key) ?? 0 }));
}

/** How many objects each image carries, in buckets. Images with none are worth seeing. */
export function byObjectCount(items: ImageRow[]): Bar[] {
  const counts = OBJECT_BUCKETS.map(() => 0);
  for (const item of items) {
    const at = OBJECT_BUCKETS.findIndex(([, low, high]) => item.objects >= low && item.objects <= high);
    if (at >= 0) counts[at] = (counts[at] ?? 0) + 1;
  }
  return OBJECT_BUCKETS.map(([label], at) => ({ key: label, label, count: counts[at]! }))
    .filter((bar) => bar.count > 0);
}

/** How many images of the selection contain each class, most first.
 *
 * Images, not boxes: an image row knows which classes are in it, not how many of each, and
 * counting an image once per class it contains is the number a filter would give back.
 */
export function byClass(items: ImageRow[], labels: Record<string, string>, colour: (label: number) => string): Bar[] {
  const counts = new Map<number, number>();
  for (const item of items) for (const label of item.classes) counts.set(label, (counts.get(label) ?? 0) + 1);
  return [...counts].sort((a, b) => b[1] - a[1] || a[0] - b[0])
    .map(([label, count]) => ({
      key: String(label),
      label: labels[String(label)] ?? String(label),
      count,
      colour: colour(label),
    }));
}

/** How big the labelled objects are, as a share of their image's area.
 *
 * The share rather than pixels: a 40-pixel box is small in a 4K frame and most of a
 * thumbnail, and what a detector struggles with is the share. Counted over the geometry in
 * hand, which is a page of images rather than the whole selection.
 */
export function byBoxSize(items: ImageRow[], boxes: Record<string, ImageBoxes>): { bars: Bar[]; images: number; objects: number } {
  const buckets: [string, number][] = [
    ["under 0.1%", 0.001],
    ["0.1–1%", 0.01],
    ["1–5%", 0.05],
    ["5–25%", 0.25],
    ["over 25%", Number.POSITIVE_INFINITY],
  ];
  const counts = buckets.map(() => 0);
  let images = 0;
  let objects = 0;
  for (const item of items) {
    const geometry = boxes[item.image];
    if (!geometry) continue;
    images += 1;
    for (const [, x0, y0, x1, y1] of geometry.b) {
      const share = Math.max(x1 - x0, 0) * Math.max(y1 - y0, 0);
      const at = orLast(buckets.findIndex(([, top]) => share < top), buckets.length - 1);
      counts[at] = (counts[at] ?? 0) + 1;
      objects += 1;
    }
  }
  return {
    bars: buckets.map(([label], at) => ({ key: label, label, count: counts[at]! })),
    images,
    objects,
  };
}
