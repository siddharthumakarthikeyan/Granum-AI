/** A 2D scatter on deck.gl, with selection tools that write region filters.
 *
 * deck.gl only draws and picks. Pan, zoom and every selection gesture are handled here
 * on one overlay, so the projection used to turn a lasso into data coordinates is the
 * same code that drew the axes -- no second source of truth to drift out of sync.
 *
 * Point buffers are rebuilt only when their inputs change: positions when the axes do,
 * colours when filters or the colour column do. A selection click touches neither.
 */

import { OrthographicView } from "@deck.gl/core";
import { DataFilterExtension } from "@deck.gl/extensions";
import { ScatterplotLayer } from "@deck.gl/layers";
import DeckGL, { type DeckGLRef } from "@deck.gl/react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { ColumnInfo } from "../api/types";
import { drawMask, extent, FILTERED_OUT, HIDDEN, numericVector, SHOWN } from "../store/derive";
import { cellValue, isNumericColumn, regionFilterKey } from "../store/filtering";
import { ellipsePolygon, simplifyPath } from "../store/geometry";
import { className } from "../store/editing";
import { useStore, type RegionMode } from "../store/store";
import { ROW_INDEX, type Point } from "../store/types";
import {
  categories, css, CATEGORICAL, defaultSlots, OTHER, pointColors, SELECTED,
  SEQUENTIAL_CSS, toggleSlot, type ColorMode,
} from "./colors";
import {
  dataToScreen, fitView, formatTick, niceTicks, normalise, screenToData,
  type Frame, type ViewState,
} from "./projection";
import type { ScatterSpec, Tool } from "./spec";

const MAX_CATEGORIES = 12;

/** The distinct values of a column, or null as soon as there are more than `limit`. */
function distinctUpTo(rows: { [key: string]: unknown }[], column: string, limit: number): Set<unknown> | null {
  const seen = new Set<unknown>();
  for (const row of rows) {
    seen.add(row[column]);
    if (seen.size > limit) return null;
  }
  return seen;
}

const MARGIN = { left: 48, bottom: 26, top: 8, right: 10 };
const BRUSH_RADIUS = 14;
const VIEW = new OrthographicView({ id: "plot", flipY: false });
/** GPU-side visibility. Hidden points must be removed, not just made transparent: a
 * transparent or zero-radius point is still drawn into the picking buffer, so it could
 * be hovered and clicked -- selecting a row the filters say is not there. */
const VISIBILITY = [new DataFilterExtension({ filterSize: 1 })];

function modeFor(event: { ctrlKey: boolean; metaKey: boolean; shiftKey: boolean }): RegionMode {
  if (event.shiftKey) return "subtract";
  if (event.ctrlKey || event.metaKey) return "add";
  return "replace";
}

interface Props {
  spec: ScatterSpec;
  width: number;
  height: number;
  tool: Tool;
}

export function ScatterChart({ spec, width, height, tool }: Props) {
  const rows = useStore((s) => s.rows);
  const columns = useStore((s) => s.columns);
  const filters = useStore((s) => s.filters);
  const selection = useStore((s) => s.selection);
  const clickRow = useStore((s) => s.clickRow);
  const applyRegion = useStore((s) => s.applyRegion);
  const updateChart = useStore((s) => s.updateChart);

  const plotWidth = Math.max(40, width - MARGIN.left - MARGIN.right);
  const plotHeight = Math.max(40, height - MARGIN.top - MARGIN.bottom);
  const n = rows.length;

  // -- data -----------------------------------------------------------------

  const xs = useMemo(() => numericVector(rows, spec.x), [rows, spec.x]);
  const ys = useMemo(() => numericVector(rows, spec.y), [rows, spec.y]);
  const xDomain = useMemo(() => extent(xs), [xs]);
  const yDomain = useMemo(() => extent(ys), [ys]);

  const positions = useMemo(() => {
    const out = new Float32Array(n * 3);
    for (let i = 0; i < n; i += 1) {
      out[i * 3] = normalise(xs[i]!, xDomain);
      out[i * 3 + 1] = normalise(ys[i]!, yDomain);
    }
    return out;
  }, [n, xs, ys, xDomain, yDomain]);

  const baseMask = drawMask(rows, filters);
  const mask = useMemo(() => {
    if (!spec.showFilteredOut) return baseMask;
    const out = baseMask.slice();
    for (let i = 0; i < out.length; i += 1) if (out[i] === HIDDEN) out[i] = FILTERED_OUT;
    return out;
  }, [baseMask, spec.showFilteredOut]);

  const colorColumn: ColumnInfo | undefined = columns.find((c) => c.name === spec.color);

  // A numeric column with a handful of distinct values (a class index, an epoch) reads
  // better as categories than as a ramp.
  const { colorIsNumeric, colorValues } = useMemo(() => {
    if (!spec.color || !colorColumn) return { colorIsNumeric: false, colorValues: [] };
    const few = distinctUpTo(rows, spec.color, MAX_CATEGORIES);
    const numeric = isNumericColumn(colorColumn) && few === null;
    return {
      colorIsNumeric: numeric,
      colorValues: numeric ? [] : categories(rows, spec.color),
    };
  }, [rows, spec.color, colorColumn]);
  const slots = useMemo(
    () => spec.slots ?? defaultSlots(colorValues),
    [spec.slots, colorValues],
  );

  const colorMode: ColorMode = useMemo(() => {
    if (!spec.color) return { kind: "none" };
    if (colorIsNumeric) {
      const values = numericVector(rows, spec.color);
      return { kind: "numeric", values, range: extent(values) };
    }
    return { kind: "categorical", column: spec.color, slots };
  }, [rows, spec.color, colorIsNumeric, slots]);

  const colors = useMemo(() => pointColors(rows, mask, colorMode), [rows, mask, colorMode]);

  const radii = useMemo(() => {
    const out = new Float32Array(n);
    const sizeValues = spec.size ? numericVector(rows, spec.size) : null;
    const [lo, hi] = sizeValues ? extent(sizeValues) : [0, 1];
    for (let i = 0; i < n; i += 1) {
      const t = sizeValues ? (sizeValues[i]! - lo) / (hi - lo || 1) : 0.5;
      out[i] = sizeValues ? spec.pointSize * (0.4 + 1.6 * (Number.isFinite(t) ? t : 0)) : spec.pointSize;
    }
    return out;
  }, [n, rows, spec.size, spec.pointSize]);

  const visibility = useMemo(() => {
    const out = new Float32Array(n);
    for (let i = 0; i < n; i += 1) {
      if (mask[i] !== HIDDEN && Number.isFinite(xs[i]!) && Number.isFinite(ys[i]!)) out[i] = 1;
    }
    return out;
  }, [n, mask, xs, ys]);

  const selectedIndices = useMemo(
    () => [...selection.rows].filter((i) => i < n && mask[i] !== HIDDEN),
    [selection.rows, n, mask],
  );

  // -- view -----------------------------------------------------------------

  const [view, setView] = useState<ViewState>(() => fitView(plotWidth, plotHeight));
  const fittedFor = useRef("");
  useEffect(() => {
    // Refit when the axes change or the chart first gets a real size.
    const key = `${spec.x}|${spec.y}`;
    if (fittedFor.current !== key) {
      fittedFor.current = key;
      setView(fitView(plotWidth, plotHeight));
    }
  }, [spec.x, spec.y, plotWidth, plotHeight]);

  const lastSize = useRef([plotWidth, plotHeight]);
  useEffect(() => {
    // Keep the same data box in view when the panel is resized.
    const [w0, h0] = lastSize.current;
    lastSize.current = [plotWidth, plotHeight];
    if (w0 === plotWidth && h0 === plotHeight) return;
    setView((v) => ({
      ...v,
      zoomX: v.zoomX + Math.log2(plotWidth / Math.max(1, w0!)),
      zoomY: v.zoomY + Math.log2(plotHeight / Math.max(1, h0!)),
    }));
  }, [plotWidth, plotHeight]);

  const frame: Frame = { width: plotWidth, height: plotHeight, xDomain, yDomain, view };

  const snapToContents = useCallback(() => {
    let x0 = Infinity, x1 = -Infinity, y0 = Infinity, y1 = -Infinity;
    for (let i = 0; i < n; i += 1) {
      if (mask[i] !== SHOWN) continue;
      const px = positions[i * 3]!;
      const py = positions[i * 3 + 1]!;
      if (!Number.isFinite(px) || !Number.isFinite(py)) continue;
      if (px < x0) x0 = px;
      if (px > x1) x1 = px;
      if (py < y0) y0 = py;
      if (py > y1) y1 = py;
    }
    setView(x0 === Infinity ? fitView(plotWidth, plotHeight) : fitView(plotWidth, plotHeight, { x0, x1, y0, y1 }));
  }, [n, mask, positions, plotWidth, plotHeight]);

  // The chart header triggers this through a DOM event, keeping the header stateless.
  const rootRef = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const node = rootRef.current;
    if (!node) return;
    const onSnap = () => snapToContents();
    node.addEventListener("granum:snap", onSnap);
    return () => node.removeEventListener("granum:snap", onSnap);
  }, [snapToContents]);

  // -- layers ---------------------------------------------------------------

  const layers = useMemo(() => {
    const points = new ScatterplotLayer({
      id: "points",
      data: {
        length: n,
        attributes: {
          getPosition: { value: positions, size: 3 },
          getFillColor: { value: colors, size: 4, normalized: true },
          getRadius: { value: radii, size: 1 },
          getFilterValue: { value: visibility, size: 1 },
        },
      },
      radiusUnits: "pixels",
      pickable: true,
      stroked: false,
      extensions: VISIBILITY,
      filterRange: [0.5, 1.5],
    });

    const selectedPositions = new Float32Array(selectedIndices.length * 3);
    const selectedRadii = new Float32Array(selectedIndices.length);
    selectedIndices.forEach((row, i) => {
      selectedPositions[i * 3] = positions[row * 3]!;
      selectedPositions[i * 3 + 1] = positions[row * 3 + 1]!;
      selectedRadii[i] = Math.max(radii[row]!, spec.pointSize) + 2.5;
    });
    const ring = new ScatterplotLayer({
      id: "selected",
      data: {
        length: selectedIndices.length,
        attributes: {
          getPosition: { value: selectedPositions, size: 3 },
          getRadius: { value: selectedRadii, size: 1 },
        },
      },
      radiusUnits: "pixels",
      filled: false,
      stroked: true,
      lineWidthUnits: "pixels",
      getLineWidth: 1.5,
      getLineColor: [...SELECTED, 255],
      pickable: false,
    });
    return [points, ring];
  }, [n, positions, colors, radii, visibility, selectedIndices, spec.pointSize]);

  // -- interaction ----------------------------------------------------------

  const deckRef = useRef<DeckGLRef>(null);
  const overlayRef = useRef<HTMLDivElement>(null);
  const [draft, setDraft] = useState<Point[] | null>(null); // screen coordinates
  const [dabs, setDabs] = useState<Point[]>([]); // brush centres, screen coordinates
  const [hover, setHover] = useState<{ index: number; x: number; y: number } | null>(null);
  const gesture = useRef<{ kind: Tool; start: Point; moved: boolean; last: Point } | null>(null);
  const hoverFrame = useRef(0);
  const hoverToken = useRef(0);

  const local = (event: { clientX: number; clientY: number }): Point => {
    const box = overlayRef.current!.getBoundingClientRect();
    return [event.clientX - box.left, event.clientY - box.top];
  };

  const commit = useCallback(
    (polygonsOnScreen: Point[][], mode: RegionMode) => {
      const inData = polygonsOnScreen.map((poly) => poly.map(([sx, sy]) => screenToData(frame, sx, sy)));
      applyRegion(spec.x, spec.y, inData, mode);
    },
    // frame is rebuilt each render from these inputs
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [applyRegion, spec.x, spec.y, view, plotWidth, plotHeight, xDomain, yDomain],
  );

  const onPointerDown = (event: React.PointerEvent) => {
    if (spec.locked || event.button !== 0) return;
    const at = local(event);
    overlayRef.current!.setPointerCapture(event.pointerId);
    if (tool === "polygon") return; // polygon works on clicks, handled in onClick
    gesture.current = { kind: tool, start: at, moved: false, last: at };
    if (tool === "rect" || tool === "lasso") setDraft([at]);
    if (tool === "brush") setDabs([at]);
  };

  const onPointerMove = (event: React.PointerEvent) => {
    const at = local(event);
    const g = gesture.current;

    if (!g) {
      if (tool === "polygon" && draft) setDraft((d) => (d ? [...d.slice(0, -1), at] : d));
      cancelAnimationFrame(hoverFrame.current);
      hoverFrame.current = requestAnimationFrame(() => {
        // Async picking: a synchronous readPixels on every mouse move stalls the GPU.
        const token = ++hoverToken.current;
        void deckRef.current?.pickObjectAsync({ x: at[0], y: at[1], radius: 3 }).then((picked) => {
          if (token !== hoverToken.current || gesture.current) return;
          setHover(picked && picked.index >= 0 ? { index: picked.index, x: at[0], y: at[1] } : null);
        });
      });
      return;
    }

    const distance = Math.hypot(at[0] - g.start[0], at[1] - g.start[1]);
    if (distance > 3) g.moved = true;
    setHover(null);

    if (g.kind === "pan") {
      const dx = at[0] - g.last[0];
      const dy = at[1] - g.last[1];
      setView((v) => ({
        ...v,
        target: [v.target[0] - dx / 2 ** v.zoomX, v.target[1] + dy / 2 ** v.zoomY],
      }));
    } else if (g.kind === "rect") {
      setDraft([g.start, [at[0], g.start[1]], at, [g.start[0], at[1]]]);
    } else if (g.kind === "lasso") {
      setDraft((d) => (d ? [...d, at] : [at]));
    } else if (g.kind === "brush") {
      const lastDab = dabs[dabs.length - 1];
      if (!lastDab || Math.hypot(at[0] - lastDab[0], at[1] - lastDab[1]) > BRUSH_RADIUS / 2) {
        setDabs((d) => [...d, at]);
      }
    }
    g.last = at;
  };

  const onPointerUp = (event: React.PointerEvent) => {
    const g = gesture.current;
    gesture.current = null;
    if (!g) return;
    const mode = modeFor(event);

    if (g.kind === "pan") {
      if (!g.moved) {
        const picked = deckRef.current?.pickObject({ x: g.start[0], y: g.start[1], radius: 4 });
        if (picked && picked.index >= 0) {
          clickRow(picked.index, event.ctrlKey || event.metaKey ? "ctrl" : event.shiftKey ? "shift" : "none");
        }
      }
      return;
    }
    if (g.kind === "rect" && draft && g.moved) commit([draft], mode);
    if (g.kind === "lasso" && draft && draft.length >= 3) commit([simplifyPath(draft, 3)], mode);
    if (g.kind === "brush") {
      commit(dabs.map(([x, y]) => ellipsePolygon(x, y, BRUSH_RADIUS, BRUSH_RADIUS)), mode);
    }
    setDraft(null);
    setDabs([]);
  };

  const onClick = (event: React.MouseEvent) => {
    if (tool !== "polygon" || spec.locked) return;
    const at = local(event);
    if (!draft) {
      setDraft([at, at]);
      return;
    }
    const vertices = draft.slice(0, -1);
    const first = vertices[0]!;
    const closes = vertices.length >= 3 && Math.hypot(at[0] - first[0], at[1] - first[1]) < 8;
    if (closes || event.detail >= 2) {
      if (vertices.length >= 3) commit([vertices], modeFor(event));
      setDraft(null);
      return;
    }
    setDraft([...vertices, at, at]);
  };

  // Escape abandons a half-drawn polygon before it reaches the global handler, which
  // would otherwise clear the row selection too.
  useEffect(() => {
    if (!draft || tool !== "polygon") return;
    const onKey = (event: KeyboardEvent) => {
      if (event.key !== "Escape") return;
      event.stopImmediatePropagation();
      setDraft(null);
    };
    window.addEventListener("keydown", onKey, true);
    return () => window.removeEventListener("keydown", onKey, true);
  }, [draft, tool]);

  useEffect(() => {
    setDraft(null);
    setDabs([]);
  }, [tool]);

  const onWheel = useCallback(
    (event: WheelEvent) => {
      if (spec.locked) return;
      event.preventDefault();
      const box = overlayRef.current!.getBoundingClientRect();
      const sx = event.clientX - box.left;
      const sy = event.clientY - box.top;
      const step = -event.deltaY * (event.deltaMode === 1 ? 0.05 : 0.0015);
      const zoomX = !event.altKey;
      const zoomY = !event.shiftKey;
      setView((v) => {
        const nx = v.target[0] + (sx - plotWidth / 2) / 2 ** v.zoomX;
        const ny = v.target[1] - (sy - plotHeight / 2) / 2 ** v.zoomY;
        const zx = zoomX ? v.zoomX + step : v.zoomX;
        const zy = zoomY ? v.zoomY + step : v.zoomY;
        return {
          zoomX: zx,
          zoomY: zy,
          target: [nx - (sx - plotWidth / 2) / 2 ** zx, ny + (sy - plotHeight / 2) / 2 ** zy],
        };
      });
    },
    [spec.locked, plotWidth, plotHeight],
  );
  useEffect(() => {
    const node = overlayRef.current;
    if (!node) return;
    node.addEventListener("wheel", onWheel, { passive: false });
    return () => node.removeEventListener("wheel", onWheel);
  }, [onWheel]);

  // -- axes -----------------------------------------------------------------

  const [left, bottom] = screenToData(frame, 0, plotHeight);
  const [right, top] = screenToData(frame, plotWidth, 0);
  const xTicks = niceTicks(left, right, Math.max(2, Math.floor(plotWidth / 90)));
  const yTicks = niceTicks(bottom, top, Math.max(2, Math.floor(plotHeight / 50)));

  const regionKey = regionFilterKey(spec.x, spec.y);
  const regions = filters[regionKey]?.kind === "region" ? filters[regionKey].regions : [];

  const cursor = spec.locked ? "default" : tool === "pan" ? (hover ? "pointer" : "grab") : "crosshair";

  return (
    <div className="scatter" ref={rootRef} style={{ width, height }}>
      <svg className="axes" width={width} height={height}>
        <g transform={`translate(${MARGIN.left},${MARGIN.top})`}>
          {xTicks.map((t) => {
            const [sx] = dataToScreen(frame, t, 0);
            return (
              <g key={`x${t}`} transform={`translate(${sx},0)`}>
                <line className="gridline" y1={0} y2={plotHeight} />
                <text className="tick" y={plotHeight + 14} textAnchor="middle">{formatTick(t)}</text>
              </g>
            );
          })}
          {yTicks.map((t) => {
            const [, sy] = dataToScreen(frame, 0, t);
            return (
              <g key={`y${t}`} transform={`translate(0,${sy})`}>
                <line className="gridline" x1={0} x2={plotWidth} />
                <text className="tick" x={-6} dy="0.32em" textAnchor="end">{formatTick(t)}</text>
              </g>
            );
          })}
          <rect className="frame" width={plotWidth} height={plotHeight} />
        </g>
        <text className="axis-name" x={MARGIN.left + plotWidth} y={height - 2} textAnchor="end">
          {spec.x === ROW_INDEX ? "row" : spec.x}
        </text>
        <text className="axis-name" transform={`translate(11,${MARGIN.top}) rotate(-90)`} textAnchor="end">
          {spec.y}
        </text>
      </svg>

      <div
        className="plot"
        style={{ left: MARGIN.left, top: MARGIN.top, width: plotWidth, height: plotHeight }}
      >
        <DeckGL
          ref={deckRef}
          views={VIEW}
          viewState={{ target: [view.target[0], view.target[1], 0], zoomX: view.zoomX, zoomY: view.zoomY }}
          controller={false}
          layers={layers}
          width={plotWidth}
          height={plotHeight}
          style={{ position: "absolute", left: "0", top: "0" }}
          getCursor={() => cursor}
        />

        <svg className="regions" width={plotWidth} height={plotHeight}>
          {regions.map((region, i) => (
            <polygon
              key={i}
              className={region.mode === "add" ? "region add" : "region subtract"}
              points={region.polygon.map(([x, y]) => dataToScreen(frame, x, y).join(",")).join(" ")}
            />
          ))}
          {draft && <polygon className="region draft" points={draft.map((p) => p.join(",")).join(" ")} />}
          {dabs.map(([x, y], i) => (
            <circle key={i} className="region draft" cx={x} cy={y} r={BRUSH_RADIUS} />
          ))}
        </svg>

        <div
          ref={overlayRef}
          className="interaction"
          style={{ cursor }}
          onPointerDown={onPointerDown}
          onPointerMove={onPointerMove}
          onPointerUp={onPointerUp}
          onPointerLeave={() => setHover(null)}
          onClick={onClick}
        />

        {hover && !gesture.current && (
          <Tooltip index={hover.index} x={hover.x} y={hover.y} spec={spec} maxX={plotWidth} />
        )}

        {spec.color && (
          <Legend
            spec={spec}
            numeric={colorMode.kind === "numeric" ? (colorMode as { range: [number, number] }).range : null}
            values={colorValues}
            slots={slots}
            mask={mask}
            onToggle={(value) => updateChart(spec.id, { slots: toggleSlot(slots, value) })}
          />
        )}
      </div>
    </div>
  );
}

function Tooltip({ index, x, y, spec, maxX }: { index: number; x: number; y: number; spec: ScatterSpec; maxX: number }) {
  const row = useStore((s) => s.rows[index]);
  if (!row) return null;
  const names = [spec.x, spec.y, spec.color, spec.size].filter(
    (c, i, all): c is string => c !== null && all.indexOf(c) === i,
  );
  const format = (value: unknown) =>
    typeof value === "number" && !Number.isInteger(value) ? value.toFixed(4) : String(value);
  const flip = x > maxX - 170;
  return (
    <div className="chart-tooltip" style={{ left: flip ? undefined : x + 12, right: flip ? maxX - x + 12 : undefined, top: y + 12 }}>
      <div className="k">row {index}</div>
      {names.map((name) => (
        <div key={name}>
          <span className="k">{name === ROW_INDEX ? "row" : name}</span>{" "}
          <span className="v">{format(cellValue(row, name, index))}</span>
        </div>
      ))}
    </div>
  );
}

interface LegendProps {
  spec: ScatterSpec;
  numeric: [number, number] | null;
  values: (string | number)[];
  slots: (string | number | null)[];
  mask: Uint8Array;
  onToggle: (value: string | number) => void;
}

function Legend({ spec, numeric, values, slots, mask, onToggle }: LegendProps) {
  const rows = useStore((s) => s.rows);
  const colorColumn = useStore((s) => s.columns.find((c) => c.name === spec.color));
  const counts = useMemo(() => {
    const out = new Map<string, number>();
    if (numeric || !spec.color) return out;
    for (let i = 0; i < rows.length; i += 1) {
      if (mask[i] !== SHOWN) continue;
      const key = String(rows[i]![spec.color]);
      out.set(key, (out.get(key) ?? 0) + 1);
    }
    return out;
  }, [rows, mask, spec.color, numeric]);

  if (numeric) {
    return (
      <div className="legend">
        <div className="legend-title">{spec.color}</div>
        <div className="ramp" style={{ background: SEQUENTIAL_CSS }} />
        <div className="ramp-labels">
          <span>{formatTick(numeric[0])}</span>
          <span>{formatTick(numeric[1])}</span>
        </div>
      </div>
    );
  }

  return (
    <div className="legend">
      <div className="legend-title" title="Click a value to give it a colour, or return it to grey">
        {spec.color}
      </div>
      <div className="legend-items">
        {values.slice(0, 60).map((value) => {
          const slot = slots.indexOf(value);
          const color = slot === -1 ? OTHER : CATEGORICAL[slot]!;
          return (
            <button key={String(value)} className={`legend-item${slot === -1 ? " other" : ""}`} onClick={() => onToggle(value)}>
              <span className="swatch" style={{ background: css(color) }} />
              <span className="name">{colorColumn?.kind === "categorical_label" ? className(colorColumn, value) : String(value)}</span>
              <span className="n">{(counts.get(String(value)) ?? 0).toLocaleString()}</span>
            </button>
          );
        })}
        {values.length > 60 && <div className="legend-more">+{values.length - 60} more</div>}
      </div>
    </div>
  );
}
