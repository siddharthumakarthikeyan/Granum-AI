/** Delete a dataset version, after saying what goes with it and which runs used it. */

import { useEffect, useState } from "react";
import { api } from "../api/client";
import type { Release } from "../api/types";
import { Modal } from "../components/Modal";
import { formatBytes, formatNumber, plural } from "../components/ui";
import { readReviewer } from "../review/status";

export function DeleteReleaseDialog({ project, release, onClose, onDeleted }: {
  project: string;
  release: Release;
  onClose: () => void;
  onDeleted: () => void;
}) {
  const [usage, setUsage] = useState<{ files: number; bytes: number; runs: string[] } | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api.releaseUsage(project, release.dataset, release.id).then(setUsage).catch((e: Error) => setError(e.message));
  }, [project, release.dataset, release.id]);

  const remove = async () => {
    setBusy(true);
    setError(null);
    try {
      await api.deleteRelease({ project, dataset: release.dataset, release_id: release.id, author: readReviewer() });
      onDeleted();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
      setBusy(false);
    }
  };

  const augmented = Object.values(release.sets).reduce((n, s) => n + (s.augmented ?? 0), 0);

  return (
    <Modal
      title={`Delete ${release.name}`}
      onClose={onClose}
      width={500}
      footer={
        <>
          <span className="spacer" />
          <button onClick={onClose}>Cancel</button>
          <button className="danger-solid" disabled={busy || !usage} onClick={() => void remove()}>
            {busy ? "Deleting" : "Delete version"}
          </button>
        </>
      }
    >
      <p className="delete-lead">
        This permanently deletes dataset version <strong>v{release.version} · {release.name}</strong>. It cannot be undone.
      </p>
      <ul className="delete-list">
        {usage === null ? (
          <li>Checking what it holds</li>
        ) : usage.files > 0 ? (
          <li>
            {augmented > 0 ? `${formatNumber(augmented)} augmented images and the` : "The"} set copies made for this version
            {" "}({plural(usage.files, "file")}, {formatBytes(usage.bytes)})
          </li>
        ) : (
          <li>Its entry only: it used the dataset's sets as they are, so no files are removed</li>
        )}
      </ul>
      <p className="muted small">Images and labels in the dataset itself are not changed.</p>
      {usage && usage.runs.length > 0 && (
        <div className="release-warning" role="alert">
          <div>
            <strong>Used by {plural(usage.runs.length, "training run")}: {usage.runs.join(", ")}</strong>
            <div className="muted small">The runs keep their scores and weights, but the images they trained on can no longer be opened from them.</div>
          </div>
        </div>
      )}
      {error && <p className="form-error">{error}</p>}
    </Modal>
  );
}
