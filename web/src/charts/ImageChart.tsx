/** One sample at a time, drawn large: the image, its boxes, and a list of instances.
 *
 * It follows the row cursor, so arrow keys in the Rows panel, a click on a scatter point
 * and the ◀ ▶ buttons here all step through the same visible order. Image and boxes live
 * in one SVG in image pixel coordinates: zooming, panning and snapping to a box are all
 * changes of the viewBox, so boxes can never drift off the pixels they describe.
 */

import { Icon } from "../components/ui";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { api } from "../api/client";
import { BoxControls, RoleLegend } from "../boxes/BoxControls";
import { BoxShapes } from "../boxes/BoxOverlay";
import { asBoxValue, boxColumns, classColor, drawnBoxes, type DrawnBox, type InstanceRef } from "../boxes/model";
import type { PredictionRef } from "../boxes/boxActions";
import { className, isEditable } from "../store/editing";
import { useStore } from "../store/store";
import type { ImageSpec } from "./spec";
import { columnLabel } from "../copy/plain";

interface Props {
  spec: ImageSpec;
  width: number;
  height: number;
}

interface View {
  x: number;
  y: number;
  w: number;
  h: number;
}

const TOOLBAR_H = 44;
const REVIEW_H = 40;
const LABELBAR_H = 40;

type Handle = "move" | "n" | "s" | "e" | "w" | "ne" | "nw" | "se" | "sw";

const HANDLE_CURSOR: Record<Handle, string> = {
  move: "move", n: "ns-resize", s: "ns-resize", e: "ew-resize", w: "ew-resize",
  ne: "nesw-resize", sw: "nesw-resize", nw: "nwse-resize", se: "nwse-resize",
};

/** Which part of a box a point grabs: an edge, a corner, the inside, or nothing. */
function handleAt(box: { x0: number; y0: number; x1: number; y1: number }, p: { x: number; y: number }, tol: number): Handle | null {
  const inX = p.x >= box.x0 - tol && p.x <= box.x1 + tol;
  const inY = p.y >= box.y0 - tol && p.y <= box.y1 + tol;
  if (!inX || !inY) return null;
  const n = Math.abs(p.y - box.y0) <= tol;
  const s = Math.abs(p.y - box.y1) <= tol;
  const w = Math.abs(p.x - box.x0) <= tol;
  const e = Math.abs(p.x - box.x1) <= tol;
  const vertical = n ? "n" : s ? "s" : "";
  const horizontal = w ? "w" : e ? "e" : "";
  if (vertical || horizontal) return (vertical + horizontal) as Handle;
  return "move";
}

function dragVertices(
  active: { kind: "draw" | "move" | "resize"; handle: Handle; start: { x: number; y: number }; box: { x0: number; y0: number; x1: number; y1: number } | null },
  p: { x: number; y: number },
): number[] {
  if (active.kind === "draw" || !active.box) return [active.start.x, active.start.y, p.x, p.y];
  const dx = p.x - active.start.x;
  const dy = p.y - active.start.y;
  let { x0, y0, x1, y1 } = active.box;
  if (active.handle === "move") return [x0 + dx, y0 + dy, x1 + dx, y1 + dy];
  if (active.handle.includes("n")) y0 += dy;
  if (active.handle.includes("s")) y1 += dy;
  if (active.handle.includes("w")) x0 += dx;
  if (active.handle.includes("e")) x1 += dx;
  return [Math.min(x0, x1), Math.min(y0, y1), Math.max(x0, x1), Math.max(y0, y1)];
}

function format(value: unknown): string {
  if (typeof value === "number" && !Number.isInteger(value)) return value.toFixed(3);
  if (value === null || value === undefined) return "–";
  return String(value);
}

/** A view of the whole image, padded to the viewport's aspect so it is never stretched. */
function fitView(imageW: number, imageH: number, viewW: number, viewH: number, box?: { x0: number; y0: number; x1: number; y1: number }): View {
  const region = box
    ? (() => {
        const bw = Math.max(box.x1 - box.x0, 8);
        const bh = Math.max(box.y1 - box.y0, 8);
        const margin = Math.max(bw, bh) * 0.6 + 16;
        return { x: box.x0 - margin, y: box.y0 - margin, w: bw + 2 * margin, h: bh + 2 * margin };
      })()
    : { x: 0, y: 0, w: imageW, h: imageH };
  const aspect = viewW / Math.max(viewH, 1);
  let { x, y, w, h } = region;
  if (w / h > aspect) {
    const nh = w / aspect;
    y -= (nh - h) / 2;
    h = nh;
  } else {
    const nw = h * aspect;
    x -= (nw - w) / 2;
    w = nw;
  }
  return { x, y, w, h };
}

export function ImageChart({ spec, width, height }: Props) {
  const rows = useStore((s) => s.rows);
  const columns = useStore((s) => s.columns);
  const anchor = useStore((s) => s.selection.anchor);
  const visible = useStore((s) => s.visibleRows());
  const moveCursor = useStore((s) => s.moveCursor);
  const clickRow = useStore((s) => s.clickRow);
  const project = useStore((s) => s.project);
  const display = useStore((s) => s.boxDisplay);
  const focused = useStore((s) => s.focusedInstance);
  const focusInstance = useStore((s) => s.focusInstance);
  const filters = useStore((s) => s.filters);
  const filterList = useMemo(() => Object.values(filters), [filters]);
  const dismissed = useStore((s) => s.dismissed);
  const staged = useStore((s) => s.staged);
  const selectedRows = useStore((s) => s.selection.rows);
  const addBox = useStore((s) => s.addBox);
  const updateBox = useStore((s) => s.updateBox);
  const deleteBoxes = useStore((s) => s.deleteBoxes);
  const copyBox = useStore((s) => s.copyBox);
  const pasteBoxes = useStore((s) => s.pasteBoxes);
  const reviewPredictions = useStore((s) => s.reviewPredictions);
  const applyStaged = useStore((s) => s.applyStaged);
  const clearStaged = useStore((s) => s.clearStaged);
  const applyNms = useStore((s) => s.applyNms);
  const [editMode, setEditMode] = useState(false);
  const [drawLabel, setDrawLabel] = useState<number | null>(null);
  const [stagedMode, setStagedMode] = useState(false);
  const [scope, setScope] = useState<"box" | "row" | "selection" | "visible">("box");
  const [nmsIou, setNmsIou] = useState(0.7);
  const [notice, setNotice] = useState<string | null>(null);
  const say = useCallback((message: string | null) => {
    setNotice(message);
    if (message) window.setTimeout(() => setNotice((m) => (m === message ? null : m)), 2500);
  }, []);

  const position = anchor === null ? -1 : visible.indexOf(anchor);
  const current = position === -1 ? visible[0] : anchor!;
  const row = current === undefined ? undefined : rows[current];
  const source = row ? String(row[spec.image] ?? "") : "";

  const { truth, predicted } = useMemo(() => boxColumns(columns), [columns]);
  const hasBoxes = Boolean(truth || predicted);
  const review = useCallback(
    (r: number) => ({ row: r, dismissed, staged }),
    [dismissed, staged],
  );
  const boxes = useMemo(
    () => (current === undefined ? [] : drawnBoxes(row, truth, predicted, display, filterList, review(current))),
    [row, truth, predicted, display, filterList, review, current],
  );
  const truthEditable = isEditable(truth ?? undefined);
  const classKeys = useMemo(() => Object.keys(truth?.value_map ?? {}).map(Number).sort((a, b) => a - b), [truth]);
  const activeLabel = drawLabel ?? classKeys[0] ?? 0;
  const [autoSnap, setAutoSnap] = useState(true);
  const [hovered] = useState<InstanceRef | null>(null);
  const setFilter = useStore((s) => s.setFilter);

  // Toolbars have fixed heights so the stage can take exactly what is left.
  const reviewTools = hasBoxes && (editMode || Boolean(predicted));
  const stageWidth = width;
  const stageHeight = hasBoxes ? Math.max(80, height - TOOLBAR_H - (reviewTools ? REVIEW_H : 0) - LABELBAR_H) : height;

  // The label filter is the dataset-wide filter on box class, so this bar and the
  // Filter panel are the same control: hiding a class here hides it everywhere.
  const labelColumn = truth ?? predicted;
  const labelFilter = labelColumn
    ? Object.values(filters).find((f) => f.scope === "element" && f.geometry === labelColumn.name && f.property === "label")
    : undefined;
  const excluded = labelFilter && labelFilter.kind === "categorical" ? labelFilter.excluded : [];
  const inImage = useMemo(() => {
    const counts = new Map<number, number>();
    const value = asBoxValue(labelColumn ? row?.[labelColumn.name] : undefined);
    for (const instance of value?.instances ?? []) {
      if (instance.label === null || instance.iscrowd) continue;
      counts.set(instance.label, (counts.get(instance.label) ?? 0) + 1);
    }
    return counts;
  }, [row, labelColumn]);
  const toggleLabel = (label: number, solo: boolean) => {
    if (!labelFilter || labelFilter.kind !== "categorical") return;
    const all = labelFilter.values as (string | number)[];
    const key = all.find((v) => Number(v) === label) ?? label;
    const next = solo
      ? all.filter((v) => Number(v) !== label)
      : excluded.includes(key) ? excluded.filter((v) => v !== key) : [...excluded, key];
    setFilter(labelFilter.column, { excluded: next });
  };

  // Image size: from the box column when present (what the boxes are measured against),
  // otherwise from the loaded image.
  const boxValue = asBoxValue(truth ? row?.[truth.name] : predicted ? row?.[predicted.name] : undefined);
  const [natural, setNatural] = useState<{ w: number; h: number } | null>(null);
  const [failed, setFailed] = useState(false);
  const imageW = boxValue?.width || natural?.w || 0;
  const imageH = boxValue?.height || natural?.h || 0;

  useEffect(() => {
    setFailed(false);
    setNatural(null);
    if (!source) return;
    let cancelled = false;
    const image = new Image();
    image.onload = () => !cancelled && setNatural({ w: image.naturalWidth, h: image.naturalHeight });
    image.onerror = () => !cancelled && setFailed(true);
    image.src = api.mediaUrl(source, undefined, project ?? undefined);
    return () => {
      cancelled = true;
    };
  }, [source, project]);

  const [view, setView] = useState<View>({ x: 0, y: 0, w: 1, h: 1 });
  const fit = useCallback(() => {
    if (imageW && imageH) setView(fitView(imageW, imageH, stageWidth, stageHeight));
  }, [imageW, imageH, stageWidth, stageHeight]);

  const focusedBox = focused && focused.row === current
    ? boxes.find((b) => b.column === focused.column && b.index === focused.index)
    : undefined;

  // Refit on a new image or a resize; snap to the focused box when there is one.
  useEffect(() => {
    if (!imageW || !imageH) return;
    if (focusedBox && autoSnap) setView(fitView(imageW, imageH, stageWidth, stageHeight, focusedBox));
    else setView(fitView(imageW, imageH, stageWidth, stageHeight));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [current, imageW, imageH, stageWidth, stageHeight, focusedBox?.column, focusedBox?.index, autoSnap]);

  // -- editing ---------------------------------------------------------------------

  const edit = useRef<{ kind: "draw" | "move" | "resize"; handle: Handle; start: { x: number; y: number }; box: DrawnBox | null } | null>(null);
  const [draft, setDraft] = useState<number[] | null>(null);
  const [hoverHandle, setHoverHandle] = useState<Handle | null>(null);

  const predictionRefs = useCallback((which: typeof scope): PredictionRef[] => {
    if (!predicted) return [];
    const inRow = (r: number) =>
      drawnBoxes(rows[r], null, predicted, display, filterList, review(r)).map((b) => ({ row: r, index: b.index }));
    if (which === "box") {
      return focusedBox && focusedBox.column === predicted.name && current !== undefined
        ? [{ row: current, index: focusedBox.index }]
        : [];
    }
    if (which === "row") return current === undefined ? [] : inRow(current);
    if (which === "selection") return [...selectedRows].flatMap(inRow);
    return visible.flatMap(inRow);
  }, [predicted, rows, display, filterList, review, focusedBox, current, selectedRows, visible]);

  const decide = useCallback((decision: "accept" | "reject", which: typeof scope = scope) => {
    const refs = predictionRefs(which);
    const problem = reviewPredictions(refs, decision, stagedMode);
    say(problem ?? `${stagedMode ? "staged" : decision === "accept" ? "accepted" : "rejected"} ${refs.length} prediction${refs.length === 1 ? "" : "s"}`);
    return problem;
  }, [predictionRefs, reviewPredictions, stagedMode, say, scope]);

  // Keyboard review: Enter accepts, Delete removes or rejects, ctrl+c/x/v copy boxes.
  const stepRef = useRef<(delta: number) => void>(() => undefined);
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      const target = event.target as HTMLElement | null;
      if (target && /^(INPUT|TEXTAREA|SELECT)$/.test(target.tagName)) return;
      const state = useStore.getState();
      const focus = state.focusedInstance;
      const ctrl = event.ctrlKey || event.metaKey;
      if (ctrl && ["c", "x", "v"].includes(event.key.toLowerCase())) {
        const key = event.key.toLowerCase();
        const problem = key === "v"
          ? (state.selection.anchor !== null ? pasteBoxes(state.selection.anchor) : "select a row to paste into")
          : copyBox(key === "x");
        if (key === "v" || focus) {
          event.preventDefault();
          say(problem ?? (key === "v" ? "pasted" : key === "x" ? "cut" : "copied box"));
        }
        return;
      }
      if (!focus || ctrl) return;
      if (event.key === "Enter" && predicted && focus.column === predicted.name) {
        event.preventDefault();
        if (!decide("accept", "box")) stepRef.current(1);
      } else if ((event.key === "Delete" || event.key === "Backspace") && focus.column === predicted?.name) {
        event.preventDefault();
        if (!decide("reject", "box")) stepRef.current(1);
      } else if ((event.key === "Delete" || event.key === "Backspace") && focus.column === truth?.name) {
        event.preventDefault();
        const problem = deleteBoxes(focus.row, focus.column, [focus.index]);
        if (problem) say(problem);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [predicted, truth, decide, deleteBoxes, copyBox, pasteBoxes, say]);

  // -- pan and zoom --------------------------------------------------------------

  const svgRef = useRef<SVGSVGElement>(null);
  const drag = useRef<{ x: number; y: number; moved: boolean } | null>(null);
  const toImage = (clientX: number, clientY: number) => {
    const box = svgRef.current!.getBoundingClientRect();
    return { x: view.x + ((clientX - box.left) / box.width) * view.w, y: view.y + ((clientY - box.top) / box.height) * view.h };
  };
  useEffect(() => {
    const node = svgRef.current;
    if (!node) return;
    const onWheel = (event: WheelEvent) => {
      event.preventDefault();
      const box = node.getBoundingClientRect();
      const factor = Math.exp(event.deltaY * (event.deltaMode === 1 ? 0.05 : 0.0015));
      setView((v) => {
        const px = v.x + ((event.clientX - box.left) / box.width) * v.w;
        const py = v.y + ((event.clientY - box.top) / box.height) * v.h;
        const w = Math.min(Math.max(v.w * factor, 4), imageW * 8 || 1e6);
        const h = w * (v.h / v.w);
        return { x: px - ((px - v.x) * w) / v.w, y: py - ((py - v.y) * h) / v.h, w, h };
      });
    };
    node.addEventListener("wheel", onWheel, { passive: false });
    return () => node.removeEventListener("wheel", onWheel);
  }, [imageW]);

  // -- navigation ------------------------------------------------------------------

  const stepRow = (delta: number) => {
    if (position !== -1) {
      moveCursor(delta);
      return;
    }
    const target = visible[delta > 0 ? Math.min(1, visible.length - 1) : 0];
    if (target !== undefined) clickRow(target, "none");
  };

  /** Next or previous box; past the last box of an image, continue into the next row. */
  const stepBox = (delta: number) => {
    if (current === undefined) return;
    const at = focusedBox ? boxes.indexOf(focusedBox) : delta > 0 ? -1 : boxes.length;
    const next = boxes[at + delta];
    if (next) {
      focusInstance({ row: current, column: next.column, index: next.index });
      return;
    }
    const rowAt = visible.indexOf(current);
    for (let r = rowAt + delta; r >= 0 && r < visible.length; r += delta) {
      const candidate = drawnBoxes(rows[visible[r]!], truth, predicted, display, filterList, review(visible[r]!));
      if (candidate.length > 0) {
        const pick = delta > 0 ? candidate[0]! : candidate[candidate.length - 1]!;
        focusInstance({ row: visible[r]!, column: pick.column, index: pick.index });
        return;
      }
    }
  };

  stepRef.current = stepBox;

  // Classification corners: only when there are no boxes to look at.
  const hasPair = !hasBoxes && spec.labels.includes("label") && spec.labels.includes("predicted") && row;
  const agrees = hasPair ? row!.label === row!.predicted : null;
  const corner = (names: string[]) =>
    names.map((name) => {
      const column = columns.find((c) => c.name === name);
      const value = row?.[name];
      const classes = column?.kind === "categorical_label" ? column : columns.find((c) => c.name === "label");
      const shown = classes?.kind === "categorical_label" && (column?.kind === "categorical_label" || name === "predicted")
        ? className(classes, value)
        : format(value);
      return (
        <div key={name}>
          <span className="k">{columnLabel(name)}</span> <span className="v">{shown}</span>
        </div>
      );
    });

  const roles = [...new Set(boxes.map((b) => b.role))];
  const pixelated = imageW > 0 && stageWidth / view.w > 3;
  const focusedIsTruth = Boolean(focusedBox && truth && focusedBox.column === truth.name);
  const focusedIsPrediction = Boolean(focusedBox && predicted && focusedBox.column === predicted.name);

  return (
    <div className="image-chart" style={{ width, height }}>
      {hasBoxes && (
        <div className="image-chart-bar" style={{ height: TOOLBAR_H }}>
          <BoxControls />
          <span className="spacer" />
          {truthEditable && (
            <button
              className={`ic-button${editMode ? " on" : ""}`}
              onClick={() => setEditMode(!editMode)}
              title="Edit mode: drag on the image to draw a box; drag a selected box to move it, its edges or corners to resize"
            >
              <Icon name="pencil" size={13} />Edit
            </button>
          )}
          <span className="sep" />
          <button className="ic-icon" onClick={() => stepBox(-1)} title="Previous box" aria-label="Previous box"><Icon name="back" size={14} /></button>
          <button className="ic-icon" onClick={() => stepBox(1)} title="Next box (continues into the next image)" aria-label="Next box"><Icon name="chevron" size={14} /></button>
          <button className={`ic-icon${autoSnap ? " on" : ""}`} onClick={() => setAutoSnap(!autoSnap)} title="Zoom to the selected box" aria-label="Snap to box"><Icon name="target" size={15} /></button>
          <button className="ic-icon" onClick={() => { focusInstance(null); fit(); }} title="Show the whole image" aria-label="Fit image"><Icon name="fit" size={15} /></button>
        </div>
      )}
      {reviewTools && (
        <div className="image-chart-bar review-bar" style={{ height: REVIEW_H }}>
          {editMode && truthEditable && (
            <>
              <label className="control-field">
                <span>New box class</span>
                <select value={activeLabel} onChange={(e) => setDrawLabel(Number(e.target.value))}>
                  {classKeys.map((k) => <option key={k} value={k}>{className(truth!, k)}</option>)}
                </select>
              </label>
              <span className="sep" />
              <button
                className="ic-button"
                onClick={() => {
                  const targetRows = scope === "visible" ? visible : scope === "selection" ? [...selectedRows] : current === undefined ? [] : [current];
                  const { removed, error } = applyNms(targetRows, truth!.name, nmsIou);
                  say(error ?? `Removed ${removed} duplicate label${removed === 1 ? "" : "s"}`);
                }}
                title="Remove duplicate labelled boxes of the same class overlapping above this IoU, in the chosen scope"
              >
                Remove duplicates
              </button>
              <label className="control-field" title="IoU above which same-class labels count as duplicates">
                <span>IoU</span>
                <input type="number" min={0.05} max={0.95} step={0.05} value={nmsIou} className="nms-iou"
                  onChange={(e) => setNmsIou(Number(e.target.value))} onKeyDown={(e) => e.stopPropagation()} />
              </label>
            </>
          )}
          {(predicted || editMode) && (
            <label className="control-field" title="What accept, reject and duplicate removal apply to">
              <span>Apply to</span>
              <select value={scope} onChange={(e) => setScope(e.target.value as typeof scope)}>
                <option value="box">Selected box</option>
                <option value="row">This image</option>
                <option value="selection">Selected rows</option>
                <option value="visible">All visible rows</option>
              </select>
            </label>
          )}
          {predicted && (
            <>
              <button className="ic-button accept" onClick={() => decide("accept")} title="Write predictions into the labels (Enter on a selected prediction)">
                <Icon name="check" size={13} />Accept
              </button>
              <button className="ic-button reject" onClick={() => decide("reject")} title="Dismiss predictions (Delete on a selected prediction)">
                <Icon name="close" size={13} />Reject
              </button>
              <button
                className={`ic-button${stagedMode ? " on" : ""}`}
                aria-pressed={stagedMode}
                onClick={() => setStagedMode(!stagedMode)}
                title="Stage decisions for review instead of applying them now"
              >
                Stage first
              </button>
              {staged.size > 0 && (
                <>
                  <button className="ic-button primary" onClick={() => say(applyStaged() ?? "Applied staged decisions")}>Apply {staged.size}</button>
                  <button className="ic-button" onClick={clearStaged}>Discard</button>
                </>
              )}
            </>
          )}
          <span className="spacer" />
          {notice && <span className="notice">{notice}</span>}
        </div>
      )}
      {hasBoxes && labelColumn && (
        <div className="label-bar" style={{ height: LABELBAR_H }} role="group" aria-label="Show or hide classes">
          <span className="label-bar-title">Classes</span>
          {classKeys.length === 0 && Object.keys(labelColumn.value_map ?? {}).length === 0 && <span className="faint small">No classes</span>}
          {Object.keys(labelColumn.value_map ?? {}).map(Number).sort((a, b) => (inImage.get(b) ?? 0) - (inImage.get(a) ?? 0) || a - b).map((label) => {
            const count = inImage.get(label) ?? 0;
            const off = excluded.some((v) => Number(v) === label);
            return (
              <button
                key={label}
                className={`label-chip${off ? " off" : ""}${count === 0 ? " absent" : ""}`}
                onClick={(e) => toggleLabel(label, e.altKey || e.detail === 2)}
                title={`${className(labelColumn, label)}: ${count} in this image. Click to ${off ? "show" : "hide"}; double-click to show only this class.`}
                aria-pressed={!off}
              >
                <i style={{ background: display.colorBy === "class" ? classColor(labelColumn, label) : undefined }} />
                {className(labelColumn, label)}
                <span className="label-chip-count">{count}</span>
              </button>
            );
          })}
          {excluded.length > 0 && (
            <button className="label-chip reset" onClick={() => labelFilter && setFilter(labelFilter.column, { excluded: [] })}>Show all</button>
          )}
          <span className="spacer" />
          <RoleLegend roles={roles} />
        </div>
      )}
      <div className="image-chart-main">
        <svg
          ref={svgRef}
          className="image-stage"
          width={stageWidth}
          height={stageHeight}
          viewBox={`${view.x} ${view.y} ${view.w} ${view.h}`}
          preserveAspectRatio="xMidYMid meet"
          onPointerDown={(e) => {
            (e.currentTarget as SVGSVGElement).setPointerCapture(e.pointerId);
            const point = toImage(e.clientX, e.clientY);
            if (editMode && truthEditable && current !== undefined && truth) {
              const tolerance = 6 * (view.w / stageWidth);
              const target = focusedBox && focusedBox.column === truth.name ? focusedBox : undefined;
              const handle = target ? handleAt(target, point, tolerance) : null;
              if (target && handle) {
                edit.current = { kind: handle === "move" ? "move" : "resize", handle, start: point, box: target };
                setDraft([target.x0, target.y0, target.x1, target.y1]);
                return;
              }
              const hit = [...boxes].reverse().find((b) => point.x >= b.x0 && point.x <= b.x1 && point.y >= b.y0 && point.y <= b.y1);
              if (!hit) {
                edit.current = { kind: "draw", handle: "se", start: point, box: null };
                setDraft([point.x, point.y, point.x, point.y]);
                return;
              }
            }
            drag.current = { x: e.clientX, y: e.clientY, moved: false };
          }}
          onPointerMove={(e) => {
            const active = edit.current;
            if (active) {
              const point = toImage(e.clientX, e.clientY);
              setDraft(dragVertices(active, point));
              return;
            }
            const d = drag.current;
            if (!d) {
              if (editMode && focusedBox && truth && focusedBox.column === truth.name) {
                const handle = handleAt(focusedBox, toImage(e.clientX, e.clientY), 6 * (view.w / stageWidth));
                setHoverHandle(handle);
              }
              return;
            }
            const dx = e.clientX - d.x;
            const dy = e.clientY - d.y;
            if (Math.abs(dx) + Math.abs(dy) > 2) d.moved = true;
            if (!d.moved) return;
            const box = svgRef.current!.getBoundingClientRect();
            setView((v) => ({ ...v, x: v.x - (dx / box.width) * v.w, y: v.y - (dy / box.height) * v.h }));
            d.x = e.clientX;
            d.y = e.clientY;
          }}
          onPointerUp={(e) => {
            const active = edit.current;
            if (active && current !== undefined && truth) {
              edit.current = null;
              const vertices = dragVertices(active, toImage(e.clientX, e.clientY));
              setDraft(null);
              let problem: string | null = null;
              if (active.kind === "draw") {
                problem = addBox(current, truth.name, vertices, activeLabel);
                if (!problem) {
                  const count = asBoxValue(useStore.getState().rows[current]?.[truth.name])?.instances.length ?? 0;
                  focusInstance({ row: current, column: truth.name, index: count - 1 });
                }
                else if (problem === "box is too small") problem = null; // a click, not a drag
              } else if (active.box) {
                const [x0, y0, x1, y1] = vertices;
                const moved = Math.abs(x0! - active.box.x0) + Math.abs(y0! - active.box.y0) + Math.abs(x1! - active.box.x1) + Math.abs(y1! - active.box.y1);
                if (moved > 0.5) problem = updateBox(current, truth.name, active.box.index, { vertices });
              }
              if (problem) say(problem);
              return;
            }
            const d = drag.current;
            drag.current = null;
            if (d && !d.moved) {
              // A click on empty image clears the box focus; clicks on boxes focus them.
              const { x, y } = toImage(e.clientX, e.clientY);
              const hit = [...boxes].reverse().find((b) => x >= b.x0 && x <= b.x1 && y >= b.y0 && y <= b.y1);
              if (hit && current !== undefined) focusInstance({ row: current, column: hit.column, index: hit.index });
              else if (focused) focusInstance(null);
            }
          }}
          style={{ cursor: edit.current ? "crosshair" : editMode ? (hoverHandle ? HANDLE_CURSOR[hoverHandle] : "crosshair") : undefined }}
        >
          {source && imageW > 0 && (
            <image
              href={api.mediaUrl(source, undefined, project ?? undefined)}
              x={0} y={0} width={imageW} height={imageH}
              preserveAspectRatio="none"
              style={{ imageRendering: pixelated ? "pixelated" : "auto" }}
            />
          )}
          {hasBoxes && (
            <BoxShapes
              boxes={boxes}
              annotate={display.annotate}
              focused={focusedBox ? { column: focusedBox.column, index: focusedBox.index } : null}
              hovered={hovered}
              fontSize={Math.max(10, view.h * 0.03)}
            />
          )}
          {draft && (
            <rect
              className="box-draft"
              x={Math.min(draft[0]!, draft[2]!)} y={Math.min(draft[1]!, draft[3]!)}
              width={Math.abs(draft[2]! - draft[0]!)} height={Math.abs(draft[3]! - draft[1]!)}
              vectorEffect="non-scaling-stroke"
            />
          )}
        </svg>
        {hasBoxes && focusedBox && current !== undefined && (
          <div className="box-card" role="dialog" aria-label="Selected box">
            <span className="box-card-swatch" style={{ borderColor: focusedBox.color, borderStyle: focusedBox.dash ? "dashed" : "solid" }} />
            {focusedIsTruth && truthEditable ? (
              <select
                value={focusedBox.label ?? 0}
                onChange={(e) => { const p = updateBox(current, truth!.name, focusedBox.index, { label: Number(e.target.value) }); if (p) say(p); }}
                aria-label="Class"
              >
                {classKeys.map((k) => <option key={k} value={k}>{className(truth!, k)}</option>)}
              </select>
            ) : (
              <span className="box-card-name">{focusedBox.text.split(" · ")[0]!.replace(/ [0-9.]+$/, "")}</span>
            )}
            {focusedBox.confidence !== null && <span className="box-card-stat">conf {focusedBox.confidence.toFixed(2)}</span>}
            {focusedBox.iou !== null && <span className="box-card-stat">IoU {focusedBox.iou.toFixed(2)}</span>}
            {focusedIsTruth && truthEditable && (
              <button className="ic-icon" onClick={() => { const p = deleteBoxes(current, truth!.name, [focusedBox.index]); if (p) say(p); }} title="Delete box (Delete)" aria-label="Delete box">
                <Icon name="close" size={14} />
              </button>
            )}
            {focusedIsPrediction && (
              <>
                <button className="ic-icon" onClick={() => { const p = reviewPredictions([{ row: current, index: focusedBox.index }], "accept", stagedMode); if (p) say(p); }} title="Accept into labels" aria-label="Accept"><Icon name="check" size={14} /></button>
                <button className="ic-icon" onClick={() => { const p = reviewPredictions([{ row: current, index: focusedBox.index }], "reject", stagedMode); if (p) say(p); }} title="Reject" aria-label="Reject"><Icon name="close" size={14} /></button>
              </>
            )}
          </div>
        )}
      </div>

      {row === undefined && <div className="empty"><div>No visible rows</div></div>}
      {failed && <div className="empty"><div>Could not load {source}</div></div>}
      {row && !hasBoxes && (
        <>
          <div className="corner tl">{corner(spec.labels.slice(0, 2))}</div>
          <div className="corner tr">
            {corner(spec.labels.slice(2))}
            {agrees !== null && (
              <div className={agrees ? "agree" : "disagree"}>
                {agrees ? "✓ prediction matches label" : "✗ prediction differs from label"}
              </div>
            )}
          </div>
        </>
      )}
      {row && (
        <div className="corner bl">
          <button className="ic-icon" onClick={() => stepRow(-1)} title="Previous image (↑)" aria-label="Previous image"><Icon name="back" size={14} /></button>
          <span className="ic-nav-text">
            <span className="ic-nav-file" title={source ?? ""}>{source ? source.slice(source.lastIndexOf("/") + 1) : `row ${current}`}</span>
            <span className="ic-nav-pos">{(Math.max(position, 0) + 1).toLocaleString()} / {visible.length.toLocaleString()}</span>
          </span>
          <button className="ic-icon" onClick={() => stepRow(1)} title="Next image (↓)" aria-label="Next image"><Icon name="chevron" size={14} /></button>
        </div>
      )}
    </div>
  );
}
