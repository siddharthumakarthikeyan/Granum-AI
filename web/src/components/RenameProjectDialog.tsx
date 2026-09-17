/** Rename a project. Everything recorded inside it follows the new name. */

import { useState } from "react";
import { api } from "../api/client";
import { navigate } from "../router";
import { useStore } from "../store/store";
import { Modal } from "./Modal";

const VALID = /^[A-Za-z0-9._\- ]+$/;

function problemWith(name: string, current: string, taken: string[]): string | null {
  const trimmed = name.trim();
  if (!trimmed) return "Enter a name.";
  if (trimmed === current) return null;
  if (trimmed.length > 80) return "At most 80 characters.";
  if (!VALID.test(trimmed)) return "Use letters, numbers, spaces, dots, dashes and underscores.";
  if (/^[ .-]|[ .-]$/.test(trimmed)) return "Cannot start or end with a space, dot or dash.";
  if (taken.some((t) => t.toLowerCase() === trimmed.toLowerCase())) return "A project with this name already exists.";
  return null;
}

export function RenameProjectDialog({ project, onClose }: { project: string; onClose: () => void }) {
  const projects = useStore((s) => s.projects);
  const refreshProjects = useStore((s) => s.refreshProjects);
  const openProject = useStore((s) => s.openProject);
  const [name, setName] = useState(project);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const taken = projects.map((p) => p.name).filter((n) => n !== project);
  const problem = problemWith(name, project, taken);
  const unchanged = name.trim() === project;

  const rename = async () => {
    if (problem || unchanged) return;
    setBusy(true);
    setError(null);
    try {
      const done = await api.renameProject(project, name.trim());
      const wasOpen = useStore.getState().project === project;
      await refreshProjects();
      onClose();
      if (wasOpen) {
        await openProject(done.name);
        navigate({ name: "overview", project: done.name }, { replace: true });
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
      setBusy(false);
    }
  };

  return (
    <Modal
      title={`Rename ${project}`}
      onClose={onClose}
      width={460}
      footer={
        <>
          <span className="spacer" />
          <button onClick={onClose}>Cancel</button>
          <button className="primary" disabled={Boolean(problem) || unchanged || busy} onClick={() => void rename()}>
            {busy ? "Renaming" : "Rename"}
          </button>
        </>
      }
    >
      <label className="field">
        <span>Project name</span>
        <input
          type="text"
          autoFocus
          value={name}
          maxLength={80}
          spellCheck={false}
          autoComplete="off"
          onFocus={(e) => e.target.select()}
          onChange={(e) => setName(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter") void rename();
          }}
        />
      </label>
      {problem && !unchanged ? <p className="form-error">{problem}</p> : (
        <p className="muted small rename-note">Datasets, versions, runs, reviews and shipments move with the project. Image files are not affected.</p>
      )}
      {error && <p className="form-error">{error}</p>}
    </Modal>
  );
}
