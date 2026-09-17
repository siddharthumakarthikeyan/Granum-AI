/** Unrolled patches: one tile per box across every visible row.
 *
 * Scanning every instance of a class is how mislabelled boxes get caught -- a "dog"
 * patch that is plainly a cat stands out in a wall of dogs in a way it never does inside
 * a busy image. Element filters apply, so filtering to one class scans just that class.
 */

import { useVirtualizer } from "@tanstack/react-virtual";
import { useEffect, useMemo, useRef, useState } from "react";
import { api } from "../api/client";
import { className, isEditable } from "../store/editing";
import { useStore } from "../store/store";
import { asBoxValue, boxColumns, drawnBoxes } from "./model";

interface Patch {
  row: number;
  index: number;
  column: string;
  x0: number;
  y0: number;
  x1: number;
  y1: number;
  width: number;
  height: number;
  image: string;
  text: string;
  color: string;
  dash: string | null;
}

const LABEL_HEIGHT = 16;

export function PatchView({ size, onToast }: { size: number; onToast: (m: string) => void }) {
  const rows = useStore((s) => s.rows);
  const columns = useStore((s) => s.columns);
  const visible = useStore((s) => s.visibleRows());
  const filters = useStore((s) => s.filters);
  const display = useStore((s) => s.boxDisplay);
  const dismissed = useStore((s) => s.dismissed);
  const staged = useStore((s) => s.staged);
  const focused = useStore((s) => s.focusedInstance);
  const focusInstance = useStore((s) => s.focusInstance);
  const relabelBoxes = useStore((s) => s.relabelBoxes);
  const { truth, predicted } = useMemo(() => boxColumns(columns), [columns]);
  const [source, setSource] = useState<"truth" | "predicted">(truth ? "truth" : "predicted");
  const [picked, setPicked] = useState<Set<string>>(new Set());
  const [label, setLabel] = useState<number | null>(null);

  const imageColumn = columns.find((c) => c.kind === "image");
  const patches = useMemo(() => {
    const out: Patch[] = [];
    const list = Object.values(filters);
    for (const r of visible) {
      const row = rows[r];
      if (!row) continue;
      const boxes = drawnBoxes(
        row,
        source === "truth" ? truth : null,
        source === "predicted" ? predicted : null,
        { ...display, showTruth: true, showPredicted: true },
        list,
        { row: r, dismissed, staged },
      );
      const value = asBoxValue(row[(source === "truth" ? truth : predicted)?.name ?? ""]);
      for (const box of boxes) {
        out.push({
          row: r, index: box.index, column: box.column, x0: box.x0, y0: box.y0, x1: box.x1, y1: box.y1,
          width: value?.width ?? 0, height: value?.height ?? 0,
          image: imageColumn ? String(row[imageColumn.name] ?? "") : "",
          text: box.text, color: box.color, dash: box.dash,
        });
      }
    }
    return out;
  }, [visible, rows, filters, display, dismissed, staged, source, truth, predicted, imageColumn]);

  useEffect(() => setPicked(new Set()), [source]);

  const scrollRef = useRef<HTMLDivElement>(null);
  const [width, setWidth] = useState(800);
  useEffect(() => {
    const node = scrollRef.current;
    if (!node) return;
    const observer = new ResizeObserver(([entry]) => setWidth(entry!.contentRect.width));
    observer.observe(node);
    return () => observer.disconnect();
  }, []);

  const tile = size + 6;
  const perRow = Math.max(1, Math.floor((width - 16) / tile));
  const virtualizer = useVirtualizer({
    count: Math.ceil(patches.length / perRow),
    getScrollElement: () => scrollRef.current,
    estimateSize: () => tile + LABEL_HEIGHT,
    overscan: 3,
  });
  useEffect(() => virtualizer.measure(), [virtualizer, tile]);

  const geometry = source === "truth" ? truth : predicted;
  const editable = source === "truth" && isEditable(truth ?? undefined);
  const classKeys = Object.keys(geometry?.value_map ?? {}).map(Number).sort((a, b) => a - b);
  const key = (p: Patch) => `${p.row}:${p.index}`;

  const relabel = () => {
    if (!truth || label === null) return;
    const refs = patches.filter((p) => picked.has(key(p))).map((p) => ({ row: p.row, index: p.index }));
    const problem = relabelBoxes(refs, truth.name, label);
    onToast(problem ?? `Relabelled ${refs.length} box${refs.length === 1 ? "" : "es"} as ${className(truth, label)}`);
    if (!problem) setPicked(new Set());
  };

  return (
    <div className="patch-view">
      <div className="patch-bar">
        {truth && predicted && (
          <select value={source} onChange={(e) => setSource(e.target.value as "truth" | "predicted")}>
            <option value="truth">labelled boxes</option>
            <option value="predicted">predicted boxes</option>
          </select>
        )}
        <span className="muted">{patches.length.toLocaleString()} patches · click to inspect · ctrl+click to pick several</span>
        {editable && picked.size > 0 && (
          <>
            <span className="sep" />
            <span>relabel {picked.size} as</span>
            <select value={label ?? ""} onChange={(e) => setLabel(Number(e.target.value))}>
              <option value="" disabled>class…</option>
              {classKeys.map((k) => <option key={k} value={k}>{className(truth!, k)}</option>)}
            </select>
            <button className="primary" disabled={label === null} onClick={relabel}>apply</button>
            <button onClick={() => setPicked(new Set())}>clear</button>
          </>
        )}
      </div>
      <div className="patch-scroll" ref={scrollRef}>
        <div style={{ height: virtualizer.getTotalSize() + 16, position: "relative" }}>
          {virtualizer.getVirtualItems().map((line) => (
            <div key={line.key} className="patch-line" style={{ transform: `translateY(${line.start}px)` }}>
              {patches.slice(line.index * perRow, (line.index + 1) * perRow).map((patch) => {
                const bw = Math.max(patch.x1 - patch.x0, 1);
                const bh = Math.max(patch.y1 - patch.y0, 1);
                // Fit the box with a little context around it.
                const scale = (size * 0.8) / Math.max(bw, bh);
                const offsetX = (size - bw * scale) / 2 - patch.x0 * scale;
                const offsetY = (size - bh * scale) / 2 - patch.y0 * scale;
                const isFocused = focused?.row === patch.row && focused.column === patch.column && focused.index === patch.index;
                const isPicked = picked.has(key(patch));
                return (
                  <div
                    key={key(patch)}
                    className={`patch${isFocused ? " focused" : ""}${isPicked ? " picked" : ""}`}
                    style={{ width: size }}
                    title={`${patch.text} · row ${patch.row}`}
                    onClick={(e) => {
                      if (e.ctrlKey || e.metaKey) {
                        setPicked((current) => {
                          const next = new Set(current);
                          if (next.has(key(patch))) next.delete(key(patch));
                          else next.add(key(patch));
                          return next;
                        });
                        return;
                      }
                      focusInstance({ row: patch.row, column: patch.column, index: patch.index });
                    }}
                  >
                    <div
                      className="patch-image"
                      style={{
                        width: size, height: size,
                        backgroundImage: patch.image ? `url("${api.mediaUrl(patch.image)}")` : undefined,
                        backgroundSize: `${patch.width * scale}px ${patch.height * scale}px`,
                        backgroundPosition: `${offsetX}px ${offsetY}px`,
                      }}
                    >
                      <svg width={size} height={size} aria-hidden="true">
                        <rect
                          x={(size - bw * scale) / 2} y={(size - bh * scale) / 2} width={bw * scale} height={bh * scale}
                          fill="none" stroke={isFocused ? "var(--accent)" : patch.color} strokeWidth={1.5}
                          strokeDasharray={patch.dash ?? undefined}
                        />
                      </svg>
                    </div>
                    <div className="patch-label">{patch.text}</div>
                  </div>
                );
              })}
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
