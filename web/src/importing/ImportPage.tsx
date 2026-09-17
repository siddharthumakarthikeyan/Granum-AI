/** Import a dataset: choose files, run preflight, decide on each finding, import. */

import { useEffect } from "react";
import { Icon, PageHeader, Progress, VerdictBadge, formatNumber, plural } from "../components/ui";
import { effectLabel, phaseLabel } from "../copy/plain";
import { routeHref } from "../router";
import { useStore } from "../store/store";
import { ReportView } from "./ReportView";
import { SourcePicker } from "./SourcePicker";
import { useImport, type Step } from "./importStore";

const STEPS: { id: Step; label: string }[] = [
  { id: "choose", label: "Select sources" },
  { id: "checking", label: "Preflight" },
  { id: "review", label: "Review findings" },
  { id: "done", label: "Done" },
];

function stepIndex(step: Step): number {
  if (step === "importing") return 2;
  return STEPS.findIndex((s) => s.id === step);
}

export function ImportPage({ project }: { project?: string }) {
  const step = useImport((s) => s.step);
  const reset = useImport((s) => s.reset);
  const projectName = useImport((s) => s.projectName);
  const setProjectName = useImport((s) => s.setProjectName);

  useEffect(() => {
    if (project && step === "choose" && !projectName) setProjectName(project);
  }, [project, step, projectName, setProjectName]);

  const current = stepIndex(step);
  return (
    <div className="page page-wide">
      <PageHeader
        title="Import COCO dataset"
        subtitle="Preflight validates annotations and images before anything is written. Resolutions are recorded with the version."
        actions={step !== "choose" && step !== "checking" && step !== "importing" ? (
          <button className="button" onClick={() => reset(project)}>New import</button>
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
      {step === "choose" && <SourcePicker />}
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
  const setProjectName = useImport((s) => s.setProjectName);
  const tableName = useImport((s) => s.tableName);
  const setTableName = useImport((s) => s.setTableName);
  const runImport = useImport((s) => s.runImport);
  const backToChoose = useImport((s) => s.backToChoose);
  const importJob = useImport((s) => s.importJob);
  const error = useImport((s) => s.error);
  const projects = useStore((s) => s.projects);

  const blocks = report.findings.filter((f) => f.severity === "block");
  const fatal = blocks.filter((f) => f.options.length === 0);
  const warnings = report.findings.filter((f) => f.severity === "warn");
  const changed = report.findings.filter((f) => f.options.length > 0 && choices[f.code] !== f.default);
  const exists = projects.some((p) => p.name === projectName.trim());
  const importing = step === "importing";

  return (
    <div className="review-layout">
      <div className="review-main">
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

          <label className="field">
            <span>Project</span>
            <input type="text" value={projectName} onChange={(e) => setProjectName(e.target.value)} list="project-names" disabled={importing} />
            <datalist id="project-names">{projects.map((p) => <option key={p.name} value={p.name} />)}</datalist>
            <span className="faint small">{projectName.trim() ? (exists ? "Existing project" : "New project") : ""}</span>
          </label>
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
              onClick={() => void runImport()}
            >
              Import
            </button>
          )}
          {!importing && <button className="button subtle" onClick={backToChoose}>Change sources</button>}
        </div>
      </aside>
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
