import { useEffect, useMemo, useRef, useState } from "react";
import { COORDINATE_SYSTEM, OrbitView } from "@deck.gl/core";
import { LineLayer, ScatterplotLayer } from "@deck.gl/layers";
import DeckGL, { type DeckGLRef } from "@deck.gl/react";
import { drawMask, extent, FILTERED_OUT, HIDDEN, numericVector } from "../store/derive";
import { isNumericColumn } from "../store/filtering";
import { useStore } from "../store/store";
import { categories, defaultSlots, pointColors, SELECTED, type ColorMode } from "./colors";
import { simplifyPath } from "../store/geometry";
import type { Point } from "../store/types";
import type { ScatterSpec, Tool } from "./spec";
import { trajectoryEdges } from "./trajectories";
import { spatialHits } from "./spatialSelection";

const view = new OrbitView({ id: "orbit", orbitAxis: "Y" });
const initial = { target: [0, 0, 0] as [number, number, number], rotationX: 20, rotationOrbit: 30, zoom: 0 };

export function Scatter3D({ spec, width, height, tool }: { spec: ScatterSpec; width: number; height: number; tool: Tool }) {
  const rows = useStore(s => s.rows);
  const columns = useStore(s => s.columns);
  const filters = useStore(s => s.filters);
  const filterBasis = useStore(s => s.filterBasis);
  const live = useStore(s => s.liveFilters);
  const selection = useStore(s => s.selection.rows);
  const clickRow = useStore(s => s.clickRow);
  const [camera, setCamera] = useState(initial);
  const [draft, setDraft] = useState<Point[]>([]);
  const path = useRef<Point[]>([]);
  const dragging = useRef(false);
  const modifier = useRef<"replace" | "add" | "subtract">("replace");
  const deckRef = useRef<DeckGLRef>(null);
  const host = useRef<HTMLDivElement>(null);
  useEffect(() => {
    setCamera(initial);
  }, [spec.x, spec.y, spec.z]);
  useEffect(() => { path.current = []; setDraft([]); dragging.current = false; }, [tool, spec.x, spec.y, spec.z, rows]);
  useEffect(() => {
    const element = host.current;
    const reset = () => setCamera(initial);
    element?.addEventListener("granum:snap", reset);
    return () => element?.removeEventListener("granum:snap", reset);
  }, []);
  const data = useMemo(() => {
    const mask = drawMask(live || filterBasis.length !== rows.length ? rows : filterBasis, filters).slice();
    if (spec.showFilteredOut) for (let i = 0; i < mask.length; i++) if (mask[i] === HIDDEN) mask[i] = FILTERED_OUT;
    const axes = [spec.x, spec.y, spec.z!].map(name => numericVector(rows, name));
    const bounds = axes.map(values => extent(values));
    // One common scale preserves the geometry of the reduced embedding.
    const span = Math.max(...bounds.map(([lo, hi]) => hi - lo), 1e-12);
    const colorColumn = columns.find(c => c.name === spec.color);
    const mode: ColorMode = !colorColumn ? { kind: "none" }
      : isNumericColumn(colorColumn) ? { kind: "numeric", values: numericVector(rows, colorColumn.name), range: extent(numericVector(rows, colorColumn.name)) }
        : { kind: "categorical", column: colorColumn.name, slots: spec.slots ?? defaultSlots(categories(rows, colorColumn.name)) };
    const colors = pointColors(rows, mask, mode);
    const sizes = spec.size ? numericVector(rows, spec.size) : null;
    const [lo, hi] = sizes ? extent(sizes) : [0, 1];
    return rows.flatMap((_row, i) => {
      if (mask[i] === HIDDEN || axes.some(axis => !Number.isFinite(axis[i]))) return [];
      const position = axes.map((axis, at) => (axis[i]! - (bounds[at]![0] + bounds[at]![1]) / 2) / span * 240) as [number, number, number];
      const t = sizes ? (sizes[i]! - lo) / (hi - lo || 1) : 0;
      const radius = sizes ? spec.pointSize * (.4 + 1.6 * (Number.isFinite(t) ? t : 0)) : spec.pointSize;
      return [{ index: i, position, radius, color: [...colors.slice(i * 4, i * 4 + 4)] as [number, number, number, number] }];
    });
  }, [rows, columns, filters, filterBasis, live, spec.x, spec.y, spec.z, spec.color, spec.slots, spec.showFilteredOut, spec.size, spec.pointSize]);
  const edges = useMemo(() => trajectoryEdges(rows, spec), [rows, spec.trajectory]);
  const lines = useMemo(() => {
    const byIndex = new Map(data.map(point => [point.index, point]));
    return edges.flatMap(([a, b]) => {
      const start = byIndex.get(a), end = byIndex.get(b);
      return start && end ? [{ start, end }] : [];
    });
  }, [edges, data]);
  const finish = () => {
    const viewport = deckRef.current?.deck?.getViewports()[0];
    if (viewport && !spec.locked) {
      const hits = spatialHits(data.map(d => ({ index: d.index, screen: viewport.project(d.position) })), path.current, tool);
      const state = useStore.getState();
      const selected = modifier.current === "replace" ? new Set<number>() : new Set(state.selection.rows);
      for (const hit of hits) { if (modifier.current === "subtract") selected.delete(hit); else selected.add(hit); }
      useStore.setState({ selection: { ...state.selection, rows: selected, elements: new Map(), anchor: hits[0] ?? null } });
    }
    path.current = []; setDraft([]); dragging.current = false;
  };
  const finishRef = useRef(finish); finishRef.current = finish;
  useEffect(() => {
    const key = (event: KeyboardEvent) => {
      if (!path.current.length || /INPUT|TEXTAREA|SELECT/.test((event.target as HTMLElement)?.tagName)) return;
      if (event.key === "Escape") { path.current = []; setDraft([]); dragging.current = false; }
      if (event.key === "Enter" && tool === "polygon") { event.preventDefault(); finishRef.current(); }
    };
    window.addEventListener("keydown", key);
    return () => window.removeEventListener("keydown", key);
  }, [tool]);
  const point = (event: React.PointerEvent<SVGSVGElement>): Point => {
    const box = event.currentTarget.getBoundingClientRect();
    return [event.clientX - box.left, event.clientY - box.top];
  };
  const drawing = tool !== "pan" && !spec.locked;
  const polygon = tool === "rect" && draft.length > 1
    ? [draft[0]!, [draft[1]![0], draft[0]![1]], draft[1]!, [draft[0]![0], draft[1]![1]]] : draft;
  return <div className="scatter" ref={host} style={{ position: "relative", width, height }} aria-label={`3D scatter: ${spec.x}, ${spec.y}, ${spec.z}`}>
    <DeckGL ref={deckRef} width={width} height={height} views={view} viewState={camera} controller={!spec.locked && !drawing}
      onViewStateChange={({ viewState }) => setCamera(viewState as typeof initial)}
      layers={[new LineLayer({ id: `trajectories3d-${spec.id}`, data: lines, coordinateSystem: COORDINATE_SYSTEM.CARTESIAN,
        getSourcePosition: d => d.start.position, getTargetPosition: d => d.end.position,
        getColor: d => [...d.end.color.slice(0, 3), 150] as [number, number, number, number], getWidth: 1.5, widthUnits: "pixels", pickable: false,
      }), new ScatterplotLayer({ id: `scatter3d-${spec.id}`, data, coordinateSystem: COORDINATE_SYSTEM.CARTESIAN,
        getPosition: d => d.position, getRadius: d => d.radius, radiusUnits: "pixels", billboard: true, pickable: !spec.locked && !drawing,
        getFillColor: d => selection.has(d.index) ? [...SELECTED, 255] : d.color,
        updateTriggers: { getFillColor: [selection] },
        onClick: (info, event) => {
          if (info.object) clickRow(info.object.index, event.srcEvent.ctrlKey || event.srcEvent.metaKey ? "ctrl" : event.srcEvent.shiftKey ? "shift" : "none");
        },
      })]}
      getTooltip={info => info.object ? { text: `Row ${info.object.index}\n${[spec.x, spec.y, spec.z!].map(name => `${name}: ${rows[info.object.index]![name]}`).join("\n")}` } : null}
    />
    {drawing && <svg width={width} height={height} aria-label="3D selection area" style={{ position: "absolute", inset: 0, cursor: "crosshair", touchAction: "none" }}
      onPointerDown={event => {
        if (event.button !== 0) return;
        const at = point(event);
        if (!path.current.length) modifier.current = event.shiftKey ? "subtract" : event.ctrlKey || event.metaKey ? "add" : "replace";
        if (tool === "polygon") {
          if (path.current.length >= 3 && Math.hypot(at[0] - path.current[0]![0], at[1] - path.current[0]![1]) < 8) finish();
          else { path.current = [...path.current, at]; setDraft(path.current); }
        } else {
          modifier.current = event.shiftKey ? "subtract" : event.ctrlKey || event.metaKey ? "add" : "replace";
          event.currentTarget.setPointerCapture(event.pointerId); dragging.current = true;
          path.current = [at]; setDraft(path.current);
        }
      }}
      onPointerMove={event => {
        if (!dragging.current) return;
        path.current = tool === "rect" ? [path.current[0]!, point(event)] : simplifyPath([...path.current, point(event)], 2);
        setDraft(path.current);
      }}
      onPointerUp={() => { if (dragging.current) finish(); }}
      onPointerCancel={() => { path.current = []; setDraft([]); dragging.current = false; }}
      onDoubleClick={() => { if (tool === "polygon") finish(); }}>
      {tool === "brush" ? <polyline points={draft.map(p => p.join(",")).join(" ")} fill="none" stroke="#56f0c060" strokeWidth={28} strokeLinecap="round" strokeLinejoin="round" />
        : <polygon points={polygon.map(p => p.join(",")).join(" ")} fill="#56f0c030" stroke="#56f0c0" strokeWidth={1} />}
    </svg>}
    <span className="muted small" style={{ position: "absolute", bottom: 6, left: 10, pointerEvents: "none" }} role="status">
      {drawing ? "Select through all depths · Ctrl adds · Shift subtracts" : "Drag to rotate · scroll to zoom · click to select"} · {selection.size} selected{spec.trajectory ? ` · ${lines.length} trajectory segments` : ""}
    </span>
  </div>;
}
