/** Write a dataset version out in somebody else's format.
 *
 * A dataset that cannot leave is one nobody will trust enough to bring in, so this asks only
 * the two questions that change the result: which layout, and what to do about the image
 * files. Everything else — which sets, which versions, which labels — was decided when the
 * version was frozen, which is the point of freezing one.
 *
 * The image question is the one people get wrong. A link costs no disk and breaks the moment
 * the folder moves to another machine; a copy is portable and as large as the images. Both
 * are spelled out here rather than hidden behind a word like "mode".
 */

import { useEffect, useState } from "react";
import { api } from "../api/client";
import type { ExportResult, FormatOption, Job } from "../api/types";
import { Modal } from "../components/Modal";
import { Icon, formatNumber, plural } from "../components/ui";

interface Props {
  project: string;
  dataset: string;
  /** The dataset version to write out, and what it is called on screen. */
  releaseId: string;
  releaseName: string;
  images: number;
  onClose: () => void;
}

/** Layouts made of the image files themselves: a YOLO tree is found by walking the image
 *  folders, and a class is the folder an image sits in. Neither can be written without them. */
const NEEDS_IMAGES = new Set(["yolo", "folders"]);

/** What each way of handling the image files costs, in the terms people choose on. */
const IMAGE_CHOICES: { id: string; label: string; detail: string }[] = [
  { id: "symlink", label: "Link to them", detail: "No extra disk. Breaks if the export is moved to another machine." },
  { id: "copy", label: "Copy them", detail: "Portable, and as large again as the images themselves." },
  { id: "hardlink", label: "Hard link them", detail: "No extra disk, and survives moving within the same drive." },
  { id: "none", label: "Labels only", detail: "Annotations alone, naming the images where they already are." },
];

export function ExportDialog({ project, dataset, releaseId, releaseName, images, onClose }: Props) {
  const [formats, setFormats] = useState<FormatOption[] | null>(null);
  const [format, setFormat] = useState("coco");
  const [handling, setHandling] = useState("symlink");
  const [job, setJob] = useState<Job<ExportResult> | null>(null);
  const [result, setResult] = useState<ExportResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    let alive = true;
    api.formats()
      .then((next) => alive && setFormats(next.exports))
      .catch((e: Error) => alive && setError(e.message));
    return () => {
      alive = false;
    };
  }, []);

  const chosen = formats?.find((entry) => entry.id === format) ?? null;
  const needsImages = NEEDS_IMAGES.has(format);
  // Switching to a layout that is made of its images cannot stay on "labels only".
  useEffect(() => {
    if (needsImages && handling === "none") setHandling("symlink");
  }, [needsImages, handling]);

  const start = async () => {
    setBusy(true);
    setError(null);
    try {
      let current = await api.startExport({
        project, dataset, release_id: releaseId, format, images: handling,
      });
      setJob(current);
      while (current.status === "running") {
        await new Promise((resume) => window.setTimeout(resume, 500));
        current = await api.job<ExportResult>(current.id);
        setJob(current);
      }
      if (current.status === "done" && current.result) setResult(current.result);
      else if (current.status === "failed") setError(current.error ?? "the export stopped");
      else setJob(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };

  const running = job !== null && job.status === "running";
  const share = job && job.total ? job.done / job.total : 0;

  if (result) {
    const inside = (path: string) => (path.startsWith(result.folder) ? path.slice(result.folder.length + 1) : path);
    return (
      <Modal
        title="Written"
        width={620}
        onClose={onClose}
        footer={<button className="button primary" onClick={onClose}>Done</button>}
      >
        <div className="screen-form">
          <p>
            {plural(result.images, "image")} written as <strong>{chosen?.name ?? result.format}</strong>.
          </p>
          <p className="mono small export-path" title={result.folder}>{result.folder}</p>
          <table className="data-table">
            <thead>
              <tr><th>Set</th><th className="num">Images</th><th>Written to</th></tr>
            </thead>
            <tbody>
              {result.sets.map((set) => (
                <tr key={set.path}>
                  <td>{set.set}</td>
                  <td className="num">{formatNumber(set.images)}</td>
                  <td className="cell-mono" title={set.path}>{inside(set.path)}</td>
                </tr>
              ))}
            </tbody>
          </table>
          {handling === "symlink" && (
            <p className="faint small">
              The images are links to where they already are. Copy them instead if this folder
              is going to another machine.
            </p>
          )}
        </div>
      </Modal>
    );
  }

  return (
    <Modal
      title={`Export ${releaseName}`}
      width={620}
      onClose={onClose}
      footer={
        <>
          {running ? (
            <button className="button subtle" onClick={() => void api.cancelJob(job.id)}>Stop</button>
          ) : (
            <button className="button subtle" onClick={onClose}>Cancel</button>
          )}
          <button className="button primary" disabled={busy || running || !formats} onClick={() => void start()}>
            <Icon name="export" size={15} />Write {formatNumber(images)} images
          </button>
        </>
      }
    >
      {error && <p className="form-error">{error}</p>}

      {running ? (
        <div className="screen-progress">
          <div className="similar-progress-text">
            <span>{job.phase}</span>
            <span className="tabular muted">{formatNumber(job.done)} / {formatNumber(job.total)}</span>
          </div>
          <div className="progress"><div className="progress-fill" style={{ width: `${share * 100}%` }} /></div>
          <p className="muted small">
            The version is read as it was frozen, so what is written is what was trained on,
            whatever has been edited since.
          </p>
        </div>
      ) : (
        <div className="screen-form">
          <label className="field">
            <span className="field-label">Format</span>
            <div className="select-wrap">
              <select value={format} onChange={(e) => setFormat(e.target.value)}>
                {(formats ?? [{ id: "coco", name: "COCO", detail: "" }]).map((entry) => (
                  <option key={entry.id} value={entry.id}>{entry.name}</option>
                ))}
              </select>
            </div>
            {chosen && <span className="faint small">{chosen.detail}</span>}
          </label>

          <div className="screen-sets">
            <span className="field-label">Image files</span>
            <div role="radiogroup" aria-label="Image files">
              {IMAGE_CHOICES.map((choice) => {
                const barred = choice.id === "none" && needsImages;
                return (
                  <label
                    key={choice.id}
                    className={`radio-row${handling === choice.id ? " checked" : ""}${barred ? " disabled" : ""}`}
                    title={barred ? `${chosen?.name ?? format} is made of the image files, so it cannot be written without them` : undefined}
                  >
                    <input
                      type="radio"
                      name="export-images"
                      disabled={barred}
                      checked={handling === choice.id}
                      onChange={() => setHandling(choice.id)}
                    />
                    <span>
                      <span className="strong">{choice.label}</span>
                      <span className="faint small"> {barred ? `Not possible: ${chosen?.name ?? format} is made of the image files.` : choice.detail}</span>
                    </span>
                  </label>
                );
              })}
            </div>
          </div>

          <p className="muted small">
            Written under this project's <span className="mono">exports</span> folder, in a folder
            named for the version, the format and the time.
          </p>
        </div>
      )}
    </Modal>
  );
}
