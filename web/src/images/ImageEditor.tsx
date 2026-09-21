/** Edit one image's annotations: boxes, masks (polygons), keypoints and the image label.
 *
 * Tools: V select · B box · P polygon · K keypoint, offered by project type (toolsFor). With select, drag an object to move it,
 * a handle to resize its box, a vertex or keypoint to move it; double-click a mask edge to
 * add a vertex. Delete removes the picked vertex or keypoint, else the object.
 * Wheel zooms, dragging empty space pans, 0 fits. Ctrl+Z / Ctrl+Shift+Z undo and redo,
 * Ctrl+S saves; leaving the image saves too. Every save is one new version of the set.
 */

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { api } from "../api/client";
import type { ImageRow, QaBox, QaImageDetail, TaskId, ValueMap } from "../api/types";
import { Icon, formatNumber, plural } from "../components/ui";
import { fileName } from "../review/status";
import { CROWD_COLOR, labelColor } from "./labelColors";

type Tool = "select" | "box" | "polygon" | "keypoint";

/** One object as the editor holds it; converted back to a stored instance on save. */
interface Shape {
  box: [number, number, number, number];
  label: number | null;
  crowd: boolean;
  /** Mask polygons, flat [x, y, x, y, ...] each. */
  polygons: number[][];
  /** A run-length mask: kept as it is, it cannot be edited here. */
  rle: unknown;
  /** COCO keypoints, [x, y, visibility] triples. */
  keypoints: number[];
  /** Everything else the instance carried (annotation_id, area, other COCO fields). */
  props: Record<string, unknown>;
  extra: Record<string, unknown>;
  /** Geometry changed, so area is recomputed on save. */
  moved: boolean;
}

type Pick = { kind: "vertex"; polygon: number; at: number } | { kind: "keypoint"; at: number } | null;

type Drag =
  | { kind: "move"; start: [number, number]; origin: Shape }
  | { kind: "handle"; handle: number; origin: Shape }
  | { kind: "vertex"; polygon: number; at: number }
  | { kind: "keypoint"; at: number }
  | { kind: "draw"; start: [number, number]; end: [number, number] }
  | { kind: "pan"; start: [number, number]; view: View };

interface View { x: number; y: number; w: number; h: number }

const TOOLS: { id: Tool; label: string; key: string; hint: string }[] = [
  { id: "select", label: "Select", key: "V", hint: "Move, resize and reshape" },
  { id: "box", label: "Box", key: "B", hint: "Drag to draw a box" },
  { id: "polygon", label: "Polygon", key: "P", hint: "Click points; click the first point or press Enter to close" },
  { id: "keypoint", label: "Keypoint", key: "K", hint: "Click to add a point to the selected object, or to start a new object; Esc starts the next one" },
];

/** The drawing tools a project's types call for; projects from before types are detection. */
export function toolsFor(tasks: TaskId[] | undefined | null): Tool[] {
  const chosen = new Set<TaskId>(tasks?.length ? tasks : ["object_detection"]);
  const drawing: Tool[] = [];
  if (chosen.has("object_detection")) drawing.push("box");
  if (chosen.has("instance_segmentation") || chosen.has("semantic_segmentation") || chosen.has("panoptic_segmentation")) drawing.push("polygon");
  if (chosen.has("keypoint_detection")) drawing.push("keypoint");
  return drawing.length ? ["select", ...drawing] : [];
}

/** The box around a shape's keypoints (padded a little), for projects with no box tool. */
function keypointBounds(keypoints: number[], width: number, height: number): [number, number, number, number] | null {
  const xs: number[] = [];
  const ys: number[] = [];
  for (let i = 0; i < keypoints.length; i += 3) {
    if (keypoints[i + 2] === 0) continue;
    xs.push(keypoints[i]!);
    ys.push(keypoints[i + 1]!);
  }
  if (!xs.length) return null;
  const [x0, x1, y0, y1] = [Math.min(...xs), Math.max(...xs), Math.min(...ys), Math.max(...ys)];
  const pad = Math.max(4, 0.08 * Math.max(x1 - x0, y1 - y0));
  return [Math.max(0, x0 - pad), Math.max(0, y0 - pad), Math.min(width, x1 + pad), Math.min(height, y1 + pad)];
}

function parseShape(box: QaBox): Shape {
  const { vertices, label, iscrowd, segmentation, coco_extra, ...props } = box;
  let polygons: number[][] = [];
  let rle: unknown = null;
  if (typeof segmentation === "string" && segmentation) {
    try {
      const parsed: unknown = JSON.parse(segmentation);
      if (Array.isArray(parsed)) polygons = parsed.filter((p): p is number[] => Array.isArray(p) && p.length >= 6);
      else if (parsed && typeof parsed === "object") rle = parsed;
    } catch {
      /* unreadable masks are left out */
    }
  }
  let extra: Record<string, unknown> = {};
  let keypoints: number[] = [];
  if (typeof coco_extra === "string" && coco_extra) {
    try {
      extra = JSON.parse(coco_extra) as Record<string, unknown>;
      if (Array.isArray(extra.keypoints)) keypoints = (extra.keypoints as number[]).map(Number);
      delete extra.keypoints;
      delete extra.num_keypoints;
    } catch {
      extra = {};
    }
  }
  const [x0 = 0, y0 = 0, x1 = 0, y1 = 0] = vertices;
  return { box: [x0, y0, x1, y1], label, crowd: Boolean(iscrowd), polygons, rle, keypoints, props, extra, moved: false };
}

function polygonArea(points: number[]): number {
  let sum = 0;
  for (let i = 0; i < points.length; i += 2) {
    const j = (i + 2) % points.length;
    sum += points[i]! * points[j + 1]! - points[j]! * points[i + 1]!;
  }
  return Math.abs(sum) / 2;
}

function boundsOf(polygons: number[][]): [number, number, number, number] | null {
  const xs = polygons.flatMap((p) => p.filter((_, i) => i % 2 === 0));
  const ys = polygons.flatMap((p) => p.filter((_, i) => i % 2 === 1));
  if (!xs.length) return null;
  return [Math.min(...xs), Math.min(...ys), Math.max(...xs), Math.max(...ys)];
}

const round = (v: number) => Math.round(v * 10) / 10;

/** Back to the stored form, declaring only properties the dataset has (or is gaining). */
function toInstance(shape: Shape, declared: Set<string>): QaBox {
  const [x0, y0, x1, y1] = shape.box;
  const box = [round(Math.min(x0, x1)), round(Math.min(y0, y1)), round(Math.max(x0, x1)), round(Math.max(y0, y1))];
  const out: QaBox = { ...shape.props, vertices: box, label: shape.label };
  if (declared.has("iscrowd") || "iscrowd" in shape.props) out.iscrowd = shape.crowd;
  if (declared.has("area") && (shape.moved || shape.props.area === null || shape.props.area === undefined)) {
    out.area = round(shape.polygons.length ? shape.polygons.reduce((n, p) => n + polygonArea(p), 0) : (box[2]! - box[0]!) * (box[3]! - box[1]!));
  }
  if (declared.has("segmentation")) {
    out.segmentation = shape.polygons.length
      ? JSON.stringify(shape.polygons.map((p) => p.map(round)))
      : shape.rle ? JSON.stringify(shape.rle) : null;
  }
  if (declared.has("coco_extra")) {
    const extra = { ...shape.extra };
    if (shape.keypoints.length) {
      extra.keypoints = shape.keypoints.map((v, i) => (i % 3 === 2 ? v : round(v)));
      extra.num_keypoints = shape.keypoints.filter((v, i) => i % 3 === 2 && v > 0).length;
    }
    out.coco_extra = Object.keys(extra).length ? JSON.stringify(extra) : null;
  }
  return out;
}

export function ImageEditor({ project, dataset, tasks, items, index, author, onIndex, onSaved, onClose }: {
  project: string;
  dataset: string;
  /** The project's types: they decide which drawing tools there are. */
  tasks?: TaskId[];
  items: ImageRow[];
  index: number;
  author: string;
  onIndex: (index: number) => void;
  /** After a save: the image whose annotations changed. */
  onSaved: (image: string) => Promise<void>;
  onClose: () => void;
}) {
  const item = items[index]!;
  const [detail, setDetail] = useState<QaImageDetail | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [shapes, setShapes] = useState<Shape[]>([]);
  const [past, setPast] = useState<Shape[][]>([]);
  const [future, setFuture] = useState<Shape[][]>([]);
  const [labels, setLabels] = useState<Record<string, string>>({});
  const [addedClasses, setAddedClasses] = useState(false);
  const [selected, setSelected] = useState<number | null>(null);
  const [pick, setPick] = useState<Pick>(null);
  const [tool, setTool] = useState<Tool>("select");
  const [drawLabel, setDrawLabel] = useState<number | null>(null);
  const [draft, setDraft] = useState<number[]>([]);
  const [cursor, setCursor] = useState<[number, number] | null>(null);
  const [drag, setDrag] = useState<Drag | null>(null);
  const [view, setView] = useState<View>({ x: 0, y: 0, w: 1, h: 1 });
  const [size, setSize] = useState({ w: 1, h: 1 });
  const [saving, setSaving] = useState<"idle" | "saving" | "saved">("idle");
  const [newClass, setNewClass] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const svgRef = useRef<SVGSVGElement>(null);
  const stageRef = useRef<HTMLDivElement>(null);
  const dirty = past.length > 0 || addedClasses;

  const width = detail?.width ?? 0;
  const height = detail?.height ?? 0;
  const fit = useCallback(() => setView({ x: 0, y: 0, w: width || 1, h: height || 1 }), [width, height]);
  const tools = useMemo(() => toolsFor(tasks), [tasks]);
  const toolsRef = useRef(tools);
  toolsRef.current = tools;
  /** With no box tool, an object's box follows its keypoints (masks already set it). */
  const withKeypoints = (shape: Shape, keypoints: number[]): Shape => {
    if (tools.includes("box") || shape.polygons.length) return { ...shape, keypoints };
    const box = keypointBounds(keypoints, width, height);
    return box ? { ...shape, keypoints, box, moved: true } : { ...shape, keypoints };
  };

  // -- loading --------------------------------------------------------------
  useEffect(() => {
    let alive = true;
    setError(null);
    api.qaImage(project, dataset, item.table, item.image)
      .then((next) => {
        if (!alive) return;
        setDetail(next);
        setShapes(next.boxes.map(parseShape));
        setLabels(next.labels);
        setAddedClasses(false);
        setPast([]);
        setFuture([]);
        setSelected(null);
        setPick(null);
        setDraft([]);
        setView({ x: 0, y: 0, w: next.width || 1, h: next.height || 1 });
      })
      .catch((e: Error) => alive && setError(e.message));
    return () => {
      alive = false;
    };
  }, [project, dataset, item.table, item.image]);

  const labelIds = useMemo(() => Object.keys(labels).map(Number).sort((a, b) => a - b), [labels]);
  useEffect(() => {
    if (drawLabel !== null && String(drawLabel) in labels) return;
    const counts = new Map<number, number>();
    for (const s of shapes) if (s.label !== null) counts.set(s.label, (counts.get(s.label) ?? 0) + 1);
    setDrawLabel([...counts.entries()].sort((a, b) => b[1] - a[1])[0]?.[0] ?? labelIds[0] ?? null);
  }, [labels, labelIds, shapes, drawLabel]);

  useEffect(() => {
    const stage = stageRef.current;
    if (!stage) return;
    const observer = new ResizeObserver(() => setSize({ w: stage.clientWidth || 1, h: stage.clientHeight || 1 }));
    observer.observe(stage);
    return () => observer.disconnect();
  }, []);

  // Screen pixels per image pixel, for handles that stay the same size at any zoom.
  const scale = Math.min(size.w / view.w, size.h / view.h) || 1;
  const px = (n: number) => n / scale;

  // -- editing --------------------------------------------------------------
  /** Change the shapes, remembering the previous state for undo. */
  const commit = useCallback((next: Shape[] | ((was: Shape[]) => Shape[])) => {
    setShapes((was) => {
      const value = typeof next === "function" ? next(was) : next;
      if (value !== was) {
        setPast((p) => [...p.slice(-99), was]);
        setFuture([]);
      }
      return value;
    });
  }, []);

  const update = (at: number, change: (shape: Shape) => Shape) => commit((was) => was.map((s, i) => (i === at ? change(s) : s)));

  const undo = () => {
    const previous = past[past.length - 1];
    if (!previous) return;
    setFuture((f) => [shapes, ...f]);
    setPast((p) => p.slice(0, -1));
    setShapes(previous);
    setPick(null);
    if (selected !== null && selected >= previous.length) setSelected(null);
  };
  const redo = () => {
    const next = future[0];
    if (!next) return;
    setPast((p) => [...p, shapes]);
    setFuture((f) => f.slice(1));
    setShapes(next);
  };

  const removeSelected = () => {
    if (selected === null) return;
    const shape = shapes[selected]!;
    if (pick?.kind === "vertex") {
      const polygon = shape.polygons[pick.polygon]!;
      if (polygon.length <= 6) {
        update(selected, (s) => ({ ...s, polygons: s.polygons.filter((_, i) => i !== pick.polygon), moved: true }));
      } else {
        update(selected, (s) => ({
          ...s, moved: true,
          polygons: s.polygons.map((p, i) => (i === pick.polygon ? p.filter((_, j) => j !== pick.at && j !== pick.at + 1) : p)),
        }));
      }
      setPick(null);
      return;
    }
    if (pick?.kind === "keypoint") {
      update(selected, (s) => withKeypoints(s, s.keypoints.filter((_, j) => j < pick.at || j >= pick.at + 3)));
      setPick(null);
      return;
    }
    commit((was) => was.filter((_, i) => i !== selected));
    setSelected(null);
  };

  /** The instance properties this save declares: the dataset's, plus any a new mask or keypoint needs. */
  const declared = useMemo(() => new Set(Object.keys(detail?.instance_properties ?? {})), [detail]);

  // -- saving ---------------------------------------------------------------
  const save = async (): Promise<boolean> => {
    if (!dirty || !detail?.box_column) return true;
    setSaving("saving");
    setError(null);
    try {
      const needs: Record<string, string> = {};
      if (shapes.some((s) => s.polygons.length || s.rle) && !declared.has("segmentation")) needs.segmentation = "string";
      if (shapes.some((s) => s.keypoints.length || Object.keys(s.extra).length) && !declared.has("coco_extra")) needs.coco_extra = "string";
      const keys = new Set([...declared, ...Object.keys(needs)]);
      const valueMap = Object.fromEntries(Object.entries(labels).map(([id, name]) => [id, { internal_name: name }])) as unknown as ValueMap;
      await api.commit({
        url: detail.table,
        values: { [detail.box_column]: { [String(detail.row)]: { width, height, instances: shapes.map((s) => toInstance(s, keys)) } } },
        new_columns: {},
        value_maps: addedClasses ? { [detail.box_column]: valueMap } : {},
        instance_properties: Object.keys(needs).length ? { [detail.box_column]: needs } : {},
        description: `Annotations edited: ${fileName(item.image)}`,
      });
      // An edited image needs another look before it counts as verified.
      await api.setQaStatus({
        project, dataset, samples: [item.image], status: "unreviewed", author, table: detail.table,
        comment: `Edited annotations (${plural(shapes.length, "object")})`,
      }).catch(() => undefined);
      setPast([]);
      setFuture([]);
      setAddedClasses(false);
      setSaving("saved");
      window.setTimeout(() => setSaving("idle"), 2000);
      await onSaved(item.image);
      return true;
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
      setSaving("idle");
      return false;
    }
  };

  const go = async (next: number) => {
    if (next < 0 || next >= items.length) return;
    if (await save()) onIndex(next);
  };
  const close = async () => {
    if (await save()) onClose();
  };

  // -- pointer ----------------------------------------------------------------
  const toImage = (event: { clientX: number; clientY: number }): [number, number] => {
    const matrix = svgRef.current?.getScreenCTM();
    if (!matrix) return [0, 0];
    const p = new DOMPoint(event.clientX, event.clientY).matrixTransform(matrix.inverse());
    return [p.x, p.y];
  };
  const clamp = ([x, y]: [number, number]): [number, number] => [Math.min(width, Math.max(0, x)), Math.min(height, Math.max(0, y))];

  const finishPolygon = (points: number[]) => {
    if (points.length < 6) {
      setDraft([]);
      return;
    }
    const bounds = boundsOf([points])!;
    if (selected !== null) {
      // A second part for the selected object's mask.
      update(selected, (s) => {
        const polygons = [...s.polygons, points];
        return { ...s, polygons, box: boundsOf(polygons)!, moved: true };
      });
    } else {
      commit((was) => [...was, { box: bounds, label: drawLabel, crowd: false, polygons: [points], rle: null, keypoints: [], props: {}, extra: {}, moved: true }]);
      setSelected(shapes.length);
    }
    setDraft([]);
  };

  const onPointerDown = (event: React.PointerEvent<SVGSVGElement>) => {
    if (!detail?.editable) return;
    const point = toImage(event);
    const middle = event.button === 1 || (event.button === 0 && event.altKey);
    if (middle) {
      event.currentTarget.setPointerCapture(event.pointerId);
      setDrag({ kind: "pan", start: [event.clientX, event.clientY], view });
      return;
    }
    if (event.button !== 0) return;
    const target = event.target as Element;
    const role = target.getAttribute("data-role");
    const at = Number(target.getAttribute("data-shape"));

    if (tool === "box") {
      event.currentTarget.setPointerCapture(event.pointerId);
      const p = clamp(point);
      setDrag({ kind: "draw", start: p, end: p });
      return;
    }
    if (tool === "polygon") {
      const p = clamp(point);
      if (draft.length >= 6 && Math.hypot(p[0] - draft[0]!, p[1] - draft[1]!) < px(8)) finishPolygon(draft);
      else setDraft([...draft, p[0], p[1]]);
      return;
    }
    if (tool === "keypoint") {
      const p = clamp(point);
      if (selected === null) {
        // A new object, starting from this point.
        const blank: Shape = { box: [p[0], p[1], p[0], p[1]], label: drawLabel, crowd: false, polygons: [], rle: null, keypoints: [], props: {}, extra: {}, moved: true };
        commit((was) => [...was, withKeypoints(blank, [p[0], p[1], 2])]);
        setSelected(shapes.length);
        return;
      }
      update(selected, (s) => withKeypoints(s, [...s.keypoints, p[0], p[1], 2]));
      return;
    }

    // Select tool.
    event.currentTarget.setPointerCapture(event.pointerId);
    if (role === "handle" && selected !== null) {
      setPast((p) => [...p.slice(-99), shapes]);
      setFuture([]);
      setDrag({ kind: "handle", handle: Number(target.getAttribute("data-handle")), origin: shapes[selected]! });
      return;
    }
    if (role === "vertex" && selected !== null) {
      const polygon = Number(target.getAttribute("data-polygon"));
      const vertex = Number(target.getAttribute("data-vertex"));
      setPick({ kind: "vertex", polygon, at: vertex });
      setPast((p) => [...p.slice(-99), shapes]);
      setFuture([]);
      setDrag({ kind: "vertex", polygon, at: vertex });
      return;
    }
    if (role === "keypoint" && selected !== null) {
      const kp = Number(target.getAttribute("data-keypoint"));
      setPick({ kind: "keypoint", at: kp });
      setPast((p) => [...p.slice(-99), shapes]);
      setFuture([]);
      setDrag({ kind: "keypoint", at: kp });
      return;
    }
    if (role === "shape" && Number.isInteger(at)) {
      setSelected(at);
      setPick(null);
      setPast((p) => [...p.slice(-99), shapes]);
      setFuture([]);
      setDrag({ kind: "move", start: point, origin: shapes[at]! });
      return;
    }
    setSelected(null);
    setPick(null);
    setDrag({ kind: "pan", start: [event.clientX, event.clientY], view });
  };

  const onPointerMove = (event: React.PointerEvent<SVGSVGElement>) => {
    const point = toImage(event);
    setCursor(point);
    if (!drag) return;
    if (drag.kind === "pan") {
      const dx = (event.clientX - drag.start[0]) / scale;
      const dy = (event.clientY - drag.start[1]) / scale;
      setView({ ...drag.view, x: drag.view.x - dx, y: drag.view.y - dy });
      return;
    }
    if (drag.kind === "draw") {
      setDrag({ ...drag, end: clamp(point) });
      return;
    }
    if (selected === null) return;
    // Direct edits during a drag: one undo step was taken when it started.
    const set = (change: (s: Shape) => Shape) => setShapes((was) => was.map((s, i) => (i === selected ? change(s) : s)));
    if (drag.kind === "move") {
      const o = drag.origin;
      let dx = point[0] - drag.start[0];
      let dy = point[1] - drag.start[1];
      dx = Math.min(width - Math.max(o.box[0], o.box[2]), Math.max(-Math.min(o.box[0], o.box[2]), dx));
      dy = Math.min(height - Math.max(o.box[1], o.box[3]), Math.max(-Math.min(o.box[1], o.box[3]), dy));
      set(() => ({
        ...o, moved: true,
        box: [o.box[0] + dx, o.box[1] + dy, o.box[2] + dx, o.box[3] + dy],
        polygons: o.polygons.map((p) => p.map((v, i) => v + (i % 2 === 0 ? dx : dy))),
        keypoints: o.keypoints.map((v, i) => (i % 3 === 0 ? v + dx : i % 3 === 1 ? v + dy : v)),
      }));
    } else if (drag.kind === "handle") {
      const [x, y] = clamp(point);
      const [x0, y0, x1, y1] = drag.origin.box;
      // Handles: 0 1 2 across the top, 3 4 5 bottom, 6 left, 7 right.
      const h = drag.handle;
      const box: [number, number, number, number] = [
        h === 0 || h === 3 || h === 6 ? x : x0,
        h <= 2 ? y : y0,
        h === 2 || h === 5 || h === 7 ? x : x1,
        h >= 3 && h <= 5 ? y : y1,
      ];
      set((s) => ({ ...s, box, moved: true }));
    } else if (drag.kind === "vertex") {
      const [x, y] = clamp(point);
      set((s) => {
        const polygons = s.polygons.map((p, i) => (i === drag.polygon ? p.map((v, j) => (j === drag.at ? x : j === drag.at + 1 ? y : v)) : p));
        return { ...s, polygons, box: boundsOf(polygons) ?? s.box, moved: true };
      });
    } else if (drag.kind === "keypoint") {
      const [x, y] = clamp(point);
      set((s) => withKeypoints(s, s.keypoints.map((v, j) => (j === drag.at ? x : j === drag.at + 1 ? y : v))));
    }
  };

  const onPointerUp = () => {
    if (drag?.kind === "draw") {
      const [x0, y0] = drag.start;
      const [x1, y1] = drag.end;
      if (Math.abs(x1 - x0) >= 3 && Math.abs(y1 - y0) >= 3) {
        commit((was) => [...was, {
          box: [Math.min(x0, x1), Math.min(y0, y1), Math.max(x0, x1), Math.max(y0, y1)], label: drawLabel, crowd: false,
          polygons: [], rle: null, keypoints: [], props: {}, extra: {}, moved: true,
        }]);
        setSelected(shapes.length);
      }
    }
    if (drag?.kind === "handle" && selected !== null) {
      // Keep boxes the right way round after dragging a handle past the other side.
      setShapes((was) => was.map((s, i) => (i === selected ? { ...s, box: [Math.min(s.box[0], s.box[2]), Math.min(s.box[1], s.box[3]), Math.max(s.box[0], s.box[2]), Math.max(s.box[1], s.box[3])] } : s)));
    }
    setDrag(null);
  };

  const onWheel = (event: React.WheelEvent<SVGSVGElement>) => {
    const [cx, cy] = toImage(event);
    const factor = Math.exp(event.deltaY * 0.0015);
    const w = Math.min(width * 4, Math.max(8, view.w * factor));
    const h = w * (view.h / view.w);
    setView({ x: cx - (cx - view.x) * (w / view.w), y: cy - (cy - view.y) * (h / view.h), w, h });
  };

  /** Double-click a mask edge to put a vertex there. */
  const onDoubleClick = (event: React.MouseEvent<SVGSVGElement>) => {
    if (tool === "polygon") {
      finishPolygon(draft);
      return;
    }
    if (selected === null) return;
    const [x, y] = toImage(event);
    const shape = shapes[selected]!;
    let best: { polygon: number; at: number; d: number } | null = null;
    shape.polygons.forEach((p, pi) => {
      for (let i = 0; i < p.length; i += 2) {
        const j = (i + 2) % p.length;
        const [ax, ay, bx, by] = [p[i]!, p[i + 1]!, p[j]!, p[j + 1]!];
        const t = Math.max(0, Math.min(1, ((x - ax) * (bx - ax) + (y - ay) * (by - ay)) / ((bx - ax) ** 2 + (by - ay) ** 2 || 1)));
        const d = Math.hypot(x - (ax + t * (bx - ax)), y - (ay + t * (by - ay)));
        if (!best || d < best.d) best = { polygon: pi, at: i + 2, d };
      }
    });
    const found = best as { polygon: number; at: number; d: number } | null;
    if (found && found.d < px(10)) {
      update(selected, (s) => ({
        ...s, moved: true,
        polygons: s.polygons.map((p, i) => (i === found.polygon ? [...p.slice(0, found.at), x, y, ...p.slice(found.at)] : p)),
      }));
      setPick({ kind: "vertex", polygon: found.polygon, at: found.at });
    }
  };

  // -- keys -------------------------------------------------------------------
  const keys = useRef({ undo, redo, save, go, close, removeSelected, index, draft, finishPolygon, fit });
  keys.current = { undo, redo, save, go, close, removeSelected, index, draft, finishPolygon, fit };
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      const target = event.target as HTMLElement;
      if (target.tagName === "INPUT" || target.tagName === "TEXTAREA" || target.tagName === "SELECT") {
        if (event.key === "Escape") target.blur();
        return;
      }
      const k = keys.current;
      const ctrl = event.ctrlKey || event.metaKey;
      const key = event.key.toLowerCase();
      if (ctrl && key === "s") void k.save();
      else if (ctrl && key === "z" && event.shiftKey) k.redo();
      else if (ctrl && key === "z") k.undo();
      else if (ctrl && key === "y") k.redo();
      else if (ctrl || event.altKey) return;
      else if (event.key === "Escape") {
        if (k.draft.length) setDraft([]);
        else if (pickRef.current) setPick(null);
        else if (selectedRef.current !== null) setSelected(null);
        else void k.close();
      } else if (event.key === "Enter" && k.draft.length) k.finishPolygon(k.draft);
      else if (event.key === "Backspace" && k.draft.length) setDraft((d) => d.slice(0, -2));
      else if (event.key === "Delete" || event.key === "Backspace") k.removeSelected();
      else if (event.key === "ArrowRight") void k.go(k.index + 1);
      else if (event.key === "ArrowLeft") void k.go(k.index - 1);
      else if (TOOLS.some((t) => t.key.toLowerCase() === key && toolsRef.current.includes(t.id))) {
        setTool(TOOLS.find((t) => t.key.toLowerCase() === key)!.id);
      }
      else if (key === "0") k.fit();
      else return;
      event.preventDefault();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);
  const pickRef = useRef(pick);
  pickRef.current = pick;
  const selectedRef = useRef(selected);
  selectedRef.current = selected;

  useEffect(() => {
    if (tool !== "polygon") setDraft([]);
    setNotice(null);
  }, [tool]);

  useEffect(() => {
    if (!dirty) return;
    const warn = (event: BeforeUnloadEvent) => {
      event.preventDefault();
      event.returnValue = "";
    };
    window.addEventListener("beforeunload", warn);
    return () => window.removeEventListener("beforeunload", warn);
  }, [dirty]);

  // -- image label (classification) -----------------------------------------------
  const whole = shapes.findIndex((s) => s.box[0] <= width * 0.02 && s.box[1] <= height * 0.02
    && s.box[2] >= width * 0.98 && s.box[3] >= height * 0.98 && !s.polygons.length);
  const setImageLabel = (value: string) => {
    if (value === "") {
      if (whole >= 0) commit((was) => was.filter((_, i) => i !== whole));
      return;
    }
    const label = Number(value);
    if (whole >= 0) update(whole, (s) => ({ ...s, label }));
    else commit((was) => [...was, { box: [0, 0, width, height], label, crowd: false, polygons: [], rle: null, keypoints: [], props: {}, extra: {}, moved: true }]);
  };

  const addClass = () => {
    const name = (newClass ?? "").trim();
    if (!name) return;
    const existing = Object.entries(labels).find(([, n]) => n.toLowerCase() === name.toLowerCase());
    if (existing) {
      setDrawLabel(Number(existing[0]));
    } else {
      const id = Math.max(-1, ...labelIds) + 1;
      setLabels({ ...labels, [String(id)]: name });
      setAddedClasses(true);
      setDrawLabel(id);
    }
    setNewClass(null);
  };

  const labelName = (label: number | null) => (label === null ? "Unlabelled" : labels[String(label)] ?? String(label));
  const colorOf = (shape: Shape) => (shape.crowd ? CROWD_COLOR : labelColor(shape.label));
  const current = selected !== null ? shapes[selected] : undefined;
  const numbered = useMemo(() => {
    const seen = new Map<number | null, number>();
    return shapes.map((s) => {
      const n = (seen.get(s.label) ?? 0) + 1;
      seen.set(s.label, n);
      return n;
    });
  }, [shapes]);
  const editable = Boolean(detail?.editable && detail.box_column);
  const drawing = drag?.kind === "draw" ? drag : null;
  const classifies = (tasks ?? []).includes("classification");
  const addClassButton = (
    <button className="button subtle small" onClick={() => setNewClass("")} title="Add a class to this dataset">
      <Icon name="plus" size={13} />Class
    </button>
  );
  const classInput = newClass !== null && (
    <div className="editor-new-class">
      <input type="text" autoFocus placeholder="New class name" value={newClass} maxLength={80}
        onChange={(e) => setNewClass(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === "Enter") addClass();
          if (e.key === "Escape") setNewClass(null);
        }} />
      <button className="button small" onClick={addClass} disabled={!newClass.trim()}>Add</button>
    </div>
  );
  const fontSize = px(12);

  return (
    <div className="qa-inspector image-editor" role="dialog" aria-modal="true" aria-label={`Edit ${fileName(item.image)}`}>
      <div className="qa-stage">
        <div className="qa-stage-bar">
          <button className="icon-button" onClick={() => void go(index - 1)} disabled={index === 0 || saving === "saving"} aria-label="Previous image"><Icon name="back" /></button>
          <span className="tabular small">{formatNumber(index + 1)} / {formatNumber(items.length)}</span>
          <button className="icon-button" onClick={() => void go(index + 1)} disabled={index >= items.length - 1 || saving === "saving"} aria-label="Next image"><Icon name="chevron" /></button>
          <span className="mono small qa-stage-name" title={item.image}>{fileName(item.image)}</span>
          <span className="spacer" />
          {tools.length > 0 && <div className="segmented editor-tools" role="group" aria-label="Tool">
            {TOOLS.filter((t) => tools.includes(t.id)).map((t) => (
              <button key={t.id} className={tool === t.id ? "on" : ""} onClick={() => setTool(t.id)} title={`${t.hint} (${t.key})`} disabled={!editable}>
                {t.label} <kbd>{t.key}</kbd>
              </button>
            ))}
          </div>}
          <button className="icon-button" onClick={fit} title="Fit image (0)" aria-label="Fit image"><Icon name="fit" size={15} /></button>
        </div>
        <div className="editor-canvas" ref={stageRef}>
          {detail && width > 0 ? (
            <svg
              ref={svgRef}
              viewBox={`${view.x} ${view.y} ${view.w} ${view.h}`}
              preserveAspectRatio="xMidYMid meet"
              className={`tool-${tool}${drag?.kind === "pan" ? " panning" : ""}`}
              onPointerDown={onPointerDown}
              onPointerMove={onPointerMove}
              onPointerUp={onPointerUp}
              onPointerLeave={() => setCursor(null)}
              onWheel={onWheel}
              onDoubleClick={onDoubleClick}
            >
              <image href={api.mediaUrl(item.image, undefined, project, dataset)} x={0} y={0} width={width} height={height} />
              {shapes.map((shape, i) => {
                const color = colorOf(shape);
                const on = i === selected;
                const [x0, y0, x1, y1] = shape.box;
                return (
                  <g key={i} className={on ? "shape selected" : "shape"}>
                    {shape.polygons.map((p, pi) => (
                      <polygon key={pi} data-role="shape" data-shape={i} points={p.join(" ")}
                        fill={color} fillOpacity={on ? 0.35 : 0.22} stroke={color} strokeWidth={px(on ? 2 : 1.2)} />
                    ))}
                    <rect data-role="shape" data-shape={i}
                      x={Math.min(x0, x1)} y={Math.min(y0, y1)} width={Math.abs(x1 - x0)} height={Math.abs(y1 - y0)}
                      fill={on ? "rgba(255,255,255,0.06)" : "transparent"} stroke={color} strokeWidth={px(on ? 2 : 1.3)}
                      strokeDasharray={shape.polygons.length ? `${px(4)} ${px(3)}` : undefined} />
                    {on && (
                      <text x={Math.min(x0, x1)} y={Math.min(y0, y1) - px(4)} fontSize={fontSize} fill={color} className="qa-box-label">
                        {labelName(shape.label)}
                      </text>
                    )}
                    {Array.from({ length: shape.keypoints.length / 3 }, (_, k) => {
                      const [kx, ky, kv] = [shape.keypoints[k * 3]!, shape.keypoints[k * 3 + 1]!, shape.keypoints[k * 3 + 2]!];
                      if (kv === 0) return null;
                      const picked = on && pick?.kind === "keypoint" && pick.at === k * 3;
                      return (
                        <circle key={`k${k}`} data-role={on ? "keypoint" : "shape"} data-shape={i} data-keypoint={k * 3}
                          cx={kx} cy={ky} r={px(picked ? 6 : 4)} fill={kv === 1 ? "none" : color} stroke={picked ? "#fff" : color} strokeWidth={px(1.5)} />
                      );
                    })}
                  </g>
                );
              })}
              {current && tool === "select" && (
                <g className="editor-handles">
                  {current.polygons.map((p, pi) => Array.from({ length: p.length / 2 }, (_, v) => {
                    const picked = pick?.kind === "vertex" && pick.polygon === pi && pick.at === v * 2;
                    return (
                      <circle key={`v${pi}-${v}`} data-role="vertex" data-polygon={pi} data-vertex={v * 2}
                        cx={p[v * 2]} cy={p[v * 2 + 1]} r={px(picked ? 6 : 4.5)} className={picked ? "vertex picked" : "vertex"} />
                    );
                  }))}
                  {!current.polygons.length && boxHandles(current.box).map(([hx, hy], h) => (
                    <rect key={h} data-role="handle" data-handle={h} x={hx - px(5)} y={hy - px(5)} width={px(10)} height={px(10)} className={`handle handle-${h}`} />
                  ))}
                </g>
              )}
              {drawing && (
                <rect className="editor-draft" x={Math.min(drawing.start[0], drawing.end[0])} y={Math.min(drawing.start[1], drawing.end[1])}
                  width={Math.abs(drawing.end[0] - drawing.start[0])} height={Math.abs(drawing.end[1] - drawing.start[1])}
                  stroke={labelColor(drawLabel)} strokeWidth={px(1.5)} />
              )}
              {draft.length > 0 && (
                <g className="editor-draft">
                  <polyline points={[...draft, ...(cursor ? cursor : [])].join(" ")} stroke={labelColor(drawLabel)} strokeWidth={px(1.5)} fill="none" />
                  {Array.from({ length: draft.length / 2 }, (_, v) => (
                    <circle key={v} cx={draft[v * 2]} cy={draft[v * 2 + 1]} r={px(v === 0 ? 6 : 3.5)} fill={v === 0 ? "#fff" : labelColor(drawLabel)} />
                  ))}
                </g>
              )}
            </svg>
          ) : (
            <span className="muted">{error ?? "Loading"}</span>
          )}
          {notice && <div className="editor-notice" role="status">{notice}</div>}
        </div>
      </div>

      <aside className="qa-side editor-side">
        <div className="qa-side-head">
          <span className="strong">Edit</span>
          <span className="muted small">{item.set} · row {formatNumber(item.row)}</span>
          <span className="spacer" />
          <button className="icon-button" onClick={() => void close()} aria-label="Close" title="Close (saves)"><Icon name="close" /></button>
        </div>

        {!editable && detail && <p className="form-error qa-side-error">This version is read-only.</p>}

        {tools.length > 0 && (
          <div className="qa-side-section">
            <h3 className="qa-side-title">Class for new shapes</h3>
            <div className="editor-class-row">
              <span className="class-swatch" style={{ background: labelColor(drawLabel) }} />
              <div className="select-wrap">
                <select value={drawLabel ?? ""} onChange={(e) => setDrawLabel(Number(e.target.value))} aria-label="Class for new shapes">
                  {labelIds.map((id) => <option key={id} value={id}>{labels[String(id)]}</option>)}
                </select>
              </div>
              {addClassButton}
            </div>
            {classInput}
          </div>
        )}

        {classifies && (
          <div className="qa-side-section">
            <h3 className="qa-side-title">Image label</h3>
            <div className="editor-class-row">
              <div className="select-wrap">
                <select value={whole >= 0 ? String(shapes[whole]!.label ?? "") : ""} onChange={(e) => setImageLabel(e.target.value)} disabled={!editable} aria-label="Image label">
                  <option value="">None</option>
                  {labelIds.map((id) => <option key={id} value={id}>{labels[String(id)]}</option>)}
                </select>
              </div>
              {tools.length === 0 && addClassButton}
            </div>
            {tools.length === 0 && classInput}
          </div>
        )}

        {current && (
          <div className="qa-side-section editor-selected">
            <h3 className="qa-side-title">Selected <span className="faint">{labelName(current.label)} #{numbered[selected!]}</span></h3>
            <div className="editor-class-row">
              <span className="class-swatch" style={{ background: colorOf(current) }} />
              <div className="select-wrap">
                <select value={current.label ?? ""} onChange={(e) => update(selected!, (s) => ({ ...s, label: Number(e.target.value) }))} aria-label="Class of the selected object">
                  {labelIds.map((id) => <option key={id} value={id}>{labels[String(id)]}</option>)}
                </select>
              </div>
              <label className="editor-crowd" title="Crowd or ignore region: neither rewarded nor penalised">
                <input type="checkbox" checked={current.crowd} onChange={(e) => update(selected!, (s) => ({ ...s, crowd: e.target.checked }))} />Crowd
              </label>
            </div>
            <dl className="image-meta">
              <div><dt>Box</dt><dd className="tabular">{Math.round(Math.abs(current.box[2] - current.box[0]))} × {Math.round(Math.abs(current.box[3] - current.box[1]))}</dd></div>
              <div><dt>Mask</dt><dd>{current.polygons.length ? `${plural(current.polygons.length, "polygon")}, ${formatNumber(current.polygons.reduce((n, p) => n + p.length / 2, 0))} points` : current.rle ? "Run-length (not editable)" : "—"}</dd></div>
              <div><dt>Keypoints</dt><dd>{current.keypoints.length ? formatNumber(current.keypoints.length / 3) : "—"}</dd></div>
            </dl>
            {current.keypoints.length > 0 && (
              <ul className="editor-keypoints">
                {Array.from({ length: current.keypoints.length / 3 }, (_, k) => {
                  const v = current.keypoints[k * 3 + 2]!;
                  return (
                    <li key={k} className={pick?.kind === "keypoint" && pick.at === k * 3 ? "on" : ""}>
                      <button className="linkish" onClick={() => setPick({ kind: "keypoint", at: k * 3 })}>Point {k + 1}</button>
                      <div className="segmented" role="group" aria-label={`Visibility of point ${k + 1}`}>
                        {([[0, "Off"], [1, "Hidden"], [2, "Visible"]] as const).map(([value, text]) => (
                          <button key={value} className={v === value ? "on" : ""}
                            onClick={() => update(selected!, (s) => withKeypoints(s, s.keypoints.map((x, j) => (j === k * 3 + 2 ? value : x))))}>{text}</button>
                        ))}
                      </div>
                      <button className="icon-button" aria-label={`Delete point ${k + 1}`}
                        onClick={() => update(selected!, (s) => withKeypoints(s, s.keypoints.filter((_, j) => j < k * 3 || j >= k * 3 + 3)))}>
                        <Icon name="close" size={12} />
                      </button>
                    </li>
                  );
                })}
              </ul>
            )}
            <div className="editor-actions">
              {tools.includes("polygon") && (
                <button className="button small" onClick={() => setTool("polygon")} title="Draw a mask polygon for this object (P)">{current.polygons.length ? "Add mask part" : "Add mask"}</button>
              )}
              {tools.includes("keypoint") && (
                <button className="button small" onClick={() => setTool("keypoint")} title="Click on the image to add keypoints (K)">Add keypoints</button>
              )}
              {current.polygons.length > 0 && (
                <button className="button small subtle" onClick={() => update(selected!, (s) => ({ ...s, polygons: [], moved: true }))}>Remove mask</button>
              )}
              {current.keypoints.length > 0 && (
                <button className="button small subtle" onClick={() => update(selected!, (s) => ({ ...s, keypoints: [] }))}>Remove keypoints</button>
              )}
              <button className="button small danger-button" onClick={() => { setPick(null); commit((was) => was.filter((_, i) => i !== selected)); setSelected(null); }}>
                <Icon name="trash" size={13} />Delete object
              </button>
            </div>
          </div>
        )}

        <div className="qa-side-section editor-objects">
          <h3 className="qa-side-title">Objects <span className="faint">{formatNumber(shapes.length)}</span></h3>
          <ul className="instance-list">
            {shapes.map((shape, i) => (
              <li key={i}>
                <button className={`instance-row${i === selected ? " on" : ""}`} onClick={() => { setSelected(i); setPick(null); setTool("select"); }}>
                  <span className="class-swatch" style={{ background: colorOf(shape) }} />
                  <span className="truncate">{labelName(shape.label)} <span className="faint">#{numbered[i]}</span></span>
                  <span className="faint small">
                    {[shape.polygons.length || shape.rle ? "mask" : "", shape.keypoints.length ? `${shape.keypoints.length / 3} kp` : "", shape.crowd ? "crowd" : ""].filter(Boolean).join(" · ")}
                  </span>
                </button>
              </li>
            ))}
            {detail && shapes.length === 0 && <li className="faint small">No objects. Draw with B or P.</li>}
          </ul>
        </div>

        <div className="editor-foot">
          {error && <p className="form-error">{error}</p>}
          <div className="editor-foot-row">
            <button className="icon-button" onClick={undo} disabled={!past.length} title="Undo (Ctrl+Z)" aria-label="Undo"><Icon name="back" size={15} /></button>
            <button className="icon-button" onClick={redo} disabled={!future.length} title="Redo (Ctrl+Shift+Z)" aria-label="Redo"><Icon name="chevron" size={15} /></button>
            <span className="muted small">
              {saving === "saving" ? "Saving" : saving === "saved" ? "Saved as a new version" : dirty ? plural(past.length, "unsaved change") : "No changes"}
            </span>
            <span className="spacer" />
            <button className="button primary" disabled={!dirty || saving === "saving" || !editable} onClick={() => void save()} title="Save as a new version (Ctrl+S)">
              Save
            </button>
          </div>
          <p className="faint small">Saving marks the image unverified.</p>
        </div>
      </aside>
    </div>
  );
}

/** Corner and edge handles: top-left, top, top-right, bottom-left, bottom, bottom-right, left, right. */
function boxHandles([x0, y0, x1, y1]: [number, number, number, number]): [number, number][] {
  const mx = (x0 + x1) / 2;
  const my = (y0 + y1) / 2;
  return [[x0, y0], [mx, y0], [x1, y0], [x0, y1], [mx, y1], [x1, y1], [x0, my], [x1, my]];
}
