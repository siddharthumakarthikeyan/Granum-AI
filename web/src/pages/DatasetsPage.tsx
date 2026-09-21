/** Datasets: the dataset versions created from the Images tab. Training uses these only. */

import { useCallback, useEffect, useState } from "react";
import { api } from "../api/client";
import type { Release } from "../api/types";
import { EmptyState, Icon, ImageStrip, PageHeader, formatNumber, formatWhen, plural } from "../components/ui";
import { tasksLabel } from "../importing/tasks";
import { TrainDialog } from "../training/Training";
import { navigate, routeHref } from "../router";
import { recipeSummary } from "../images/AugmentationPanel";
import { DeleteReleaseDialog } from "./DeleteReleaseDialog";
import { useStore } from "../store/store";
import { groupDatasets } from "./datasets";

export function DatasetsPage({ project }: { project: string }) {
  const tables = useStore((s) => s.tables);
  const loading = useStore((s) => s.loading);
  const datasets = groupDatasets(tables);
  const [releases, setReleases] = useState<Release[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [training, setTraining] = useState<string | null>(null);
  const [deleting, setDeleting] = useState<Release | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  const load = useCallback(() => {
    api.releases(project).then(({ releases }) => setReleases(releases)).catch((e: Error) => setError(e.message));
  }, [project]);
  useEffect(load, [load, tables]);

  return (
    <div className="page">
      <PageHeader
        title="Datasets"
        context={project}
        subtitle={releases ? plural(releases.length, "dataset version") : undefined}
      />
      {error && <p className="form-error">{error}</p>}
      {notice && <div className="toast" role="status">{notice}</div>}

      {datasets.length > 0 && (
        <section className="release-section" aria-label="Dataset versions">
          {releases && releases.length === 0 && (
            <p className="muted release-empty">
              No dataset version yet. Review images, then use <a href={routeHref({ name: "images", project })}>Create dataset</a> on the Images tab.
            </p>
          )}
          {releases?.map((release) => (
            <ReleaseRibbon key={`${release.dataset}/${release.id}`} project={project} release={release}
              onTrain={() => setTraining(release.id)} onDelete={() => setDeleting(release)} />
          ))}
        </section>
      )}

      {datasets.length === 0 && !loading && (
        <EmptyState
          title="No datasets"
          action={<a className="button primary" href={routeHref({ name: "import", project })}><Icon name="import" />Add data</a>}
        >
          <p>Datasets written by training scripts with the Granum SDK also appear here.</p>
        </EmptyState>
      )}

      {deleting && (
        <DeleteReleaseDialog
          project={project}
          release={deleting}
          onClose={() => setDeleting(null)}
          onDeleted={() => {
            setNotice(`Deleted ${deleting.name}`);
            window.setTimeout(() => setNotice(null), 4000);
            setDeleting(null);
            load();
          }}
        />
      )}

      {training && (
        <TrainDialog
          project={project}
          preset={{ release: training }}
          onClose={() => setTraining(null)}
          onStarted={() => navigate({ name: "runs", project })}
        />
      )}
    </div>
  );
}

/** One dataset version, laid out like a working dataset: its sets, a strip of images, the
 * facts of how it was made, and a way to train on it. */
function ReleaseRibbon({ project, release, onTrain, onDelete }: { project: string; release: Release; onTrain: () => void; onDelete: () => void }) {
  const sets = Object.entries(release.sets);
  const [chosen, setChosen] = useState(() => (sets.find(([name]) => /^train/i.test(name)) ?? sets[0])?.[0] ?? "");
  const current = release.sets[chosen] ?? sets[0]?.[1];
  const images = sets.reduce((n, [, s]) => n + s.images, 0);
  const verifiedOf = (set: { images: number; verified?: number }) => set.verified ?? set.images;
  const verified = sets.reduce((n, [, s]) => n + verifiedOf(s), 0);
  const unverified = images - verified;
  const heading = `release-${release.dataset}-${release.id}`;

  return (
    <section className="dataset-panel release-panel" aria-labelledby={heading}>
      <header className="dataset-panel-head">
        <span className="release-version tabular" title={`Version ${release.version} of ${release.dataset}`}>v{release.version}</span>
        <div className="dataset-panel-title">
          <h2 id={heading}>{release.name}</h2>
          <span className="muted small">
            {tasksLabel(release.tasks)} · {formatNumber(images)} images from {release.dataset}
            {release.note ? ` · ${release.note}` : ""}
          </span>
        </div>
        <span className="spacer" />
        <div className="segmented split-toggle" role="tablist" aria-label="Set">
          {sets.map(([name, set]) => (
            <button key={name} role="tab" aria-selected={name === chosen} className={name === chosen ? "on" : ""} onClick={() => setChosen(name)}>
              {name}
              <span className="split-toggle-count">{formatNumber(set.images)}</span>
            </button>
          ))}
        </div>
        <button className="button primary" onClick={onTrain}><Icon name="runs" size={15} />Train</button>
        <button className="icon-button release-delete" onClick={onDelete} title={`Delete ${release.name}`} aria-label={`Delete ${release.name}`}>
          <Icon name="trash" size={15} />
        </button>
      </header>

      {current && (
        <ImageStrip key={current.url} url={current.url} project={project} dataset={release.dataset} count={12} height={96} />
      )}

      <dl className={`split-facts${release.augmentation ? " with-augmentation" : ""}`}>
        <div><dt>Version</dt><dd>v{release.version}</dd></div>
        <div><dt>Images</dt><dd>{formatNumber(images)}</dd></div>
        <div><dt>Verified</dt><dd>{formatNumber(verified)}</dd></div>
        <div>
          <dt>Contents</dt>
          <dd>
            {release.mode === "verified" ? (
              <span className="qa-chip reviewed">Verified only</span>
            ) : unverified > 0 ? (
              <span className="qa-chip rework">{formatNumber(unverified)} unverified</span>
            ) : (
              <span className="qa-chip reviewed">All verified</span>
            )}
          </dd>
        </div>
        {release.augmentation && (
          <div>
            <dt>Augmentation</dt>
            <dd title={recipeSummary(release.augmentation).detail}>
              {release.augmentation.copies}× · {recipeSummary(release.augmentation).names}
            </dd>
          </div>
        )}
        <div><dt>Created</dt><dd>{formatWhen(release.time)}</dd></div>
        <div><dt>By</dt><dd>{release.author || "—"}</dd></div>
      </dl>

      <div className="table-scroll">
        <table className="data-table version-table">
          <thead>
            <tr>
              <th style={{ width: 34 }} />
              <th>Set</th>
              <th>Set version</th>
              <th className="num">Images</th>
              <th className="num">Verified</th>
              <th className="num">Unverified</th>
            </tr>
          </thead>
          <tbody>
            {sets.map(([name, set]) => {
              const left = set.images - verifiedOf(set);
              return (
                <tr
                  key={name}
                  className={`clickable${name === chosen ? " selected" : ""}`}
                  onClick={() => navigate({ name: "table", project, url: set.url })}
                  title={set.url}
                >
                  <td><span className={`version-dot${name === chosen ? " latest" : ""}`} /></td>
                  <td>{name}</td>
                  <td className="cell-mono">{set.name}</td>
                  <td className="num">
                    {formatNumber(set.images)}
                    {set.augmented ? <span className="cell-sub">{formatNumber(set.originals ?? 0)} + {formatNumber(set.augmented)} augmented</span> : null}
                  </td>
                  <td className="num">{formatNumber(verifiedOf(set))}</td>
                  <td className={`num${left ? " warn-text" : " faint"}`}>{left ? formatNumber(left) : "—"}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </section>
  );
}
