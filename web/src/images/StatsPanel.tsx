/** What the selected images are made of, beside the images themselves.
 *
 * A panel rather than a page, because the numbers are of whatever the ribbon has left: change
 * a filter and they change with it, which is how a reader finds out that the class they are
 * missing is missing only from the validation set. Bars that correspond to a filter are
 * buttons — picking one narrows the gallery to it, and picking it again lets it go.
 *
 * No chart library: these are counts on one axis, and a bar is the honest drawing of a count.
 */

import { useMemo } from "react";
import type { ImageBoxes, ImageRow, QaState } from "../api/types";
import { Icon, formatNumber, plural } from "../components/ui";
import { labelColor } from "./labelColors";
import { type Bar, byBoxSize, byClass, byObjectCount, byStatus, bySet } from "./stats";

interface Props {
  /** The images the ribbon leaves, which is what most numbers here are about. */
  items: ImageRow[];
  /** The same images without the set filter, so every set is still a bar to pick. */
  acrossSets: ImageRow[];
  /** And without the class filter, for the same reason. */
  acrossClasses: ImageRow[];
  statuses: Record<string, QaState>;
  labels: Record<string, string>;
  /** Geometry for the images fetched so far: enough for box sizes, not for counts. */
  boxes: Record<string, ImageBoxes>;
  /** The ribbon's own state, so a bar can show as chosen and clicking it can clear it. */
  split: string;
  onSplit: (set: string) => void;
  classes: Set<number>;
  onClasses: (next: Set<number>) => void;
  onClose: () => void;
}

export function StatsPanel({ items, acrossSets, acrossClasses, statuses, labels, boxes, split, onSplit, classes, onClasses, onClose }: Props) {
  const sets = useMemo(() => bySet(acrossSets), [acrossSets]);
  const status = useMemo(() => byStatus(items, statuses), [items, statuses]);
  const objects = useMemo(() => byObjectCount(items), [items]);
  const perClass = useMemo(() => byClass(acrossClasses, labels, labelColor), [acrossClasses, labels]);
  const sizes = useMemo(() => byBoxSize(items, boxes), [items, boxes]);
  const total = items.reduce((sum, item) => sum + item.objects, 0);

  return (
    <aside className="qa-side stats-panel">
      <div className="qa-side-head">
        <span className="strong">{formatNumber(items.length)} images</span>
        <span className="muted small">{plural(total, "object")}</span>
        <span className="spacer" />
        <button className="icon-button" onClick={onClose} aria-label="Close"><Icon name="close" /></button>
      </div>

      <Section title="Sets">
        <Bars
          bars={sets}
          chosen={new Set(split === "all" ? [] : [split])}
          onPick={(key) => onSplit(split === key ? "all" : key)}
        />
      </Section>

      <Section title="Review">
        <Bars bars={status} />
      </Section>

      <Section title="Objects per image">
        <Bars bars={objects} />
      </Section>

      <Section title="Classes" note={`${formatNumber(perClass.length)} in these images`}>
        <Bars
          bars={perClass}
          chosen={new Set([...classes].map(String))}
          onPick={(key) => {
            const next = new Set(classes);
            const label = Number(key);
            if (next.has(label)) next.delete(label);
            else next.add(label);
            onClasses(next);
          }}
        />
      </Section>

      <Section
        title="Object size"
        note={sizes.images < items.length ? `${formatNumber(sizes.images)} images read` : undefined}
      >
        {sizes.objects === 0 ? (
          <p className="muted small">Reading the boxes of these images…</p>
        ) : (
          <>
            <Bars bars={sizes.bars} />
            <p className="faint small stats-note">
              Share of the image each box covers, over the {plural(sizes.objects, "object")} of the
              {" "}{formatNumber(sizes.images)} images whose boxes have been read so far.
            </p>
          </>
        )}
      </Section>
    </aside>
  );
}

function Section({ title, note, children }: { title: string; note?: string; children: React.ReactNode }) {
  return (
    <div className="qa-side-section">
      <h3 className="qa-side-title">
        {title}
        {note && <span className="faint">{note}</span>}
      </h3>
      {children}
    </div>
  );
}

/** Counts as bars, widest first where the order is by count, against the largest of them. */
function Bars({ bars, chosen, onPick }: { bars: Bar[]; chosen?: Set<string>; onPick?: (key: string) => void }) {
  const top = Math.max(1, ...bars.map((bar) => bar.count));
  if (bars.length === 0) return <p className="muted small">Nothing here.</p>;
  return (
    <ul className="stat-bars">
      {bars.map((bar) => {
        const on = chosen?.has(bar.key) ?? false;
        const row = (
          <>
            {bar.colour && <span className="class-swatch" style={{ background: bar.colour }} />}
            <span className="truncate small">{bar.label}</span>
            <span className="stat-bar-track"><span className="stat-bar-fill" style={{ width: `${(bar.count / top) * 100}%` }} /></span>
            <span className="faint small tabular">{formatNumber(bar.count)}</span>
          </>
        );
        return (
          <li key={bar.key}>
            {onPick ? (
              <button
                className={`stat-bar${on ? " on" : ""}`}
                aria-pressed={on}
                onClick={() => onPick(bar.key)}
                title={on ? "Show them all again" : `Show only ${bar.label}`}
              >
                {row}
              </button>
            ) : (
              <span className="stat-bar">{row}</span>
            )}
          </li>
        );
      })}
    </ul>
  );
}
