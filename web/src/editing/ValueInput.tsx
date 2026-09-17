/** An input for one value of one column, shaped by the column's type. */

import { useEffect, useRef, useState } from "react";
import type { ColumnInfo } from "../api/types";
import { className, parseCellInput } from "../store/editing";

interface Props {
  column: ColumnInfo;
  value: unknown;
  /** Called with a parsed, valid value. */
  onCommit: (value: unknown) => void;
  onCancel?: () => void;
  autoFocus?: boolean;
  /** Commit on every change rather than on Enter / blur (for bulk-assign pickers). */
  immediate?: boolean;
}

export function ValueInput({ column, value, onCommit, onCancel, autoFocus, immediate }: Props) {
  const [text, setText] = useState(value === null || value === undefined ? "" : String(value));
  const [error, setError] = useState<string | null>(null);
  const ref = useRef<HTMLInputElement & HTMLSelectElement>(null);
  const done = useRef(false);

  useEffect(() => {
    if (autoFocus) {
      ref.current?.focus();
      if (ref.current instanceof HTMLInputElement) ref.current.select();
    }
  }, [autoFocus]);

  useEffect(() => {
    setText(value === null || value === undefined ? "" : String(value));
  }, [value]);

  const keys = (event: React.KeyboardEvent) => {
    event.stopPropagation(); // typing must not trigger dashboard shortcuts
    if (event.key === "Escape") {
      done.current = true;
      onCancel?.();
    }
    if (event.key === "Enter") submit(text);
  };

  const submit = (raw: string) => {
    if (done.current && !immediate) return;
    const parsed = parseCellInput(column, raw);
    if ("error" in parsed) {
      setError(`expected ${parsed.error}`);
      return;
    }
    if (!immediate) done.current = true;
    setError(null);
    onCommit(parsed.value);
  };

  if (column.kind === "categorical_label" || column.kind === "bool") {
    const options =
      column.kind === "bool"
        ? [["true", "true"], ["false", "false"]]
        : Object.keys(column.value_map ?? {})
            .sort((a, b) => Number(a) - Number(b))
            .map((key) => [key, `${className(column, Number(key))} (${key})`]);
    return (
      <select
        ref={ref}
        className="value-input"
        value={text}
        onKeyDown={keys}
        onChange={(e) => {
          setText(e.target.value);
          submit(e.target.value);
        }}
        onBlur={() => !immediate && onCancel?.()}
      >
        {!options.some(([key]) => key === text) && <option value={text}>{text === "" ? "choose…" : text}</option>}
        {options.map(([key, label]) => (
          <option key={key} value={key}>{label}</option>
        ))}
      </select>
    );
  }

  return (
    <span className="value-input-wrap">
      <input
        ref={ref}
        className={`value-input${error ? " invalid" : ""}`}
        type="text"
        inputMode={column.kind === "string" ? "text" : "decimal"}
        value={text}
        title={error ?? undefined}
        onChange={(e) => {
          setText(e.target.value);
          setError(null);
          if (immediate) submit(e.target.value);
        }}
        onKeyDown={keys}
        onBlur={() => (immediate ? undefined : submit(text))}
      />
      {error && <span className="value-error">{error}</span>}
    </span>
  );
}
