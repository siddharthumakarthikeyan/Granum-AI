/** Create a dataset version: a named, frozen snapshot of every set, the only data training uses.
 *
 * With unverified images left, the dialog says how many and asks whether to take the whole
 * dataset or only its verified images (see POST /api/qa/release). It then asks whether to
 * augment the train set (AugmentationPanel); augmenting runs as a job followed here.
 */

import { useEffect, useMemo, useRef, useState } from "react";
import { api } from "../api/client";
import type { ImageRow, Job, QaState, Release, TaskId } from "../api/types";
import { Modal } from "../components/Modal";
import { Icon, formatNumber, plural } from "../components/ui";
import { AugmentationPanel, NO_AUGMENTATION, augmentationProblem, recipeOf, type AugmentationState } from "./AugmentationPanel";
import { isVerified } from "./ImagesPage";

type Mode = "all" | "verified";

export function CreateDatasetDialog({ project, dataset, images, statuses, author, labels, tasks, onClose, onCreated }: {
  project: string;
  dataset: string;
  /** Class index -> name, for the augmentation preview. */
  labels: Record<string, string>;
  tasks?: TaskId[];
  /** The images of the train/valid/test sets, without isolated ones. */
  images: ImageRow[];
  statuses: Record<string, QaState>;
  author: string;
  onClose: () => void;
  onCreated: (release: Release) => void;
}) {
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [mode, setMode] = useState<Mode>("verified");
  const [existing, setExisting] = useState<Release[] | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [augmentation, setAugmentation] = useState<AugmentationState>(NO_AUGMENTATION);
  const [job, setJob] = useState<Job<{ release: Release }> | null>(null);
  const alive = useRef(true);
  useEffect(() => () => {
    alive.current = false;
  }, []);

  useEffect(() => {
    api.releases(project)
      .then(({ releases }) => {
        const own = releases.filter((r) => r.dataset === dataset);
        setExisting(own);
        setName((was) => was || `${dataset} v${own.length + 1}`);
      })
      .catch(() => setExisting([]));
  }, [project, dataset]);

  const bySet = useMemo(() => {
    const out = new Map<string, { total: number; verified: number; rework: number }>();
    for (const image of images) {
      const row = out.get(image.set) ?? { total: 0, verified: 0, rework: 0 };
      row.total += 1;
      if (isVerified(statuses[image.image])) row.verified += 1;
      else if (statuses[image.image]?.status === "rework") row.rework += 1;
      out.set(image.set, row);
    }
    return [...out.entries()];
  }, [images, statuses]);

  const total = images.length;
  const verified = bySet.reduce((n, [, r]) => n + r.verified, 0);
  const rework = bySet.reduce((n, [, r]) => n + r.rework, 0);
  const unverified = total - verified;
  const effectiveMode: Mode = unverified === 0 ? "all" : verified === 0 ? "all" : mode;
  const taken = effectiveMode === "all" ? total : verified;
  const trimmed = name.trim();
  const nameTaken = existing?.some((r) => r.name.toLowerCase() === trimmed.toLowerCase());
  const trainSet = bySet.map(([set]) => set).find((set) => /^train/i.test(set)) ?? null;
  const trainRow = bySet.find(([set]) => set === trainSet)?.[1];
  const trainTaken = trainRow ? (effectiveMode === "all" ? trainRow.total : trainRow.verified) : 0;
  const recipe = recipeOf(augmentation);
  const added = recipe ? trainTaken * recipe.copies : 0;
  const problem = !trimmed ? "Name the dataset." : nameTaken ? "A dataset version already has this name." : total === 0 ? "No images to include."
    : augmentationProblem(augmentation);

  const create = async () => {
    setBusy(true);
    setError(null);
    try {
      const started = await api.createRelease({
        project, dataset, name: trimmed, description: description.trim(), mode: effectiveMode, author, augmentation: recipe,
      });
      if (started.release) {
        onCreated(started.release);
        return;
      }
      // Augmenting: follow the job until the version is written.
      let current = started.job;
      setJob(current);
      while (current.status === "running") {
        await new Promise((resolve) => window.setTimeout(resolve, 700));
        if (!alive.current) return;
        current = await api.job<{ release: Release }>(current.id);
        setJob(current);
      }
      if (current.status === "done" && current.result) onCreated(current.result.release);
      else {
        setError(current.status === "cancelled" ? "Cancelled. Nothing was saved." : current.error ?? "Augmentation failed.");
        setJob(null);
        setBusy(false);
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
      setJob(null);
      setBusy(false);
    }
  };
  const running = job?.status === "running";

  return (
    <Modal
      title="Create dataset"
      onClose={running ? () => undefined : onClose}
      width={720}
      footer={running && job ? (
        <>
          <div className="aug-progress">
            <div className="aug-progress-text">
              <span>{job.phase}</span>
              <span className="tabular muted">{formatNumber(job.done)} / {formatNumber(job.total || added)}</span>
            </div>
            <div className="progress"><div className="progress-fill" style={{ width: `${job.total ? (job.done / job.total) * 100 : 0}%` }} /></div>
          </div>
          <button onClick={() => void api.cancelJob(job.id)}>Cancel</button>
        </>
      ) : (
        <>
          <span className="muted small tabular">
            {formatNumber(taken + added)} images{added > 0 && <> · {formatNumber(added)} augmented</>}
          </span>
          <span className="spacer" />
          <button onClick={onClose}>Cancel</button>
          <button className="primary" disabled={Boolean(problem) || busy} onClick={() => void create()}>
            {busy ? "Creating" : "Create dataset"}
          </button>
        </>
      )}
    >
      <label className="field">
        <span>Name</span>
        <input type="text" value={name} autoFocus maxLength={80} onChange={(e) => setName(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && !problem && !busy && void create()} />
      </label>
      <label className="field">
        <span>Description</span>
        <textarea className="release-description" rows={3} maxLength={4000} value={description}
          placeholder="What changed, what it is for" onChange={(e) => setDescription(e.target.value)} />
      </label>

      <div className="data-table-wrap">
        <table className="data-table release-sets">
          <thead>
            <tr><th>Set</th><th className="num">Images</th><th className="num">Verified</th><th className="num">Unverified</th></tr>
          </thead>
          <tbody>
            {bySet.map(([set, r]) => (
              <tr key={set}>
                <td>{set}</td>
                <td className="num tabular">{formatNumber(r.total)}</td>
                <td className="num tabular">{formatNumber(r.verified)}</td>
                <td className={`num tabular${r.total - r.verified ? " warn-text" : ""}`}>{formatNumber(r.total - r.verified)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {unverified > 0 && (
        <div className="release-warning" role="alert">
          <Icon name="warn" size={16} />
          <div>
            <strong>{formatNumber(unverified)} of {formatNumber(total)} images are unverified</strong>
            {rework > 0 && <span className="muted"> ({formatNumber(rework)} sent for rework)</span>}
          </div>
        </div>
      )}
      {unverified > 0 && (
        <div className="release-modes" role="radiogroup" aria-label="Images to include">
          <label className={`family-card${effectiveMode === "all" ? " checked" : ""}`}>
            <input type="radio" name="release-mode" checked={effectiveMode === "all"} onChange={() => setMode("all")} />
            <span className="family-name">Use entire dataset</span>
            <span className="faint small">{plural(total, "image")}, including {formatNumber(unverified)} unverified</span>
          </label>
          <label className={`family-card${effectiveMode === "verified" ? " checked" : ""}${verified === 0 ? " unavailable" : ""}`}>
            <input type="radio" name="release-mode" disabled={verified === 0} checked={effectiveMode === "verified"} onChange={() => setMode("verified")} />
            <span className="family-name">Use only verified</span>
            <span className="faint small">{verified === 0 ? "No image is verified yet" : plural(verified, "image")}</span>
          </label>
        </div>
      )}

      <AugmentationPanel
        project={project}
        dataset={dataset}
        state={augmentation}
        onChange={setAugmentation}
        trainImages={trainTaken}
        trainSet={trainSet}
        labels={labels}
        tasks={tasks}
        disabled={busy}
      />

      {(error || (problem && trimmed && existing)) && <p className="form-error">{error ?? problem}</p>}
    </Modal>
  );
}
