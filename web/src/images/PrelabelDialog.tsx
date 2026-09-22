/** Draft a set's labels with a model, so labelling becomes correcting.
 *
 * Labelling from nothing is the expensive part of a dataset; a detector that is roughly
 * right turns it into correction, which is several times faster and much less tiring. What
 * keeps that honest is that every box it draws is marked as a draft, in the gallery, in the
 * editor and in what gets exported, so nobody can mistake a machine's guess for a label
 * somebody checked.
 *
 * The dialog is deliberately blunt about the two choices that can lose work: which sets are
 * drafted, and whether images that already have labels are redrawn. The default leaves every
 * labelled image alone, and a new version is written either way — the labels that were there
 * stay in the version before it.
 */

import { useEffect, useMemo, useState } from "react";
import { api } from "../api/client";
import type { ImageSet, Job, ModelOptions, PrelabelResult } from "../api/types";
import { Modal } from "../components/Modal";
import { Icon, formatNumber, plural } from "../components/ui";

interface Props {
  project: string;
  dataset: string;
  /** The dataset's sets as the Images tab knows them: the newest version of each. */
  sets: ImageSet[];
  onClose: () => void;
  /** Boxes were written: the gallery must read the new versions. */
  onDone: (result: PrelabelResult) => void;
}

export function PrelabelDialog({ project, dataset, sets, onClose, onDone }: Props) {
  const [options, setOptions] = useState<ModelOptions | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [model, setModel] = useState("");
  const [chosen, setChosen] = useState<Set<string>>(new Set());
  const [mode, setMode] = useState<"empty" | "replace">("empty");
  const [confidence, setConfidence] = useState(0.4);
  const [job, setJob] = useState<Job<PrelabelResult> | null>(null);
  const [busy, setBusy] = useState(false);

  const drafting = useMemo(() => sets.filter((set) => chosen.has(set.url)), [sets, chosen]);
  const images = drafting.reduce((n, set) => n + set.images, 0);

  useEffect(() => {
    let alive = true;
    api.models(project)
      .then((next) => {
        if (!alive) return;
        setOptions(next);
        setModel(next.models[0] ? `run:${next.models[0].name}` : next.pretrained[0] ? `pretrained:${next.pretrained[0]}` : "");
      })
      .catch((e) => alive && setError(e instanceof Error ? e.message : String(e)));
    return () => {
      alive = false;
    };
  }, [project]);

  const trained = options?.models.find((m) => `run:${m.name}` === model) ?? null;

  const start = async () => {
    if (drafting.length === 0 || !model) return;
    setBusy(true);
    setError(null);
    try {
      let current = await api.startPrelabel({
        project,
        dataset,
        tables: drafting.map((set) => set.url),
        ...(model.startsWith("run:") ? { weights_run: model.slice(4) } : { pretrained: model.slice(11) }),
        mode,
        confidence,
        image_size: trained?.image_size ?? 640,
      });
      setJob(current);
      while (current.status === "running") {
        await new Promise((resume) => window.setTimeout(resume, 800));
        current = await api.job<PrelabelResult>(current.id);
        setJob(current);
      }
      if (current.status === "done" && current.result) onDone(current.result);
      else if (current.status === "failed") setError(current.error ?? "the pass stopped");
      else setJob(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };

  const running = job !== null && job.status === "running";
  const share = job && job.total ? job.done / job.total : 0;

  return (
    <Modal
      title="Pre-label with a model"
      width={620}
      onClose={onClose}
      footer={
        <>
          {running ? (
            <button className="button subtle" onClick={() => void api.cancelJob(job.id)}>Stop</button>
          ) : (
            <button className="button subtle" onClick={onClose}>Cancel</button>
          )}
          <button
            className="button primary"
            disabled={busy || running || drafting.length === 0 || !model || !options?.available}
            onClick={() => void start()}
          >
            <Icon name="pencil" size={15} />Draft {formatNumber(images)} images
          </button>
        </>
      }
    >
      {error && <p className="form-error">{error}</p>}
      {options && !options.available && <p className="form-error">{options.reason}</p>}
      {options?.busy_elsewhere && <p className="notice">A model is already running on this computer for another project.</p>}

      {running ? (
        <div className="screen-progress">
          <div className="similar-progress-text">
            <span>{job.phase}</span>
            <span className="tabular muted">{formatNumber(job.done)} / {formatNumber(job.total)}</span>
          </div>
          <div className="progress"><div className="progress-fill" style={{ width: `${share * 100}%` }} /></div>
          <p className="muted small">
            Each set becomes a new version with the model's boxes in it. What is there now stays
            where it is: a version is written, nothing is overwritten.
          </p>
        </div>
      ) : (
        <div className="screen-form">
          <div className="screen-sets">
            <span className="field-label">Sets to draft</span>
            <div className="segmented" role="group" aria-label="Sets">
              {sets.map((set) => (
                <button
                  key={set.url}
                  className={chosen.has(set.url) ? "on" : ""}
                  onClick={() => setChosen((was) => {
                    const next = new Set(was);
                    if (next.has(set.url)) next.delete(set.url);
                    else next.add(set.url);
                    return next;
                  })}
                >
                  {set.set}<span className="split-toggle-count">{formatNumber(set.images)}</span>
                </button>
              ))}
            </div>
          </div>

          <label className="field">
            <span className="field-label">Model</span>
            <div className="select-wrap">
              <select value={model} onChange={(e) => setModel(e.target.value)}>
                {(options?.models ?? []).map((m) => (
                  <option key={m.name} value={`run:${m.name}`}>
                    {m.name} — trained here{m.map50 ? `, mAP50 ${m.map50.toFixed(3)}` : ""}
                  </option>
                ))}
                {(options?.pretrained ?? []).map((v) => (
                  <option key={v} value={`pretrained:${v}`}>{v} — has never seen this data</option>
                ))}
              </select>
            </div>
          </label>

          <div className="screen-sets">
            <span className="field-label">Images that already have labels</span>
            <div className="segmented" role="group" aria-label="What to do with labelled images">
              <button className={mode === "empty" ? "on" : ""} onClick={() => setMode("empty")}>Leave them alone</button>
              <button className={mode === "replace" ? "on" : ""} onClick={() => setMode("replace")}>Redraw them</button>
            </div>
            <p className="faint small">
              {mode === "empty"
                ? "Only images with no labels at all get boxes. Nothing anybody drew is touched."
                : "Every image gets the model's boxes instead of the ones it has. The labels that are there now stay in the version before this one."}
            </p>
          </div>

          <label className="field">
            <span className="field-label">
              Draw boxes the model is at least {Math.round(confidence * 100)}% sure of
            </span>
            <input
              type="range"
              min={5}
              max={95}
              step={5}
              value={Math.round(confidence * 100)}
              onChange={(e) => setConfidence(Number(e.target.value) / 100)}
            />
            <span className="faint small">
              Lower finds more objects and draws more boxes to delete; higher leaves more to add
              by hand. Every box is marked as a draft either way.
            </span>
          </label>

          <p className="muted small">
            {plural(images, "image")} to read{options?.gpu ? ` on ${options.gpu}` : ""}.
            {model.startsWith("pretrained:") && " A model that has never seen this data can only draw the classes it knows; the rest are left for a person."}
          </p>
        </div>
      )}
    </Modal>
  );
}
