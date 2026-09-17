/** Train a model from the dashboard: choose what to train on, watch it, see how it compares.
 *
 * Training runs as a separate process on this computer (see granum.training.train); these
 * components start it, follow its progress, and explain the result in plain terms.
 */

import { useCallback, useEffect, useMemo, useState } from "react";
import { api } from "../api/client";
import type { Job, ModelFamily, ObjectEntry, TrainingResult, TrainingStatus } from "../api/types";
import { Modal } from "../components/Modal";
import { Icon, Progress, formatNumber } from "../components/ui";
import { HOLDING_SETS, groupDatasets, splitOfTable } from "../pages/datasets";
import { routeHref } from "../router";
import { useStore } from "../store/store";

const EPOCH_PRESETS = [12, 30, 60, 100];
const IMAGE_SIZES = [640, 960, 1280];

export interface TrainPreset {
  trainUrl?: string;
  compareWith?: string;
}

export function TrainDialog({ project, preset, onClose, onStarted }: {
  project: string;
  preset?: TrainPreset;
  onClose: () => void;
  onStarted: (job: Job<TrainingResult>) => void;
}) {
  const tables = useStore((s) => s.tables);
  const runs = useStore((s) => s.runs);
  const datasets = useMemo(() => groupDatasets(tables), [tables]);
  const pick = (pattern: RegExp) => {
    for (const dataset of datasets) {
      const split = dataset.splits.find((s) => pattern.test(s.name));
      if (split) return split.latest.url;
    }
    return "";
  };
  const presetSplit = preset?.trainUrl ? splitOfTable(datasets, preset.trainUrl) : null;
  const checkDefault = () => {
    // Check against the validation set of the same dataset as the training choice.
    const home = presetSplit?.dataset ?? datasets.find((d) => d.splits.some((s) => /^train/i.test(s.name)));
    const own = home?.splits.find((s) => /^(valid|val)/i.test(s.name)) ?? home?.splits.find((s) => /^test/i.test(s.name));
    return own?.latest.url ?? pick(/^(valid|val|test)/i);
  };

  const finished = [...runs].filter((r) => r.status !== "running").sort((a, b) => b.created.localeCompare(a.created));
  const [trainUrl, setTrainUrl] = useState(preset?.trainUrl ?? (pick(/^train/i) || datasets[0]?.latest.url || ""));
  const [validUrl, setValidUrl] = useState(checkDefault);
  const [rounds, setRounds] = useState(12);
  const [familyId, setFamilyId] = useState("yolo");
  const [versionId, setVersionId] = useState("yolo26n.pt");
  const [imageSize, setImageSize] = useState(640);
  const [trackLearning, setTrackLearning] = useState(true);
  const [compareWith, setCompareWith] = useState(preset?.compareWith ?? finished[0]?.name ?? "");
  const [status, setStatus] = useState<TrainingStatus | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [starting, setStarting] = useState(false);

  useEffect(() => {
    api.trainingStatus(project).then(setStatus).catch((e: Error) => setError(e.message));
  }, [project]);

  // Only shipped versions can be trained on: once they are known, move the choices onto them.
  const shipped = useMemo(() => new Set(status?.shipped ?? []), [status]);
  useEffect(() => {
    if (!status) return;
    const first = (pattern: RegExp) => {
      for (const dataset of datasets) {
        for (const split of dataset.splits) {
          if (!pattern.test(split.name)) continue;
          const found = [...split.revisions].reverse().find((r) => shipped.has(r.entry.url));
          if (found) return found.entry.url;
        }
      }
      return "";
    };
    if (!shipped.has(trainUrl)) setTrainUrl(first(/^train/i) || first(/./));
    if (!shipped.has(validUrl)) setValidUrl(first(/^(valid|val)/i) || first(/^test/i));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [status]);

  const families = status?.families ?? [];
  const family = families.find((f) => f.id === familyId);
  const chooseFamily = (next: ModelFamily) => {
    setFamilyId(next.id);
    setVersionId(next.versions[0]?.id ?? "");
  };

  const train = splitOfTable(datasets, trainUrl);
  const valid = splitOfTable(datasets, validUrl);
  const problem =
    status && shipped.size === 0 ? "No dataset has been shipped yet."
      : !train || !valid ? "Choose training and validation data."
      : trainUrl === validUrl || (train.dataset.name === valid.dataset.name && train.split.name === valid.split.name)
        ? "Training and validation data must come from different sets."
        : family && !family.installed ? `${family.name} is not installed (${family.install_hint}).`
          : !Number.isInteger(rounds) || rounds < 1 || rounds > 300 ? "Epochs must be between 1 and 300."
            : null;

  const start = async () => {
    setStarting(true);
    setError(null);
    try {
      const job = await api.startTraining({
        project, train_table: trainUrl, valid_table: validUrl, rounds,
        family: familyId, version: versionId,
        image_size: family?.supports_closer ? imageSize : 640,
        track_learning: trackLearning,
        compare_with: compareWith || null,
      });
      onStarted(job);
      onClose();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
      setStarting(false);
    }
  };

  const versionOptions = datasets.flatMap((dataset) =>
    dataset.splits.filter((split) => !HOLDING_SETS.includes(split.name) && split.revisions.some((r) => shipped.has(r.entry.url))).map((split) => (
      <optgroup key={`${dataset.name}/${split.name}`} label={`${dataset.name} / ${split.name}`}>
        {[...split.revisions].reverse().filter(({ entry }) => shipped.has(entry.url)).map(({ entry }) => (
          <option key={entry.url} value={entry.url}>
            {entry.name}{entry.url === split.latest.url ? " (newest)" : ""}, {formatNumber(entry.row_count)} images
          </option>
        ))}
      </optgroup>
    )),
  );

  return (
    <Modal
      title="Train model"
      onClose={onClose}
      width={640}
      footer={
        <>
          <span className="muted small">{status?.gpu ?? (status?.available ? "CPU" : "")}</span>
          <span className="spacer" />
          <button onClick={onClose}>Cancel</button>
          <button
            className="primary"
            disabled={Boolean(problem) || !status || starting || !status.available || status.busy_elsewhere || Boolean(status.running_job)}
            onClick={() => void start()}
          >
            {starting ? "Starting" : "Start training"}
          </button>
        </>
      }
    >
      {status && !status.available && <p className="form-error">{status.reason}</p>}
      {status && (status.running_job || status.busy_elsewhere) && <p className="form-error">Another training job is running on this machine.</p>}

      <div className="form-section">
        <h3>Data</h3>
        <div className="field-pair">
          <label className="field">
            <span>Train</span>
            <div className="select-wrap">
              <select value={trainUrl} onChange={(e) => setTrainUrl(e.target.value)}>{versionOptions}</select>
            </div>
          </label>
          <label className="field">
            <span>Validation</span>
            <div className="select-wrap">
              <select value={validUrl} onChange={(e) => setValidUrl(e.target.value)}>{versionOptions}</select>
            </div>
          </label>
        </div>
        {status && shipped.size === 0 ? (
          <p className="form-error">
            Only shipped datasets can be trained on. <a href={routeHref({ name: "review", project })} onClick={onClose}>Review and ship a dataset</a> first.
          </p>
        ) : (
          problem && train && valid && <p className="form-error">{problem}</p>
        )}
        {status && shipped.size > 0 && <p className="faint small">Showing shipped versions only.</p>}
      </div>

      <div className="form-section">
        <h3>Model</h3>
        {!status && <p className="muted small"><span className="spinner" /> Detecting installed frameworks</p>}
        <div className="family-grid" role="radiogroup" aria-label="Architecture">
          {families.map((option) => (
            <label key={option.id} className={`family-card${familyId === option.id ? " checked" : ""}${option.installed ? "" : " unavailable"}`}>
              <input type="radio" name="family" checked={familyId === option.id} onChange={() => chooseFamily(option)} />
              <span className="family-name">{option.name}</span>
              <span className="faint small">{option.installed ? option.maker : "Not installed"}</span>
            </label>
          ))}
        </div>
        {family && (
          <div className="field-pair">
            <label className="field">
              <span>Weights</span>
              <div className="select-wrap">
                <select value={versionId} onChange={(e) => setVersionId(e.target.value)} disabled={!family.installed}>
                  {family.versions.map((v) => <option key={v.id} value={v.id}>{v.name}</option>)}
                </select>
              </div>
            </label>
            <label className="field">
              <span>Image size</span>
              <div className="select-wrap">
                <select value={family.supports_closer ? imageSize : 640} onChange={(e) => setImageSize(Number(e.target.value))} disabled={!family.supports_closer}>
                  {IMAGE_SIZES.map((size) => <option key={size} value={size}>{size} px</option>)}
                </select>
              </div>
            </label>
          </div>
        )}
      </div>

      <div className="form-section">
        <h3>Schedule</h3>
        <div className="field-pair">
          <div className="field">
            <span>Epochs</span>
            <div className="epoch-input">
              <input type="number" min={1} max={300} value={rounds} onChange={(e) => setRounds(Number(e.target.value))} aria-label="Epochs" />
              <div className="segmented" role="group" aria-label="Epoch presets">
                {EPOCH_PRESETS.map((n) => (
                  <button key={n} type="button" className={rounds === n ? "on" : ""} onClick={() => setRounds(n)}>{n}</button>
                ))}
              </div>
            </div>
          </div>
          <label className="field">
            <span>Compare with</span>
            <div className="select-wrap">
              <select value={compareWith} onChange={(e) => setCompareWith(e.target.value)}>
                <option value="">None</option>
                {finished.map((run) => <option key={run.url} value={run.name}>{run.name}</option>)}
              </select>
            </div>
          </label>
        </div>
        <label className="check-row small">
          <input type="checkbox" checked={trackLearning} onChange={(e) => setTrackLearning(e.target.checked)} />
          Record per-sample metrics and predictions every epoch
        </label>
      </div>

      {error && <p className="form-error">{error}</p>}
    </Modal>
  );
}

/** Follows the training job for a project, whoever started it, including after a reload. */
export function useTrainingJob(project: string) {
  const [job, setJob] = useState<Job<TrainingResult> | null>(null);
  const refreshProject = useStore((s) => s.refreshProject);

  useEffect(() => {
    let alive = true;
    api.trainingStatus(project).then((s) => alive && s.running_job && setJob(s.running_job)).catch(() => undefined);
    return () => {
      alive = false;
    };
  }, [project]);

  useEffect(() => {
    if (!job || job.status !== "running") return;
    const timer = window.setInterval(() => {
      api.job<TrainingResult>(job.id)
        .then((next) => {
          setJob(next);
          if (next.status !== "running") void refreshProject();
        })
        .catch(() => undefined);
    }, 2000);
    return () => window.clearInterval(timer);
  }, [job, refreshProject]);

  const cancel = useCallback(async () => {
    if (!job) return;
    await api.cancelJob(job.id).catch(() => undefined);
  }, [job]);

  return { job, setJob, dismiss: () => setJob(null), cancel };
}

export function TrainingProgressCard({ project, job, onCancel, onDismiss }: {
  project: string;
  job: Job<TrainingResult>;
  onCancel: () => void;
  onDismiss: () => void;
}) {
  const [showLog, setShowLog] = useState(false);
  const [confirmCancel, setConfirmCancel] = useState(false);
  const runs = useStore((s) => s.runs);
  const running = job.status === "running";
  const runName = job.result?.run_name;
  const run = runs.find((r) => r.name === runName);
  const minutes = Math.floor(job.elapsed / 60);
  const seconds = Math.round(job.elapsed % 60);
  const title = running ? job.phase
    : job.status === "done" ? (job.result?.cancelled ? "Training cancelled" : "Training finished")
      : job.status === "cancelled" ? "Training cancelled" : "Training failed";

  return (
    <section className={`training-card training-${job.status}`} aria-live="polite">
      <div className="training-card-head">
        {running ? <span className="live-dot training-dot" /> : <Icon name={job.status === "done" && !job.result?.cancelled ? "check" : "warn"} size={15} />}
        <span className="strong">{title}</span>
        {runName && <span className="cell-mono muted">{runName}</span>}
        <span className="faint small tabular">{minutes > 0 ? `${minutes}m ` : ""}{seconds}s</span>
        {running && job.total > 0 && <span className="faint small tabular">{job.done}/{job.total} epochs</span>}
        <span className="spacer" />
        {!running && job.status === "done" && run && !job.result?.cancelled && (
          <>
            {run.parameters?.tracks_learning === true && <a className="button" href={routeHref({ name: "learning", project, url: run.url })}>Samples</a>}
            <a className="button" href={routeHref({ name: "run", project, url: run.url })}>Open run</a>
          </>
        )}
        <button className="button subtle" onClick={() => setShowLog(!showLog)} aria-expanded={showLog}>Log</button>
        {running ? (
          confirmCancel ? (
            <>
              <button className="button subtle" onClick={() => setConfirmCancel(false)}>Keep running</button>
              <button className="button danger-button" onClick={() => { onCancel(); setConfirmCancel(false); }}>Stop training</button>
            </>
          ) : (
            <button className="button subtle" onClick={() => setConfirmCancel(true)}>Cancel</button>
          )
        ) : (
          <button className="icon-button" onClick={onDismiss} aria-label="Dismiss"><Icon name="close" size={14} /></button>
        )}
      </div>
      {running && <Progress done={job.done} total={job.total} />}
      {job.error && <p className="form-error">{job.error}</p>}
      {showLog && <pre className="code-block training-log">{(job.log ?? []).slice(-40).join("\n") || "No output yet"}</pre>}
    </section>
  );
}

/** A run scored against an earlier one on the same validation labels. */
export function Comparison({ run, project }: { run: ObjectEntry; project: string }) {
  const p = run.parameters ?? {};
  const mine = Number(p.compare_map50_this);
  const theirs = Number(p.compare_map50_earlier);
  if (!Number.isFinite(mine) || !Number.isFinite(theirs) || p.compare_map50_this === undefined) return null;
  const difference = mine - theirs;
  const noise = Math.abs(difference) < 0.02;
  const earlier = useStore.getState().runs.find((r) => r.name === p.compared_with);
  const recallMine = Number(p.compare_recall_this);
  const recallTheirs = Number(p.compare_recall_earlier);

  return (
    <div className={`comparison ${noise ? "comparison-even" : difference > 0 ? "comparison-better" : "comparison-worse"}`}>
      <span className="comparison-label">Comparison</span>
      <span className="comparison-pair">
        <a className="strong" href={routeHref({ name: "run", project, url: run.url })}>{run.name}</a>
        <span className="comparison-value">{mine.toFixed(3)}</span>
        <span className="muted">vs</span>
        {earlier ? <a href={routeHref({ name: "run", project, url: earlier.url })}>{String(p.compared_with)}</a> : <span>{String(p.compared_with)}</span>}
        <span className="comparison-value">{theirs.toFixed(3)}</span>
        <span className="muted">mAP50</span>
      </span>
      <span className={`comparison-delta${noise ? "" : difference > 0 ? " up" : " down"}`}>
        {difference >= 0 ? "+" : ""}{difference.toFixed(3)}{noise ? ", within run-to-run noise" : ""}
      </span>
      {Number.isFinite(recallMine) && Number.isFinite(recallTheirs) && (
        <span className="muted small">Recall {recallMine.toFixed(3)} vs {recallTheirs.toFixed(3)}</span>
      )}
      <span className="spacer" />
      <span className="faint small">Scored identically on {String(p.compare_labels)}</span>
    </div>
  );
}
