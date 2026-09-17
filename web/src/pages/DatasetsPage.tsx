/** Datasets, their sets, and each set's version history. */

import { useState } from "react";
import { EmptyState, Icon, ImageStrip, PageHeader, VerdictBadge, formatNumber, formatWhen, plural } from "../components/ui";
import { navigate, routeHref } from "../router";
import { useStore } from "../store/store";
import { HOLDING_SETS, REMOVED_SET, describeOp, groupDatasets, type Dataset, type Revision } from "./datasets";

/** The revision stack: one plate per version, the newest on top. */
export function RevisionStack({ revisions, latestUrl, max = 4 }: { revisions: Revision[]; latestUrl: string; max?: number }) {
  const shown = revisions.slice(-max);
  return (
    <div className="revision-stack" aria-hidden="true">
      {shown.map((revision, i) => (
        <span
          key={revision.entry.url}
          className={`plate${revision.entry.url === latestUrl ? " latest" : ""}${revision.depth === 0 ? " root" : ""}`}
          style={{ bottom: i * 5, zIndex: i }}
        />
      ))}
    </div>
  );
}

export function DatasetsPage({ project }: { project: string }) {
  const tables = useStore((s) => s.tables);
  const loading = useStore((s) => s.loading);
  const datasets = groupDatasets(tables);

  return (
    <div className="page">
      <PageHeader
        title="Datasets"
        context={project}
        subtitle={`${plural(datasets.length, "dataset")}, ${plural(tables.length, "version")}`}
        actions={<a className="button" href={routeHref({ name: "import", project })}><Icon name="import" />Import</a>}
      />
      {datasets.length === 0 && !loading && (
        <EmptyState
          title="No datasets"
          action={<a className="button primary" href={routeHref({ name: "import", project })}><Icon name="import" />Import a COCO dataset</a>}
        >
          <p>Datasets written by training scripts with the Granum SDK also appear here.</p>
        </EmptyState>
      )}
      {datasets.map((dataset) => <DatasetPanel key={dataset.name} project={project} dataset={dataset} />)}
    </div>
  );
}

/** One dataset; its sets (train, valid, test, removed) are views of it, chosen with a toggle. */
function DatasetPanel({ project, dataset }: { project: string; dataset: Dataset }) {
  const live = dataset.splits.filter((s) => !HOLDING_SETS.includes(s.name));
  const [chosen, setChosen] = useState(() => (live.find((s) => /^train/i.test(s.name)) ?? dataset.splits[0])!.name);
  const split = dataset.splits.find((s) => s.name === chosen) ?? dataset.splits[0]!;
  const removed = split.name === REMOVED_SET;
  const images = live.reduce((n, s) => n + s.latest.row_count, 0);
  const boxes = live.reduce((n, s) => n + (s.latest.box_count ?? 0), 0);
  const classes = Math.max(0, ...live.map((s) => s.latest.class_count ?? 0));
  const imported = split.revisions.find((r) => r.entry.preflight)?.entry.preflight;
  const history = [...split.revisions].reverse();

  return (
    <section className="dataset-panel" aria-labelledby={`dataset-${dataset.name}`}>
      <header className="dataset-panel-head">
        <div className="dataset-panel-title">
          <h2 id={`dataset-${dataset.name}`}>{dataset.name}</h2>
          <span className="muted small">{formatNumber(images)} images, {formatNumber(boxes)} boxes, {plural(classes, "class", "classes")}</span>
        </div>
        <span className="spacer" />
        <div className="segmented split-toggle" role="tablist" aria-label="Set">
          {dataset.splits.map((s) => (
            <button
              key={s.name}
              role="tab"
              aria-selected={s.name === split.name}
              className={s.name === split.name ? "on" : ""}
              onClick={() => setChosen(s.name)}
            >
              {s.name}
              <span className="split-toggle-count">{formatNumber(s.latest.row_count)}</span>
            </button>
          ))}
        </div>
        {removed ? (
          <a className="button primary" href={routeHref({ name: "removed", project, dataset: dataset.name })}>Review removed</a>
        ) : (
          <a className="button primary" href={routeHref({ name: "table", project, url: split.latest.url })}>Open {split.name}</a>
        )}
      </header>

      {!removed && (
        <ImageStrip
          key={split.latest.url}
          url={split.latest.url}
          project={project}
          dataset={dataset.name}
          count={12}
          height={96}
          onOpen={() => navigate({ name: "table", project, url: split.latest.url })}
        />
      )}

      <dl className="split-facts">
        <div><dt>Newest version</dt><dd className="mono">{split.latest.name}</dd></div>
        <div><dt>Images</dt><dd>{formatNumber(split.latest.row_count)}</dd></div>
        <div><dt>Boxes</dt><dd>{split.latest.box_count !== undefined ? formatNumber(split.latest.box_count) : "—"}</dd></div>
        <div><dt>Versions</dt><dd>{split.revisions.length}</dd></div>
        <div><dt>Last change</dt><dd>{describeOp(split.latest.op)}, {formatWhen(split.latest.created)}</dd></div>
        <div>
          <dt>Preflight</dt>
          <dd>
            {imported ? (
              <a href={routeHref({ name: "report", project, id: imported.import_id })}>
                <VerdictBadge verdict={imported.verdict} label={imported.verdict === "pass" ? "Passed" : plural(imported.warnings, "warning")} />
              </a>
            ) : "—"}
          </dd>
        </div>
      </dl>

      <div className="table-scroll">
        <table className="data-table version-table">
          <thead>
            <tr>
              <th style={{ width: 34 }} />
              <th>Version</th>
              <th>Change</th>
              <th className="num">Images</th>
              <th className="num">Δ</th>
              <th>Created</th>
            </tr>
          </thead>
          <tbody>
            {history.map((revision, i) => {
              const entry = revision.entry;
              const previous = history[i + 1]?.entry;
              const delta = previous ? entry.row_count - previous.row_count : null;
              const latest = entry.url === split.latest.url;
              return (
                <tr
                  key={entry.url}
                  className={removed ? "" : "clickable"}
                  onClick={() => !removed && navigate({ name: "table", project, url: entry.url })}
                  title={entry.url}
                >
                  <td><span className={`version-dot${latest ? " latest" : ""}`} /></td>
                  <td className="cell-mono">{entry.name}{latest && <span className="tag">newest</span>}</td>
                  <td className="muted version-change">{describeOp(entry.op)}{entry.description && entry.op !== "from_coco" ? `: ${entry.description}` : ""}</td>
                  <td className="num">{formatNumber(entry.row_count)}</td>
                  <td className={`num ${delta && delta < 0 ? "delta-down" : delta ? "delta-up" : "faint"}`}>{delta ? `${delta > 0 ? "+" : ""}${formatNumber(delta)}` : "—"}</td>
                  <td className="muted">{formatWhen(entry.created)}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </section>
  );
}
