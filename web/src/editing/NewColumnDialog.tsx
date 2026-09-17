/** Create an editable column: a checkbox to mark reviewed samples, a free-text note. */

import { useState } from "react";
import { Modal } from "../components/Modal";
import { defaultFor, EDITABLE_KINDS, parseCellInput, type EditableKind } from "../store/editing";
import { useStore } from "../store/store";

export function NewColumnDialog({ onClose }: { onClose: () => void }) {
  const addColumn = useStore((s) => s.addColumn);
  const [name, setName] = useState("");
  const [kind, setKind] = useState<EditableKind>("bool");
  const [initial, setInitial] = useState(String(defaultFor("bool")));
  const [error, setError] = useState<string | null>(null);

  const create = () => {
    const parsed = parseCellInput({ name, kind, writable: true, default_visible: true, number_role: null }, initial);
    if ("error" in parsed) {
      setError(`default must be ${parsed.error}`);
      return;
    }
    const problem = addColumn(name, kind, parsed.value);
    if (problem) setError(problem);
    else onClose();
  };

  return (
    <Modal
      title="New column"
      onClose={onClose}
      width={380}
      footer={
        <>
          <span className="spacer" />
          <button onClick={onClose}>cancel</button>
          <button className="primary" onClick={create}>create</button>
        </>
      }
    >
      <label className="field">
        <span>name</span>
        <input type="text" value={name} autoFocus placeholder="e.g. reviewed"
          onChange={(e) => setName(e.target.value)}
          onKeyDown={(e) => { e.stopPropagation(); if (e.key === "Enter") create(); }} />
      </label>
      <label className="field">
        <span>type</span>
        <select value={kind} onChange={(e) => {
          const next = e.target.value as EditableKind;
          setKind(next);
          setInitial(String(defaultFor(next)));
        }}>
          {EDITABLE_KINDS.map((k) => <option key={k} value={k}>{k}</option>)}
        </select>
      </label>
      <label className="field">
        <span>value for every row</span>
        <input type="text" value={initial} onChange={(e) => setInitial(e.target.value)}
          onKeyDown={(e) => { e.stopPropagation(); if (e.key === "Enter") create(); }} />
      </label>
      {error && <div className="form-error">{error}</div>}
    </Modal>
  );
}
