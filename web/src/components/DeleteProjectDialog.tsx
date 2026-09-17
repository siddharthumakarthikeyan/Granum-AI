/** Delete a project for good, after the name is typed again. */

import { useState } from "react";
import { api } from "../api/client";
import type { ProjectSummary } from "../api/types";
import { navigate } from "../router";
import { useStore } from "../store/store";
import { Modal } from "./Modal";
import { plural } from "./ui";

export function DeleteProjectDialog({ project, onClose }: { project: ProjectSummary; onClose: () => void }) {
  const [typed, setTyped] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const refreshProjects = useStore((s) => s.refreshProjects);
  const matches = typed === project.name;

  const remove = async () => {
    setBusy(true);
    setError(null);
    try {
      await api.deleteProject(project.name, typed);
      if (useStore.getState().project === project.name) {
        useStore.setState({ project: null, loadedProject: null, tables: [], runs: [], imports: [], lineageEdges: [] });
      }
      await refreshProjects();
      onClose();
      navigate({ name: "home" });
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
      setBusy(false);
    }
  };

  return (
    <Modal
      title={`Delete ${project.name}`}
      onClose={onClose}
      width={500}
      footer={
        <>
          <span className="spacer" />
          <button onClick={onClose}>Cancel</button>
          <button className="danger-solid" disabled={!matches || busy} onClick={() => void remove()}>
            {busy ? "Deleting" : "Delete project"}
          </button>
        </>
      }
    >
      <p className="delete-lead">
        This permanently deletes <strong>{project.name}</strong> from this computer. It cannot be undone.
      </p>
      <ul className="delete-list">
        <li>{plural(project.tables, "dataset version")} and {plural(project.runs, "training run")}</li>
        <li>Reviews, comments, shipments and import reports</li>
        <li>Model weights saved by this project's training runs</li>
      </ul>
      <p className="muted small">Your original image and annotation files are not deleted.</p>
      <label className="field delete-confirm">
        <span>Type <span className="mono strong">{project.name}</span> to confirm</span>
        <input
          type="text"
          autoFocus
          value={typed}
          onChange={(e) => setTyped(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && matches && !busy) void remove();
          }}
          spellCheck={false}
          autoComplete="off"
        />
      </label>
      {error && <p className="form-error">{error}</p>}
    </Modal>
  );
}
