/** Import a dataset: choose files, run preflight, decide on each finding, import. */

import { useEffect, useMemo, useRef, useState } from "react";
import type { PreflightReport } from "../api/types";
import { Icon, PageHeader, Progress, VerdictBadge, formatNumber, plural } from "../components/ui";
import { Modal } from "../components/Modal";
import { effectLabel, phaseLabel } from "../copy/plain";
import { routeHref } from "../router";
import { useStore } from "../store/store";
import { ReportView } from "./ReportView";
import { SourcePicker } from "./SourcePicker";
import { SplitSlider } from "./SplitSlider";
import { taskLabel, taskWarning, tasksLabel } from "./tasks";
import { useImport, type Step } from "./importStore";

/** How splits are usually read, whatever order preflight returns them in. */
const SPLIT_ORDER = ["train", "valid", "val", "validation", "test"];

const STEPS: { id: Step; label: string }[] = [
  { id: "choose", label: "Project and data" },
  { id: "checking", label: "Preflight" },
  { id: "review", label: "Review findings" },
  { id: "done", label: "Done" },
];

function stepIndex(step: Step): number {
  if (step === "importing") return 2;
  return STEPS.findIndex((s) => s.id === step);
}

export function ImportPage({ project, example }: { project?: string; example?: boolean }) {
  const step = useImport((s) => s.step);
  const reset = useImport((s) => s.reset);
  const projectName = useImport((s) => s.projectName);
  const setProjectName = useImport((s) => s.setProjectName);

  const projects = useStore((s) => s.projects);
  const sourceCount = useImport((s) => s.sources.length);
  const loadExample = useImport((s) => s.loadExample);
  // Opened from "Try the example project": start with the generated dataset chosen.
  const exampleAsked = useRef(false);
  useEffect(() => {
    if (!example || exampleAsked.current || step !== "choose" || sourceCount) return;
    exampleAsked.current = true;
    void loadExample();
  }, [example, step, sourceCount, loadExample]);
  // Adding data fixes the project; creating one starts from a free name.
  useEffect(() => {
    if (step !== "choose") return;
    if (project && projectName !== project) setProjectName(project);
    if (!project && projects.some((p) => p.name === projectName)) setProjectName("");
  }, [project, step, projectName, setProjectName, projects]);

  const current = stepIndex(step);
  return (
    <div className="page page-wide">
      <PageHeader
        title={project ? "Add data" : "Create project"}
        context={project}
        subtitle="Preflight validates annotations and images before anything is written."
        actions={step !== "choose" && step !== "checking" && step !== "importing" ? (
          <button className="button" onClick={() => reset(project)}>Start over</button>
        ) : undefined}
      />
      <ol className="stepper" aria-label="Import progress">
        {STEPS.map((s, i) => (
          <li key={s.id} className={i < current ? "done" : i === current ? "current" : ""} aria-current={i === current ? "step" : undefined}>
            <span className="step-number">{i < current ? <Icon name="check" size={13} /> : i + 1}</span>
            {s.label}
          </li>
        ))}
      </ol>
      {step === "choose" && <SourcePicker project={project} />}
      {step === "checking" && <Checking />}
      {(step === "review" || step === "importing") && <Review />}
      {step === "done" && <Done />}
    </div>
  );
}

function Checking() {
  const job = useImport((s) => s.job);
  const cancel = useImport((s) => s.cancel);
  const sources = useImport((s) => s.sources);
  return (
    <div className="panel-card checking" aria-live="polite">
      <h2 className="card-title">{phaseLabel(job?.phase)}</h2>
      <Progress done={job?.done ?? 0} total={job?.total ?? 0} />
      <p className="muted">
        {job && job.total > 0 ? `${formatNumber(job.done)} of ${formatNumber(job.total)} done` : `Checking ${sources.map((s) => s.split).join(" and ")}`}
        {job ? `, ${job.elapsed.toFixed(0)} s` : ""}
      </p>
      <button className="button" onClick={() => void cancel()}>Cancel</button>
    </div>
  );
}

function Review() {
  const report = useImport((s) => s.report)!;
  const choices = useImport((s) => s.choices);
  const choose = useImport((s) => s.choose);
  const step = useImport((s) => s.step);
  const projectName = useImport((s) => s.projectName);
  const tableName = useImport((s) => s.tableName);
  const setTableName = useImport((s) => s.setTableName);
  const runImport = useImport((s) => s.runImport);
  const backToChoose = useImport((s) => s.backToChoose);
  const importJob = useImport((s) => s.importJob);
  const error = useImport((s) => s.error);
  const chosenTasks = useImport((s) => s.tasks);
  const projects = useStore((s) => s.projects);
  const detected = report.summary.task;
  const tasks = chosenTasks.length ? chosenTasks : [detected?.detected ?? "object_detection"];
  // The chosen types, checked against what the annotation files hold.
  const mismatches = tasks.map((t) => taskWarning(t, detected?.counts)).filter((w): w is string => Boolean(w));
  const [confirming, setConfirming] = useState(false);
  const asked = useRef(false);
  useEffect(() => {
    if (mismatches.length && !asked.current && step === "review") {
      asked.current = true;
      setConfirming(true);
    }
  }, [mismatches.length, step]);

  const blocks = report.findings.filter((f) => f.severity === "block");
  const fatal = blocks.filter((f) => f.options.length === 0);
  const warnings = report.findings.filter((f) => f.severity === "warn");
  const changed = report.findings.filter((f) => f.options.length > 0 && choices[f.code] !== f.default);
  const exists = projects.some((p) => p.name === projectName.trim());
  const importing = step === "importing";

  return (
    <div className="review-layout">
      <div className="review-main">
        <SplitPlan report={report} disabled={importing} />
        <ReportView report={report} choices={choices} onChoose={importing ? undefined : choose} />
      </div>
      <aside className="review-side">
        <div className="panel-card decision-card">
          <VerdictBadge verdict={report.verdict} />
          <p className="decision-summary">
            {formatNumber(report.summary.images)} images, {formatNumber(report.summary.boxes)} boxes
          </p>
          <ul className="decision-counts">
            {blocks.length > 0 && <li><span className="severity-block">{plural(blocks.length, "blocker")}</span>, resolved on import</li>}
            {warnings.length > 0 && <li><span className="severity-warn">{plural(warnings.length, "warning")}</span></li>}
            <li>{changed.length === 0 ? "Default resolutions" : `${plural(changed.length, "resolution")} changed from default`}</li>
          </ul>
          {fatal.length > 0 && (
            <p className="form-error">
              {fatal[0]!.title}. Cannot be resolved on import; fix the source file and rerun preflight.
            </p>
          )}

          <dl className="import-facts">
            <div><dt>Project</dt><dd>{projectName.trim()} <span className="faint small">{exists ? "existing" : "new"}</span></dd></div>
            <div><dt>Type</dt><dd>{tasksLabel(tasks)}</dd></div>
          </dl>
          {mismatches.length > 0 ? (
            <ul className="type-mismatches">
              {mismatches.map((m) => <li key={m} className="small warn-text">{m}</li>)}
            </ul>
          ) : detected && (
            <p className="faint small">Type matches the data: {detected.reason}.</p>
          )}
          <label className="field">
            <span>Initial version name</span>
            <input type="text" value={tableName} onChange={(e) => setTableName(e.target.value)} disabled={importing} />
          </label>

          {error && <p className="form-error">{error}</p>}
          {importing ? (
            <div aria-live="polite">
              <Progress done={importJob?.done ?? 0} total={importJob?.total ?? 0} />
              <p className="muted small">{phaseLabel(importJob?.phase)}</p>
            </div>
          ) : (
            <button
              className="button primary large"
              disabled={fatal.length > 0 || !projectName.trim()}
              onClick={() => (mismatches.length ? setConfirming(true) : void runImport())}
            >
              Import
            </button>
          )}
          {!importing && <button className="button subtle" onClick={backToChoose}>Change sources</button>}
        </div>
      </aside>
      {confirming && (
        <Modal
          title="Project type does not match the data"
          onClose={() => setConfirming(false)}
          width={520}
          footer={
            <>
              <span className="spacer" />
              <button onClick={() => { setConfirming(false); backToChoose(); }}>Change project type</button>
              <button className="primary" disabled={fatal.length > 0 || !projectName.trim()} onClick={() => { setConfirming(false); void runImport(); }}>
                Import anyway
              </button>
            </>
          }
        >
          <p>
            You chose <span className="strong">{tasksLabel(tasks)}</span>, but the data does not fully support it:
          </p>
          <ul className="type-mismatches">
            {mismatches.map((m) => <li key={m} className="warn-text">{m}</li>)}
          </ul>
          {detected && (
            <p className="muted small">
              From the annotation files this looks like <span className="strong">{taskLabel(detected.detected)}</span> ({detected.reason}).
            </p>
          )}
          <p className="muted small">Import anyway to keep the chosen type, or go back and change it.</p>
        </Modal>
      )}
    </div>
  );
}

/** How many images each split gets, and a slider to move them between splits. */
function SplitPlan({ report, disabled }: { report: PreflightReport; disabled: boolean }) {
  const splitPlan = useImport((s) => s.splitPlan);
  const setSplitPlan = useImport((s) => s.setSplitPlan);
  // train, valid, test reads better than the alphabetical order preflight returns.
  const splits = useMemo(() => {
    const rank = (name: string) => {
      const at = SPLIT_ORDER.indexOf(name);
      return at === -1 ? SPLIT_ORDER.length : at;
    };
    return [...report.summary.splits].sort((a, b) => rank(a.split) - rank(b.split) || a.split.localeCompare(b.split));
  }, [report.summary.splits]);
  const original = useMemo(
    () => Object.fromEntries(splits.map((s) => [s.split, s.images])),
    [splits],
  );
  const leakage = report.findings.some((f) => f.code.startsWith("split."));
  const plan = splitPlan ?? original;
  const changed = splits.some((s) => plan[s.split] !== s.images);

  if (splits.length === 0) return null;

  return (
    <div className="panel-card split-plan">
      <div className="split-plan-head">
        <h2 className="card-title">Splits</h2>
        <span className="muted small">
          {formatNumber(report.summary.images)} images
          {splits.length > 1 ? " · drag a handle to move images between splits" : ""}
        </span>
        {changed && (
          <button className="button subtle small" disabled={disabled} onClick={() => setSplitPlan(null)}>Reset</button>
        )}
      </div>
      {splits.length > 1 ? (
        <SplitSlider splits={splits} plan={plan} onChange={setSplitPlan} disabled={disabled} />
      ) : (
        <p className="muted">
          {splits[0]!.split}: {formatNumber(splits[0]!.images)} images. Import more than one split to re-cut them.
        </p>
      )}
      {changed && (
        <p className="faint small">
          Images move between splits on import; none are left out.
          {leakage && " Preflight found leakage between the splits as they are now, so check its findings before re-cutting."}
        </p>
      )}
    </div>
  );
}

function Done() {
  const result = useImport((s) => s.result)!;
  const refreshProjects = useStore((s) => s.refreshProjects);
  useEffect(() => {
    void refreshProjects();
  }, [refreshProjects]);
  const project = result.project_name;

  return (
    <div className="done">
      <div className="panel-card done-card">
        <h2>Imported into {project}</h2>
        <ul className="done-tables">
          {result.tables.map((table) => (
            <li key={table.url}>
              <div>
                <span className="strong">{table.split}</span>
                <span className="muted"> {formatNumber(table.rows)} images, {formatNumber(table.boxes)} boxes</span>
              </div>
              <a className="button primary" href={routeHref({ name: "table", project, url: table.url })}>Open {table.split}</a>
            </li>
          ))}
        </ul>
        {Object.keys(result.effects).length > 0 && (
          <>
            <h3 className="card-title">What was changed during import</h3>
            <ul className="effects">
              {Object.entries(result.effects).sort().map(([effect, count]) => (
                <li key={effect}><span className="effect-count">{formatNumber(count)}</span><span>{effectLabel(effect)}</span></li>
              ))}
            </ul>
          </>
        )}
        <div className="done-actions">
          <a className="button" href={routeHref({ name: "report", project, id: result.id })}>See the health check report</a>
          <a className="button subtle" href={routeHref({ name: "overview", project })}>Go to project</a>
        </div>
      </div>
    </div>
  );
}
