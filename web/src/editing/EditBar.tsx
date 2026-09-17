/** Pending-edit status and actions, in the top bar whenever an object is open. */

import { useEffect, useMemo, useState } from "react";
import { editCount } from "../store/editing";
import { useStore } from "../store/store";

export function EditBar({ onCommit }: { onCommit: () => void }) {
  const undoStack = useStore((s) => s.undoStack);
  const redoStack = useStore((s) => s.redoStack);
  const pendingEdits = useStore((s) => s.pendingEdits);
  const undo = useStore((s) => s.undo);
  const redo = useStore((s) => s.redo);
  const discardAll = useStore((s) => s.discardAll);
  const force = useStore((s) => s.forceWeightOnCorrection);
  const setForce = useStore((s) => s.setForceWeight);
  const hasEditable = useStore((s) => s.columns.some((c) => c.writable && c.source === "table"));
  const [armed, setArmed] = useState(false);

  const count = useMemo(() => editCount(pendingEdits()), [pendingEdits, undoStack]);
  useEffect(() => {
    if (!armed) return;
    const timer = window.setTimeout(() => setArmed(false), 3000);
    return () => window.clearTimeout(timer);
  }, [armed]);

  if (!hasEditable && undoStack.length === 0) return null;
  const last = undoStack[undoStack.length - 1];
  const next = redoStack[redoStack.length - 1];

  return (
    <div className={`edit-bar${count > 0 ? " dirty" : ""}`}>
      <span className="count" title={count > 0 ? "Uncommitted edits" : "No uncommitted edits"}>
        {count === 0 ? "No unsaved changes" : `${count} unsaved change${count === 1 ? "" : "s"}`}
      </span>
      <button onClick={undo} disabled={!last} title={last ? `Undo: ${last.label} (Ctrl+Z)` : "Nothing to undo"}>Undo</button>
      <button onClick={redo} disabled={!next} title={next ? `Redo: ${next.label} (Ctrl+Shift+Z)` : "Nothing to redo"}>Redo</button>
      <button
        className={force ? "on" : ""}
        onClick={() => setForce(!force)}
        title={force
          ? "On: editing a row with weight 0 sets its weight back to 1"
          : "Off: edits leave weights unchanged"}
      >
        Reweight on edit
      </button>
      {count > 0 && (
        <button
          className={armed ? "danger" : ""}
          onClick={() => {
            if (!armed) {
              setArmed(true);
              return;
            }
            setArmed(false);
            discardAll();
          }}
          title="Throw away every unsaved change"
        >
          {armed ? `Click again to discard ${count}` : "Discard"}
        </button>
      )}
      <button className="primary" disabled={count === 0} onClick={onCommit} title="Review your changes and save them as a new version (Ctrl+S)">
        Save changes
      </button>
    </div>
  );
}
