/** The Images tab: browse a dataset's images, review them, and create dataset versions.
 *
 * Everything in the ribbon filters and orders in the browser over one payload from
 * /api/images, so changing a filter is instant. Box geometry is far bigger, so it is
 * fetched a screenful at a time from /api/images/boxes as the reader scrolls.
 *
 * Review is a mode of this page, switched on in the ribbon: images become selectable for
 * bulk decisions (verify, rework, isolate, delete) and open in the full-screen inspector,
 * where boxes can be edited. Duplicates is another: copies of one picture, images that sit
 * in two sets at once and images with nothing like them, read off the dataset's image vectors
 * and selectable in the same way. Create dataset freezes the sets into a named dataset
 * version; only those are offered for training.
 *
 * Patches is a third mode: every labelled object of the images the ribbon leaves, one tile
 * each, which is how a class is checked for consistency -- a wrong label stands out in a wall
 * of its own kind in a way it never does inside a busy image.
 *
 * The same vectors answer two questions about a single image, and both are ordinary states of
 * the gallery rather than modes of their own: "what else looks like this one", which replaces
 * the list with that image's neighbours nearest first, and "how unlike the rest of the set is
 * each image", which is an order to sort by. Both need the dataset to have been read once.
 */

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { api } from "../api/client";
import type { EmbeddingReport, EmbeddingStatus, ImageBoxes, ImageRow, ImagesOverview, Job, QaState, QaStatus, SavedView, SimilarImages, TagOverview } from "../api/types";
import { EmptyState, Icon, PageHeader, formatNumber, formatWhen, plural } from "../components/ui";
import { ISOLATED_SET, groupDatasets, REMOVED_SET } from "../pages/datasets";
import { ImageInspector } from "../review/ImageInspector";
import { STATUS_LABEL, fileName, readReviewer, saveReviewer, type MoveAction } from "../review/status";
import { navigate, routeHref } from "../router";
import { useStore } from "../store/store";
import { tasksLabel } from "../importing/tasks";
import { CreateDatasetDialog } from "./CreateDatasetDialog";
import { DuplicatesView, type SimilarTab } from "./DuplicatesView";
import { ImageDetail } from "./ImageDetail";
import { ImageEditor } from "./ImageEditor";
import { PatchesView } from "./PatchesView";
import { PrelabelDialog } from "./PrelabelDialog";
import { StatsPanel } from "./StatsPanel";
import { labelColor } from "./labelColors";
import { likeRows, readReport, type SimilarMark } from "./similar";

const PAGE = 120;
/** Objects drawn at once in Patches, and how many more each page adds. One page is a run
 *  a reader can scan in a sitting; beyond that it is scrolling rather than checking. */
const PATCHES = 600;
/** Neighbours asked for at a time when the gallery is ordered by likeness; the service caps
 *  it at 200, which is also as far as "more like this" is worth reading. */
const NEIGHBOURS = 60;
const MOST_NEIGHBOURS = 200;

type StatusFilter = "all" | "verified" | "unverified" | "rework" | "commented";
type OrderKey = "filename" | "updated" | "added" | "uniqueness";
type Direction = "asc" | "desc";
type TrayMode = "rework" | "isolate" | "delete" | null;

const ORDER_LABEL: Record<OrderKey, string> = {
  filename: "Filename",
  updated: "Last updated",
  added: "Date added",
  uniqueness: "Uniqueness",
};

/** Verified is the reviewed status; unreviewed and rework both read as unverified. */
export function isVerified(state: QaState | undefined): boolean {
  return state?.status === "reviewed";
}

/** Rework, or a comment thread: worth a mark on the thumbnail either way. */
export function isFlagged(state: QaState | undefined): boolean {
  return state?.status === "rework" || (state?.comments ?? 0) > 0;
}

function matchesStatus(filter: StatusFilter, state: QaState | undefined): boolean {
  if (filter === "verified") return isVerified(state);
  if (filter === "unverified") return !isVerified(state);
  if (filter === "rework") return state?.status === "rework";
  if (filter === "commented") return (state?.comments ?? 0) > 0;
  return true;
}

export function ImagesPage({ project, dataset, review, edit, similar, patches, stats, like, open: openImage }: { project: string; dataset?: string; review: boolean; edit: boolean; similar: boolean; patches: boolean; stats: boolean; like?: string; open?: string }) {
  const tables = useStore((s) => s.tables);
  const loading = useStore((s) => s.loading);
  const refreshProject = useStore((s) => s.refreshProject);
  const datasets = useMemo(
    () => groupDatasets(tables).filter((d) => d.splits.some((s) => s.name !== REMOVED_SET)),
    [tables],
  );
  const active = dataset ?? datasets[0]?.name;
  const tasks = tables.find((t) => t.dataset_name === active && t.tasks?.length)?.tasks;
  const removedCount = datasets.find((d) => d.name === active)?.splits.find((s) => s.name === REMOVED_SET)?.latest.row_count ?? 0;

  const [data, setData] = useState<ImagesOverview | null>(null);
  const [boxes, setBoxes] = useState<Record<string, ImageBoxes>>({});
  const [error, setError] = useState<string | null>(null);

  const [split, setSplit] = useState<string>("all");
  const [classes, setClasses] = useState<Set<number>>(new Set());
  const [status, setStatus] = useState<StatusFilter>("all");
  const [order, setOrder] = useState<OrderKey>("filename");
  const [direction, setDirection] = useState<Direction>("asc");
  const [annotations, setAnnotations] = useState(true);
  /** Boxes of the classes not being filtered for are hidden rather than their images. */
  const [onlyClasses, setOnlyClasses] = useState(false);
  // Words people put on images, and the filter sets worth coming back to. Both live with
  // the dataset rather than in this tab, so they outlive the tab and are shared.
  const [tags, setTags] = useState<TagOverview | null>(null);
  const [tagFilter, setTagFilter] = useState<Set<string>>(new Set());
  const [views, setViews] = useState<SavedView[]>([]);
  const [asList, setAsList] = useState(false);
  const [shown, setShown] = useState(PAGE);
  const [open, setOpen] = useState<string | null>(null);
  /** The images the viewer steps through when that is not the gallery: a group, or a pair. */
  const [openScope, setOpenScope] = useState<ImageRow[] | null>(null);
  /** The object to pick out when the viewer was opened from a patch rather than a thumbnail. */
  const [openInstance, setOpenInstance] = useState<number | null>(null);
  const [patchLimit, setPatchLimit] = useState(PATCHES);

  // Duplicates mode. The vectors are computed once per dataset and read back as a graph,
  // which costs the service a pass over all of them -- so only when this mode is opened.
  const [vectors, setVectors] = useState<EmbeddingStatus | null>(null);
  const [report, setReport] = useState<EmbeddingReport | null>(null);
  const [similarError, setSimilarError] = useState<string | null>(null);
  const [reading, setReading] = useState(false);
  const [embedJob, setEmbedJob] = useState<Job<{ status: EmbeddingStatus["status"]; unreadable: number }> | null>(null);
  const [similarTab, setSimilarTab] = useState<SimilarTab>("copies");
  const askedForGraph = useRef(false);

  // "What else looks like this one" and "how unlike the rest is each image": the same vectors
  // as Duplicates, asked one image at a time. Both are fetched only when asked for, because a
  // dataset that has never been read has neither and should not be made to look broken.
  const [neighbours, setNeighbours] = useState<SimilarImages | null>(null);
  const [likeError, setLikeError] = useState<string | null>(null);
  const [likeBusy, setLikeBusy] = useState(false);
  const [nearest, setNearest] = useState(NEIGHBOURS);
  const [scores, setScores] = useState<Record<string, number> | null>(null);
  const [scoresError, setScoresError] = useState<string | null>(null);

  // Review mode.
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [inspecting, setInspecting] = useState<number | null>(null);
  const [trayMode, setTrayMode] = useState<TrayMode>(null);
  const [trayNote, setTrayNote] = useState("");
  const [busy, setBusy] = useState(false);
  const [toast, setToast] = useState<{ text: string; href?: string } | null>(null);
  const [author, setAuthorState] = useState(readReviewer);
  const [creating, setCreating] = useState(false);
  const [drafting, setDrafting] = useState(false);
  const lastClicked = useRef<number | null>(null);
  const [editing, setEditing] = useState<number | null>(null);
  /** An image to open in the inspector or editor once that mode is on. */
  const pendingInspect = useRef<number | null>(null);

  const setAuthor = (name: string) => {
    setAuthorState(name);
    saveReviewer(name);
  };

  const setReview = (on: boolean) => navigate({ name: "images", project, dataset, review: on || undefined, stats: stats || undefined, like });
  const setEdit = (on: boolean) => navigate({ name: "images", project, dataset, edit: on || undefined, stats: stats || undefined, like });
  const setSimilar = (on: boolean) => navigate({ name: "images", project, dataset, similar: on || undefined, stats: stats || undefined, like });
  const setPatches = (on: boolean) => navigate({ name: "images", project, dataset, patches: on || undefined, stats: stats || undefined, like });
  /** The counts panel, on beside whatever the gallery is doing. */
  const setStats = (on: boolean) => navigate({
    name: "images", project, dataset,
    review: review || undefined, edit: edit || undefined, similar: similar || undefined,
    patches: patches || undefined, stats: on || undefined, like,
  });
  /** Order the gallery by likeness to one image, or go back to the whole dataset. */
  const setLike = (image: string | null) => navigate({
    name: "images", project, dataset,
    review: review || undefined, edit: edit || undefined, similar: similar || undefined,
    patches: patches || undefined, stats: stats || undefined,
    like: image ?? undefined,
  });

  const load = useCallback(async () => {
    if (!active) return;
    try {
      setData(await api.images(project, active));
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }, [project, active]);

  const loadTags = useCallback(async () => {
    if (!active) return;
    try {
      setTags(await api.tags(project, active));
    } catch {
      // Tags are an extra: a dataset with none, or a service that cannot read them, is
      // not a reason to fail the gallery.
    }
  }, [project, active]);

  useEffect(() => {
    setTags(null);
    setTagFilter(new Set());
    setViews([]);
    void loadTags();
    if (active) api.views(project, active).then(({ views: saved }) => setViews(saved)).catch(() => undefined);
  }, [project, active, loadTags]);

  useEffect(() => {
    setData(null);
    setBoxes({});
    setOpen(null);
    setOpenScope(null);
    setVectors(null);
    setReport(null);
    setSimilarError(null);
    askedForGraph.current = false;
    setNeighbours(null);
    setLikeError(null);
    setScores(null);
    setScoresError(null);
    setSplit("all");
    setClasses(new Set());
    setSelected(new Set());
    setInspecting(null);
    void load();
  }, [load]);

  useEffect(() => {
    // Leaving review drops its selection; the side panel and the inspector don't mix.
    setSelected(new Set());
    setTrayMode(null);
    setInspecting(review ? pendingInspect.current : null);
    setEditing(edit ? pendingInspect.current : null);
    pendingInspect.current = null;
    setOpen(null);
    setOpenScope(null);
    if (!review && (status === "rework" || status === "commented")) setStatus("all");
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [review, edit, similar, patches]);

  const statuses = data?.statuses ?? {};
  const labels = data?.labels ?? {};

  // Returning every isolated image empties that set; fall back to all images.
  useEffect(() => {
    if (data && split !== "all" && !data.sets.some((s) => s.set === split)) setSplit("all");
  }, [data, split]);

  /** The images of the chosen split; isolated images only when their chip is chosen. */
  const inSplit = useMemo(() => {
    if (!data) return [];
    if (split === "all") return data.images.filter((image) => image.set !== ISOLATED_SET);
    return data.images.filter((image) => image.set === split);
  }, [data, split]);

  const byImage = useMemo(() => new Map((data?.images ?? []).map((i) => [i.image, i])), [data]);

  /** The image the gallery is being compared against, when it is. */
  const likeItem = like ? byImage.get(like) ?? null : null;

  /** Its neighbours, joined to the images the dataset holds now, nearest first. */
  const likeList = useMemo(
    () => (neighbours && neighbours.image === like ? likeRows(neighbours, byImage) : null),
    [neighbours, like, byImage],
  );

  /** Where each neighbour came in the answer: the order the gallery is put in. */
  const likeRank = useMemo(
    () => (likeList ? new Map(likeList.map((row, at) => [row.item.image, at])) : null),
    [likeList],
  );

  /** How alike each neighbour is, as a share of the typical distance, for its thumbnail. */
  const likeShare = useMemo(
    () => (likeList ? new Map(likeList.map((row) => [row.item.image, row.share])) : null),
    [likeList],
  );

  /** Class counts over the images the other filters leave, so the numbers track. */
  const beforeClass = useMemo(
    () => inSplit.filter((image) => matchesStatus(status, statuses[image.image])
      && (tagFilter.size === 0
        || (tags?.images[image.image] ?? []).some((tag) => tagFilter.has(tag)))),
    [inSplit, status, statuses, tagFilter, tags],
  );

  const classCounts = useMemo(() => {
    const counts = new Map<number, number>();
    for (const image of beforeClass) for (const label of image.classes) counts.set(label, (counts.get(label) ?? 0) + 1);
    return counts;
  }, [beforeClass]);

  const items = useMemo(() => {
    const filtered = classes.size === 0
      ? beforeClass
      : beforeClass.filter((image) => image.classes.some((label) => classes.has(label)));
    // Compared against one image, the gallery is that image's neighbours and nothing else:
    // the filters still narrow them, but the order is the service's answer, not a column.
    if (likeRank) {
      return filtered
        .filter((image) => likeRank.has(image.image))
        .sort((a, b) => likeRank.get(a.image)! - likeRank.get(b.image)!);
    }
    const sign = direction === "asc" ? 1 : -1;
    const when = (image: ImageRow) => statuses[image.image]?.time ?? "";
    const sorted = [...filtered];
    sorted.sort((a, b) => {
      let by = 0;
      if (order === "filename") by = fileName(a.image).localeCompare(fileName(b.image), undefined, { numeric: true });
      // Never-touched images have no time; they sort as the oldest either way.
      else if (order === "updated") by = when(a).localeCompare(when(b));
      // Images with no score yet -- added since the last read -- sort as the least unusual,
      // which keeps them out of the way of what the reader asked to see.
      else if (order === "uniqueness") by = (scores?.[a.image] ?? 0) - (scores?.[b.image] ?? 0);
      else by = a.added.localeCompare(b.added) || a.row - b.row;
      return by !== 0 ? by * sign : a.image.localeCompare(b.image);
    });
    return sorted;
  }, [beforeClass, classes, order, direction, statuses, scores, likeRank]);

  // Linked from elsewhere (a finding) to edit one image: open it once the list is in.
  const openedFromLink = useRef<string | null>(null);
  useEffect(() => {
    if (!edit || !openImage || !data || openedFromLink.current === openImage) return;
    const at = items.findIndex((item) => item.image === openImage);
    if (at < 0) return;
    openedFromLink.current = openImage;
    if (at >= shown) setShown(at + 1);
    setEditing(at);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [edit, openImage, data, items]);


  useEffect(() => {
    setShown(PAGE);
    setSelected(new Set());
    setPatchLimit(PATCHES);
  }, [split, status, order, direction, classes, like, tagFilter]);

  // Isolating or deleting the inspected image shortens the list; stay at the same position.
  useEffect(() => {
    if (inspecting !== null && inspecting >= items.length) setInspecting(items.length ? items.length - 1 : null);
  }, [inspecting, items.length]);

  const visible = useMemo(() => items.slice(0, shown), [items, shown]);

  /** Counts for the panel, each leaving out the filter it would set.
   *
   * A distribution of sets drawn after the set filter is one bar, and a class list drawn
   * after the class filter is the class already chosen. Leaving each filter out of its own
   * counts keeps every bar something that can be picked, and matches the class menu in the
   * ribbon, which counts the same way.
   */
  const facets = useMemo(() => {
    const inLike = (rows: ImageRow[]) => (likeRank ? rows.filter((row) => likeRank.has(row.image)) : rows);
    const inClasses = (rows: ImageRow[]) =>
      classes.size === 0 ? rows : rows.filter((row) => row.classes.some((label) => classes.has(label)));
    const inStatus = (rows: ImageRow[]) => rows.filter((row) => matchesStatus(status, statuses[row.image]));
    // Isolated images are out of the way unless their own chip is the one chosen.
    const all = inLike((data?.images ?? []).filter((row) => row.set !== ISOLATED_SET || split === ISOLATED_SET));
    const chosen = split === "all" ? all : all.filter((row) => row.set === split);
    return { sets: inClasses(inStatus(all)), classes: inStatus(chosen) };
  }, [data, split, status, classes, statuses, likeRank]);

  // Geometry is fetched for what is on screen and kept: the aerial set's 11,882 images
  // carry 644,000 boxes, which is not something to hold in a browser to draw thumbnails.
  const requested = useRef<Set<string>>(new Set());
  useEffect(() => {
    if (!active || (!annotations && !patches)) return;
    // A group opened from Duplicates is not part of the gallery page, and the viewer
    // draws boxes over whatever it is shown.
    const wanted = openScope ? [...visible, ...openScope] : visible;
    const missing = wanted
      .filter((image) => !(image.image in boxes) && !requested.current.has(image.image))
      .slice(0, 500);
    if (missing.length === 0) return;
    for (const image of missing) requested.current.add(image.image);
    // A reply that arrives after this effect has run again is kept, not dropped: the images
    // it covers are already marked as asked for, so dropping it would leave them without
    // geometry until the dataset is reloaded. Nothing else keys on when it arrived -- boxes
    // are looked up by image, and an image of a dataset since left behind is never asked for.
    api.imageBoxes(project, active, missing.map((image) => ({ table: image.table, row: image.row })))
      .then((next) => setBoxes((was) => ({ ...was, ...next })))
      .catch(() => {
        // Leave them unrequested so scrolling back tries again.
        for (const image of missing) requested.current.delete(image.image);
      });
  }, [project, active, annotations, patches, visible, openScope, boxes]);

  const live = useMemo(() => (data?.images ?? []).filter((image) => image.set !== ISOLATED_SET), [data]);
  const counts = useMemo(() => {
    const bySplit = new Map<string, number>();
    for (const image of data?.images ?? []) bySplit.set(image.set, (bySplit.get(image.set) ?? 0) + 1);
    const tally = (filter: StatusFilter) => inSplit.filter((i) => matchesStatus(filter, statuses[i.image])).length;
    const verified = live.filter((i) => isVerified(statuses[i.image])).length;
    const rework = live.filter((i) => statuses[i.image]?.status === "rework").length;
    return {
      total: live.length, bySplit, verified, rework,
      status: {
        all: inSplit.length, verified: tally("verified"), unverified: tally("unverified"),
        rework: tally("rework"), commented: tally("commented"),
      } as Record<StatusFilter, number>,
    };
  }, [data, live, inSplit, statuses]);

  const scope = openScope ?? items;
  const opened = open === null ? null : scope.find((i) => i.image === open) ?? null;
  const openedIndex = opened ? scope.indexOf(opened) : -1;

  /** The graph read against the images the dataset holds now: groups, leaks and marks. */
  const joined = useMemo(() => (report ? readReport(report, live) : null), [report, live]);

  /** Ask the service what vectors this dataset has, and read the graph when it has some. */
  const loadSimilar = useCallback(async () => {
    if (!active) return;
    askedForGraph.current = true;
    setReading(true);
    setSimilarError(null);
    try {
      const status = await api.embeddings(project, active);
      setVectors(status);
      setReport(status.status === null ? null : await api.embeddingReport(project, active));
    } catch (e) {
      setSimilarError(e instanceof Error ? e.message : String(e));
    } finally {
      setReading(false);
    }
  }, [project, active]);

  useEffect(() => {
    if (similar && !askedForGraph.current) void loadSimilar();
  }, [similar, loadSimilar]);

  /** One image's neighbours. Cheap: the vectors are already on the service, and the answer
   *  is a few hundred names rather than the whole graph. */
  const loadNeighbours = useCallback(async (image: string, k: number) => {
    if (!active) return;
    setLikeBusy(true);
    setLikeError(null);
    try {
      setNeighbours(await api.similarImages(project, active, image, k));
    } catch (e) {
      setNeighbours(null);
      setLikeError(e instanceof Error ? e.message : String(e));
    } finally {
      setLikeBusy(false);
    }
  }, [project, active]);

  useEffect(() => {
    if (!like) {
      setNeighbours(null);
      setLikeError(null);
      return;
    }
    void loadNeighbours(like, nearest);
  }, [like, nearest, loadNeighbours]);

  // Uniqueness is one number per image and arrives whole, so it is asked for once -- when
  // the order first calls for it, and again after the images have been read afresh. A failure
  // stops it being asked for again: the notice under the ribbon says what to do instead.
  useEffect(() => {
    if (order !== "uniqueness" || !active || scores || scoresError) return;
    let alive = true;
    api.embeddingScores(project, active)
      .then((answer) => alive && setScores(answer.uniqueness))
      .catch((e) => alive && setScoresError(e instanceof Error ? e.message : String(e)));
    return () => {
      alive = false;
    };
  }, [order, project, active, scores, scoresError]);

  /** Read every image of the dataset. Minutes on a large one, so it is followed as a job. */
  const computeVectors = useCallback(async () => {
    if (!active) return;
    setSimilarError(null);
    try {
      let job = await api.computeEmbeddings({ project, dataset: active });
      setEmbedJob(job);
      while (job.status === "running") {
        await new Promise((resume) => window.setTimeout(resume, 700));
        job = await api.job<{ status: EmbeddingStatus["status"]; unreadable: number }>(job.id);
        setEmbedJob(job);
      }
      setEmbedJob(null);
      if (job.status === "failed") setSimilarError(job.error ?? "the images could not be read");
      else if (job.status === "done") {
        // Every reading of the vectors is now out of date, including the ones this page was
        // shown before the images were read.
        setScores(null);
        setScoresError(null);
        await loadSimilar();
        if (like) await loadNeighbours(like, nearest);
      }
    } catch (e) {
      setEmbedJob(null);
      setSimilarError(e instanceof Error ? e.message : String(e));
    }
  }, [project, active, loadSimilar, like, nearest, loadNeighbours]);

  const flash = (text: string, href?: string) => {
    setToast({ text, href });
    window.setTimeout(() => setToast(null), 5000);
  };

  // -- review decisions ---------------------------------------------------------

  /** Apply a status at once; the service call follows and a failure reloads the truth. */
  const decide = useCallback(async (images: string[], next: QaStatus, comment = "") => {
    if (!active || images.length === 0) return false;
    setData((before) => {
      if (!before) return before;
      const statuses = { ...before.statuses };
      for (const image of images) {
        const was = statuses[image] ?? { status: "unreviewed", comments: 0 };
        statuses[image] = { ...was, status: next, author, note: comment, comments: was.comments + (comment ? 1 : 0), time: new Date().toISOString() };
      }
      return { ...before, statuses };
    });
    try {
      // One call per set version, so each decision records the version it was made on.
      const groups = new Map<string, string[]>();
      for (const image of images) {
        const table = byImage.get(image)?.table ?? "";
        groups.set(table, [...(groups.get(table) ?? []), image]);
      }
      for (const [table, samples] of groups) {
        const done = await api.setQaStatus({ project, dataset: active, samples, status: next, comment, author, table: table || undefined });
        setData((before) => before && { ...before, statuses: { ...before.statuses, ...done.statuses } });
      }
      return true;
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
      void load();
      return false;
    }
  }, [project, active, author, byImage, load]);

  /** Isolate, delete or return images; each writes new set versions, so reload after. */
  const move = useCallback(async (images: string[], action: MoveAction, reason = "") => {
    if (!active || images.length === 0) return false;
    setBusy(true);
    try {
      const payload = { project, dataset: active, reason, author };
      if (action === "return") {
        await api.returnIsolated({ ...payload, samples: images });
      } else {
        const groups = new Map<string, string[]>();
        for (const image of images) {
          const table = byImage.get(image)?.table;
          if (table) groups.set(table, [...(groups.get(table) ?? []), image]);
        }
        for (const [table, samples] of groups) {
          if (action === "isolate") await api.isolate({ ...payload, table, samples });
          else await api.deleteImages({ ...payload, table, samples });
        }
      }
      const verb = action === "isolate" ? "isolated" : action === "delete" ? "deleted" : "returned to their sets";
      flash(`${plural(images.length, "image")} ${verb}`);
      setSelected((was) => new Set([...was].filter((i) => !images.includes(i))));
      await Promise.all([load(), refreshProject()]);
      return true;
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
      await load();
      return false;
    } finally {
      setBusy(false);
    }
  }, [project, active, author, byImage, load, refreshProject]);

  const closeTray = () => {
    setTrayMode(null);
    setTrayNote("");
  };

  const bulk = async (next: QaStatus, comment = "") => {
    setBusy(true);
    const images = [...selected];
    if (await decide(images, next, comment)) {
      flash(`${plural(images.length, "image")} marked ${STATUS_LABEL[next].toLowerCase()}`);
      setSelected(new Set());
      closeTray();
    }
    setBusy(false);
  };

  const runTray = async () => {
    const note = trayNote.trim();
    if (trayMode === "rework") {
      if (note) await bulk("rework", note);
    } else if (trayMode) {
      if (await move([...selected], trayMode, note)) closeTray();
    }
  };

  /** Add or drop images from the selection, whichever view picked them out. */
  const selectImages = useCallback((images: string[], on: boolean) => {
    setSelected((was) => {
      const next = new Set(was);
      for (const image of images) {
        if (on) next.add(image);
        else next.delete(image);
      }
      return next;
    });
  }, []);

  /** Click toggles one image; shift-click selects the run from the last one clicked. */
  const toggle = (index: number, range: boolean) => {
    const image = items[index]!.image;
    const from = lastClicked.current;
    setSelected((was) => {
      const next = new Set(was);
      if (range && from !== null && from !== index) {
        const [a, b] = from < index ? [from, index] : [index, from];
        for (const item of items.slice(a, b + 1)) next.add(item.image);
      } else if (next.has(image)) next.delete(image);
      else next.add(image);
      return next;
    });
    lastClicked.current = index;
  };

  if (datasets.length === 0 && !loading) {
    return (
      <div className="page">
        <PageHeader title="Images" context={project} />
        <EmptyState
          title="No images yet"
          action={<a className="button primary" href={routeHref({ name: "import", project })}><Icon name="import" />Add data</a>}
        >
          <p>Imported datasets appear here, with their annotations.</p>
        </EmptyState>
      </div>
    );
  }

  const onIsolated = split === ISOLATED_SET;
  const visibleCount = Math.min(shown, items.length);
  const allSelected = items.length > 0 && items.every((i) => selected.has(i.image));
  const statusFilters: StatusFilter[] = review ? ["all", "verified", "unverified", "rework", "commented"] : ["all", "verified", "unverified"];
  const STATUS_FILTER_LABEL: Record<StatusFilter, string> = {
    all: "All", verified: "Verified", unverified: "Unverified", rework: "Rework", commented: "Commented",
  };
  const progress = counts.total ? counts.verified / counts.total : 0;

  return (
    <div className={`page page-wide images-page${review ? " reviewing" : ""}${edit ? " editing" : ""}${similar ? " similar" : ""}${stats ? " with-detail" : ""}`}>
      <PageHeader
        title="Images"
        context={project}
        subtitle={data ? `${tasksLabel(tasks)} · ${formatNumber(counts.total)} images · ${formatNumber(counts.verified)} verified` : undefined}
        actions={
          <>
            {datasets.length > 1 && (
              <div className="select-wrap">
                <select aria-label="Dataset" value={active} onChange={(e) => navigate({ name: "images", project, dataset: e.target.value, review: review || undefined })}>
                  {datasets.map((d) => <option key={d.name} value={d.name}>{d.name}</option>)}
                </select>
              </div>
            )}
            {removedCount > 0 && (
              <a className="button subtle" href={routeHref({ name: "removed", project, dataset: active! })} title="Deleted images; put them back from here">
                <Icon name="trash" size={15} />Removed <span className="split-toggle-count">{formatNumber(removedCount)}</span>
              </a>
            )}
            <button
              className="button"
              disabled={!data || counts.total === 0}
              onClick={() => setDrafting(true)}
              title="Draw a model's boxes into these sets as labels to correct"
            >
              <Icon name="pencil" size={15} />Pre-label
            </button>
            <button
              className="button primary create-dataset"
              disabled={!data || counts.total === 0}
              onClick={() => void load().then(() => setCreating(true))}
              title="Freeze these images into a named dataset version for training"
            >
              <Icon name="plus" size={16} />Create dataset
            </button>
          </>
        }
      />
      {error && <p className="form-error">{error}</p>}

      {data && (
        <>
          <div className="ribbon">
            {!similar && (
              <>
            <div className="segmented" role="group" aria-label="Split">
              <button className={split === "all" ? "on" : ""} onClick={() => setSplit("all")}>
                All<span className="split-toggle-count">{formatNumber(counts.total)}</span>
              </button>
              {data.sets.map((s) => (
                <button
                  key={s.set}
                  className={`${split === s.set ? "on" : ""}${s.set === ISOLATED_SET ? " isolated-tab" : ""}`}
                  onClick={() => setSplit(s.set)}
                  title={s.set === ISOLATED_SET ? "Set aside in review; not part of new dataset versions" : undefined}
                >
                  {s.set}<span className="split-toggle-count">{formatNumber(counts.bySplit.get(s.set) ?? 0)}</span>
                </button>
              ))}
            </div>

            <ClassFilter labels={labels} counts={classCounts} chosen={classes} onChange={setClasses} />

            {classes.size > 0 && (
              <button
                className={`button subtle toggle-button${onlyClasses ? " on" : ""}`}
                aria-pressed={onlyClasses}
                onClick={() => setOnlyClasses(!onlyClasses)}
                title="Draw only the boxes of the chosen classes, instead of every box on the image"
              >
                <Icon name="fit" size={15} />Only their boxes
              </button>
            )}

            {tags && Object.keys(tags.counts).length > 0 && (
              <TagFilter counts={tags.counts} chosen={tagFilter} onChange={setTagFilter} />
            )}

            <div className="segmented" role="group" aria-label="Status">
              {statusFilters.map((key) => (
                <button key={key} className={status === key ? "on" : ""} onClick={() => setStatus(key)}>
                  {STATUS_FILTER_LABEL[key]}<span className="split-toggle-count">{formatNumber(counts.status[key])}</span>
                </button>
              ))}
            </div>

            <div className="ribbon-order">
              {like ? (
                <span className="muted small" title="Compared against one image, the order is how alike each image is to it">
                  Most alike first
                </span>
              ) : (
                <>
                  <div className="select-wrap">
                    <select
                      aria-label="Order by"
                      value={order}
                      onChange={(e) => {
                        const next = e.target.value as OrderKey;
                        setOrder(next);
                        // The point of this order is what nothing else in the set looks like,
                        // so it opens at that end rather than at the copies.
                        if (next === "uniqueness") setDirection("desc");
                      }}
                    >
                      {(Object.keys(ORDER_LABEL) as OrderKey[]).map((key) => (
                        <option key={key} value={key}>{ORDER_LABEL[key]}</option>
                      ))}
                    </select>
                  </div>
                  <button
                    className="icon-button"
                    onClick={() => setDirection(direction === "asc" ? "desc" : "asc")}
                    aria-label={direction === "asc" ? "Ascending" : "Descending"}
                    title={direction === "asc" ? "Ascending — click for descending" : "Descending — click for ascending"}
                  >
                    <Icon name={direction === "asc" ? "up" : "down"} size={15} />
                  </button>
                </>
              )}
            </div>
              </>
            )}
            {similar && <span className="spacer" />}

            <div className="ribbon-views">
              <ViewsMenu
                views={views}
                onSave={async (name) => {
                  if (!active) return;
                  const { views: saved } = await api.saveView({
                    project, dataset: active, name, author,
                    state: {
                      split, status, order, direction,
                      classes: [...classes], tags: [...tagFilter], onlyClasses,
                    },
                  });
                  setViews(saved);
                  flash(`Saved “${name}”`);
                }}
                onOpen={(view) => {
                  const state = view.state;
                  setSplit(state.split ?? "all");
                  setStatus((state.status as StatusFilter) ?? "all");
                  setOrder((state.order as OrderKey) ?? "filename");
                  setDirection((state.direction as Direction) ?? "asc");
                  setClasses(new Set(state.classes ?? []));
                  setTagFilter(new Set(state.tags ?? []));
                  setOnlyClasses(Boolean(state.onlyClasses));
                }}
                onDelete={async (view) => {
                  if (!active) return;
                  const { views: saved } = await api.deleteView(project, active, view.id);
                  setViews(saved);
                }}
              />
              {!similar && !patches && (
              <button
                className={`button subtle toggle-button${annotations ? " on" : ""}`}
                aria-pressed={annotations}
                onClick={() => setAnnotations(!annotations)}
                title="Draw boxes on the images"
              >
                <Icon name="boxes" size={15} />Annotations
              </button>
              )}
              <button
                className={`button subtle toggle-button${similar ? " on" : ""}`}
                aria-pressed={similar}
                onClick={() => setSimilar(!similar)}
                title="Images that are the same picture, and images that sit in two sets at once"
              >
                <Icon name="copy" size={15} />Duplicates
                {joined && <span className="split-toggle-count">{formatNumber(joined.groups.length)}</span>}
              </button>
              <button
                className={`button subtle toggle-button${stats ? " on" : ""}`}
                aria-pressed={stats}
                onClick={() => setStats(!stats)}
                title="Counts of what these images hold: sets, review, objects per image, classes, object size"
              >
                <Icon name="runs" size={15} />Stats
              </button>
              <button
                className={`button subtle toggle-button${patches ? " on" : ""}`}
                aria-pressed={patches}
                onClick={() => setPatches(!patches)}
                title="Every labelled object as its own tile, to check a class for consistency"
              >
                <Icon name="grid" size={15} />Patches
              </button>
              <button
                className={`button subtle toggle-button${review ? " on" : ""}`}
                aria-pressed={review}
                onClick={() => setReview(!review)}
                title="Select images to verify, rework, isolate or delete; open one to edit its boxes"
              >
                <Icon name="review" size={15} />Review
              </button>
              <button
                className={`button subtle toggle-button${edit ? " on" : ""}`}
                aria-pressed={edit}
                onClick={() => setEdit(!edit)}
                title="Open an image to move, resize, draw and delete boxes, masks and keypoints"
              >
                <Icon name="pencil" size={15} />Edit
              </button>
              {!similar && !patches && (
              <button
                className={`button subtle toggle-button${asList ? " on" : ""}`}
                aria-pressed={asList}
                onClick={() => setAsList(!asList)}
                title="See the images as a list"
              >
                <Icon name="list" size={15} />See in list
              </button>
              )}
            </div>
          </div>

          {like && !similar && (
            <LikeBar
              project={project}
              dataset={active!}
              image={like}
              item={likeItem}
              set={neighbours?.set ?? likeItem?.set ?? null}
              rows={items.length}
              asked={nearest}
              busy={likeBusy}
              error={likeError}
              job={embedJob}
              onMore={() => setNearest(MOST_NEIGHBOURS)}
              onCompute={() => void computeVectors()}
              onClear={() => setLike(null)}
            />
          )}

          {!similar && !like && order === "uniqueness" && (scoresError || !scores) && (
            <UniquenessNote
              error={scoresError}
              job={embedJob}
              onCompute={() => {
                setScoresError(null);
                void computeVectors();
              }}
            />
          )}

          {review && (
            <div className="review-bar">
              <div className="review-progress" title={`${formatNumber(counts.verified)} of ${formatNumber(counts.total)} verified`}>
                <span className="strong tabular">{Math.floor(progress * 100)}%</span>
                <span className="qa-bar">
                  <span className="qa-bar-reviewed" style={{ width: `${progress * 100}%` }} />
                  <span className="qa-bar-rework" style={{ width: `${counts.total ? (counts.rework / counts.total) * 100 : 0}%` }} />
                </span>
                <span className="muted small tabular">
                  {formatNumber(counts.verified)} verified · {formatNumber(counts.rework)} rework · {formatNumber(counts.total - counts.verified - counts.rework)} unverified
                </span>
              </div>
              {onIsolated && <span className="muted small">Isolated images stay out of new dataset versions until returned.</span>}
              <span className="spacer" />
              <div className="qa-select" role="group" aria-label="Selection">
                <button
                  className="button subtle"
                  onClick={() => setSelected(new Set(visible.map((i) => i.image)))}
                  disabled={items.length === 0}
                  title="Select the images loaded on this page"
                >
                  Select shown <span className="split-toggle-count">{formatNumber(visibleCount)}</span>
                </button>
                <button
                  className="button subtle"
                  onClick={() => setSelected(new Set(items.map((i) => i.image)))}
                  disabled={items.length === 0 || allSelected}
                  title="Select every image matching the filters, including those not loaded yet"
                >
                  Select all <span className="split-toggle-count">{formatNumber(items.length)}</span>
                </button>
                {selected.size > 0 && <button className="button subtle" onClick={() => setSelected(new Set())}>Select none</button>}
              </div>
              <label className="inline-field small reviewer-field">
                <span className="muted">Reviewer</span>
                <input type="text" value={author} onChange={(e) => setAuthor(e.target.value)} placeholder="Your name" maxLength={80} />
              </label>
            </div>
          )}

          <div className="images-body">
            <div className="images-main">
              {patches ? (
                <PatchesView
                  project={project}
                  dataset={active!}
                  items={items}
                  boxes={boxes}
                  classes={classes}
                  labels={labels}
                  limit={patchLimit}
                  reach={Math.min(shown, items.length)}
                  more={items.length > shown}
                  onMore={() => {
                    // More objects, and the images to cut them from: a page of each, so
                    // that asking for more never stalls on geometry that was never fetched.
                    setPatchLimit(patchLimit + PATCHES);
                    if (items.length > shown) setShown(shown + PAGE);
                  }}
                  onOpen={(image, instance) => {
                    setOpenInstance(instance);
                    setOpen(image);
                  }}
                />
              ) : similar ? (
                <DuplicatesView
                  project={project}
                  dataset={active!}
                  status={vectors}
                  joined={joined}
                  scale={report?.scale ?? 0}
                  duplicateAt={report?.policy.duplicate ?? 0}
                  leakAt={report?.policy.leak ?? 0}
                  outlierAt={report?.policy.outlier ?? 0}
                  reading={reading}
                  error={similarError}
                  job={embedJob}
                  onCompute={() => void computeVectors()}
                  onCancelJob={() => embedJob && void api.cancelJob(embedJob.id)}
                  tab={similarTab}
                  onTab={setSimilarTab}
                  selected={selected}
                  onSelect={selectImages}
                  onOpen={(image, rows) => {
                    setOpenScope(rows);
                    setOpen(image);
                  }}
                  onLike={(image) => navigate({ name: "images", project, dataset: active, like: image })}
                />
              ) : items.length === 0 ? (
                <p className="muted qa-empty">No images match these filters.</p>
              ) : asList ? (
                <ImageList
                  items={visible}
                  statuses={statuses}
                  marks={joined?.marks}
                  scores={order === "uniqueness" ? scores : null}
                  shares={likeShare}
                  labels={labels}
                  project={project}
                  dataset={active!}
                  opened={open}
                  selected={review ? selected : null}
                  onToggle={(i, range) => toggle(i, range)}
                  onOpen={(image, i) => (review ? setInspecting(i) : edit ? setEditing(i) : setOpen(image))}
                />
              ) : (
                <div className="images-grid">
                  {visible.map((item, i) => (
                    <ImageCard
                      key={item.image}
                      item={item}
                      state={statuses[item.image]}
                      mark={joined?.marks.get(item.image)}
                      tags={tags?.images[item.image]}
                      drafted={item.drafted}
                      unique={order === "uniqueness" ? scores?.[item.image] : undefined}
                      share={likeShare?.get(item.image)}
                      boxes={annotations ? boxes[item.image] : undefined}
                      onlyLabels={onlyClasses && classes.size > 0 ? classes : null}
                      project={project}
                      dataset={active!}
                      opened={open === item.image}
                      checked={review ? selected.has(item.image) : null}
                      onToggle={(range) => toggle(i, range)}
                      onOpen={() => (review ? setInspecting(i) : edit ? setEditing(i) : setOpen(item.image))}
                      onLike={() => setLike(item.image)}
                    />
                  ))}
                </div>
              )}
              {items.length > shown && !patches && (
                <div className="qa-more">
                  <button className="button" onClick={() => setShown(shown + PAGE)}>
                    Show {formatNumber(Math.min(PAGE, items.length - shown))} more
                  </button>
                  <span className="muted small">{formatNumber(Math.min(shown, items.length))} of {formatNumber(items.length)}</span>
                </div>
              )}
            </div>

            {stats && data && (
              <StatsPanel
                items={items}
                acrossSets={facets.sets}
                acrossClasses={facets.classes}
                statuses={statuses}
                labels={labels}
                boxes={boxes}
                split={split}
                onSplit={setSplit}
                classes={classes}
                onClasses={setClasses}
                onClose={() => setStats(false)}
              />
            )}

            {opened && !review && !edit && (
              <ImageDetail
                project={project}
                dataset={active!}
                item={opened}
                instance={openInstance}
                index={openedIndex}
                total={scope.length}
                state={statuses[opened.image]}
                labels={labels}
                boxes={boxes[opened.image]}
                hasPrev={openedIndex > 0}
                hasNext={openedIndex >= 0 && openedIndex < scope.length - 1}
                onStep={(step) => {
                  const at = openedIndex + step;
                  const next = scope[at];
                  if (next) {
                    setOpenInstance(null);
                    setOpen(next.image);
                    if (!openScope && at >= shown) setShown(at + 1);
                  }
                }}
                author={author}
                onComment={(text) => decide([opened.image], "unreviewed", text)}
                onEdit={() => {
                  pendingInspect.current = openedIndex;
                  setEdit(true);
                }}
                like={like === opened.image}
                onLike={() => {
                  setOpen(null);
                  setOpenScope(null);
                  setLike(opened.image);
                }}
                onClose={() => {
                  setOpen(null);
                  setOpenScope(null);
                  setOpenInstance(null);
                }}
              />
            )}
          </div>
        </>
      )}

      {(review || similar) && selected.size > 0 && (
        <div className="decision-tray" role="region" aria-label="Selected images">
          <span className="strong">{plural(selected.size, "image")} selected</span>
          {trayMode === null && !similar && !allSelected && items.length > selected.size && (
            <button className="button subtle qa-select-all-link" onClick={() => setSelected(new Set(items.map((i) => i.image)))}>
              Select all {formatNumber(items.length)}
            </button>
          )}
          {trayMode !== null ? (
            <>
              <input
                type="text"
                className="qa-tray-note"
                autoFocus
                value={trayNote}
                onChange={(e) => setTrayNote(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Enter") void runTray();
                  if (e.key === "Escape") closeTray();
                }}
                placeholder={trayMode === "rework" ? "What needs rework?" : trayMode === "isolate" ? "Why set aside? (optional)" : "Why delete? (optional)"}
              />
              {trayMode === "delete" && <span className="muted small">Moves to the removed set; recoverable from Removed.</span>}
              <button className="button subtle" onClick={closeTray}>Cancel</button>
              <button
                className={`button ${trayMode === "isolate" ? "primary" : "danger-button"}`}
                disabled={busy || (trayMode === "rework" && !trayNote.trim())}
                onClick={() => void runTray()}
              >
                {trayMode === "rework" ? "Send to rework" : trayMode === "isolate" ? `Isolate ${formatNumber(selected.size)}` : `Delete ${formatNumber(selected.size)}`}
              </button>
            </>
          ) : (
            <>
              <span className="spacer" />
              <button className="button subtle" onClick={() => setSelected(new Set())}>Clear</button>
              <button className="button danger-button" disabled={busy} onClick={() => setTrayMode("delete")}><Icon name="trash" />Delete…</button>
              {onIsolated ? (
                <button className="button" disabled={busy} onClick={() => void move([...selected], "return")}><Icon name="back" />Return to set</button>
              ) : (
                <button className="button" disabled={busy} onClick={() => setTrayMode("isolate")}><Icon name="isolate" />Isolate…</button>
              )}
              <TagAction
                counts={tags?.counts ?? {}}
                onTag={async (tag, on) => {
                  if (!active) return;
                  const images = [...selected];
                  await api.tagImages({
                    project, dataset: active, samples: images, author,
                    ...(on ? { add: [tag] } : { remove: [tag] }),
                  });
                  await loadTags();
                  flash(`${on ? "Tagged" : "Untagged"} ${plural(images.length, "image")} ${on ? "as" : ""} “${tag}”`);
                }}
              />
              <button className="button" disabled={busy} onClick={() => void bulk("unreviewed")}>Unverify</button>
              <button className="button" disabled={busy} onClick={() => setTrayMode("rework")}>Rework…</button>
              <button className="button primary" disabled={busy} onClick={() => void bulk("reviewed")}><Icon name="check" />Verify</button>
            </>
          )}
        </div>
      )}
      {toast && (
        <div className="toast" role="status">
          {toast.text}
          {toast.href && <a href={toast.href} className="toast-link">View</a>}
        </div>
      )}

      {edit && editing !== null && items[editing] && (
        <ImageEditor
          project={project}
          dataset={active!}
          tasks={tasks}
          items={items}
          index={editing}
          author={author}
          onIndex={(i) => {
            setEditing(i);
            if (i >= shown) setShown(i + 1);
          }}
          onSaved={async (image) => {
            // Its boxes changed: draw them afresh.
            requested.current.delete(image);
            setBoxes((was) => {
              const next = { ...was };
              delete next[image];
              return next;
            });
            await Promise.all([load(), refreshProject()]);
          }}
          onClose={() => setEditing(null)}
        />
      )}

      {review && inspecting !== null && items[inspecting] && (
        <ImageInspector
          project={project}
          dataset={active!}
          items={items}
          index={inspecting}
          statuses={statuses}
          author={author}
          isolated={items[inspecting]!.set === ISOLATED_SET}
          onMove={move}
          onSaved={load}
          onIndex={(i) => {
            setInspecting(i);
            if (i >= shown) setShown(i + 1);
          }}
          onDecide={decide}
          onComment={(image, comments) =>
            setData((before) => before && {
              ...before,
              statuses: { ...before.statuses, [image]: { ...(before.statuses[image] ?? { status: "unreviewed" }), comments } },
            })}
          onClose={() => setInspecting(null)}
        />
      )}

      {drafting && data && active && (
        <PrelabelDialog
          project={project}
          dataset={active}
          sets={data.sets.filter((set) => set.set !== ISOLATED_SET)}
          onClose={() => setDrafting(false)}
          onDone={(result) => {
            setDrafting(false);
            const boxes = result.sets.reduce((n, set) => n + set.boxes, 0);
            const images = result.sets.reduce((n, set) => n + set.images, 0);
            flash(`${formatNumber(boxes)} boxes drafted on ${plural(images, "image")} with ${result.model} — check them before training`);
            // New versions of the sets: the gallery is looking at the old ones.
            requested.current.clear();
            setBoxes({});
            void Promise.all([load(), refreshProject()]);
          }}
        />
      )}

      {creating && data && active && (
        <CreateDatasetDialog
          project={project}
          dataset={active}
          images={live}
          statuses={statuses}
          author={author}
          labels={labels}
          tasks={tasks}
          onClose={() => setCreating(false)}
          onCreated={(release) => {
            setCreating(false);
            const images = Object.values(release.sets).reduce((n, s) => n + s.images, 0);
            const augmented = Object.values(release.sets).reduce((n, s) => n + (s.augmented ?? 0), 0);
            flash(`Created ${release.name}: ${plural(images, "image")}${augmented ? `, ${formatNumber(augmented)} of them augmented` : ""}, ready for training`, routeHref({ name: "datasets", project }));
            void refreshProject();
          }}
        />
      )}
    </div>
  );
}

/** The image the gallery is being compared against, above the gallery it has reordered.
 *
 * Likeness is a distance, and a distance in an embedding means nothing on its own, so every
 * number here is a share of this dataset's own typical distance -- the same unit the copies
 * and leaks are judged in. The reader is told how many neighbours were asked for, because
 * "the 60 most alike" is a different claim from "everything like this".
 */
function LikeBar({ project, dataset, image, item, set, rows, asked, busy, error, job, onMore, onCompute, onClear }: {
  project: string;
  dataset: string;
  image: string;
  /** The row for the image itself, when the dataset still holds it. */
  item: ImageRow | null;
  set: string | null;
  /** Neighbours on screen after the ribbon's filters, which can be fewer than were asked for. */
  rows: number;
  asked: number;
  busy: boolean;
  error: string | null;
  job: Job<unknown> | null;
  onMore: () => void;
  onCompute: () => void;
  onClear: () => void;
}) {
  const reading = job !== null && job.status === "running";
  return (
    <div className="review-bar like-bar">
      <img className="like-thumb" src={api.mediaUrl(image, 96, project, dataset)} alt="" />
      <div className="like-what">
        <span className="mono small truncate" title={image}>{fileName(image)}</span>
        <span className="muted small">
          {set ? `${set} · ` : ""}
          {error ? "no vectors for this dataset yet"
            : busy ? "looking…"
            : `${plural(rows, "image")} like this one, most alike first`}
        </span>
      </div>
      {error && !reading && (
        <>
          <span className="muted small">
            Images are compared by content, which has to be read once per dataset before
            anything can be found like this one.
          </span>
          <button className="button" onClick={onCompute}><Icon name="search" size={15} />Read the images</button>
        </>
      )}
      {reading && (
        <span className="muted small tabular">
          {job.phase} {formatNumber(job.done)} / {formatNumber(job.total)}
        </span>
      )}
      <span className="spacer" />
      {!error && asked < MOST_NEIGHBOURS && (
        <button className="button subtle" disabled={busy} onClick={onMore} title={`Ask for the ${MOST_NEIGHBOURS} most alike instead of the ${asked} most alike`}>
          Ask for {formatNumber(MOST_NEIGHBOURS)}
        </button>
      )}
      {item && (
        <a className="button subtle" href={routeHref({ name: "images", project, dataset, open: image })} title="Open this image full screen">
          <Icon name="open" size={15} />Open it
        </a>
      )}
      <button className="button subtle" onClick={onClear}><Icon name="close" size={15} />Show the whole set</button>
    </div>
  );
}

/** Why a gallery ordered by uniqueness is not ordered yet: it has nothing to order by. */
function UniquenessNote({ error, job, onCompute }: { error: string | null; job: Job<unknown> | null; onCompute: () => void }) {
  const reading = job !== null && job.status === "running";
  return (
    <div className="review-bar">
      <Icon name="info" size={15} />
      <span className="muted small">
        {reading
          ? `${job.phase} — ${formatNumber(job.done)} of ${formatNumber(job.total)}`
          : error
            ? "Uniqueness comes from reading every image once, which this dataset has not had done."
            : "Reading how unlike the rest of the set each image is…"}
      </span>
      <span className="spacer" />
      {error && !reading && (
        <button className="button" onClick={onCompute}><Icon name="search" size={15} />Read the images</button>
      )}
    </div>
  );
}

/** Boxes drawn over a thumbnail, in the image's own coordinate space.
 *
 * The thumbnail is letterboxed (object-fit: contain) inside a frame of a fixed shape, so
 * the overlay is inset to cover exactly the part of the frame the image occupies --
 * otherwise every box would sit off the object it marks.
 */
export function BoxLayer({ boxes, only, frameAspect = 4 / 3 }: {
  boxes: ImageBoxes;
  only?: Set<number> | null;
  frameAspect?: number;
}) {
  const aspect = boxes.w && boxes.h ? boxes.w / boxes.h : frameAspect;
  // Width and height, not insets: an <svg> with a viewBox has an intrinsic ratio that
  // wins over inset: 0, and would draw itself square whatever the frame.
  const size = aspect > frameAspect
    ? { left: "0%", width: "100%", height: `${(frameAspect / aspect) * 100}%`, top: `${((1 - frameAspect / aspect) / 2) * 100}%` }
    : { top: "0%", height: "100%", width: `${(aspect / frameAspect) * 100}%`, left: `${((1 - aspect / frameAspect) / 2) * 100}%` };
  return (
    <svg className="box-layer" style={size} viewBox="0 0 1 1" preserveAspectRatio="none" aria-hidden="true">
      {boxes.b.map(([label, x0, y0, x1, y1], i) => {
        if (only && only.size > 0 && (label === null || !only.has(label))) return null;
        return (
          <rect
            key={i}
            x={x0}
            y={y0}
            width={Math.max(0, x1 - x0)}
            height={Math.max(0, y1 - y0)}
            fill="none"
            stroke={labelColor(label)}
            strokeWidth={1}
            // A box a model drew and nobody has checked is drawn as what it is: a draft.
            strokeDasharray={boxes.d?.[i] ? "3 2" : undefined}
            vectorEffect="non-scaling-stroke"
          />
        );
      })}
    </svg>
  );
}

function ImageCard({ item, state, mark, tags, drafted, unique, share, boxes, onlyLabels, project, dataset, opened, checked, onToggle, onOpen, onLike }: {
  item: ImageRow;
  state: QaState | undefined;
  /** What the neighbour graph found about this image, once it has been read. */
  mark: SimilarMark | undefined;
  /** Words people have put on this image. */
  tags: string[] | undefined;
  /** Boxes on it a model drafted and nobody has checked. */
  drafted: number | undefined;
  /** Its uniqueness, when the gallery is ordered by it. */
  unique: number | undefined;
  /** How alike it is to the image the gallery is compared against, when there is one. */
  share: number | undefined;
  boxes: ImageBoxes | undefined;
  /** Draw only these classes' boxes, when the reader has asked to see just them. */
  onlyLabels: Set<number> | null;
  project: string;
  dataset: string;
  opened: boolean;
  /** Review mode: whether the image is selected; null outside review. */
  checked: boolean | null;
  onToggle: (range: boolean) => void;
  onOpen: () => void;
  onLike: () => void;
}) {
  const verified = isVerified(state);
  const flagged = isFlagged(state);
  const rework = state?.status === "rework";
  return (
    <div
      className={`image-card${opened ? " opened" : ""}${verified ? " verified" : ""}${rework ? " rework" : ""}${checked ? " selected" : ""}`}
      title={item.image}
    >
      <button className="image-card-frame" onClick={onOpen} aria-label={`Open ${fileName(item.image)}`}>
        <img loading="lazy" src={api.mediaUrl(item.image, 320, project, dataset)} alt="" />
        {boxes && <BoxLayer boxes={boxes} only={onlyLabels} />}
        {flagged && (
          <span
            className="image-flag"
            title={rework ? `Rework: ${state?.note || "no note"}` : plural(state?.comments ?? 0, "comment")}
          />
        )}
        {verified && checked === null && <span className="image-tick" title="Verified"><Icon name="check" size={11} /></span>}
        {item.from && <span className="qa-origin" title={item.reason || undefined}>from {item.from}</span>}
        <SimilarMarks mark={mark} unique={unique} share={share} />
        {drafted ? (
          <span className="image-draft" title={`${drafted} of these boxes were drawn by a model and not checked by anyone`}>
            <Icon name="pencil" size={10} />{drafted}
          </span>
        ) : null}
      </button>
      {/* Outside the frame: the frame is itself a button, and one cannot hold another. */}
      <button
        className="image-action"
        onClick={onLike}
        title="Show the images most like this one"
        aria-label={`Find images like ${fileName(item.image)}`}
      >
        <Icon name="search" size={13} />
      </button>
      {checked !== null && (
        <label className="image-check" onClick={(e) => e.stopPropagation()}>
          <input
            type="checkbox"
            checked={checked}
            onChange={() => undefined}
            onClick={(e) => onToggle(e.shiftKey)}
            aria-label={`Select ${fileName(item.image)}`}
          />
        </label>
      )}
      <span className="image-card-foot">
        {checked !== null && (
          <span className={`qa-chip ${state?.status ?? "unreviewed"}`}>{STATUS_LABEL[state?.status ?? "unreviewed"]}</span>
        )}
        <span className="mono small truncate">{fileName(item.image)}</span>
        {tags && tags.length > 0 && (
          <span className="image-tags" title={tags.join(", ")}>
            <Icon name="star" size={11} />{tags.length > 1 ? tags.length : tags[0]}
          </span>
        )}
        {(state?.comments ?? 0) > 0 && checked !== null && (
          <span className="qa-comments small" title={plural(state!.comments, "comment")}><Icon name="comment" size={12} />{state!.comments}</span>
        )}
        <span className="faint small tabular" title="Labelled objects">{item.objects}</span>
      </span>
    </div>
  );
}

/** What the neighbour graph found, on a thumbnail: copies of it, copies *of* it, and leaks.
 *
 * The two counts are different facts and are never merged. "3 images are the same picture as
 * this one" is redundancy. "the export wrote this picture twice" is the augmentation somebody
 * asked for, and calling that a duplicate would invite deleting it.
 */
function SimilarMarks({ mark, unique, share }: {
  mark: SimilarMark | undefined;
  unique?: number;
  share?: number;
}) {
  const graph = mark && (mark.copies > 1 || mark.exports > 1 || mark.leak);
  if (!graph && unique === undefined && share === undefined) return null;
  return (
    <span className="image-marks">
      {share !== undefined && (
        <span
          className="image-mark alike"
          title={`${(share * 100).toFixed(share < 0.1 ? 1 : 0)}% of the distance between two images of this dataset picked at random — 0% is the same picture`}
        >
          {share <= 0.02 ? "the same" : `${Math.round(share * 100)}%`}
        </span>
      )}
      {unique !== undefined && (
        <span
          className="image-mark"
          title="How unlike the rest of this dataset this image is: 0 is a copy of something here, 1 is nothing like it"
        >
          <Icon name="target" size={10} />{unique.toFixed(2)}
        </span>
      )}
      {mark && mark.copies > 1 && (
        <span className="image-mark" title={`${mark.copies} images in this dataset are the same picture as this one`}>
          <Icon name="copy" size={10} />{mark.copies}
        </span>
      )}
      {mark && mark.exports > 1 && (
        <span className="image-mark export" title={`The export wrote this picture out ${mark.exports} times — augmented copies, not duplicates`}>
          <Icon name="layers" size={10} />{mark.exports}
        </span>
      )}
      {mark?.leak && (
        <span className="image-mark leak" title="A near copy of this image sits in another set, so a score measured on it is not honest">
          Leak
        </span>
      )}
    </span>
  );
}

function ImageList({ items, statuses, marks, scores, shares, labels, project, dataset, opened, selected, onToggle, onOpen }: {
  items: ImageRow[];
  statuses: Record<string, QaState>;
  marks: Map<string, SimilarMark> | undefined;
  /** Uniqueness per image, when the list is ordered by it. */
  scores: Record<string, number> | null;
  /** Likeness to the image the list is compared against, when there is one. */
  shares: Map<string, number> | null;
  labels: Record<string, string>;
  project: string;
  dataset: string;
  opened: string | null;
  /** Review mode: the selected images; null outside review. */
  selected: Set<string> | null;
  onToggle: (index: number, range: boolean) => void;
  onOpen: (image: string, index: number) => void;
}) {
  return (
    <div className="data-table-wrap">
      <table className="data-table images-table">
        <thead>
          <tr>
            {selected && <th className="images-table-check" />}
            <th />
            <th>File</th>
            <th>Split</th>
            <th className="num">Objects</th>
            <th>Classes</th>
            <th>Status</th>
            <th>Updated</th>
          </tr>
        </thead>
        <tbody>
          {items.map((item, index) => {
            const state = statuses[item.image];
            return (
              <tr
                key={item.image}
                className={opened === item.image || selected?.has(item.image) ? "selected" : ""}
                onClick={() => onOpen(item.image, index)}
              >
                {selected && (
                  <td className="images-table-check" onClick={(e) => e.stopPropagation()}>
                    <input type="checkbox" checked={selected.has(item.image)} onChange={() => undefined}
                      onClick={(e) => onToggle(index, e.shiftKey)} aria-label={`Select ${fileName(item.image)}`} />
                  </td>
                )}
                <td className="images-table-thumb">
                  <img loading="lazy" src={api.mediaUrl(item.image, 96, project, dataset)} alt="" />
                </td>
                <td className="cell-mono small" title={item.image}>
                  {fileName(item.image)}
                  <SimilarMarks mark={marks?.get(item.image)} unique={scores?.[item.image]} share={shares?.get(item.image)} />
                </td>
                <td>{item.set}</td>
                <td className="num tabular">{item.objects}</td>
                <td className="images-table-classes">
                  {item.classes.map((label) => (
                    <span key={label} className="class-chip small">
                      <span className="class-swatch" style={{ background: labelColor(label) }} />
                      {labels[String(label)] ?? label}
                    </span>
                  ))}
                </td>
                <td>
                  <span className={`qa-chip ${state?.status ?? "unreviewed"}`}>{STATUS_LABEL[state?.status ?? "unreviewed"]}</span>
                  {isFlagged(state) && <span className="image-flag inline" title={state?.status === "rework" ? "Rework" : "Commented"} />}
                </td>
                <td className="muted small">{state?.time ? formatWhen(state.time) : "—"}</td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

/** Filter by class: a menu, because a dataset can have far more classes than fit a ribbon. */
function ClassFilter({ labels, counts, chosen, onChange }: {
  labels: Record<string, string>;
  counts: Map<number, number>;
  chosen: Set<number>;
  onChange: (next: Set<number>) => void;
}) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);
  const all = useMemo(
    () => Object.keys(labels).map(Number).sort((a, b) => (counts.get(b) ?? 0) - (counts.get(a) ?? 0) || a - b),
    [labels, counts],
  );

  useEffect(() => {
    if (!open) return;
    const close = (event: MouseEvent) => {
      if (ref.current && !ref.current.contains(event.target as Node)) setOpen(false);
    };
    const key = (event: KeyboardEvent) => event.key === "Escape" && setOpen(false);
    document.addEventListener("mousedown", close);
    document.addEventListener("keydown", key);
    return () => {
      document.removeEventListener("mousedown", close);
      document.removeEventListener("keydown", key);
    };
  }, [open]);

  const toggle = (label: number) => {
    const next = new Set(chosen);
    if (next.has(label)) next.delete(label);
    else next.add(label);
    onChange(next);
  };

  const summary = chosen.size === 0
    ? "All classes"
    : chosen.size === 1
      ? labels[String([...chosen][0])] ?? String([...chosen][0])
      : `${chosen.size} classes`;

  return (
    <div className="class-filter" ref={ref}>
      <button className={`button subtle${chosen.size ? " on" : ""}`} aria-expanded={open} onClick={() => setOpen(!open)}>
        <Icon name="layers" size={15} />
        {summary}
        <Icon name="chevron" size={13} className="chevron-down" />
      </button>
      {open && (
        <div className="class-menu" role="group" aria-label="Filter by class">
          <div className="class-menu-head">
            <span className="muted small">{all.length ? plural(all.length, "class", "classes") : "No classes"}</span>
            {chosen.size > 0 && <button className="button subtle small" onClick={() => onChange(new Set())}>Clear</button>}
          </div>
          <ul>
            {all.map((label) => (
              <li key={label}>
                <label>
                  <input type="checkbox" checked={chosen.has(label)} onChange={() => toggle(label)} />
                  <span className="class-swatch" style={{ background: labelColor(label) }} />
                  <span className="truncate">{labels[String(label)] ?? label}</span>
                  <span className="faint small tabular">{formatNumber(counts.get(label) ?? 0)}</span>
                </label>
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}


/** Filter by the words people have put on images. A menu, because tags are invented freely
 *  and a ribbon cannot hold however many a team decides it needs. */
function TagFilter({ counts, chosen, onChange }: {
  counts: Record<string, number>;
  chosen: Set<string>;
  onChange: (next: Set<string>) => void;
}) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!open) return;
    const close = (event: MouseEvent) => {
      if (ref.current && !ref.current.contains(event.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", close);
    return () => document.removeEventListener("mousedown", close);
  }, [open]);

  const toggle = (tag: string) => {
    const next = new Set(chosen);
    if (next.has(tag)) next.delete(tag);
    else next.add(tag);
    onChange(next);
  };
  const summary = chosen.size === 0 ? "Any tag" : chosen.size === 1 ? [...chosen][0]! : `${chosen.size} tags`;

  return (
    <div className="class-filter" ref={ref}>
      <button className={`button subtle${chosen.size ? " on" : ""}`} aria-expanded={open} onClick={() => setOpen(!open)}>
        <Icon name="star" size={15} />
        {summary}
        <Icon name="chevron" size={13} className="chevron-down" />
      </button>
      {open && (
        <div className="class-menu" role="group" aria-label="Filter by tag">
          <div className="class-menu-head">
            <span className="muted small">{plural(Object.keys(counts).length, "tag")}</span>
            {chosen.size > 0 && <button className="button subtle small" onClick={() => onChange(new Set())}>Clear</button>}
          </div>
          <ul>
            {Object.entries(counts).map(([tag, count]) => (
              <li key={tag}>
                <label>
                  <input type="checkbox" checked={chosen.has(tag)} onChange={() => toggle(tag)} />
                  <span className="truncate">{tag}</span>
                  <span className="faint small tabular">{formatNumber(count)}</span>
                </label>
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}

/** Save the filters in front of you under a name, and come back to them.
 *
 * The state saved is what the ribbon holds, not the scroll position or the selection: a
 * view is a question ("the unverified night shots in valid"), not a moment.
 */
function ViewsMenu({ views, onSave, onOpen, onDelete }: {
  views: SavedView[];
  onSave: (name: string) => Promise<void>;
  onOpen: (view: SavedView) => void;
  onDelete: (view: SavedView) => Promise<void>;
}) {
  const [open, setOpen] = useState(false);
  const [naming, setNaming] = useState(false);
  const [name, setName] = useState("");
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!open) return;
    const close = (event: MouseEvent) => {
      if (ref.current && !ref.current.contains(event.target as Node)) {
        setOpen(false);
        setNaming(false);
      }
    };
    document.addEventListener("mousedown", close);
    return () => document.removeEventListener("mousedown", close);
  }, [open]);

  const save = async () => {
    const text = name.trim();
    if (!text) return;
    await onSave(text);
    setName("");
    setNaming(false);
    setOpen(false);
  };

  return (
    <div className="class-filter" ref={ref}>
      <button className="button subtle" aria-expanded={open} onClick={() => setOpen(!open)} title="Named sets of filters">
        <Icon name="star" size={15} />Views
        {views.length > 0 && <span className="split-toggle-count">{formatNumber(views.length)}</span>}
      </button>
      {open && (
        <div className="class-menu views-menu" role="group" aria-label="Saved views">
          <div className="class-menu-head">
            <span className="muted small">{views.length ? plural(views.length, "saved view") : "Nothing saved yet"}</span>
            <button className="button subtle small" onClick={() => setNaming(true)}>Save these filters</button>
          </div>
          {naming && (
            <div className="views-name">
              <input
                autoFocus
                type="text"
                value={name}
                maxLength={60}
                placeholder="Name these filters"
                onChange={(e) => setName(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Enter") void save();
                  if (e.key === "Escape") setNaming(false);
                }}
              />
              <button className="button primary small" disabled={!name.trim()} onClick={() => void save()}>Save</button>
            </div>
          )}
          <ul>
            {views.map((view) => (
              <li key={view.id} className="views-row">
                <button className="views-open" onClick={() => { onOpen(view); setOpen(false); }} title={`Saved ${formatWhen(view.time)}${view.author ? ` by ${view.author}` : ""}`}>
                  <span className="truncate">{view.name}</span>
                </button>
                <button className="icon-button" aria-label={`Delete ${view.name}`} onClick={() => void onDelete(view)}>
                  <Icon name="trash" size={13} />
                </button>
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}

/** Put a word on every selected image, or take one off. */
function TagAction({ counts, onTag }: { counts: Record<string, number>; onTag: (tag: string, on: boolean) => Promise<void> }) {
  const [open, setOpen] = useState(false);
  const [text, setText] = useState("");
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!open) return;
    const close = (event: MouseEvent) => {
      if (ref.current && !ref.current.contains(event.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", close);
    return () => document.removeEventListener("mousedown", close);
  }, [open]);

  const apply = async (tag: string, on: boolean) => {
    const word = tag.trim();
    if (!word) return;
    await onTag(word, on);
    setText("");
    setOpen(false);
  };

  return (
    <div className="class-filter" ref={ref}>
      <button className="button" onClick={() => setOpen(!open)} aria-expanded={open}>
        <Icon name="star" size={15} />Tag…
      </button>
      {open && (
        <div className="class-menu tag-menu" role="group" aria-label="Tag the selection">
          <div className="views-name">
            <input
              autoFocus
              type="text"
              value={text}
              maxLength={40}
              placeholder="A word for these images"
              onChange={(e) => setText(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter") void apply(text, true);
                if (e.key === "Escape") setOpen(false);
              }}
            />
            <button className="button primary small" disabled={!text.trim()} onClick={() => void apply(text, true)}>Add</button>
          </div>
          {Object.keys(counts).length > 0 && (
            <ul>
              {Object.keys(counts).slice(0, 12).map((tag) => (
                <li key={tag} className="views-row">
                  <button className="views-open" onClick={() => void apply(tag, true)}>
                    <span className="truncate">{tag}</span>
                  </button>
                  <button className="button subtle small" onClick={() => void apply(tag, false)} title={`Take “${tag}” off these images`}>
                    Remove
                  </button>
                </li>
              ))}
            </ul>
          )}
        </div>
      )}
    </div>
  );
}
