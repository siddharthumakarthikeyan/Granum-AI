/** Is this dataset fit to train on? One page, one answer, and what to do about it.
 *
 * Nothing here is a new measurement. The import found broken files, the neighbour graph
 * found copies and leaks, a check found labels worth looking at, the review log knows what
 * has been verified — each of those lives on the page where the work happens, which is the
 * right place to fix things and the wrong place to ask whether they are fixed.
 *
 * What the page adds is a threshold for each of them, stated out loud, and a link to the
 * place the work is done. It says *not looked at* where nothing has looked, rather than
 * showing a green tick for a question nobody asked: a health report that cannot be wrong is
 * a decoration.
 */

import { useEffect, useMemo, useState } from "react";
import { api } from "../api/client";
import type { DatasetHealth } from "../api/types";
import { EmptyState, Icon, PageHeader, formatNumber, plural } from "../components/ui";
import { groupDatasets, REMOVED_SET } from "./datasets";
import { navigate, routeHref } from "../router";
import { useStore } from "../store/store";

const TONE: Record<string, string> = { block: "bad", warn: "warn", ok: "good" };
const VERDICT: Record<string, string> = {
  block: "Not ready to train on",
  warn: "Worth a look before training",
  ok: "Nothing standing in the way",
};

export function HealthPage({ project, dataset }: { project: string; dataset?: string }) {
  const tables = useStore((s) => s.tables);
  const datasets = useMemo(
    () => groupDatasets(tables).filter((d) => d.splits.some((s) => s.name !== REMOVED_SET)),
    [tables],
  );
  const active = dataset ?? datasets[0]?.name;
  const [report, setReport] = useState<DatasetHealth | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!active) return;
    let alive = true;
    setReport(null);
    setError(null);
    api.datasetHealth(project, active)
      .then((next) => alive && setReport(next))
      .catch((e) => alive && setError(e instanceof Error ? e.message : String(e)));
    return () => {
      alive = false;
    };
  }, [project, active]);

  /** Where each check is worked on. A verdict with nowhere to go is only a complaint. */
  const where = (code: string): { label: string; href: string } | null => {
    if (!active) return null;
    const images = (extra: Record<string, string>) =>
      routeHref({ name: "images", project, dataset: active, ...extra });
    switch (code) {
      case "leaks":
      case "copies":
      case "outliers":
        return { label: "Open Duplicates", href: images({ similar: true } as never) };
      case "findings":
        return { label: "Open Findings", href: routeHref({ name: "findings", project }) };
      case "drafts":
        return { label: "Open Images", href: images({}) };
      case "review":
        return { label: "Open Review", href: images({ review: true } as never) };
      case "classes":
        return { label: "See the classes", href: images({}) };
      case "holdout":
        return { label: "Open Datasets", href: routeHref({ name: "datasets", project }) };
      default:
        return null;
    }
  };

  const header = (
    <PageHeader
      title="Health"
      context={project}
      subtitle={report
        ? `${plural(report.images, "image")} · ${formatNumber(report.boxes)} boxes · ${plural(report.checks.length, "check")}`
        : "What stands between this dataset and a run worth trusting"}
      actions={datasets.length > 1 ? (
        <div className="select-wrap">
          <select aria-label="Dataset" value={active} onChange={(e) => navigate({ name: "health", project, dataset: e.target.value })}>
            {datasets.map((d) => <option key={d.name} value={d.name}>{d.name}</option>)}
          </select>
        </div>
      ) : undefined}
    />
  );

  if (!active) {
    return (
      <div className="page">
        {header}
        <EmptyState title="No dataset yet" action={<a className="button primary" href={routeHref({ name: "import", project })}><Icon name="import" />Add data</a>}>
          <p>Import a dataset and this page will say whether it is fit to train on.</p>
        </EmptyState>
      </div>
    );
  }

  return (
    <div className="page health-page">
      {header}
      {error && <p className="form-error">{error}</p>}
      {!report && !error && <p className="muted"><span className="spinner" /> Reading the dataset</p>}

      {report && (
        <>
          <div className={`panel health-verdict ${TONE[report.verdict]}`}>
            <span className={`health-dot ${TONE[report.verdict]}`} />
            <div className="health-verdict-text">
              <span className="strong">{VERDICT[report.verdict]}</span>
              <span className="muted small">
                {report.counts.block > 0 && `${plural(report.counts.block, "thing")} to fix · `}
                {report.counts.warn > 0 && `${formatNumber(report.counts.warn)} to look at · `}
                {formatNumber(report.counts.ok)} fine
              </span>
            </div>
            <span className="spacer" />
            <div className="health-sets">
              {Object.entries(report.sets).map(([name, count]) => (
                <span key={name} className="set-chip">{name} {formatNumber(count)}</span>
              ))}
            </div>
          </div>

          <ul className="health-checks">
            {report.checks.map((item) => {
              const go = where(item.code);
              return (
                <li key={item.code} className={`health-check ${TONE[item.severity]}`}>
                  <span className={`health-dot ${TONE[item.severity]}`} />
                  <div className="health-check-text">
                    <span className="strong">{item.title}</span>
                    <span className="muted small">{item.detail}</span>
                    {item.rows && item.rows.length > 0 && (
                      <span className="health-rows">
                        {item.rows.map((row) => (
                          <span key={row.label} className={`health-class ${row.verdict === "ok" ? "" : "thin"}`}>
                            {row.name}<span className="faint"> {formatNumber(row.labels)}</span>
                          </span>
                        ))}
                      </span>
                    )}
                  </div>
                  <span className="spacer" />
                  {go && <a className="button subtle small" href={go.href}>{go.label}</a>}
                </li>
              );
            })}
          </ul>

          <p className="faint small health-policy">
            Thresholds: a class needs {report.policy.min_class_labels} labels and{" "}
            {Math.round((report.policy.rare_share ?? 0) * 100)}% of the largest class; a held-out set needs{" "}
            {report.policy.min_holdout} images; repeats above{" "}
            {Math.round((report.policy.duplicate_share ?? 0) * 100)}% of the set are worth removing. They are
            defaults, not laws — argue with them in <span className="mono">granum.metrics.health</span>.
          </p>
        </>
      )}
    </div>
  );
}
