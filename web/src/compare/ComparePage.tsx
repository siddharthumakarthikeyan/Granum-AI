/** Two runs side by side: what improved, what regressed, and what the comparison is worth.
 *
 * The order is deliberate. Whether the two runs may be compared at all comes first, then
 * what the difference is read as (a controlled comparison, or one where the data moved
 * too), and only then the numbers. Aggregates never stand alone: every count carries its
 * support, and the images neither run shares are shown rather than averaged away.
 */

import { useCallback, useEffect, useMemo, useState } from "react";
import { api } from "../api/client";
import type { CompatibilityCheck, ComparisonReport, DataChange, ObjectEntry, SampleChange, SliceRow } from "../api/types";
import { EmptyState, Icon, PageHeader, formatNumber, formatWhen, plural } from "../components/ui";
import { navigate, routeHref } from "../router";
import { useStore } from "../store/store";

type OutcomeFilter = "improved" | "regressed" | "unchanged" | "only_baseline" | "only_candidate" | null;

const OUTCOMES: { id: Exclude<OutcomeFilter, null>; label: string; hint: string }[] = [
  { id: "improved", label: "Improved", hint: "Fewer mistakes than before on this image" },
  { id: "regressed", label: "Regressed", hint: "More mistakes than before on this image" },
  { id: "unchanged", label: "Unchanged", hint: "The same true positives, false positives and misses" },
  { id: "only_baseline", label: "Only in baseline", hint: "Scored by the first run and not by the second" },
  { id: "only_candidate", label: "Only in candidate", hint: "Scored by the second run and not by the first" },
];

const PAGE = 50;
const fileOf = (path: string) => path.split("/").pop() ?? path;
const signed = (value: number, digits = 3) => `${value >= 0 ? "+" : ""}${value.toFixed(digits)}`;
const sentence = (text: string) => text.charAt(0).toUpperCase() + text.slice(1);

export function ComparePage({ project, baseline, candidate, split }: {
  project: string;
  baseline?: string;
  candidate?: string;
  split?: string;
}) {
  const runs = useStore((s) => s.runs);
  const finished = useMemo(
    () => [...runs].filter((r) => r.status !== "running").sort((a, b) => b.created.localeCompare(a.created)),
    [runs],
  );
  // Newest against the one before it: the comparison someone who just retrained wants.
  const candidateUrl = candidate ?? finished[0]?.url;
  const baselineUrl = baseline ?? finished.find((r) => r.url !== candidateUrl)?.url;

  const [report, setReport] = useState<ComparisonReport | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [outcome, setOutcome] = useState<OutcomeFilter>(null);
  const [shown, setShown] = useState(PAGE);

  const load = useCallback(async () => {
    if (!baselineUrl || !candidateUrl || baselineUrl === candidateUrl) return;
    setReport(null);
    setError(null);
    try {
      setReport(await api.compareRuns(baselineUrl, candidateUrl, split));
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }, [baselineUrl, candidateUrl, split]);

  useEffect(() => {
    void load();
  }, [load]);
  useEffect(() => setShown(PAGE), [outcome, split]);

  const go = (changes: { baseline?: string; candidate?: string; split?: string }) =>
    navigate({ name: "compare", project, baseline: baselineUrl, candidate: candidateUrl, split, ...changes });

  const header = (
    <PageHeader
      title="Compare runs"
      context={project}
      subtitle="Two runs on the same evaluation set, image by image."
      actions={report?.samples && baselineUrl && candidateUrl ? (
        <a className="button" href={api.comparisonFileUrl(baselineUrl, candidateUrl, report.split ?? undefined)} download>
          <Icon name="down" />Download report
        </a>
      ) : undefined}
    />
  );

  if (finished.length < 2) {
    return (
      <div className="page">
        {header}
        <EmptyState title="Two finished runs are needed" action={<a className="button" href={routeHref({ name: "runs", project })}>Go to runs</a>}>
          <p>A comparison needs a baseline and something to compare with it. Train a second model on the same evaluation set and come back.</p>
        </EmptyState>
      </div>
    );
  }

  return (
    <div className="page compare-page">
      {header}

      <div className="compare-pickers">
        <RunPicker label="Baseline" runs={finished} value={baselineUrl} exclude={candidateUrl} onChange={(url) => go({ baseline: url })} />
        <button className="icon-button compare-swap" title="Swap" aria-label="Swap the runs"
                onClick={() => go({ baseline: candidateUrl, candidate: baselineUrl })}>
          <Icon name="swap" size={15} />
        </button>
        <RunPicker label="Candidate" runs={finished} value={candidateUrl} exclude={baselineUrl} onChange={(url) => go({ candidate: url })} />
        {report && report.shared_splits.length > 1 && (
          <label className="inline-field small compare-split">
            <span className="muted">Set</span>
            <select value={report.split ?? ""} onChange={(e) => go({ split: e.target.value })}>
              {report.shared_splits.map((name) => <option key={name} value={name}>{name}</option>)}
            </select>
          </label>
        )}
      </div>

      {error && <p className="form-error">{error}</p>}
      {!report && !error && <p className="muted"><span className="spinner" /> Reading both runs' per-image results</p>}

      {report && (
        <>
          <Verdict report={report} />
          {/* A refusal states its reason in the card above; the rest of the checks still matter. */}
          <Checks checks={report.interpretation.kind === "blocked" ? report.checks.filter((c) => c.status !== "blocked") : report.checks} />

          {report.samples && report.slices && (
            <>
              <div className="compare-tiles">
                {OUTCOMES.map((o) => (
                  <button key={o.id} className={`compare-tile${outcome === o.id ? " on" : ""}${report.samples!.counts[o.id] ? "" : " empty"} tile-${o.id}`}
                          title={o.hint} disabled={!report.samples!.counts[o.id]}
                          onClick={() => setOutcome(outcome === o.id ? null : o.id)}>
                    <span className="tile-value">{formatNumber(report.samples!.counts[o.id])}</span>
                    <span className="tile-label">{o.label}</span>
                  </button>
                ))}
              </div>

              <Pooled report={report} />
              <Images report={report} project={project} outcome={outcome} shown={shown} onMore={() => setShown(shown + PAGE * 2)} />
              <Slices slices={report.slices} />
              <Changes report={report} />
              <Cost report={report} />
            </>
          )}
        </>
      )}
    </div>
  );
}

function RunPicker({ label, runs, value, exclude, onChange }: {
  label: string;
  runs: ObjectEntry[];
  value?: string;
  exclude?: string;
  onChange: (url: string) => void;
}) {
  return (
    <label className="inline-field compare-picker">
      <span className="muted">{label}</span>
      <select value={value ?? ""} onChange={(e) => onChange(e.target.value)}>
        {runs.map((r) => (
          <option key={r.url} value={r.url} disabled={r.url === exclude}>
            {r.name} — {formatWhen(r.created)}
          </option>
        ))}
      </select>
    </label>
  );
}

/** What may be read out of this comparison, before any number is shown. */
function Verdict({ report }: { report: ComparisonReport }) {
  const { interpretation: reading, headline } = report;
  if (reading.kind === "blocked") {
    return (
      <div className="compare-verdict blocked">
        <span className="compare-kind">Not comparable</span>
        <p>{reading.summary}</p>
        <p className="muted small">Granum will not average over two runs that were not measured the same way. Pick runs scored on the same set under the same rules.</p>
      </div>
    );
  }
  const delta = headline?.delta ?? null;
  const tone = delta === null || headline?.verdict === "too close to call" ? "even" : delta > 0 ? "better" : "worse";
  return (
    <div className={`compare-verdict ${tone}`}>
      <span className="compare-kind">{reading.kind === "controlled" ? "Controlled comparison" : "Observational comparison"}</span>
      {headline && headline.baseline !== null && headline.candidate !== null ? (
        <p className="compare-headline">
          <span className="compare-value">{headline.baseline.toFixed(3)}</span>
          <Icon name="chevron" size={13} className="compare-arrow" />
          <span className="compare-value">{headline.candidate.toFixed(3)}</span>
          <span className="muted">mAP50</span>
          <span className={`comparison-delta${tone === "even" ? "" : tone === "better" ? " up" : " down"}`}>
            {signed(delta ?? 0)}{headline.verdict === "too close to call" ? `, inside the ${headline.tolerance} tolerance` : ""}
          </span>
        </p>
      ) : (
        <p className="muted">Neither run recorded a final score, so there is no headline number. The per-image results below still compare.</p>
      )}
      <p>{reading.summary}</p>
      {headline && !headline.same_labels && (
        <p className="muted small">The two scores were computed on different labels ({headline.scored_on.baseline ?? "—"} and {headline.scored_on.candidate ?? "—"}).</p>
      )}
    </div>
  );
}

function Checks({ checks }: { checks: CompatibilityCheck[] }) {
  const [open, setOpen] = useState(false);
  const notable = checks.filter((c) => c.status !== "ok");
  const passed = checks.length - notable.length;
  return (
    <div className="compare-checks">
      <ul>
        {(open ? checks : notable).map((check) => (
          <li key={check.check} className={`check-${check.status}`}>
            <Icon name={check.status === "ok" ? "check" : check.status === "warn" ? "warn" : "block"} size={13} />
            <span className="check-name">{sentence(check.check.replace(/_/g, " "))}</span>
            <span className="muted">{check.detail}</span>
          </li>
        ))}
      </ul>
      {passed > 0 && (
        <button className="link-button small" onClick={() => setOpen(!open)}>
          {open ? "Hide" : `${passed} ${passed === 1 ? "check" : "checks"} passed`}
        </button>
      )}
    </div>
  );
}

/** Pooled over the images both runs scored, so the two columns rest on the same support. */
function Pooled({ report }: { report: ComparisonReport }) {
  const shared = report.samples!.shared;
  const rows = [
    { key: "f1" as const, label: "F1" },
    { key: "precision" as const, label: "Precision" },
    { key: "recall" as const, label: "Recall" },
  ];
  return (
    <div className="data-table-wrap compare-pooled">
      <table className="data-table">
        <thead>
          <tr>
            <th>On the {formatNumber(shared.baseline.images)} images both runs scored</th>
            <th className="num">{report.runs.baseline.name}</th>
            <th className="num">{report.runs.candidate.name}</th>
            <th className="num">Change</th>
          </tr>
        </thead>
        <tbody>
          {rows.map(({ key, label }) => (
            <tr key={key}>
              <td>{label}</td>
              <td className="num">{shared.baseline[key].toFixed(3)}</td>
              <td className="num">{shared.candidate[key].toFixed(3)}</td>
              <td className={`num ${shared.candidate[key] > shared.baseline[key] ? "up" : shared.candidate[key] < shared.baseline[key] ? "down" : ""}`}>
                {signed(shared.candidate[key] - shared.baseline[key])}
              </td>
            </tr>
          ))}
          <tr>
            <td>Found / missed / false</td>
            <td className="num cell-mono">{shared.baseline.tp} / {shared.baseline.fn} / {shared.baseline.fp}</td>
            <td className="num cell-mono">{shared.candidate.tp} / {shared.candidate.fn} / {shared.candidate.fp}</td>
            <td className="num muted">{plural(shared.baseline.labels, "label")}</td>
          </tr>
        </tbody>
      </table>
      <p className="compare-note muted small">
        At the operating point of {report.policy.operating_confidence} confidence, matched at IoU {report.policy.match_iou}.
        Round {(report.runs.baseline.epoch ?? 0) + 1} of the baseline against round {(report.runs.candidate.epoch ?? 0) + 1} of the candidate.
      </p>
    </div>
  );
}

function Images({ report, project, outcome, shown, onMore }: {
  report: ComparisonReport;
  project: string;
  outcome: OutcomeFilter;
  shown: number;
  onMore: () => void;
}) {
  const samples = report.samples!;
  const dataset = report.runs.candidate.dataset ?? report.runs.baseline.dataset ?? undefined;
  const unmatched = outcome === "only_baseline" || outcome === "only_candidate";
  const rows: SampleChange[] = unmatched ? [] : samples.images.filter((row) => outcome === null || row.outcome === outcome);
  const missing = outcome === "only_baseline" ? samples.only_baseline : outcome === "only_candidate" ? samples.only_candidate : [];

  const open = (image: string) => navigate({ name: "images", project, dataset, open: image });

  if (unmatched) {
    return (
      <div className="data-table-wrap">
        <table className="data-table">
          <thead>
            <tr><th>{outcome === "only_baseline" ? `Only ${report.runs.baseline.name} scored these` : `Only ${report.runs.candidate.name} scored these`}</th></tr>
          </thead>
          <tbody>
            {missing.slice(0, shown).map((image) => (
              <tr key={image} className="clickable" onClick={() => open(image)}>
                <td className="cell-mono">{fileOf(image)}</td>
              </tr>
            ))}
          </tbody>
        </table>
        {missing.length > shown && <div className="learning-more"><button className="button" onClick={onMore}>Show more</button></div>}
      </div>
    );
  }

  return (
    <div className="data-table-wrap">
      <table className="data-table">
        <thead>
          <tr>
            <th>Image</th>
            <th>Outcome</th>
            <th className="num">{report.runs.baseline.name}<span className="cell-sub">found / missed / false</span></th>
            <th className="num">{report.runs.candidate.name}<span className="cell-sub">found / missed / false</span></th>
            <th className="num">F1</th>
          </tr>
        </thead>
        <tbody>
          {rows.slice(0, shown).map((row) => (
            <tr key={row.image} className="clickable" onClick={() => open(row.image)}>
              <td className="cell-mono truncate">{fileOf(row.image)}</td>
              <td><span className={`outcome-tag tile-${row.outcome}`}>{row.outcome}</span></td>
              <td className="num cell-mono">{row.baseline.tp} / {row.baseline.fn} / {row.baseline.fp}</td>
              <td className="num cell-mono">{row.candidate.tp} / {row.candidate.fn} / {row.candidate.fp}</td>
              <td className={`num ${row.delta_f1 > 0 ? "up" : row.delta_f1 < 0 ? "down" : "muted"}`}>{signed(row.delta_f1)}</td>
            </tr>
          ))}
        </tbody>
      </table>
      {rows.length > shown ? (
        <div className="learning-more"><button className="button" onClick={onMore}>Show {formatNumber(Math.min(PAGE * 2, rows.length - shown))} more</button></div>
      ) : samples.images.length > samples.shown ? (
        <p className="compare-note muted small">The {formatNumber(samples.shown)} biggest moves are shown here; the downloaded report holds every image.</p>
      ) : null}
    </div>
  );
}

function Slices({ slices }: { slices: NonNullable<ComparisonReport["slices"]> }) {
  if (!slices.known) return <p className="notice">{slices.reason}</p>;
  return (
    <div className="compare-slices">
      <SliceTable title="By class" rows={slices.classes} unit="labels" />
      <SliceTable title="By object size" rows={slices.sizes} unit="labels" />
    </div>
  );
}

function SliceTable({ title, rows, unit }: { title: string; rows: SliceRow[]; unit: string }) {
  if (rows.length === 0) return null;
  return (
    <div className="data-table-wrap">
      <table className="data-table">
        <thead>
          <tr>
            <th>{title}</th>
            <th className="num">Support</th>
            <th className="num">Before</th>
            <th className="num">After</th>
            <th className="num">Change</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={String(row.key)} className={row.conclusive ? "" : "row-faint"}>
              <td>
                {row.name}
                <span className="cell-sub">{row.metric === "recall" ? "recall" : "F1"}</span>
              </td>
              <td className="num" title={`${row.support} ${unit}`}>
                {formatNumber(row.support)}
                {!row.conclusive && <span className="cell-sub">too few to call</span>}
              </td>
              <td className="num">{row.baseline[row.metric].toFixed(3)}</td>
              <td className="num">{row.candidate[row.metric].toFixed(3)}</td>
              <td className={`num ${!row.conclusive ? "muted" : row.delta > 0 ? "up" : row.delta < 0 ? "down" : ""}`}>{signed(row.delta)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function Changes({ report }: { report: ComparisonReport }) {
  return (
    <div className="compare-changes">
      <ChangeCard title="Training data" change={report.training_data} />
      <ChangeCard title="Evaluation data" change={report.evaluation_data ?? { known: false, reason: "not compared" }} />
    </div>
  );
}

function ChangeCard({ title, change }: { title: string; change: DataChange }) {
  return (
    <section className="panel-card compare-change">
      <h3>{title}</h3>
      {!change.known ? (
        <p className="muted">{change.reason}</p>
      ) : change.identical ? (
        <p className="muted">The same version on both sides — nothing changed here.</p>
      ) : (
        <>
          <ul className="compare-facts">
            <li><span>{formatNumber(change.images_baseline ?? 0)} → {formatNumber(change.images_candidate ?? 0)}</span> images</li>
            {(change.images_added ?? 0) > 0 && <li><span>+{formatNumber(change.images_added!)}</span> added</li>}
            {(change.images_removed ?? 0) > 0 && <li><span>−{formatNumber(change.images_removed!)}</span> removed</li>}
            {(change.images_edited ?? 0) > 0 && <li><span>{formatNumber(change.images_edited!)}</span> with edited labels</li>}
          </ul>
          <ul className="compare-facts">
            <li><span>{formatNumber(change.boxes_baseline ?? 0)} → {formatNumber(change.boxes_candidate ?? 0)}</span> boxes</li>
            {(change.boxes_added ?? 0) > 0 && <li><span>+{formatNumber(change.boxes_added!)}</span> drawn</li>}
            {(change.boxes_removed ?? 0) > 0 && <li><span>−{formatNumber(change.boxes_removed!)}</span> deleted</li>}
            {(change.boxes_relabelled ?? 0) > 0 && <li><span>{formatNumber(change.boxes_relabelled!)}</span> relabelled</li>}
            {(change.boxes_moved ?? 0) > 0 && <li><span>{formatNumber(change.boxes_moved!)}</span> moved</li>}
            {(change.boxes_with_removed_images ?? 0) > 0 && <li><span>−{formatNumber(change.boxes_with_removed_images!)}</span> left with removed images</li>}
            {(change.boxes_with_added_images ?? 0) > 0 && <li><span>+{formatNumber(change.boxes_with_added_images!)}</span> came with new images</li>}
          </ul>
          <p className="muted small">Drawn, deleted, relabelled and moved are counted on the images both versions hold.</p>
        </>
      )}
    </section>
  );
}

function Cost({ report }: { report: ComparisonReport }) {
  const cost = report.cost!;
  const clock = (seconds: number | null) =>
    seconds === null ? "—" : seconds >= 3600 ? `${(seconds / 3600).toFixed(1)} h` : seconds >= 90 ? `${Math.round(seconds / 60)} min` : `${Math.round(seconds)} s`;
  const review = cost.review;
  return (
    <section className="panel-card compare-cost">
      <h3>What this cost</h3>
      <div className="data-table-wrap">
        <table className="data-table">
          <thead>
            <tr><th /><th className="num">{report.runs.baseline.name}</th><th className="num">{report.runs.candidate.name}</th></tr>
          </thead>
          <tbody>
            <tr>
              <td>Rounds logged</td>
              <td className="num">{cost.baseline.rounds_logged}</td>
              <td className="num">{cost.candidate.rounds_logged}</td>
            </tr>
            <tr>
              <td>Training time<span className="cell-sub">over the logged rounds</span></td>
              <td className="num">{clock(cost.baseline.wall_clock_seconds)}</td>
              <td className="num">{clock(cost.candidate.wall_clock_seconds)}</td>
            </tr>
            <tr>
              <td>Model</td>
              <td className="num cell-mono">{String(cost.baseline.recipe.version ?? cost.baseline.recipe.framework ?? "—")}</td>
              <td className="num cell-mono">{String(cost.candidate.recipe.version ?? cost.candidate.recipe.framework ?? "—")}</td>
            </tr>
          </tbody>
        </table>
      </div>
      {review.known && review.observed ? (
        review.observed.decisions === 0 ? (
          <p className="compare-note small muted">No review decisions were recorded between these runs.</p>
        ) : (
          <p className="compare-note small">
            <span className="strong">{plural(review.observed.decisions, "review decision")}</span> recorded between these runs
            on {plural(review.observed.images, "image")}
            {review.observed.reviewers.length > 0 && <> by {review.observed.reviewers.join(", ")}</>}.
            <span className="muted"> About {review.estimated!.minutes} minutes at {review.estimated!.basis} — an estimate.</span>
          </p>
        )
      ) : (
        <p className="compare-note small muted">{review.reason}</p>
      )}
    </section>
  );
}
