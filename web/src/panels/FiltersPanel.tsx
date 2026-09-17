/** The Filters panel: one widget per filterable column.
 *
 * The two-tone histogram is the detail worth noticing. Dark grey is what *this* filter
 * excluded; the gap to full height is what other filters excluded. Without that split
 * you cannot tell whether narrowing a filter did anything.
 */

import { useCallback, useMemo, useRef, useState } from "react";
import {
  categoricalCounts, elementCategoricalCounts, elementCounts, elementHistogram, histogram, isActive,
} from "../store/filtering";
import { ClassesDialog } from "../editing/ClassesDialog";
import { className, isEditable } from "../store/editing";
import { useStore } from "../store/store";
import { ROW_INDEX, type CategoricalFilter, type Filter, type NumericFilter, type RegionFilter } from "../store/types";
import { columnLabel } from "../copy/plain";

function NumericWidget({ filter }: { filter: NumericFilter }) {
  const rows = useStore((s) => s.rows);
  const filters = useStore((s) => s.filters);
  const setFilter = useStore((s) => s.setFilter);
  const trackRef = useRef<HTMLDivElement>(null);
  const dragging = useRef(false);
  const start = useRef(0);

  const bins = useMemo(
    () => filter.scope === "element"
      ? elementHistogram(rows, filter, Object.values(filters))
      : histogram(rows, filter, Object.values(filters)),
    [rows, filter, filters],
  );
  const peak = Math.max(1, ...bins.map((b) => b.total));

  const valueAt = useCallback(
    (clientX: number): number => {
      const box = trackRef.current?.getBoundingClientRect();
      if (!box) return filter.bounds[0];
      const fraction = Math.min(1, Math.max(0, (clientX - box.left) / box.width));
      const [lo, hi] = filter.bounds;
      return lo + fraction * (hi - lo);
    },
    [filter.bounds],
  );

  /** Paint a range directly on the histogram -- faster than typing two numbers. */
  const onDown = (event: React.MouseEvent) => {
    dragging.current = true;
    start.current = valueAt(event.clientX);
    setFilter(filter.column, { range: [start.current, start.current] });
  };
  const onMove = (event: React.MouseEvent) => {
    if (!dragging.current) return;
    const current = valueAt(event.clientX);
    setFilter(filter.column, {
      range: current < start.current ? [current, start.current] : [start.current, current],
    });
  };
  const onUp = () => {
    dragging.current = false;
  };

  const step = (filter.bounds[1] - filter.bounds[0]) / 1000 || 0.001;

  return (
    <>
      <div
        className="histogram"
        ref={trackRef}
        onMouseDown={onDown}
        onMouseMove={onMove}
        onMouseUp={onUp}
        onMouseLeave={onUp}
        title="Drag to paint a range"
      >
        {bins.map((bin, index) => {
          const height = (bin.total / peak) * 100;
          const inShare = bin.total > 0 ? bin.filteredIn / bin.total : 0;
          return (
            <div className="bin" key={index} title={`${bin.lo.toFixed(3)} – ${bin.hi.toFixed(3)}
${bin.filteredIn} of ${bin.total} shown`}>
              <div className="out" style={{ height: `${height * (1 - inShare)}%` }} />
              <div className="in" style={{ height: `${height * inShare}%` }} />
            </div>
          );
        })}
      </div>
      <div className="range-row">
        <input
          type="number"
          step={step}
          value={Number(filter.range[0].toFixed(4))}
          onChange={(e) =>
            setFilter(filter.column, { range: [Number(e.target.value), filter.range[1]] })
          }
        />
        <span className="to">–</span>
        <input
          type="number"
          step={step}
          value={Number(filter.range[1].toFixed(4))}
          onChange={(e) =>
            setFilter(filter.column, { range: [filter.range[0], Number(e.target.value)] })
          }
        />
      </div>
    </>
  );
}

function CategoricalWidget({ filter }: { filter: CategoricalFilter }) {
  const rows = useStore((s) => s.rows);
  // An element filter on a box's class takes its names from the box column.
  const column = useStore((s) => s.columns.find((c) => c.name === (filter.geometry ?? filter.column)));
  const filters = useStore((s) => s.filters);
  const setFilter = useStore((s) => s.setFilter);
  const counts = useMemo(
    () => filter.scope === "element"
      ? elementCategoricalCounts(rows, filter, Object.values(filters))
      : categoricalCounts(rows, filter, Object.values(filters)),
    [rows, filter, filters],
  );

  const toggle = (value: string | number) => {
    const excluded = filter.excluded.includes(value)
      ? filter.excluded.filter((v) => v !== value)
      : [...filter.excluded, value];
    setFilter(filter.column, { excluded });
  };

  const isClass = column?.kind === "categorical_label" || (filter.scope === "element" && filter.property === "label");
  const boxLabels = filter.scope === "element" && filter.property === "label";
  const visible = useStore((s) => s.visibleRows());
  // For box classes, also count the images (shown now) that contain at least one such box.
  const imagesWith = useMemo(() => {
    const out = new Map<string, number>();
    if (!boxLabels || !filter.geometry) return out;
    for (const index of visible) {
      const value = rows[index]?.[filter.geometry] as { instances?: { label?: unknown }[] } | null | undefined;
      const seen = new Set<string>();
      for (const instance of value?.instances ?? []) seen.add(String(instance.label));
      for (const label of seen) out.set(label, (out.get(label) ?? 0) + 1);
    }
    return out;
  }, [boxLabels, filter.geometry, rows, visible]);
  const nameOf = (value: string | number) => (isClass ? className(column, value) : String(value));

  // Class-like filters with a handful of values read best as a ranked list with bars.
  if (filter.values.length <= 30) {
    const ranked = [...filter.values].sort((a, b) => (counts.get(b)?.total ?? 0) - (counts.get(a)?.total ?? 0));
    const peak = Math.max(1, ...ranked.map((v) => counts.get(v)?.total ?? 0));
    return (
      <div className={`value-list${boxLabels ? " with-images" : ""}`}>
        {boxLabels && (
          <div className="value-head" aria-hidden="true">
            <span />
            <span>Class</span>
            <span>Boxes</span>
            <span>Images</span>
          </div>
        )}
        {ranked.map((value) => {
          const bucket = counts.get(value);
          const off = filter.excluded.includes(value);
          const shown = bucket ? bucket.filteredIn : 0;
          return (
            <button
              key={String(value)}
              className={`value-row${off ? " off" : ""}`}
              onClick={(e) => {
                if (e.altKey || e.detail === 2) setFilter(filter.column, { excluded: filter.values.filter((v) => v !== value) });
                else toggle(value);
              }}
              title={`${nameOf(value)}: click to ${off ? "include" : "exclude"}, double-click to show only this`}
              aria-pressed={!off}
            >
              <span className="value-check" aria-hidden="true" />
              <span className="value-name">{nameOf(value)}</span>
              <span className="value-count" title={boxLabels ? "Boxes of this class" : undefined}>{shown.toLocaleString()}</span>
              {boxLabels && <span className="value-count images" title="Images containing this class">{(imagesWith.get(String(value)) ?? 0).toLocaleString()}</span>}
              <span className="value-bar" aria-hidden="true"><span style={{ width: `${((bucket?.total ?? 0) / peak) * 100}%` }} /></span>
            </button>
          );
        })}
      </div>
    );
  }

  return (
    <div className="chips">
      {filter.values.slice(0, 200).map((value) => {
        const bucket = counts.get(value);
        const off = filter.excluded.includes(value);
        return (
          <button className={`chip${off ? " off" : ""}`} key={String(value)} onClick={() => toggle(value)}>
            {column?.kind === "categorical_label" || (filter.scope === "element" && filter.property === "label")
              ? className(column, value)
              : String(value)}
            <span className="n">{bucket ? bucket.filteredIn : 0}</span>
          </button>
        );
      })}
    </div>
  );
}

function BooleanWidget({ filter }: { filter: Filter & { kind: "boolean" } }) {
  const setFilter = useStore((s) => s.setFilter);
  const rows = useStore((s) => s.rows);
  const filters = useStore((s) => s.filters);
  const counts = useMemo(
    () => (filter.scope === "element" ? elementCategoricalCounts(rows, filter, Object.values(filters)) : null),
    [rows, filter, filters],
  );
  return (
    <div className="chips">
      {[
        { label: "any", value: null },
        { label: "true", value: true },
        { label: "false", value: false },
      ].map((option) => (
        <button
          key={option.label}
          className={`chip${filter.value === option.value ? "" : " off"}`}
          onClick={() => setFilter(filter.column, { value: option.value })}
        >
          {option.label}
          {counts && option.value !== null && (
            <span className="n">{counts.get(String(option.value))?.filteredIn ?? 0}</span>
          )}
        </button>
      ))}
    </div>
  );
}

function RegionWidget({ filter }: { filter: RegionFilter }) {
  const setFilter = useStore((s) => s.setFilter);
  const added = filter.regions.filter((r) => r.mode === "add").length;
  const removed = filter.regions.length - added;
  return (
    <div className="region-summary">
      {added > 0 && <span>{added} added</span>}
      {removed > 0 && <span>{removed} subtracted</span>}
      {filter.regions.length > 0 && (
        <button
          onClick={() => setFilter(filter.column, { regions: filter.regions.slice(0, -1) })}
          title="Undo the last region"
        >
          undo last
        </button>
      )}
    </div>
  );
}

/** Region filters are named after their chart axes rather than a single column. */
function filterLabel(filter: Filter): string {
  if (filter.scope === "element") return columnLabel(filter.property ?? filter.column);
  if (filter.kind !== "region") return columnLabel(filter.column);
  const axis = (name: string) => (name === ROW_INDEX ? "row" : columnLabel(name));
  return `Area drawn on ${axis(filter.y)} against ${axis(filter.x)}`;
}

export function FilterWidget({ filter }: { filter: Filter }) {
  const setFilter = useStore((s) => s.setFilter);
  const resetFilter = useStore((s) => s.resetFilter);
  const toggleLock = useStore((s) => s.toggleFilterLock);
  const hideColumns = useStore((s) => s.hideColumns);
  const showColumn = useStore((s) => s.showColumn);
  const hidden = useStore((s) => s.hidden);
  const active = isActive(filter);
  const isHidden = hidden.has(filter.column);
  const column = useStore((s) => s.columns.find((c) => c.name === filter.column));
  const [classesOpen, setClassesOpen] = useState(false);
  const editableClasses = column?.kind === "categorical_label" && isEditable(column);

  return (
    <div className={`filter${filter.locked ? " locked" : ""}`}>
      <div className="filter-head">
        {active && <span className="dot" />}
        <span
          className="name"
          onClick={() => {
            if (filter.kind === "region" || filter.scope === "element") return;
            if (isHidden) showColumn(filter.column);
            else hideColumns([filter.column]);
          }}
          title={isHidden ? "Column hidden - click to show" : "Click to hide this column"}
          style={isHidden ? { opacity: 0.5 } : undefined}
        >
          {filterLabel(filter)}
        </span>
        <span className="filter-tools">
          <button
            className={filter.showFilteredOut ? "on" : ""}
            onClick={() => setFilter(filter.column, { showFilteredOut: !filter.showFilteredOut })}
            title="Show filtered-out points in charts"
          >
            ◐
          </button>
          <button
            className={filter.inverted ? "on" : ""}
            onClick={() => setFilter(filter.column, { inverted: !filter.inverted })}
            title="Invert this filter"
          >
            ⇄
          </button>
          <button onClick={() => resetFilter(filter.column)} title="Reset this filter">↺</button>
          {editableClasses && (
            <button onClick={() => setClassesOpen(true)} title="Edit classes">✎</button>
          )}
          <button
            className={filter.locked ? "on" : ""}
            onClick={() => toggleLock(filter.column)}
            title="Lock: clear-all will not touch this filter"
          >
            {filter.locked ? "🔒" : "🔓"}
          </button>
        </span>
      </div>
      {filter.kind === "numeric" && <NumericWidget filter={filter} />}
      {filter.kind === "categorical" && <CategoricalWidget filter={filter} />}
      {filter.kind === "boolean" && <BooleanWidget filter={filter} />}
      {filter.kind === "region" && <RegionWidget filter={filter} />}
      {classesOpen && <ClassesDialog column={filter.column} onClose={() => setClassesOpen(false)} />}
    </div>
  );
}

/** Filters over the boxes in one geometry column. A row stays visible while at least one
 * of its boxes passes all of them. */
function ElementSection({ geometry }: { geometry: string }) {
  const filters = useStore((s) => s.filters);
  const rows = useStore((s) => s.rows);
  const visible = useStore((s) => s.visibleRows());
  // Per-object ids are unique by construction; a histogram of them tells nothing.
  const members = Object.values(filters).filter((f) =>
    f.scope === "element" && f.geometry === geometry && ((f.property !== "annotation_id" && f.property !== "area") || isActive(f)));
  const counts = useMemo(() => elementCounts(rows, visible, Object.values(filters), geometry), [rows, visible, filters, geometry]);
  return (
    <div className="element-section">
      <div className="element-head" title="Filters for individual objects. An image stays visible while at least one of its objects matches all of them.">
        <span className="name">{columnLabel(geometry)}</span>
        <span className="counts">{counts.shown === counts.total ? counts.total.toLocaleString() : `${counts.shown.toLocaleString()} of ${counts.total.toLocaleString()}`}</span>
      </div>
      {members.map((filter) => <FilterWidget key={filter.column} filter={filter} />)}
    </div>
  );
}

/** Identifiers, file names and bookkeeping: filterable, but rarely where a review starts. */
const SECONDARY_NAMES = new Set(["image_id", "example_id", "annotation_id", "coco_image", "source_image", "content_hash", "Edited", "Visited", "Selected", "sequence"]);

function isSecondary(filter: Filter, kind: string | undefined): boolean {
  if (filter.kind === "region") return false;
  if (SECONDARY_NAMES.has(filter.column)) return true;
  // Free text with many distinct values (paths, JSON blobs) makes a wall of chips.
  if (filter.kind === "categorical" && kind === "string" && filter.values.length > 24) return true;
  return false;
}

export function FiltersPanel() {
  const filters = useStore((s) => s.filters);
  const order = useStore((s) => s.order);
  const columns = useStore((s) => s.columns);
  const [showMore, setShowMore] = useState(false);
  const clearFilters = useStore((s) => s.clearFilters);
  const liveFilters = useStore((s) => s.liveFilters);
  const setLiveFilters = useStore((s) => s.setLiveFilters);
  const activeCount = useStore((s) => s.activeFilterCount());

  // Filter order follows column order, so the two panels stay legible together.
  // Chart regions first: they are usually the most recent and most specific narrowing.
  const regions = Object.values(filters).filter((f) => f.kind === "region" && isActive(f));
  const ordered = [
    ...regions,
    ...(order.map((name) => filters[name]).filter(Boolean) as Filter[]),
  ];
  const elementGroups = [...new Set(Object.values(filters).filter((f) => f.scope === "element").map((f) => f.geometry!))];
  const kindOf = new Map(columns.map((c) => [c.name, c.kind]));
  // Boxes per image sits right under the box filters: it is the first question about a detection set.
  const primary = ordered.filter((f) => !isSecondary(f, kindOf.get(f.column)) || isActive(f))
    .sort((a, b) => Number(b.column === "boxes_per_image") - Number(a.column === "boxes_per_image"));
  const secondary = ordered.filter((f) => isSecondary(f, kindOf.get(f.column)) && !isActive(f));

  return (
    <div className="panel" style={{ width: "100%", height: "100%" }}>
      <div className="panel-head">
        <span className="title">Filter</span>
        {activeCount > 0 && <span>{activeCount} in use</span>}
        <span className="spacer" />
        <button
          className={liveFilters ? "on" : ""}
          onClick={() => setLiveFilters(!liveFilters)}
          title="Live filters: re-evaluate as values change. Turn off to keep a row you are editing from vanishing."
        >
          Live
        </button>
        {activeCount > 0 && (
          <button onClick={clearFilters} title="Clear all unlocked filters (D)">Clear all</button>
        )}
      </div>
      <div className="panel-body">
        {ordered.length === 0 && elementGroups.length === 0 ? (
          <div className="empty"><div>No filterable columns</div></div>
        ) : (
          <>
            {elementGroups.map((geometry) => <ElementSection key={geometry} geometry={geometry} />)}
            {primary.map((filter) => <FilterWidget key={filter.column} filter={filter} />)}
            {secondary.length > 0 && (
              <button className="filters-more" onClick={() => setShowMore(!showMore)} aria-expanded={showMore}>
                {showMore ? "Hide" : "Show"} {secondary.length} more filters
                <span className="faint">{secondary.map((f) => columnLabel(f.column)).join(", ")}</span>
              </button>
            )}
            {showMore && secondary.map((filter) => <FilterWidget key={filter.column} filter={filter} />)}
          </>
        )}
      </div>
    </div>
  );
}
