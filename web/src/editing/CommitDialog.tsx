/** Review the session's edits, discard any group, and write them as a new revision. */

import { useMemo, useState } from "react";
import { Modal } from "../components/Modal";
import { editCount, groupEdits } from "../store/editing";
import { useStore } from "../store/store";

function shortName(url: string): string {
  const parts = url.split("/");
  return parts.slice(-1)[0] ?? url;
}

export function CommitDialog({ onClose, onToast }: { onClose: () => void; onToast: (m: string) => void }) {
  const undoStack = useStore((s) => s.undoStack);
  const pendingEdits = useStore((s) => s.pendingEdits);
  const discardGroup = useStore((s) => s.discardGroup);
  const commit = useStore((s) => s.commit);
  const committing = useStore((s) => s.committing);
  const sourceKind = useStore((s) => s.sourceKind);

  const net = useMemo(() => pendingEdits(), [pendingEdits, undoStack]);
  const groups = useMemo(() => groupEdits(net), [net]);
  const tables = [...new Set(groups.map((g) => g.table))];
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [error, setError] = useState<string | null>(null);

  const submit = async () => {
    setError(null);
    const { results, error: failure } = await commit(name, description);
    if (failure) {
      setError(failure);
      return;
    }
    onToast(`Saved as new version ${results.map((r) => r.name).join(", ")}${sourceKind === "run" ? ". This run now shows it" : ""}`);
    onClose();
  };

  const count = editCount(net);

  return (
    <Modal
      title="Save changes as a new version"
      onClose={onClose}
      width={520}
      footer={
        <>
          <span className="muted">
            {count === 0 ? "Nothing to save" : `${count} change${count === 1 ? "" : "s"}, saved as ${tables.length} new version${tables.length === 1 ? "" : "s"}`}
          </span>
          <span className="spacer" />
          <button onClick={onClose}>Keep editing</button>
          <button className="primary" disabled={count === 0 || committing} onClick={() => void submit()}>
            {committing ? "Saving" : "Save"}
          </button>
        </>
      }
    >
      {tables.map((table) => (
        <div key={table} className="commit-table">
          <div className="commit-table-name" title={table}>
            New version of <b>{shortName(table)}</b>
          </div>
          {groups
            .filter((g) => g.table === table)
            .map((group) => (
              <div key={group.key} className={`commit-group ${group.category}`}>
                <span className="title">{group.title}</span>
                <button
                  onClick={() => discardGroup(group)}
                  title={group.category === "column" ? "Discard this column and every value set in it" : "Discard these edits"}
                >
                  Undo this
                </button>
              </div>
            ))}
        </div>
      ))}
      <label className="field">
        <span>Version name <span className="muted">(optional)</span></span>
        <input
          type="text"
          value={name}
          placeholder="for example: fixed-car-labels"
          onChange={(e) => setName(e.target.value)}
          onKeyDown={(e) => e.stopPropagation()}
          autoFocus
        />
      </label>
      <label className="field">
        <span>What did you change, and why? <span className="muted">(optional, helps your team)</span></span>
        <textarea
          rows={2}
          value={description}
          placeholder="for example: relabelled vans that were marked as cars"
          onChange={(e) => setDescription(e.target.value)}
          onKeyDown={(e) => e.stopPropagation()}
        />
      </label>
      <div className="muted note">
        The current version stays exactly as it is; your changes go into a new version on top of it. The next training run uses the newest version automatically.
      </div>
      {error && <div className="form-error">{error}</div>}
    </Modal>
  );
}
