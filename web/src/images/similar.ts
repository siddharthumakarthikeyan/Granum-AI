/** Reading the neighbour graph against the images a dataset holds right now.
 *
 * The service judges duplicates and leaks over the vectors it has, which are keyed by image
 * and outlive every version of a set. The dashboard holds a report for as long as the reader
 * stays on the page, and images move or leave while they work, so everything here re-joins the
 * report to the current list before anything is drawn: a group that has lost all but one of
 * its members is no longer a group, and a pair whose sides now sit in one set is no longer a
 * leak. Pure functions, so the rules can be tested without a browser.
 *
 * The distinction that runs through all of it: a group holds *pictures*, and one picture can
 * be in the dataset as several images — the exporter's copies of it, usually augmented. Those
 * copies are not redundancy, so "select the rest" means the other pictures and the copies that
 * came with them, never the keeper's own.
 */

import type { EmbeddingReport, ExportGroup, ImageRow, LeakPair, SimilarImages } from "../api/types";
import { fileName } from "../review/status";

/** One image of a group, and which of the group's source pictures it came from. */
export interface GroupImage {
  item: ImageRow;
  family: number;
}

/** Images that are the same picture as each other, from more than one source picture. */
export interface CopyGroup {
  /** Stable across re-joins: the first image of the group. */
  id: string;
  images: GroupImage[];
  sets: string[];
  /** The group straddles sets, so removing the repeats also closes a leak. */
  crossesSets: boolean;
  /** How far apart its least alike pair is, as a share of the typical distance: near zero
   *  is one shot taken twice, higher is a run of frames chained together. */
  spread: number;
  /** Distinct source pictures in the group: what there is to choose between. */
  sources: number;
}

/** The exporter's copies of one picture, as images the dataset still holds. */
export interface ExportSet {
  id: string;
  source: string;
  images: ImageRow[];
  sets: string[];
  /** The copies were dealt into different sets, which is a leak however alike they are. */
  crossesSets: boolean;
}

/** Two near-identical images on opposite sides of a split. */
export interface LeakRow {
  id: string;
  a: ImageRow;
  b: ImageRow;
  /** Cosine distance, and what that is as a share of the dataset's typical distance. */
  distance: number;
  share: number;
  /** Under the duplicate threshold: the same photograph, not merely a close frame. */
  sameImage: boolean;
  /** Both sides are copies of one source picture, so the split was cut through it. */
  sameSource: boolean;
}

/** One image far from anything else in the dataset. */
export interface OutlierRow {
  item: ImageRow;
  /** Distance to its nearest neighbour, as a share of the typical distance: 1 is a whole
   *  typical distance away, which is as far as two images of one dataset usually get. */
  score: number;
  /** Past the policy's threshold: nothing in this dataset is really like it. The rest of
   *  the list is only "the furthest from anything here", which on a set of one subject
   *  taken by one camera is the most anybody will get. */
  alone: boolean;
}

/** One answer to "what else looks like this", as a row the gallery can draw. */
export interface LikeRow {
  item: ImageRow;
  distance: number;
  /** The distance as a share of this dataset's typical distance, which is what makes it
   *  readable: 0.05 is the same picture again, 1.0 is an unrelated image. */
  share: number;
}

/** What to say about one image in the gallery, once a report has been read. */
export interface SimilarMark {
  /** How many images are the same picture as this one, itself included. */
  copies: number;
  /** How many times the exporter wrote this image's source picture out. */
  exports: number;
  /** This image is one side of a cross-split leak. */
  leak: boolean;
}

/** The set whose copy is worth keeping: the model needs it, the evaluation must not have it. */
const TRAIN = "train";

/** Order within a group: the training copy first, then by filename. The first is the keeper. */
function keepOrder(a: GroupImage, b: GroupImage): number {
  const rank = (image: GroupImage) => (image.item.set === TRAIN ? 0 : 1);
  return rank(a) - rank(b)
    || a.item.set.localeCompare(b.item.set)
    || fileName(a.item.image).localeCompare(fileName(b.item.image), undefined, { numeric: true });
}

/** The report's duplicate groups, as rows of images the dataset still holds. */
export function liveGroups(
  groups: string[][],
  byImage: Map<string, ImageRow>,
  spreads: number[] = [],
  families: number[][] = [],
): CopyGroup[] {
  const live: CopyGroup[] = [];
  for (const [at, group] of groups.entries()) {
    const images: GroupImage[] = [];
    for (const [member, image] of group.entries()) {
      const item = byImage.get(image);
      if (item) images.push({ item, family: families[at]?.[member] ?? member });
    }
    const sources = new Set(images.map((image) => image.family));
    // One picture left is not a repetition of anything, however many copies of it remain.
    if (sources.size < 2) continue;
    images.sort(keepOrder);
    // The keeper's own copies stay beside it: they are one picture, not a repetition.
    const keeper = images[0]!.family;
    images.sort((a, b) => Number(b.family === keeper) - Number(a.family === keeper) || keepOrder(a, b));
    const sets = [...new Set(images.map((image) => image.item.set))].sort();
    // The spread was measured over the whole group, including any member since deleted:
    // it is a fact about the pictures, not about what is left of them.
    live.push({
      id: images[0]!.item.image, images, sets, sources: sources.size,
      crossesSets: sets.length > 1, spread: spreads[at] ?? 0,
    });
  }
  live.sort((a, b) => b.sources - a.sources || b.images.length - a.images.length
    || fileName(a.images[0]!.item.image).localeCompare(fileName(b.images[0]!.item.image), undefined, { numeric: true }));
  return live;
}

/** The exporter's copy sets, as images the dataset still holds. */
export function liveExports(groups: ExportGroup[], byImage: Map<string, ImageRow>): ExportSet[] {
  const live: ExportSet[] = [];
  for (const group of groups) {
    const images = group.images.map((image) => byImage.get(image)).filter((row): row is ImageRow => row !== undefined);
    if (images.length < 2) continue;
    images.sort((a, b) => a.set.localeCompare(b.set)
      || fileName(a.image).localeCompare(fileName(b.image), undefined, { numeric: true }));
    const sets = [...new Set(images.map((image) => image.set))].sort();
    live.push({ id: group.source, source: group.source, images, sets, crossesSets: sets.length > 1 });
  }
  // The copies that were dealt into different sets come first: those are a leak, and the
  // rest of this tab is only here to be checked.
  live.sort((a, b) => Number(b.crossesSets) - Number(a.crossesSets)
    || b.images.length - a.images.length
    || a.source.localeCompare(b.source, undefined, { numeric: true }));
  return live;
}

/** The report's leaks, as pairs of images that are still in the dataset and still apart. */
export function liveLeaks(leaks: LeakPair[], byImage: Map<string, ImageRow>, scale: number): LeakRow[] {
  const live: LeakRow[] = [];
  for (const pair of leaks) {
    const a = byImage.get(pair.a);
    const b = byImage.get(pair.b);
    if (!a || !b || a.set === b.set) continue;
    live.push({
      id: `${pair.a}\u0000${pair.b}`,
      a, b,
      distance: pair.distance,
      share: scale > 0 ? pair.distance / scale : 0,
      sameImage: pair.same_image,
      sameSource: pair.same_source,
    });
  }
  live.sort((x, y) => x.distance - y.distance);
  return live;
}

/** The repeats of every group: the other source pictures, and the copies that came with them.
 *
 * Never the keeper's own copies — those are one picture written out twice, and removing them
 * undoes an augmentation rather than removing redundancy.
 */
export function redundantImages(groups: CopyGroup[]): string[] {
  return groups.flatMap((group) => {
    const keeper = group.images[0]!.family;
    return group.images.filter((image) => image.family !== keeper).map((image) => image.item.image);
  });
}

/** The images of one side of the leaks: the sides are the two sets a pair straddles. */
export function leakSide(leaks: LeakRow[], set: string): string[] {
  const images = new Set<string>();
  for (const leak of leaks) {
    for (const image of [leak.a, leak.b]) if (image.set === set) images.add(image.image);
  }
  return [...images];
}

/** How many leaked images each set holds, most first: the choice of which side to remove. */
export function leakSides(leaks: LeakRow[]): { set: string; images: number }[] {
  const counts = new Map<string, Set<string>>();
  for (const leak of leaks) {
    for (const image of [leak.a, leak.b]) {
      const held = counts.get(image.set) ?? new Set<string>();
      held.add(image.image);
      counts.set(image.set, held);
    }
  }
  return [...counts].map(([set, images]) => ({ set, images: images.size }))
    .sort((a, b) => b.images - a.images || a.set.localeCompare(b.set));
}

/** The report's outliers, as images the dataset still holds, furthest from anything first. */
export function liveOutliers(
  outliers: { image: string; score: number; set: string; alone?: boolean }[],
  byImage: Map<string, ImageRow>,
): OutlierRow[] {
  const live: OutlierRow[] = [];
  for (const outlier of outliers) {
    const item = byImage.get(outlier.image);
    if (item) live.push({ item, score: outlier.score, alone: outlier.alone ?? false });
  }
  live.sort((a, b) => b.score - a.score
    || fileName(a.item.image).localeCompare(fileName(b.item.image), undefined, { numeric: true }));
  return live;
}

/** The neighbours of one image, as rows of the gallery, nearest first.
 *
 * The service answers over the dataset as it stands now, but the gallery's own list is a
 * moment older or newer, so anything it cannot place is dropped rather than drawn as a gap.
 * The image asked about never appears among its own neighbours.
 */
export function likeRows(answer: SimilarImages, byImage: Map<string, ImageRow>): LikeRow[] {
  const rows: LikeRow[] = [];
  for (const neighbour of answer.neighbours) {
    const item = byImage.get(neighbour.image);
    if (!item || item.image === answer.image) continue;
    rows.push({
      item,
      distance: neighbour.distance,
      share: answer.scale > 0 ? neighbour.distance / answer.scale : 0,
    });
  }
  return rows;
}

/** What to mark on each thumbnail in the ordinary gallery, once the graph has been read. */
export function marksFor(groups: CopyGroup[], exported: ExportSet[], leaks: LeakRow[]): Map<string, SimilarMark> {
  const marks = new Map<string, SimilarMark>();
  const mark = (image: string) => {
    const held = marks.get(image) ?? { copies: 0, exports: 0, leak: false };
    marks.set(image, held);
    return held;
  };
  for (const group of groups) {
    for (const image of group.images) mark(image.item.image).copies = group.images.length;
  }
  for (const group of exported) {
    for (const image of group.images) mark(image.image).exports = group.images.length;
  }
  for (const leak of leaks) {
    mark(leak.a.image).leak = true;
    mark(leak.b.image).leak = true;
  }
  return marks;
}

/** Everything the gallery and the tabs need from one report, joined to the live images. */
export function readReport(report: EmbeddingReport, images: ImageRow[]) {
  const byImage = new Map(images.map((image) => [image.image, image]));
  const groups = liveGroups(report.duplicates.groups, byImage, report.duplicates.spreads, report.duplicates.families);
  const exported = liveExports(report.exports.groups, byImage);
  const leaks = liveLeaks(report.leaks, byImage, report.scale);
  const outliers = liveOutliers(report.outliers, byImage);
  return {
    groups,
    exports: exported,
    leaks,
    outliers,
    marks: marksFor(groups, exported, leaks),
    /** Images that would go if every group kept one picture and the copies of it. */
    redundant: redundantImages(groups).length,
    /** Images with nothing in the set really like them, of the ones listed. */
    alone: outliers.filter((row) => row.alone).length,
    /** Everything the service found, whether or not it sent the detail of all of it. */
    found: {
      groups: report.duplicates.total,
      /** Source pictures that repeat another picture: what there is to remove. */
      redundant: report.duplicates.redundant,
      sources: report.exports.sources,
      exported: report.exports.repeated,
      exportedImages: report.exports.images,
      leaks: report.leaks_total,
    },
    /** The service capped what it sent; say so rather than imply these are all of them. */
    moreGroups: Math.max(0, report.duplicates.total - report.duplicates.shown),
    moreExports: Math.max(0, report.exports.repeated - report.exports.shown),
    moreLeaks: Math.max(0, report.leaks_total - report.leaks.length),
  };
}
