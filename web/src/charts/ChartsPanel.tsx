/** The Charts panel: tiled charts, each with its own tools.
 *
 * Charts wrap onto new rows past the "per row" setting and the panel scrolls
 * vertically, so adding a fifth chart never squeezes the first four.
 */

import { useEffect, useRef, useState } from "react";
import { FilterWidget } from "../panels/FiltersPanel";
import { isFilterable, isNumericColumn, regionFilterKey } from "../store/filtering";
import { Icon } from "../components/ui";
import { useStore } from "../store/store";
import { ROW_INDEX } from "../store/types";
import { ImageChart } from "./ImageChart";
import { ScatterChart } from "./ScatterChart";
import {
  chartFromColumns, chartSignature, COLUMN_DRAG_TYPE, type ChartSpec, type ScatterSpec, type Tool,
} from "./spec";
import { columnLabel } from "../copy/plain";

const TOOLS: { tool: Tool; icon: string; label: string }[] = [
  { tool: "pan", icon: "✥", label: "Pan and zoom · click a point to select its row" },
  { tool: "rect", icon: "▭", label: "Rectangle" },
  { tool: "lasso", icon: "➰", label: "Lasso" },
  { tool: "polygon", icon: "⬠", label: "Polygon · click vertices, double-click or click the first vertex to close" },
  { tool: "brush", icon: "●", label: "Brush" },
];

/** The element's size, tracked from whenever it mounts: a callback ref, because the
 * measured element is not rendered while the panel shows its empty bar. */
function useSize<T extends HTMLElement>() {
  const [node, setNode] = useState<T | null>(null);
  const [size, setSize] = useState({ width: 0, height: 0 });
  useEffect(() => {
    if (!node) return;
    const observer = new ResizeObserver(([entry]) => {
      const box = entry!.contentRect;
      setSize({ width: Math.floor(box.width), height: Math.floor(box.height) });
    });
    observer.observe(node);
    return () => observer.disconnect();
  }, [node]);
  return [setNode, size] as const;
}

function ScatterControls({ spec }: { spec: ScatterSpec }) {
  const columns = useStore((s) => s.columns);
  const updateChart = useStore((s) => s.updateChart);
  const numeric = columns.filter(isNumericColumn);
  const colorable = columns.filter(isFilterable);

  const select = (
    value: string | null,
    options: { name: string }[],
    onChange: (v: string | null) => void,
    title: string,
    none?: string,
  ) => (
    <select
      value={value ?? ""}
      title={title}
      onChange={(e) => onChange(e.target.value === "" ? null : e.target.value)}
    >
      {none !== undefined && <option value="">{none}</option>}
      {options.map((c) => (
        <option key={c.name} value={c.name}>{c.name === ROW_INDEX ? "row" : columnLabel(c.name)}</option>
      ))}
    </select>
  );

  return (
    <>
      {select(spec.x, [{ name: ROW_INDEX }, ...numeric], (x) => updateChart(spec.id, { x: x ?? ROW_INDEX }), "x axis")}
      <span className="vs">×</span>
      {select(spec.y, numeric, (y) => y && updateChart(spec.id, { y }), "y axis")}
      {select(spec.color, colorable, (color) => updateChart(spec.id, { color, slots: null }), "Colour by", "no colour")}
      {select(spec.size, numeric, (size) => updateChart(spec.id, { size }), "Radius by", "fixed size")}
      <input
        type="range"
        min={1}
        max={12}
        step={0.5}
        value={spec.pointSize}
        title={`Point size ${spec.pointSize}px`}
        onChange={(e) => updateChart(spec.id, { pointSize: Number(e.target.value) })}
      />
    </>
  );
}

function ChartTile({ spec, width, height }: { spec: ChartSpec; width: number; height: number }) {
  const updateChart = useStore((s) => s.updateChart);
  const removeChart = useStore((s) => s.removeChart);
  const cloneChart = useStore((s) => s.cloneChart);
  const toggleFavourite = useStore((s) => s.toggleFavourite);
  const addChartFromSelection = useStore((s) => s.addChartFromSelection);
  const favourites = useStore((s) => s.favourites);
  const filters = useStore((s) => s.filters);
  const removeFilter = useStore((s) => s.removeFilter);
  const [tool, setTool] = useState<Tool>("pan");
  const [dropping, setDropping] = useState(false);
  const bodyRef = useRef<HTMLDivElement>(null);

  const favourite = favourites.has(chartSignature(spec));
  const regionKey = spec.kind === "scatter" ? regionFilterKey(spec.x, spec.y) : null;
  const region = regionKey ? filters[regionKey] : undefined;
  const regionCount = region?.kind === "region" ? region.regions.length : 0;

  const overlays = spec.overlays.filter((name) => filters[name]);
  const bodyHeight = Math.max(80, height - 30);
  const plotWidth = overlays.length > 0 ? Math.max(120, width - 216) : width;

  return (
    <div className={`chart${spec.locked ? " locked" : ""}${dropping ? " dropping" : ""}`} style={{ width, height }}>
      <div className="chart-head">
        <div className="chart-controls">
        {spec.kind === "scatter" ? (
          <>
            <span className="tools">
              {TOOLS.map((t) => (
                <button
                  key={t.tool}
                  className={tool === t.tool ? "on" : ""}
                  onClick={() => setTool(t.tool)}
                  disabled={spec.locked && t.tool !== "pan"}
                  title={t.tool === "pan" ? t.label : `${t.label} · drag replaces the selection, ctrl adds, shift subtracts`}
                >
                  {t.icon}
                </button>
              ))}
            </span>
            <ScatterControls spec={spec} />
          </>
        ) : (
          <span className="chart-title"><Icon name="layers" size={14} />Image inspector</span>
        )}
        </div>
        <div className="chart-actions">
        {regionCount > 0 && (
          <button
            className="on"
            onClick={() => removeFilter(regionKey!)}
            title="Clear the regions drawn on this chart"
          >
            {regionCount} region{regionCount === 1 ? "" : "s"} ✕
          </button>
        )}
        {spec.kind === "scatter" && (
          <>
            <button
              className={spec.showFilteredOut ? "on" : ""}
              onClick={() => updateChart(spec.id, { showFilteredOut: !spec.showFilteredOut })}
              title="Show filtered-out points in grey"
            >
              ◐
            </button>
            <button
              onClick={() => bodyRef.current?.querySelector(".scatter")?.dispatchEvent(new Event("granum:snap"))}
              title="Snap to the visible points"
            >
              ⤢
            </button>
          </>
        )}
        <button
          className={`chart-icon${spec.locked ? " on" : ""}`}
          onClick={() => updateChart(spec.id, { locked: !spec.locked })}
          title="Lock this chart: no panning, zooming or drawing"
          aria-label="Lock chart"
        >
          <Icon name={spec.locked ? "lock" : "unlock"} size={14} />
        </button>
        <button className="chart-icon" onClick={() => cloneChart(spec.id)} title="Clone this chart" aria-label="Clone chart">
          <Icon name="copy" size={14} />
        </button>
        <button
          className={`chart-icon${favourite ? " on favourite" : ""}`}
          onClick={() => toggleFavourite(spec.id)}
          title={favourite ? "Remove from favourites" : "Favourite: reopen this chart automatically for this project"}
          aria-label="Favourite chart"
        >
          <Icon name="star" size={14} />
        </button>
        <button
          className="chart-icon"
          onClick={() => { const problem = addChartFromSelection(); if (problem) window.alert(problem); }}
          title="Add a chart from the selected column headers (Ctrl+click headers to pick several)"
          aria-label="Add chart"
        >
          <Icon name="plus" size={14} />
        </button>
        <button className="chart-icon" onClick={() => removeChart(spec.id)} title="Close this chart" aria-label="Close chart">
          <Icon name="close" size={14} />
        </button>
        </div>
      </div>

      <div
        className="chart-body"
        ref={bodyRef}
        style={{ height: bodyHeight }}
        onDragOver={(e) => {
          if (!e.dataTransfer.types.includes(COLUMN_DRAG_TYPE)) return;
          e.preventDefault();
          setDropping(true);
        }}
        onDragLeave={() => setDropping(false)}
        onDrop={(e) => {
          setDropping(false);
          const column = e.dataTransfer.getData(COLUMN_DRAG_TYPE);
          if (!column || !filters[column] || spec.overlays.includes(column)) return;
          e.preventDefault();
          updateChart(spec.id, { overlays: [...spec.overlays, column] });
        }}
      >
        {width > 0 && spec.kind === "scatter" && (
          <ScatterChart spec={spec} width={plotWidth} height={bodyHeight} tool={spec.locked ? "pan" : tool} />
        )}
        {width > 0 && spec.kind === "image" && (
          <ImageChart spec={spec} width={plotWidth} height={bodyHeight} />
        )}
        {overlays.length > 0 && (
          <div className="chart-overlays">
            {overlays.map((name) => (
              <div key={name} className="chart-overlay">
                <button
                  className="close"
                  onClick={() => updateChart(spec.id, { overlays: spec.overlays.filter((o) => o !== name) })}
                  title="Remove this filter from the chart"
                >
                  ✕
                </button>
                <FilterWidget filter={filters[name]!} />
              </div>
            ))}
          </div>
        )}
        {dropping && <div className="drop-hint">Drop to show this column's filter here</div>}
      </div>
    </div>
  );
}

export function ChartsPanel({ onToast }: { onToast: (message: string) => void }) {
  const charts = useStore((s) => s.charts);
  const perRow = useStore((s) => s.chartsPerRow);
  const setPerRow = useStore((s) => s.setChartsPerRow);
  const addChartFromSelection = useStore((s) => s.addChartFromSelection);
  const selectedColumns = useStore((s) => s.selection.columns);
  const [bodyRef, size] = useSize<HTMLDivElement>();

  const gap = 6;
  const columnsInRow = Math.max(1, Math.min(perRow, charts.length));
  const tileWidth = Math.floor((size.width - gap * (columnsInRow + 1)) / columnsInRow);
  const tileHeight = Math.max(240, size.height - gap * 2);

  const add = () => {
    const problem = addChartFromSelection();
    if (problem) onToast(problem);
  };

  // With no charts the panel is a single bar of shortcuts, so the images get the space.
  if (charts.length === 0) {
    return (
      <div className="panel charts-bar">
        <span className="title">Charts</span>
        <QuickCharts onToast={onToast} />
        <span className="spacer" />
        <button className="button subtle" onClick={add} title="Select column headers (Ctrl+click for several), then add a chart. Brush a chart to filter.">
          {selectedColumns.size > 0 ? `Chart ${[...selectedColumns].join(" against ")}` : "Add chart from selected columns"}
        </button>
      </div>
    );
  }

  return (
    <div className={`panel${charts.length === 1 ? " single-chart" : ""}`} style={{ flex: 1, minHeight: 0 }}>
      <div className="panel-head">
        <span className="title">Charts</span>
        {charts.length > 0 && <span>{charts.length}</span>}
        <span className="spacer" />
        <button
          onClick={add}
          title="Chart the selected columns, in the order you selected them: one numeric column plots row versus value, two plot x versus y, a third colours the points. An image column on its own opens an image chart."
        >
          {selectedColumns.size > 0 ? `Chart ${[...selectedColumns].join(" against ")}` : "Add chart"}
        </button>
        {charts.length > 1 && <label className="per-row" title="Charts side by side before wrapping">
          Charts per row
          <input
            type="number"
            min={1}
            max={6}
            value={perRow}
            onChange={(e) => setPerRow(Number(e.target.value))}
          />
        </label>}
      </div>
      <div className="panel-body charts-body" ref={bodyRef}>
        {charts.length === 0 ? (
          <div className="empty charts-empty">
            <div className="title">No charts</div>
            <QuickCharts onToast={onToast} />
            <div className="muted small">
              Or select column headers (Ctrl+click for several) and press <b>Add chart</b>. Brush a chart to filter.
            </div>
          </div>
        ) : (
          <div className="chart-grid" style={{ gap, padding: gap }}>
            {size.width > 0 &&
              charts.map((spec) => (
                <ChartTile key={spec.id} spec={spec} width={tileWidth} height={tileHeight} />
              ))}
          </div>
        )}
      </div>
    </div>
  );
}

/** One-click charts for people who do not want to pick columns. */
function QuickCharts({ onToast }: { onToast: (message: string) => void }) {
  const columns = useStore((s) => s.columns);
  const addChart = useStore((s) => s.addChart);
  const image = columns.find((c) => c.kind === "image");
  const numeric = columns.filter((c) => c.source !== "session" && isNumericColumn(c) && c.kind !== "example_id");
  const make = (names: string[]) => {
    const spec = chartFromColumns(names, columns);
    if (typeof spec === "string") onToast(spec);
    else addChart(spec);
  };
  return (
    <div className="quick-charts">
      {image && (
        <button className="button" onClick={() => make([image.name])}>
          Image inspector
        </button>
      )}
      {numeric.filter((c) => c.name !== "weight" && c.name !== "image_id").slice(0, 3).map((column) => (
        <button key={column.name} className="button" onClick={() => make([column.name])}>
          {columnLabel(column.name)} histogram
        </button>
      ))}
    </div>
  );
}
