/** Edit a categorical column's classes: add, rename, recolour, remove unused. */

import { useMemo, useState } from "react";
import type { ValueMap } from "../api/types";
import { Modal } from "../components/Modal";
import { useStore } from "../store/store";

export function ClassesDialog({ column, onClose }: { column: string; onClose: () => void }) {
  const info = useStore((s) => s.columns.find((c) => c.name === column));
  const rows = useStore((s) => s.rows);
  const setClasses = useStore((s) => s.setClasses);
  const [draft, setDraft] = useState<ValueMap>(() => ({ ...(info?.value_map ?? {}) }));
  const [error, setError] = useState<string | null>(null);

  const usage = useMemo(() => {
    const counts = new Map<string, number>();
    for (const row of rows) {
      const key = String(row[column]);
      counts.set(key, (counts.get(key) ?? 0) + 1);
    }
    return counts;
  }, [rows, column]);

  const keys = Object.keys(draft).sort((a, b) => Number(a) - Number(b));
  const update = (key: string, field: "internal_name" | "display_name" | "color", value: string) =>
    setDraft((d) => ({ ...d, [key]: { ...d[key]!, [field]: value } }));

  const add = () => {
    const next = String(Math.max(-1, ...Object.keys(draft).map(Number), ...Object.keys(info?.value_map ?? {}).map(Number)) + 1);
    setDraft((d) => ({ ...d, [next]: { internal_name: "", display_name: "", color: "" } }));
  };

  const save = () => {
    const problem = setClasses(column, draft);
    if (problem) setError(problem);
    else onClose();
  };

  return (
    <Modal
      title={`Classes of "${column}"`}
      onClose={onClose}
      width={560}
      footer={
        <>
          <button onClick={add}>+ add class</button>
          <span className="spacer" />
          <button onClick={onClose}>cancel</button>
          <button className="primary" onClick={save}>apply</button>
        </>
      }
    >
      <table className="classes">
        <thead>
          <tr>
            <th>index</th><th>internal name</th><th>display name</th><th>colour</th><th>rows</th><th />
          </tr>
        </thead>
        <tbody>
          {keys.map((key) => {
            const entry = draft[key]!;
            const used = usage.get(key) ?? 0;
            return (
              <tr key={key}>
                <td className="num muted">{key}</td>
                <td>
                  <input type="text" value={entry.internal_name} onKeyDown={(e) => e.stopPropagation()}
                    onChange={(e) => update(key, "internal_name", e.target.value)} placeholder="required" />
                </td>
                <td>
                  <input type="text" value={entry.display_name} onKeyDown={(e) => e.stopPropagation()}
                    onChange={(e) => update(key, "display_name", e.target.value)} placeholder={entry.internal_name} />
                </td>
                <td>
                  <input type="color" value={/^#[0-9a-f]{6}$/i.test(entry.color) ? entry.color : "#888888"}
                    onChange={(e) => update(key, "color", e.target.value)} />
                </td>
                <td className="num muted">{used.toLocaleString()}</td>
                <td>
                  <button
                    disabled={used > 0}
                    title={used > 0 ? "Relabel the rows using this class before removing it" : "Remove this class"}
                    onClick={() => setDraft((d) => {
                      const next = { ...d };
                      delete next[key];
                      return next;
                    })}
                  >
                    remove
                  </button>
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
      <div className="muted note">Indices are what the data stores, so they never change; names are free to.</div>
      {error && <div className="form-error">{error}</div>}
    </Modal>
  );
}
