/** Check a dataset version's labels with one model, without training anything.
 *
 * Findings used to need a finished training run with its predictions kept round by round,
 * which is an afternoon before a dataset can be checked at all. One pass of a model over
 * the labels answers the same four questions in minutes -- weaker evidence, and the report
 * says so, but available on the day the data arrives.
 *
 * Two models are worth offering and they are not the same offer. A model trained in this
 * project knows these classes exactly, and pointing it at labels edited since it was
 * trained is the strongest thing here. A model that has never seen this data knows the
 * classes it was trained on; how many of these it can speak about is only known once it
 * runs, and whatever it cannot speak about is left alone rather than reported as wrong.
 */

import { useEffect, useMemo, useState } from "react";
import { api } from "../api/client";
import type { Job, Release, ScreeningOptions } from "../api/types";
import { Modal } from "../components/Modal";
import { Icon, formatNumber, formatWhen, plural } from "../components/ui";

interface Props {
  project: string;
  onClose: () => void;
  /** A check has finished: its run is the one to read findings from. */
  onDone: (runName: string) => void;
}

export function ScreenDialog({ project, onClose, onDone }: Props) {
  const [options, setOptions] = useState<ScreeningOptions | null>(null);
  const [releases, setReleases] = useState<Release[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [version, setVersion] = useState<string>("");
  const [model, setModel] = useState<string>("");
  const [sets, setSets] = useState<Set<string>>(new Set());
  const [job, setJob] = useState<Job<{ run_name: string }> | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    let alive = true;
    Promise.all([api.screeningOptions(project), api.releases(project)])
      .then(([next, { releases: list }]) => {
        if (!alive) return;
        setOptions(next);
        setReleases(list);
        const newest = [...list].sort((a, b) => b.time.localeCompare(a.time))[0];
        if (newest) {
          setVersion(newest.id);
          // The sets a model was not trained on are the ones its opinion is worth most on.
          setSets(new Set(Object.keys(newest.sets).filter((name) => name !== "train")));
        }
        setModel(next.models[0] ? `run:${next.models[0].name}` : next.pretrained[0] ? `pretrained:${next.pretrained[0]}` : "");
        if (next.running_job) setJob(next.running_job);
      })
      .catch((e) => alive && setError(e instanceof Error ? e.message : String(e)));
    return () => {
      alive = false;
    };
  }, [project]);

  const release = useMemo(() => releases?.find((r) => r.id === version) ?? null, [releases, version]);
  const chosen = useMemo(
    () => Object.entries(release?.sets ?? {}).filter(([name]) => sets.has(name)),
    [release, sets],
  );
  const images = chosen.reduce((n, [, set]) => n + set.images, 0);
  const trained = options?.models.find((m) => `run:${m.name}` === model) ?? null;

  const start = async () => {
    if (!release || chosen.length === 0 || !model) return;
    setBusy(true);
    setError(null);
    try {
      let current = await api.startScreening({
        project,
        sets: Object.fromEntries(chosen.map(([name, set]) => [name, set.url])),
        ...(model.startsWith("run:") ? { weights_run: model.slice(4) } : { pretrained: model.slice(11) }),
        image_size: trained?.image_size ?? 640,
      });
      setJob(current);
      while (current.status === "running") {
        await new Promise((resume) => window.setTimeout(resume, 800));
        current = await api.job<{ run_name: string }>(current.id);
        setJob(current);
      }
      if (current.status === "done" && current.result?.run_name) onDone(current.result.run_name);
      else if (current.status === "failed") setError(current.error ?? "the check stopped");
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
      title="Check the labels with a model"
      width={620}
      onClose={onClose}
      footer={
        <>
          {running ? (
            <button className="button subtle" onClick={() => void api.cancelJob(job.id)}>Stop the check</button>
          ) : (
            <button className="button subtle" onClick={onClose}>Cancel</button>
          )}
          <button
            className="button primary"
            disabled={busy || running || !release || chosen.length === 0 || !model || !options?.available}
            onClick={() => void start()}
          >
            <Icon name="search" size={15} />Read {formatNumber(images)} images
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
            The model reads each image once and records what it sees. Nothing is trained and no
            label is changed; the findings are what it disagrees with.
          </p>
        </div>
      ) : (
        <div className="screen-form">
          <label className="field">
            <span className="field-label">Dataset version</span>
            <div className="select-wrap">
              <select
                value={version}
                onChange={(e) => {
                  setVersion(e.target.value);
                  const next = releases?.find((r) => r.id === e.target.value);
                  setSets(new Set(Object.keys(next?.sets ?? {}).filter((name) => name !== "train")));
                }}
              >
                {(releases ?? []).map((r) => (
                  <option key={r.id} value={r.id}>{r.dataset} {r.name} · {formatWhen(r.time)}</option>
                ))}
              </select>
            </div>
          </label>

          {release && (
            <div className="screen-sets">
              <span className="field-label">Sets to read</span>
              <div className="segmented" role="group" aria-label="Sets">
                {Object.entries(release.sets).map(([name, set]) => (
                  <button
                    key={name}
                    className={sets.has(name) ? "on" : ""}
                    onClick={() => setSets((was) => {
                      const next = new Set(was);
                      if (next.has(name)) next.delete(name);
                      else next.add(name);
                      return next;
                    })}
                  >
                    {name}<span className="split-toggle-count">{formatNumber(set.images)}</span>
                  </button>
                ))}
              </div>
              <p className="faint small">
                A model's opinion is worth most on labels it was not trained on. Reading the
                training set as well is useful once, to see what it learned to accept.
              </p>
            </div>
          )}

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

          <p className="muted small">
            {model.startsWith("run:") ? (
              <>
                {trained?.name} knows this dataset's classes exactly. Checking labels edited
                since it was trained is what this is for: one pass, not another training run.
              </>
            ) : model ? (
              <>
                A model that has never seen this data knows the classes it was trained on.
                Whichever of yours it cannot name are left alone rather than reported as
                wrong, and the report says which those were.
              </>
            ) : (
              "No model on this computer yet. Train one, or install the training add-on."
            )}
          </p>
          <p className="faint small">
            {plural(images, "image")} to read{options?.gpu ? ` on ${options.gpu}` : ""}. Roughly a
            minute for every thousand on a graphics card, longer on a processor.
          </p>
        </div>
      )}
    </Modal>
  );
}
