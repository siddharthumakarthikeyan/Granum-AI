/** Set a value on every selected row at once: the fast path for correcting labels. */

import { useEffect, useMemo, useState } from "react";
import { isCellEditable } from "../store/editing";
import { useStore } from "../store/store";
import { ClassesDialog } from "./ClassesDialog";
import { ValueInput } from "./ValueInput";
import { columnLabel } from "../copy/plain";

export function AssignBar({ onToast }: { onToast: (m: string) => void }) {
  const columns = useStore((s) => s.columns);
  const selection = useStore((s) => s.selection);
  const rows = useStore((s) => s.rows);
  const editCells = useStore((s) => s.editCells);
  const toggleWeights = useStore((s) => s.toggleWeights);

  const editable = useMemo(() => columns.filter(isCellEditable), [columns]);
  const preferred = editable.find((c) => c.kind === "categorical_label") ?? editable[0];
  const [columnName, setColumnName] = useState<string | undefined>(preferred?.name);
  const [value, setValue] = useState<unknown>(undefined);
  const [classesOpen, setClassesOpen] = useState(false);

  useEffect(() => {
    if (!editable.some((c) => c.name === columnName)) setColumnName(preferred?.name);
  }, [editable, columnName, preferred]);

  const column = editable.find((c) => c.name === columnName);
  const selected = [...selection.rows];
  const weight = editable.find((c) => c.kind === "sample_weight");
  if (!column) return null;
  if (selected.length === 0) {
    // The bar keeps its height when empty. If it appeared on the first click of a
    // double-click, the table would shift and the second click would land a row higher.
    return (
      <div className="assign-bar idle">
        <span className="muted">
          Select rows to set <b>{editable.map((c) => columnLabel(c.name)).join(", ")}</b> in bulk, or double-click a cell. <kbd>W</kbd> toggles weight.
        </span>
      </div>
    );
  }

  // Seed the picker with the anchor row's current value so "assign" is never blind.
  const anchorValue = selection.anchor !== null ? rows[selection.anchor]?.[column.name] : undefined;

  const assign = () => {
    const chosen = value === undefined ? anchorValue : value;
    if (chosen === undefined) {
      onToast("Pick a value to assign");
      return;
    }
    const problem = editCells(column.name, selected, chosen);
    if (problem) onToast(problem);
  };

  return (
    <div className="assign-bar">
      <span className="muted">For the {selected.length.toLocaleString()} selected, set</span>
      <select value={column.name} onChange={(e) => { setColumnName(e.target.value); setValue(undefined); }}>
        {editable.map((c) => <option key={c.name} value={c.name}>{columnLabel(c.name)}</option>)}
      </select>
      <span className="eq">to</span>
      <ValueInput
        key={`${column.name}:${selection.anchor}`}
        column={column}
        value={value === undefined ? anchorValue : value}
        onCommit={setValue}
        immediate
      />
      <button className="primary" onClick={assign} title="Apply to every selected image">Apply</button>
      {column.kind === "categorical_label" && (
        <button onClick={() => setClassesOpen(true)} title="Add, rename or recolour labels">Edit labels</button>
      )}
      {weight && (
        <>
          <span className="sep" />
          <button onClick={() => editCells(weight.name, selected, 0)} title="The model will not train on these images">Don't use in training</button>
          <button onClick={() => editCells(weight.name, selected, 1)} title="The model will train on these images">Use in training</button>
          <button onClick={() => { const p = toggleWeights(selected); if (p) onToast(p); }} title="Toggle weight between 0 and 1 (W)">
            <kbd>W</kbd>
          </button>
        </>
      )}
      {classesOpen && <ClassesDialog column={column.name} onClose={() => setClassesOpen(false)} />}
    </div>
  );
}
