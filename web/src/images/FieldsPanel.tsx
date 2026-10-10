/** The Fields panel: a control for every column the set actually has.
 *
 * Until this existed the ribbon asked four questions -- which set, which class, which review
 * status, which tag -- and a dataset that carried a capture time, a camera, a city or a
 * weight had no way to be asked about any of it. The controls here are not written one by
 * one: `/api/images` describes the set's columns and this builds a widget from each
 * descriptor, so a column that arrives in an import next week is filterable the day it
 * lands and nothing here changes.
 *
 * Each widget counts against the images the *other* filters leave, which is what makes a
 * narrowing legible -- the dark part of a bar is what this filter excluded, the gap to full
 * height is what the rest of the ribbon did. Opening a field's summary gives the numbers
 * FiftyOne calls aggregations: bounds, mean, deviation, quantiles and distinct values, over
 * whatever is on screen rather than over the whole column.
 */

import { useMemo, useState } from "react";
import type { FieldInfo, ImageRow } from "../api/types";
import { Icon, formatNumber, plural } from "../components/ui";
import {
  displayValue,
  fieldFilterActive,
  fieldHistogram,
  fieldValueCounts,
  filterByFields,
  summarizeField,
  type FieldFilter,
  type NumberFieldFilter,
  type TextFieldFilter,
  type ValueFieldFilter,
} from "./fields";

interface Props {
  fields: FieldInfo[];
  filters: Record<string, FieldFilter>;
  /** The images before any field filter, but after the rest of the ribbon. */
  items: ImageRow[];
  onChange: (name: string, changes: Partial<FieldFilter>) => void;
  onReset: (name: string) => void;
  onClearAll: () => void;
  onClose: () => void;
}

export function FieldsPanel({ fields, filters, items, onChange, onReset, onClearAll, onClose }: Props) {
  const active = Object.values(filters).filter(fieldFilterActive).length;
  const ordered = useMemo(
    () => [...fields].sort((a, b) => Number(Boolean(a.identifier)) - Number(Boolean(b.identifier))),
    [fields],
  );
  const firstIdentifier = ordered.findIndex((field) => field.identifier);

  return (
    <aside className="qa-side fields-panel">
      <div className="qa-side-head">
        <span className="strong">Fields</span>
        <span className="muted small">{active > 0 ? `${active} in use` : plural(fields.length, "column")}</span>
        <span className="spacer" />
        {active > 0 && <button className="button subtle" onClick={onClearAll}>Clear</button>}
        <button className="icon-button" onClick={onClose} aria-label="Close"><Icon name="close" /></button>
      </div>

      {fields.length === 0 ? (
        <p className="muted small qa-side-empty">
          This dataset's sets carry nothing beside the images and their boxes. Columns from an
          import — a capture time, a camera, a city, a weight — appear here.
        </p>
      ) : (
        ordered.map((field, at) => (
          <div key={field.name}>
            {at === firstIdentifier && firstIdentifier > 0 && (
              <div className="fields-divider">Identifiers</div>
            )}
            <FieldWidget
              field={field}
              filter={filters[field.name]}
              items={items}
              filters={filters}
              onChange={onChange}
              onReset={onReset}
            />
          </div>
        ))
      )}
    </aside>
  );
}

function FieldWidget({ field, filter, items, filters, onChange, onReset }: {
  field: FieldInfo;
  filter: FieldFilter | undefined;
  items: ImageRow[];
  filters: Record<string, FieldFilter>;
  onChange: (name: string, changes: Partial<FieldFilter>) => void;
  onReset: (name: string) => void;
}) {
  const [summary, setSummary] = useState(false);
  // Counted against the images the other filters leave: a widget that counted its own
  // choice would show one value with everything in it and the rest at zero.
  const others = useMemo(() => filterByFields(items, filters, field.name), [items, filters, field.name]);
  const active = filter ? fieldFilterActive(filter) : false;

  if (!filter) {
    return (
      <div className="field-widget">
        <div className="field-head">
          <span className="name">{field.label}</span>
          <span className="faint small">nothing here</span>
        </div>
      </div>
    );
  }

  return (
    <div className={`field-widget${active ? " on" : ""}`}>
      <div className="field-head" title={field.detail}>
        {active && <span className="dot" />}
        <span className="name">{field.label}</span>
        <span className="spacer" />
        <button
          className={`icon-button${summary ? " on" : ""}`}
          onClick={() => setSummary(!summary)}
          aria-pressed={summary}
          title="Bounds, mean, deviation, quantiles and distinct values over the images on screen"
        >
          <Icon name="runs" size={13} />
        </button>
        {active && (
          <button className="icon-button" onClick={() => onReset(field.name)} title="Reset this field">↺</button>
        )}
      </div>

      {filter.kind === "number" ? (
        <NumberWidget field={field} filter={filter} items={others} onChange={onChange} />
      ) : filter.kind === "text" ? (
        <TextWidget field={field} filter={filter} items={others} onChange={onChange} />
      ) : (
        <ValueWidget field={field} filter={filter} items={others} onChange={onChange} />
      )}

      {field.present < items.length && (
        <button
          className={`field-missing${filter.withoutValue ? "" : " off"}`}
          aria-pressed={!filter.withoutValue}
          onClick={() => onChange(field.name, { withoutValue: !filter.withoutValue })}
          title={filter.withoutValue
            ? "Images with no value for this field are shown — click to hide them"
            : "Images with no value for this field are hidden — click to show them"}
        >
          <span className="value-check" aria-hidden="true" />
          Images with no value
        </button>
      )}

      {summary && <FieldSummaryRows field={field} items={others} />}
    </div>
  );
}

function NumberWidget({ field, filter, items, onChange }: {
  field: FieldInfo;
  filter: NumberFieldFilter;
  items: ImageRow[];
  onChange: (name: string, changes: Partial<FieldFilter>) => void;
}) {
  const bins = useMemo(() => fieldHistogram(items, filter), [items, filter]);
  const peak = Math.max(1, ...bins.map((bin) => bin.total));
  const [lo, hi] = filter.bounds;
  const step = (hi - lo) / 1000 || 1;
  const flat = lo === hi;

  return (
    <>
      <div className="histogram" aria-hidden="true">
        {bins.map((bin, at) => {
          const height = (bin.total / peak) * 100;
          const share = bin.total > 0 ? bin.shown / bin.total : 0;
          return (
            <div className="bin" key={at} title={`${round(bin.lo)} – ${round(bin.hi)}\n${formatNumber(bin.shown)} of ${formatNumber(bin.total)} shown`}>
              <div className="out" style={{ height: `${height * (1 - share)}%` }} />
              <div className="in" style={{ height: `${height * share}%` }} />
            </div>
          );
        })}
      </div>
      <div className="range-row">
        <input
          type="number"
          step={step}
          value={Number(filter.range[0].toFixed(4))}
          disabled={flat}
          aria-label={`${field.label} from`}
          onChange={(e) => onChange(field.name, { range: [Number(e.target.value), filter.range[1]] } as Partial<FieldFilter>)}
        />
        <span className="to">–</span>
        <input
          type="number"
          step={step}
          value={Number(filter.range[1].toFixed(4))}
          disabled={flat}
          aria-label={`${field.label} to`}
          onChange={(e) => onChange(field.name, { range: [filter.range[0], Number(e.target.value)] } as Partial<FieldFilter>)}
        />
      </div>
    </>
  );
}

function ValueWidget({ field, filter, items, onChange }: {
  field: FieldInfo;
  filter: ValueFieldFilter;
  items: ImageRow[];
  onChange: (name: string, changes: Partial<FieldFilter>) => void;
}) {
  const { counts } = useMemo(() => fieldValueCounts(items, field.name), [items, field.name]);
  const ranked = useMemo(
    () => [...filter.values].sort((a, b) => (counts.get(String(b)) ?? 0) - (counts.get(String(a)) ?? 0)),
    [filter.values, counts],
  );
  const peak = Math.max(1, ...ranked.map((value) => counts.get(String(value)) ?? 0));

  const toggle = (key: string) => {
    const excluded = filter.excluded.includes(key)
      ? filter.excluded.filter((v) => v !== key)
      : [...filter.excluded, key];
    onChange(field.name, { excluded } as Partial<FieldFilter>);
  };

  return (
    <div className={`value-list${ranked.length > 12 ? " scrolls" : ""}`}>
      {ranked.map((value) => {
        const key = String(value);
        const off = filter.excluded.includes(key);
        const count = counts.get(key) ?? 0;
        return (
          <button
            key={key}
            className={`value-row${off ? " off" : ""}`}
            aria-pressed={!off}
            onClick={(e) => {
              // Double-click, or alt-click, is "only this one" -- the fastest way to a
              // single value when a column has twenty.
              if (e.altKey || e.detail === 2) {
                onChange(field.name, { excluded: filter.values.map(String).filter((v) => v !== key) } as Partial<FieldFilter>);
              } else toggle(key);
            }}
            title={`${displayValue(field, value)}: click to ${off ? "include" : "exclude"}, double-click to show only this`}
          >
            <span className="value-check" aria-hidden="true" />
            <span className="value-name">{displayValue(field, value)}</span>
            <span className="value-count">{formatNumber(count)}</span>
            <span className="value-bar" aria-hidden="true"><span style={{ width: `${(count / peak) * 100}%` }} /></span>
          </button>
        );
      })}
    </div>
  );
}

/** A column with thousands of values -- file names, hashes, free text -- asked as a search.
 *
 * A list of six thousand file names is not a control. What a reader actually wants of a path
 * column is "the ones from this flight", and that is a substring.
 */
function TextWidget({ field, filter, items, onChange }: {
  field: FieldInfo;
  filter: TextFieldFilter;
  items: ImageRow[];
  onChange: (name: string, changes: Partial<FieldFilter>) => void;
}) {
  const matched = useMemo(() => {
    const query = filter.query.trim().toLowerCase();
    if (!query) return null;
    let count = 0;
    for (const item of items) {
      const value = item.values?.[field.name];
      if (value !== undefined && String(value).toLowerCase().includes(query)) count += 1;
    }
    return count;
  }, [items, field.name, filter.query]);

  return (
    <div className="field-text">
      <input
        type="text"
        value={filter.query}
        placeholder="contains…"
        aria-label={`${field.label} contains`}
        onChange={(e) => onChange(field.name, { query: e.target.value } as Partial<FieldFilter>)}
      />
      <span className="faint small">
        {matched === null
          ? `${formatNumber(field.distinct ?? 0)} values`
          : `${formatNumber(matched)} of ${formatNumber(items.length)}`}
      </span>
    </div>
  );
}

/** What the column adds up to over the images on screen: FiftyOne's aggregations. */
function FieldSummaryRows({ field, items }: { field: FieldInfo; items: ImageRow[] }) {
  const summary = useMemo(() => summarizeField(items, field.name), [items, field.name]);
  const rows: [string, string][] = [
    ["Images", formatNumber(summary.count)],
    ["With a value", formatNumber(summary.present)],
    ["Distinct", formatNumber(summary.distinct)],
  ];
  if (summary.missing > 0) rows.splice(2, 0, ["Missing", formatNumber(summary.missing)]);
  if (summary.min !== undefined) {
    rows.push(
      ["Bounds", `${round(summary.min)} – ${round(summary.max!)}`],
      ["Mean", round(summary.mean!)],
      ["Deviation", round(summary.std!)],
      ["Median", round(summary.quantiles!["0.5"]!)],
      ["Quartiles", `${round(summary.quantiles!["0.25"]!)} · ${round(summary.quantiles!["0.75"]!)}`],
      ["Sum", round(summary.sum!)],
    );
  }
  return (
    <dl className="field-summary">
      {rows.map(([label, value]) => (
        <div key={label}>
          <dt>{label}</dt>
          <dd className="tabular">{value}</dd>
        </div>
      ))}
      {summary.min === undefined && summary.top.length > 0 && (
        <div className="field-summary-top">
          <dt>Commonest</dt>
          <dd>{summary.top.slice(0, 3).map((entry) => `${displayValue(field, entry.value)} (${formatNumber(entry.count)})`).join(", ")}</dd>
        </div>
      )}
    </dl>
  );
}

function round(value: number): string {
  if (!Number.isFinite(value)) return "—";
  if (Number.isInteger(value)) return formatNumber(value);
  const scale = Math.abs(value) >= 100 ? 1 : Math.abs(value) >= 1 ? 2 : 4;
  return Number(value.toFixed(scale)).toLocaleString("en-US");
}
