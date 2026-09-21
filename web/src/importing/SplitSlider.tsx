/** Re-cut train / valid / test before importing, by dragging the boundaries between them.
 *
 * The dataset keeps every image: moving a handle only moves images from one split to its
 * neighbour, so the total never changes. Counts come from the annotation files, so they
 * can be a little above what is finally written (excluded images); the service reads the
 * plan as proportions, which keeps the cut the user drew.
 */

import { useRef, useState } from "react";
import { formatNumber } from "../components/ui";

const SEGMENT_COLORS = ["var(--cyan)", "var(--pink)", "var(--amber)", "var(--pass)", "var(--accent-dim)"];

export interface SplitCount {
  split: string;
  images: number;
}

/** Prefix sums: boundary i sits between split i and split i + 1. */
function boundaries(counts: number[]): number[] {
  const out: number[] = [];
  let running = 0;
  for (const count of counts) {
    running += count;
    out.push(running);
  }
  return out;
}

export function SplitSlider({ splits, plan, onChange, disabled }: {
  splits: SplitCount[];
  plan: Record<string, number>;
  onChange: (next: Record<string, number>) => void;
  disabled?: boolean;
}) {
  const barRef = useRef<HTMLDivElement>(null);
  const [dragging, setDragging] = useState<number | null>(null);

  const names = splits.map((s) => s.split);
  const counts = names.map((name) => plan[name] ?? 0);
  const total = counts.reduce((a, b) => a + b, 0);
  const cum = boundaries(counts);

  if (total === 0 || splits.length < 2) return null;

  /** Move boundary `index` to `value`, taking from (or giving to) its two neighbours. */
  const setBoundary = (index: number, value: number) => {
    const low = index === 0 ? 0 : cum[index - 1]!;
    const high = cum[index + 1] ?? total;
    const at = Math.max(low, Math.min(high, Math.round(value)));
    const next = [...counts];
    next[index] = at - low;
    next[index + 1] = high - at;
    onChange(Object.fromEntries(names.map((name, i) => [name, next[i]!])));
  };

  const dragTo = (index: number, clientX: number) => {
    const rect = barRef.current?.getBoundingClientRect();
    if (!rect || rect.width === 0) return;
    setBoundary(index, ((clientX - rect.left) / rect.width) * total);
  };

  return (
    <div className={`split-slider${disabled ? " disabled" : ""}`}>
      <div className="split-slider-counts">
        {names.map((name, i) => (
          <div key={name} className="split-slider-count">
            <span className="split-slider-swatch" style={{ background: SEGMENT_COLORS[i % SEGMENT_COLORS.length] }} />
            <span className="strong">{name}</span>
            <span className="tabular">{formatNumber(counts[i]!)}</span>
            <span className="faint small tabular">{Math.round((counts[i]! / total) * 100)}%</span>
          </div>
        ))}
      </div>

      <div className="split-slider-bar" ref={barRef}>
        {names.map((name, i) => (
          <span
            key={name}
            className="split-slider-segment"
            style={{
              width: `${(counts[i]! / total) * 100}%`,
              background: SEGMENT_COLORS[i % SEGMENT_COLORS.length],
            }}
            title={`${name}: ${formatNumber(counts[i]!)}`}
          />
        ))}
        {names.slice(0, -1).map((name, i) => (
          <button
            key={name}
            type="button"
            className={`split-slider-handle${dragging === i ? " dragging" : ""}`}
            style={{ left: `${(cum[i]! / total) * 100}%` }}
            disabled={disabled}
            role="slider"
            aria-label={`Images in ${name}`}
            aria-valuemin={i === 0 ? 0 : cum[i - 1]!}
            aria-valuemax={cum[i + 1] ?? total}
            aria-valuenow={cum[i]!}
            aria-valuetext={`${formatNumber(counts[i]!)} images in ${name}`}
            onPointerDown={(event) => {
              if (disabled) return;
              event.preventDefault();
              event.currentTarget.setPointerCapture(event.pointerId);
              setDragging(i);
            }}
            onPointerMove={(event) => dragging === i && dragTo(i, event.clientX)}
            onPointerUp={(event) => {
              event.currentTarget.releasePointerCapture(event.pointerId);
              setDragging(null);
            }}
            onPointerCancel={() => setDragging(null)}
            onKeyDown={(event) => {
              const step = event.shiftKey ? 10 : 1;
              if (event.key === "ArrowLeft") setBoundary(i, cum[i]! - step);
              else if (event.key === "ArrowRight") setBoundary(i, cum[i]! + step);
              else return;
              event.preventDefault();
            }}
          />
        ))}
      </div>
    </div>
  );
}
