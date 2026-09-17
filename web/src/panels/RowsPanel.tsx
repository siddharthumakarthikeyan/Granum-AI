/** The Rows panel: the grid, its selection model, and the thumbnail view.
 *
 * The selection model looks trivial and is not. Rows, columns, ranges and keyboard
 * traversal interlock, and Escape peels back one layer at a time. Getting this right
 * now is what lets Stage 7 add per-element selection without rewriting the panel.
 */

import { useVirtualizer } from "@tanstack/react-virtual";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { api } from "../api/client";
import { COLUMN_DRAG_TYPE } from "../charts/spec";
import type { ColumnInfo } from "../api/types";
import { BoxControls } from "../boxes/BoxControls";
import { BoxOverlay } from "../boxes/BoxOverlay";
import { PatchView } from "../boxes/PatchView";
import { boxColumns, drawnBoxes, summarizeBoxes } from "../boxes/model";
import { AssignBar } from "../editing/AssignBar";
import { ReviewBar } from "../editing/ReviewBar";
import { NewColumnDialog } from "../editing/NewColumnDialog";
import { ValueInput } from "../editing/ValueInput";
import { copyToClipboard, formatSelection, type CopyFormat } from "../store/clipboard";
import { cellKey, className, isCellEditable, isEditable, targetOf } from "../store/editing";
import { cellValue, elementCounts } from "../store/filtering";
import { useStore } from "../store/store";
import { columnLabel } from "../copy/plain";

const NUMERIC = new Set([
  "int32", "int64", "float32", "confidence", "fraction", "probability",
  "iou", "sample_weight", "example_id", "epoch", "foreign_table_id",
]);

/** Must match `--row-h` plus the cell border in app.css. */
const ROW_HEIGHT = 27;

function isImage(column: ColumnInfo): boolean {
  return column.kind === "image";
}

function render(value: unknown, column: ColumnInfo): string {
  if (value === null || value === undefined) return "";
  if (column.kind === "categorical_label") return className(column, value);
  if (column.kind === "bounding_boxes_2d") return summarizeBoxes(value, column);
  if (column.kind === "int32_list" && Array.isArray(value)) return `[${value.join(", ")}]`;
  if (column.source === "session" && column.kind === "bool") return value ? "✓" : "";
  if (typeof value === "number") {
    if (Number.isInteger(value)) return String(value);
    return value.toFixed(4);
  }
  if (Array.isArray(value)) return `[${value.length}]`;
  if (isImage(column)) {
    const text = String(value);
    return text.slice(text.lastIndexOf("/") + 1);
  }
  return String(value);
}

interface Props {
  onToast: (message: string) => void;
}

function BoxCount({ geometry, visible }: { geometry: string; visible: number[] }) {
  const rows = useStore((s) => s.rows);
  const filters = useStore((s) => s.filters);
  const { shown, total } = useMemo(
    () => elementCounts(rows, visible, Object.values(filters), geometry),
    [rows, visible, filters, geometry],
  );
  return <span className="rows-count-boxes">{shown === total ? total.toLocaleString() : `${shown.toLocaleString()} of ${total.toLocaleString()}`} boxes</span>;
}

export function RowsPanel({ onToast }: Props) {
  const rows = useStore((s) => s.rows);
  const total = useStore((s) => s.total);
  const selection = useStore((s) => s.selection);
  const sort = useStore((s) => s.sort);
  const viewMode = useStore((s) => s.viewMode);
  const gridSize = useStore((s) => s.gridSize);
  const sourceKind = useStore((s) => s.sourceKind);
  const hidden = useStore((s) => s.hidden);

  const clickRow = useStore((s) => s.clickRow);
  const clickColumn = useStore((s) => s.clickColumn);
  const toggleSort = useStore((s) => s.toggleSort);
  const hideColumns = useStore((s) => s.hideColumns);
  const showColumn = useStore((s) => s.showColumn);
  const selectAllRows = useStore((s) => s.selectAllRows);
  const clearSelection = useStore((s) => s.clearSelection);
  const setViewMode = useStore((s) => s.setViewMode);
  const setGridSize = useStore((s) => s.setGridSize);
  const moveColumn = useStore((s) => s.moveColumn);

  const address = useStore((s) => s.address);
  const undoStack = useStore((s) => s.undoStack);
  const pendingEdits = useStore((s) => s.pendingEdits);
  const editCells = useStore((s) => s.editCells);
  const [editing, setEditing] = useState<{ index: number; column: string } | null>(null);
  const [newColumnOpen, setNewColumnOpen] = useState(false);

  // Which (table row, column) cells carry an uncommitted edit, for the yellow marking.
  const edited = useMemo(() => new Set(pendingEdits().cells.keys()), [pendingEdits, undoStack]);
  const isEdited = (index: number, column: string) => {
    if (edited.size === 0 || !address) return false;
    const target = targetOf(address, rows, index);
    return target !== null && edited.has(cellKey(target.table, target.row, column));
  };

  /** Commit an inline edit: to the whole selection if the edited row is part of one. */
  const commitCell = (index: number, column: string, value: unknown) => {
    const indices = selection.rows.has(index) && selection.rows.size > 1 ? [...selection.rows] : [index];
    const problem = editCells(column, indices, value);
    if (problem) onToast(problem);
    else if (indices.length > 1) onToast(`Set ${column} on ${indices.length} selected rows`);
    setEditing(null);
  };

  const allColumns = useStore((s) => s.columns);
  const boxDisplay = useStore((s) => s.boxDisplay);
  const filters = useStore((s) => s.filters);
  const filterList = useMemo(() => Object.values(filters), [filters]);
  const { truth: truthBoxes, predicted: predictedBoxes } = useMemo(() => boxColumns(allColumns), [allColumns]);
  const hasBoxes = Boolean(truthBoxes || predictedBoxes);

  const visible = useStore((s) => s.visibleRows());
  const columns = useStore((s) => s.visibleColumns());
  const dragged = useRef<string | null>(null);

  // Only the rows on screen exist in the DOM. A run with 80k metrics rows rendered as a
  // plain table is 800k nodes and a frozen tab.
  const bodyRef = useRef<HTMLDivElement>(null);
  const [bodyWidth, setBodyWidth] = useState(800);
  useEffect(() => {
    const node = bodyRef.current;
    if (!node) return;
    const observer = new ResizeObserver(([entry]) => setBodyWidth(entry!.contentRect.width));
    observer.observe(node);
    return () => observer.disconnect();
  }, []);

  const perRow = Math.max(1, Math.floor((bodyWidth - 16 + 6) / (gridSize + 6)));
  // Tiles stretch so a row always fills the width; the slider sets how many fit.
  const tileWidth = Math.max(gridSize, Math.floor((bodyWidth - 16 - 6 * (perRow - 1)) / perRow));
  const tileHeight = Math.round(tileWidth * 0.75) + 22;
  const tile = tileHeight + 6;
  const lineCount = viewMode === "grid" ? Math.ceil(visible.length / perRow) : visible.length;
  const virtualizer = useVirtualizer({
    count: lineCount,
    getScrollElement: () => bodyRef.current,
    estimateSize: () => (viewMode === "grid" ? tile : ROW_HEIGHT),
    overscan: viewMode === "grid" ? 3 : 20,
  });
  useEffect(() => {
    virtualizer.measure();
  }, [virtualizer, viewMode, tile]);

  // Keep the cursor on screen when it moves from elsewhere: arrow keys, or a click on a
  // chart point.
  const anchor = selection.anchor;
  useEffect(() => {
    if (anchor === null) return;
    const position = visible.indexOf(anchor);
    if (position === -1) return;
    virtualizer.scrollToIndex(viewMode === "grid" ? Math.floor(position / perRow) : position, {
      align: "auto",
    });
  }, [anchor, visible, viewMode, perRow, virtualizer]);

  const items = virtualizer.getVirtualItems();
  const padTop = items.length > 0 ? items[0]!.start : 0;
  const padBottom = items.length > 0 ? virtualizer.getTotalSize() - items[items.length - 1]!.end : 0;

  const sortIndex = useMemo(
    () => new Map(sort.map((key, index) => [key.column, { ...key, index }])),
    [sort],
  );

  const onCopy = useCallback(
    async (format: CopyFormat) => {
      const indices = selection.rows.size > 0 ? [...selection.rows] : visible;
      const names =
        selection.columns.size > 0 ? [...selection.columns] : columns.map((c) => c.name);
      const ok = await copyToClipboard(formatSelection(rows, indices, names, format));
      onToast(
        ok
          ? `Copied ${indices.length} rows x ${names.length} columns as ${format.toUpperCase()}`
          : "Copy failed - the browser blocked clipboard access",
      );
    },
    [columns, onToast, rows, selection, visible],
  );

  const imageColumn = columns.find(isImage);

  return (
    <div className="panel" style={{ flex: 1, minHeight: 0 }}>
      <div className="panel-head rows-toolbar">
        <span className="title">{sourceKind === "run" ? "Rows" : "Images"}</span>
        <span className="rows-count">
          <b>{visible.length.toLocaleString()}</b>
          {visible.length !== rows.length && <> of {rows.length.toLocaleString()}</>}
          {total > rows.length && <> ({total.toLocaleString()} in table)</>}
          {hasBoxes && <BoxCount geometry={(truthBoxes ?? predictedBoxes)!.name} visible={visible} />}
          {selection.rows.size > 0 && <span className="rows-selected">{selection.rows.size.toLocaleString()} selected</span>}
        </span>
        <span className="spacer" />
        <div className="segmented view-switch" role="group" aria-label="View">
          <button className={viewMode === "list" ? "on" : ""} onClick={() => setViewMode("list")} title="Table">Table</button>
          <button className={viewMode === "grid" ? "on" : ""} onClick={() => setViewMode("grid")} title="Image grid">Grid</button>
          {hasBoxes && (
            <button className={viewMode === "patches" ? "on" : ""} onClick={() => setViewMode("patches")} title="Every labelled object, cropped">
              Objects
            </button>
          )}
        </div>
        {viewMode !== "list" && hasBoxes && <BoxControls compact />}
        {viewMode !== "list" && (
          <input
            className="size-slider"
            type="range"
            min={60}
            max={260}
            value={gridSize}
            title="Tile size"
            aria-label="Tile size"
            onChange={(e) => setGridSize(Number(e.target.value))}
          />
        )}
        <span className="toolbar-sep" />
        <button onClick={selectAllRows} title="Select every row shown (A)">Select all</button>
        {selection.rows.size > 0 && <button onClick={clearSelection} title="Clear selection (Esc)">Clear</button>}
        <button onClick={() => void onCopy("csv")} title="Copy selected rows as CSV">Copy</button>
        {hidden.size > 0 && (
          <button onClick={() => hidden.forEach(showColumn)} title={`Show ${hidden.size} hidden columns, including Edited, Visited and Selected`}>
            +{hidden.size} columns
          </button>
        )}
        {address && address.sources.length > 0 && (
          <button onClick={() => setNewColumnOpen(true)} title="Add a column, such as a note or a flag">Add column</button>
        )}
      </div>
      <div className="selection-bar">
        <ReviewBar onToast={onToast} />
        <AssignBar onToast={onToast} />
      </div>
      {newColumnOpen && <NewColumnDialog onClose={() => setNewColumnOpen(false)} />}

      <div className="panel-body" ref={bodyRef} style={viewMode === "patches" ? { overflow: "hidden" } : undefined}>
        {viewMode === "patches" && hasBoxes ? (
          <PatchView size={gridSize} onToast={onToast} />
        ) : viewMode === "grid" ? (
          <div className="thumbs" style={{ height: virtualizer.getTotalSize() + 16 }}>
            {items.map((line) => (
              <div
                key={line.key}
                className="thumb-line"
                style={{ transform: `translateY(${line.start}px)`, height: tile }}
              >
                {visible.slice(line.index * perRow, (line.index + 1) * perRow).map((index) => {
                  const row = rows[index]!;
                  const source = imageColumn ? String(row[imageColumn.name] ?? "") : "";
                  return (
                    <div
                      key={index}
                      className={`thumb${selection.rows.has(index) ? " selected" : ""}`}
                      style={{ width: tileWidth, height: tileHeight }}
                      onClick={(e) =>
                        clickRow(index, e.ctrlKey || e.metaKey ? "ctrl" : e.shiftKey ? "shift" : "none")
                      }
                    >
                      {source ? (
                        <img
                          src={api.mediaUrl(source, Math.min(512, tileWidth * 2))}
                          alt=""
                          loading="lazy"
                          style={hasBoxes ? { objectFit: "contain" } : undefined}
                        />
                      ) : (
                        <div className="noimg">row {index}</div>
                      )}
                      <div className="thumb-caption">
                        <span className="thumb-name">{source ? source.slice(source.lastIndexOf("/") + 1) : `row ${index}`}</span>
                        {hasBoxes && (
                          <span className="thumb-boxes">
                            {((truthBoxes ? row[truthBoxes.name] : row[predictedBoxes!.name]) as { instances?: unknown[] } | undefined)?.instances?.length ?? 0}
                          </span>
                        )}
                      </div>
                      {hasBoxes && (() => {
                        const value = (truthBoxes ? row[truthBoxes.name] : row[predictedBoxes!.name]) as { width?: number; height?: number } | undefined;
                        return (
                          <BoxOverlay
                            boxes={drawnBoxes(row, truthBoxes, predictedBoxes, boxDisplay, filterList)}
                            width={value?.width ?? 0}
                            height={value?.height ?? 0}
                            annotate="none"
                            stroke={1.2}
                          />
                        );
                      })()}
                      {columns.some((c) => isEdited(index, c.name)) && (
                        <div className="thumb-edited" title="Has uncommitted edits">✎</div>
                      )}
                    </div>
                  );
                })}
              </div>
            ))}
          </div>
        ) : (
          <table className="grid">
            <thead>
              <tr>
                <th style={{ width: 56 }} className="muted">#</th>
                {columns.map((column) => {
                  const key = sortIndex.get(column.name);
                  return (
                    <th
                      key={column.name}
                      className={selection.columns.has(column.name) ? "selected" : ""}
                      draggable
                      onDragStart={(e) => {
                        dragged.current = column.name;
                        e.dataTransfer.setData(COLUMN_DRAG_TYPE, column.name);
                        e.dataTransfer.effectAllowed = "copyMove";
                      }}
                      onDragOver={(e) => e.preventDefault()}
                      onDrop={() => {
                        if (dragged.current && dragged.current !== column.name) {
                          moveColumn(dragged.current, column.name);
                        }
                        dragged.current = null;
                      }}
                      onDragEnd={() => (dragged.current = null)}
                      onClick={(e) => {
                        if (e.shiftKey) toggleSort(column.name, e.ctrlKey || e.metaKey);
                        else clickColumn(column.name, e.ctrlKey || e.metaKey ? "ctrl" : "none");
                      }}
                      onContextMenu={(e) => {
                        e.preventDefault();
                        hideColumns([column.name]);
                        onToast(`Hid ${columnLabel(column.name)}`);
                      }}
                      title={`${columnLabel(column.name)} (column "${column.name}")
Click to select for a chart. Shift+click to sort. Right-click to hide.
Drag onto another header to reorder, or onto a chart to show its filter there.`}
                    >
                      {columnLabel(column.name)}
                      {isEditable(column) && (
                        <span
                          className="editable-mark"
                          title={isCellEditable(column) ? "Editable: double-click a cell" : "Editable: select a row and edit its boxes in an image chart"}
                        >
                          ✎
                        </span>
                      )}
                      {key && (
                        <span className="sortmark">
                          {key.direction === "asc" ? "▲" : "▼"}
                          {sort.length > 1 ? key.index + 1 : ""}
                        </span>
                      )}
                    </th>
                  );
                })}
              </tr>
            </thead>
            <tbody>
              {padTop > 0 && (
                <tr className="spacer" style={{ height: padTop }}>
                  <td colSpan={columns.length + 1} />
                </tr>
              )}
              {items.map((item) => {
                const index = visible[item.index]!;
                const row = rows[index]!;
                return (
                  <tr
                    key={index}
                    className={selection.rows.has(index) ? "selected" : ""}
                    onClick={(e) =>
                      clickRow(
                        index,
                        e.ctrlKey || e.metaKey ? "ctrl" : e.shiftKey ? "shift" : "none",
                      )
                    }
                  >
                    <td className="num muted">{index}</td>
                    {columns.map((column) => {
                      const value = cellValue(row, column.name, index);
                      const editable = isCellEditable(column);
                      const changedOnly = isEditable(column);
                      const changed = changedOnly && isEdited(index, column.name);
                      const isOpen = editing?.index === index && editing.column === column.name;
                      return (
                        <td
                          key={column.name}
                          className={[
                            NUMERIC.has(column.kind) ? "num" : "",
                            selection.columns.has(column.name) ? "col-selected" : "",
                            editable ? "editable" : "readonly",
                            changed ? "edited" : "",
                            isOpen ? "editing" : "",
                          ].join(" ")}
                          title={editable ? `${String(value ?? "")} · double-click to edit` : String(value ?? "")}
                          onDoubleClick={() => editable && setEditing({ index, column: column.name })}
                          onClick={(e) => isOpen && e.stopPropagation()}
                        >
                          {isOpen ? (
                            <ValueInput
                              column={column}
                              value={value}
                              autoFocus
                              onCommit={(next) => commitCell(index, column.name, next)}
                              onCancel={() => setEditing(null)}
                            />
                          ) : (
                            render(value, column)
                          )}
                        </td>
                      );
                    })}
                  </tr>
                );
              })}
              {padBottom > 0 && (
                <tr className="spacer" style={{ height: padBottom }}>
                  <td colSpan={columns.length + 1} />
                </tr>
              )}
            </tbody>
          </table>
        )}
      </div>

      <div className="hint">
        <kbd>click</kbd> select · <kbd>ctrl</kbd> add · <kbd>shift</kbd> range ·
        <kbd>↑↓</kbd> move · <kbd>A</kbd> all · <kbd>Esc</kbd> clear ·
        <kbd>shift+click</kbd> header to sort · <kbd>right-click</kbd> header to hide ·
        <kbd>D</kbd> clear filters
      </div>
    </div>
  );
}
