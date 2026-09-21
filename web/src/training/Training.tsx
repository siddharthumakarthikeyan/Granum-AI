/** Train a model from the dashboard: choose what to train on, watch it, see how it compares.
 *
 * Training runs as a separate process on this computer (see granum.training.train); these
 * components start it, follow its progress, and explain the result in plain terms.
 */

import { useCallback, useEffect, useState } from "react";
import { api } from "../api/client";
import type { Job, ModelFamily, ObjectEntry, Release, TrainingResult, TrainingStatus } from "../api/types";
import { Modal } from "../components/Modal";
import { Icon, Progress, formatNumber } from "../components/ui";
import { tasksLabel, trainsOnBoxes } from "../importing/tasks";
import { routeHref } from "../router";
import { useStore } from "../store/store";

const EPOCH_PRESETS = [12, 30, 60, 100];
const IMAGE_SIZES = [640, 960, 1280];

export interface TrainPreset {
  /** A dataset version id to start on. */
  release?: string;
  trainUrl?: string;
  compareWith?: string;
}

export function TrainDialog({ project, preset, onClose, onStarted }: {
  project: string;
  preset?: TrainPreset;
  onClose: () => void;
  onStarted: (job: Job<TrainingResult>) => void;
}) {
  const runs = useStore((s) => s.runs);
  const finished = [...runs].filter((r) => r.status !== "running").sort((a, b) => b.created.localeCompare(a.created));
  const [releases, setReleases] = useState<Release[] | null>(null);
  const [releaseId, setReleaseId] = useState("");
  const [trainSet, setTrainSet] = useState("");
  const [validSet, setValidSet] = useState("");
  const [testSet, setTestSet] = useState("");
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

  /** Train on the train set, check on valid (else test) and hold out test, when a version has them. */
  const chooseRelease = useCallback((release: Release | undefined) => {
    setReleaseId(release?.id ?? "");
    const sets = Object.keys(release?.sets ?? {});
    const train = sets.find((n) => /^train/i.test(n)) ?? sets[0] ?? "";
    const valid = sets.find((n) => /^(valid|val)/i.test(n)) ?? sets.find((n) => /^test/i.test(n)) ?? sets.find((n) => n !== train) ?? "";
    const test = sets.find((n) => /^test/i.test(n) && n !== valid && n !== train) ?? "";
    setTrainSet(train);
    setValidSet(valid);
    setTestSet(test);
  }, []);

  // Only dataset versions can be trained on; start on the one asked for, else the newest.
  useEffect(() => {
    api.releases(project)
      .then(({ releases }) => {
        setReleases(releases);
        const wanted = releases.find((r) => r.id === preset?.release)
          ?? releases.find((r) => preset?.trainUrl && Object.values(r.sets).some((s) => s.url === preset.trainUrl))
          ?? releases[0];
        chooseRelease(wanted);
      })
      .catch((e: Error) => setError(e.message));
  }, [project, preset?.release, preset?.trainUrl, chooseRelease]);

  const release = releases?.find((r) => r.id === releaseId);
  const trainUrl = release?.sets[trainSet]?.url ?? "";
  const validUrl = release?.sets[validSet]?.url ?? "";
  const testUrl = testSet ? release?.sets[testSet]?.url ?? "" : "";

  const families = status?.families ?? [];
  const family = families.find((f) => f.id === familyId);
  const chooseFamily = (next: ModelFamily) => {
    setFamilyId(next.id);
    setVersionId(next.versions[0]?.id ?? "");
  };

  const problem =
    releases && releases.length === 0 ? "No dataset version yet."
      : !trainUrl || !validUrl ? "Choose training and validation sets."
      : trainSet === validSet ? "Training and validation data must come from different sets."
      : testSet && (testSet === trainSet || testSet === validSet) ? "The test set must differ from the training and validation sets."
        : family && !family.installed ? `${family.name} is not installed (${family.install_hint}).`
          : !Number.isInteger(rounds) || rounds < 1 || rounds > 300 ? "Epochs must be between 1 and 300."
            : null;

  const start = async () => {
    setStarting(true);
    setError(null);
    try {
      const job = await api.startTraining({
        project, train_table: trainUrl, valid_table: validUrl, test_table: testUrl || null, rounds,
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

  const setOptions = Object.entries(release?.sets ?? {}).map(([name, set]) => (
    <option key={name} value={name}>{name}, {formatNumber(set.images)} images</option>
  ));

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
      {status && !status.available && (
        status.installable ? (
          <TrainingAddon
            size={status.install_size ?? "a few GB"}
            running={status.install_job ?? null}
            onInstalled={() => api.trainingStatus(project).then(setStatus).catch((e: Error) => setError(e.message))}
          />
        ) : (
          <p className="form-error">{status.reason}</p>
        )
      )}
      {status && (status.running_job || status.busy_elsewhere) && <p className="form-error">Another training job is running on this machine.</p>}

      <div className="form-section">
        <h3>Data</h3>
        <label className="field">
          <span>Dataset version</span>
          <div className="select-wrap">
            <select value={releaseId} disabled={!releases?.length} onChange={(e) => chooseRelease(releases?.find((r) => r.id === e.target.value))}>
              {(releases ?? []).map((r) => (
                <option key={r.id} value={r.id}>
                  v{r.version} · {r.name}{r.name.includes(r.dataset) ? "" : ` (${r.dataset})`} · {formatNumber(Object.values(r.sets).reduce((n, s) => n + s.images, 0))} images{r.mode === "verified" ? ", verified only" : ""}
                </option>
              ))}
            </select>
          </div>
        </label>
        <div className="field-pair field-trio">
          <label className="field">
            <span>Train on</span>
            <div className="select-wrap">
              <select value={trainSet} disabled={!release} onChange={(e) => setTrainSet(e.target.value)}>{setOptions}</select>
            </div>
          </label>
          <label className="field">
            <span>Validate on</span>
            <div className="select-wrap">
              <select value={validSet} disabled={!release} onChange={(e) => setValidSet(e.target.value)}>{setOptions}</select>
            </div>
          </label>
          <label className="field">
            <span>Test on</span>
            <div className="select-wrap">
              <select value={testSet} disabled={!release} onChange={(e) => setTestSet(e.target.value)}>
                <option value="">None</option>
                {setOptions}
              </select>
            </div>
          </label>
        </div>
        <p className="faint small">Validation picks the best weights. The test set is held out and scored once, on the final model.</p>
        {releases && releases.length === 0 ? (
          <p className="form-error">
            Training uses dataset versions only. <a href={routeHref({ name: "images", project })} onClick={onClose}>Create a dataset</a> from Images first.
          </p>
        ) : (
          problem && release && <p className="form-error">{problem}</p>
        )}
        {release && !trainsOnBoxes(release.tasks) && (
          <p className="small warn-text">
            {release.name} is labelled for {tasksLabel(release.tasks).toLowerCase()}. These models are box detectors and train on its boxes only.
          </p>
        )}
        {release?.mode === "all" && Object.values(release.sets).some((s) => (s.verified ?? s.images) < s.images) && (
          <p className="faint small">This version includes unverified images.</p>
        )}
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

/** Training packages are not installed: offer to install them into Granum's own folder. */
function TrainingAddon({ size, running, onInstalled }: {
  size: string;
  running: Job<{ installed: string }> | null;
  onInstalled: () => void;
}) {
  const [job, setJob] = useState(running);
  const [error, setError] = useState<string | null>(null);
  const [showLog, setShowLog] = useState(false);

  useEffect(() => {
    if (!job || job.status !== "running") return;
    const timer = window.setInterval(() => {
      api.job<{ installed: string }>(job.id)
        .then((next) => {
          setJob(next);
          if (next.status === "done") onInstalled();
        })
        .catch(() => undefined);
    }, 1500);
    return () => window.clearInterval(timer);
  }, [job, onInstalled]);

  const start = async () => {
    setError(null);
    try {
      setJob(await api.installTraining());
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  };

  const busy = job?.status === "running";
  return (
    <div className="addon-card">
      <div className="addon-head">
        <Icon name="runs" />
        <div>
          <span className="strong">Training support is not installed</span>
          <span className="muted small block">
            Granum installs PyTorch and Ultralytics into its own folder ({size} download). Nothing is added to your system.
          </span>
        </div>
        <span className="spacer" />
        {!busy && job?.status !== "done" && (
          <button className="button primary" onClick={() => void start()}>
            {job?.status === "failed" ? "Retry" : "Install training support"}
          </button>
        )}
      </div>
      {busy && (
        <>
          <p className="small addon-phase"><span className="spinner" /> {job!.phase}</p>
          <Progress done={0} total={0} />
          <p className="faint small">This can take several minutes. You can keep using Granum; installation continues in the background.</p>
        </>
      )}
      {job?.status === "failed" && <p className="form-error">{job.error}</p>}
      {job?.status === "done" && <p className="small addon-done"><Icon name="check" size={13} /> Installed</p>}
      {error && <p className="form-error">{error}</p>}
      {job && (
        <>
          <button className="button subtle small" onClick={() => setShowLog(!showLog)}>{showLog ? "Hide details" : "Details"}</button>
          {showLog && <pre className="code-block training-log">{(job.log ?? []).slice(-30).join("\n") || "Starting"}</pre>}
        </>
      )}
    </div>
  );
}

function formatDuration(seconds: number): string {
  if (seconds < 90) return `${Math.max(1, Math.round(seconds))} s`;
  if (seconds < 5400) return `${Math.round(seconds / 60)} min`;
  return `${Math.floor(seconds / 3600)} h ${Math.round((seconds % 3600) / 60)} min`;
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
        {running && (job.steps ?? 0) > 0 && (
          <span className="faint small tabular">
            step {formatNumber(job.step ?? 0)}/{formatNumber(job.steps!)}
            {job.round_eta ? ` · ~${formatDuration(job.round_eta)} left in this round` : ""}
          </span>
        )}
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
      {running && (
        (job.steps ?? 0) > 0
          ? <Progress done={job.done * job.steps! + (job.step ?? 0)} total={job.total * job.steps!} />
          : <Progress done={job.done} total={job.total} />
      )}
      {running && job.done === 0 && (
        <p className="faint small training-note">Charts and per-image dynamics update at the end of each round.</p>
      )}
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
