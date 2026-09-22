/** Findings: the labels a model suggests are worth checking, ranked, with the evidence for
 * each, and a decision recorded per image.
 *
 * Two kinds of evidence, the same four rules. A **training run** watched every image in
 * every epoch after it became competent on the set, and a finding earns its place by
 * recurring. A **check** is one pass of a model over the labels -- a model trained here, or
 * one that has never seen this data -- and a finding is worth what the model's confidence
 * is worth. The check is weaker and says so; it also needs no training, which is the
 * difference between checking a dataset today and checking it after an afternoon.
 *
 * On the training set the model learns the labels it is given, so a wrong label can stop
 * showing up; held-out sets give stronger evidence, and say so.
 */

import { useCallback, useEffect, useMemo, useState } from "react";
import { api } from "../api/client";
import type { FindingRule, FindingsReport, FindingsSplit, FlaggedImage } from "../api/types";
import { EmptyState, Icon, PageHeader, formatNumber, plural } from "../components/ui";
import { navigate, routeHref } from "../router";
import { useStore } from "../store/store";
import { FindingReview } from "./FindingReview";
import { ScreenDialog } from "./ScreenDialog";
import { RULE, RULES, SECONDS_PER_FINDING, STATUS_LABEL, cropView, evidence, faded, rectOf } from "./text";

type StatusFilter = "open" | "decided" | "all";

const PAGE = 60;

const isOpen = (image: FlaggedImage) => !image.review || image.review.status === "unreviewed";

export function FindingsPage({ project, url }: { project: string; url?: string }) {
  const runs = useStore((s) => s.runs);
  const refreshProject = useStore((s) => s.refreshProject);
  const tracked = useMemo(
    () => [...runs].filter((r) => r.parameters?.tracks_learning === true && r.status !== "running")
      .sort((a, b) => b.created.localeCompare(a.created)),
    [runs],
  );
  const runUrl = url ?? tracked[0]?.url;
  const run = runs.find((r) => r.url === runUrl);

  const [report, setReport] = useState<FindingsReport | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [splitName, setSplitName] = useState<string | null>(null);
  const [rule, setRule] = useState<FindingRule | null>(null);
  const [status, setStatus] = useState<StatusFilter>("open");
  const [shown, setShown] = useState(PAGE);
  /** What to put first: the strongest single finding, or the least trustworthy image. */
  const [order, setOrder] = useState<"finding" | "image">("finding");
  const [reviewing, setReviewing] = useState<{ index: number; items: FlaggedImage[] } | null>(null);
  const [checking, setChecking] = useState(false);

  const load = useCallback(async () => {
    if (!runUrl) return;
    try {
      const next = await api.runFindings(runUrl);
      setReport(next);
      setError(null);
      // Open on the strongest evidence: a held-out set with findings, else the first with any.
      setSplitName((current) => current && next.splits.some((s) => s.split === current) ? current
        : (next.splits.filter((s) => s.held_out && s.images.length).sort((a, b) => b.images.length - a.images.length)[0]
          ?? next.splits.find((s) => s.images.length) ?? next.splits[0])?.split ?? null);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }, [runUrl]);

  useEffect(() => {
    setReport(null);
    setSplitName(null);
    void load();
  }, [load]);

  const split = report?.splits.find((s) => s.split === splitName) ?? null;
  const images = useMemo(() => {
    if (!split) return [];
    const kept = split.images.filter((image) =>
      (rule === null || image.findings.some((f) => f.rule === rule))
      && (status === "all" || (status === "open") === isOpen(image)));
    // By image, the worst-labelled picture comes first even when no single finding on it is
    // the strongest: twenty middling disagreements are a worse picture than one loud one.
    if (order === "image") {
      return [...kept].sort((a, b) => (a.trust ?? 1) - (b.trust ?? 1) || b.score - a.score);
    }
    return kept;
  }, [split, rule, status, order]);
  useEffect(() => setShown(PAGE), [splitName, rule, status, order]);

  const decided = split ? split.images.filter((i) => !isOpen(i)).length : 0;
  const openFindings = split ? split.images.filter(isOpen).reduce((n, i) => n + i.findings.length, 0) : 0;

  const dialog = checking && (
    <ScreenDialog
      project={project}
      onClose={() => setChecking(false)}
      onDone={(name) => {
        setChecking(false);
        // Open what it just produced. The run list is asked for directly rather than through
        // the store, so the page lands on the new check whatever the store has caught up to.
        void api.runs(project).then((list) => {
          const made = list.find((entry) => entry.name === name);
          void refreshProject();
          if (made) navigate({ name: "findings", project, url: made.url });
          else void load();
        }).catch(() => void load());
      }}
    />
  );

  const header = (
    <PageHeader
      title="Findings"
      context={run?.name}
      subtitle={report && split
        ? split.single_pass
          ? <>Labels one pass of {report.model?.version ?? "a model"} disagrees with, ranked by how sure it was; rules {report.rules_version}.</>
          : <>Labels this run suggests checking, ranked by evidence. Judged on epochs {split.competent_from !== null ? split.competent_from + 1 : "?"}–{split.observed ? (split.competent_from ?? 0) + split.window : "?"}, once the model found most labels; rules {report.rules_version}.</>
        : "Labels a model suggests checking, ranked by evidence."}
      actions={
        <>
          {tracked.length > 1 && (
            <label className="inline-field small">
              <span className="muted">From</span>
              <select value={runUrl} onChange={(e) => navigate({ name: "findings", project, url: e.target.value })}>
                {tracked.map((r) => (
                  <option key={r.url} value={r.url}>
                    {r.parameters?.kind === "screening" ? `check · ${r.name}` : r.name}
                  </option>
                ))}
              </select>
            </label>
          )}
          <button className="button" onClick={() => setChecking(true)} title="Read these labels with a model, without training anything">
            <Icon name="search" size={15} />Check labels
          </button>
        </>
      }
    />
  );

  if (!runUrl) {
    return (
      <div className="page">
        {dialog}
        {header}
        <EmptyState
          title="Nothing has read these labels yet"
          action={<button className="button primary" onClick={() => setChecking(true)}><Icon name="search" size={15} />Check labels with a model</button>}
        >
          <p>
            A check reads every image once with a model — one you trained here, or one that has
            never seen this data — and lists the labels it disagrees with. It changes nothing and
            takes minutes.
          </p>
          <p className="muted small">
            Training with “Record per-sample metrics and predictions every epoch” on gives stronger
            evidence for the same four rules, because a finding then has to recur round after round.
            <a className="findings-runs-link" href={routeHref({ name: "runs", project })}>Go to runs</a>
          </p>
        </EmptyState>
      </div>
    );
  }
  if (error) return <div className="page">{dialog}{header}<p className="form-error">{error}</p></div>;
  if (report && !report.stores_boxes) {
    const stopped = run?.status === "cancelled" || run?.status === "interrupted" || run?.status === "failed";
    return (
      <div className="page">
        {dialog}
        {header}
        {stopped && report.splits.length === 0 ? (
          <EmptyState title="This run stopped before its first epoch finished">
            <p>No epoch's predictions were recorded, so there is nothing to judge. Choose another run, or train again.</p>
          </EmptyState>
        ) : (
          <EmptyState title="This run did not save the model's boxes">
            <p>Findings need the predicted boxes from every epoch. Train again with “Record per-sample metrics and predictions every epoch” on.</p>
          </EmptyState>
        )}
      </div>
    );
  }

  return (
    <div className="page findings-page">
      {dialog}
      {header}
      {!report && <p className="muted"><span className="spinner" /> Reading every epoch's predictions</p>}

      {report && report.splits.length > 1 && (
        <div className="tabs" role="tablist" aria-label="Set">
          {report.splits.map((s) => (
            <button key={s.split} role="tab" aria-selected={s.split === splitName} className={`tab${s.split === splitName ? " on" : ""}`} onClick={() => setSplitName(s.split)}>
              {s.split}
              <span className="small">{plural(s.images.length, "image")} of {formatNumber(s.images_total)}{s.held_out ? ", held out" : ""}</span>
            </button>
          ))}
        </div>
      )}

      {report && split && split.single_pass && (
        <div className="panel screening-note">
          <p className="small">
            <strong>One pass, not a training run.</strong>{" "}
            {report.model?.with === "pretrained"
              ? `${report.model.version} read these labels once; it has never seen this data.`
              : `${report.model?.version ?? "A model"}${report.model?.from_run ? ` from ${report.model.from_run}` : ""} read these labels once.`}
            {" "}A finding here is worth what the model's confidence is worth; a training run's
            findings have to recur round after round, which is stronger evidence for the same rules.
          </p>
          {split.competence && <Competence split={split} />}
          {split.swaps.length > 0 && (
            <p className="small screening-swaps">
              <span className="muted">Most often disagreed:</span>
              {split.swaps.map((swap) => (
                <span key={`${swap.label}-${swap.predicted}`} className="swap-chip">
                  {split.classes[String(swap.label)] ?? swap.label} → {split.classes[String(swap.predicted)] ?? swap.predicted}
                  <span className="count">{formatNumber(swap.count)}</span>
                </span>
              ))}
            </p>
          )}
        </div>
      )}

      {split && !split.held_out && (
        <p className="notice">
          The model trained on these labels. It can learn a wrong label as it is, so some errors stop showing up in later epochs;
          findings on held-out sets are stronger evidence.
        </p>
      )}

      {split && (
        <>
          <div className="findings-bar">
            <div className="segmented findings-rules" role="group" aria-label="Rule">
              <button className={rule === null ? "on" : ""} onClick={() => setRule(null)}>
                All <span className="count">{formatNumber(split.images.length)}</span>
              </button>
              {RULES.map((r) => (
                <button key={r.id} className={rule === r.id ? "on" : ""} onClick={() => setRule(rule === r.id ? null : r.id)} disabled={!split.counts[r.id]} title={r.action}>
                  <span className="rule-dot" style={{ background: r.color }} />{r.short} <span className="count">{formatNumber(split.counts[r.id])}</span>
                </button>
              ))}
            </div>
            <span className="spacer" />
            {split.images.some((image) => image.trust !== undefined) && (
              <div className="segmented" role="group" aria-label="Order">
                <button className={order === "finding" ? "on" : ""} onClick={() => setOrder("finding")}
                  title="The strongest single disagreement first">
                  Strongest finding
                </button>
                <button className={order === "image" ? "on" : ""} onClick={() => setOrder("image")}
                  title="The image whose labelling is least trustworthy first, worst box deciding">
                  Least trustworthy
                </button>
              </div>
            )}
            <div className="segmented" role="group" aria-label="Decision">
              <button className={status === "open" ? "on" : ""} onClick={() => setStatus("open")}>To review</button>
              <button className={status === "decided" ? "on" : ""} onClick={() => setStatus("decided")}>Decided</button>
              <button className={status === "all" ? "on" : ""} onClick={() => setStatus("all")}>All</button>
            </div>
          </div>

          <div className="findings-progress">
            <span className="progress-track"><span style={{ width: `${split.images.length ? (decided / split.images.length) * 100 : 0}%` }} /></span>
            <span className="small">
              <span className="strong">{formatNumber(decided)}</span> of {plural(split.images.length, "image")} decided
              {openFindings > 0 && <span className="muted">, about {Math.max(1, Math.round((openFindings * SECONDS_PER_FINDING) / 60))} min of review left (estimate)</span>}
            </span>
          </div>

          {split.images.length === 0 ? (
            <EmptyState title="Nothing to check in this set">
              <p>
                {split.single_pass
                  ? "This model agrees with every label it can judge here. That is not proof every label is right."
                  : "No label raised a finding often enough in the epochs judged. That is not proof every label is right."}
              </p>
            </EmptyState>
          ) : images.length === 0 ? (
            <p className="muted findings-none">No image matches these filters.</p>
          ) : (
            <div className="finding-grid">
              {images.slice(0, shown).map((image, i) => (
                <FindingCard key={image.example_id} image={image} split={split} project={project} onOpen={() => setReviewing({ index: i, items: images })} />
              ))}
            </div>
          )}
          {images.length > shown && (
            <div className="learning-more">
              <button className="button" onClick={() => setShown(shown + PAGE * 2)}>Show {formatNumber(Math.min(PAGE * 2, images.length - shown))} more</button>
            </div>
          )}
        </>
      )}

      {reviewing && split && report && runUrl && (
        <FindingReview
          project={project}
          runUrl={runUrl}
          version={report.rules_version}
          split={split}
          items={reviewing.items}
          index={reviewing.index}
          onIndex={(index) => {
            setReviewing({ ...reviewing, index });
            if (index >= shown) setShown(index + PAGE);
          }}
          onDecided={load}
          onClose={() => setReviewing(null)}
        />
      )}
    </div>
  );
}

/** One image: a close-up of its strongest finding, what it is, and the decision if any. */
function FindingCard({ image, split, project, onOpen }: { image: FlaggedImage; split: FindingsSplit; project: string; onOpen: () => void }) {
  const top = image.findings[0]!;
  const info = RULE.get(top.rule)!;
  const file = image.image?.split("/").pop() ?? `image ${image.example_id}`;
  const note = faded(top);
  return (
    <button className={`finding-card${isOpen(image) ? "" : " decided"}`} onClick={onOpen} title={`${file}\n${evidence(top, split.classes)}${note ? ` ${note}` : ""}`}>
      <span className="finding-thumb">
        {image.image && image.width && image.height ? (
          <CloseUp image={image} project={project} dataset={split.dataset} findingIndex={0} />
        ) : <Icon name="file" />}
        {image.review && !isOpen(image) && <span className="decision-tag finding-status">{STATUS_LABEL[image.review.status] ?? image.review.status}</span>}
      </span>
      <span className="finding-meta">
        <span className="finding-rule" style={{ borderLeftColor: info.color }}>{info.short}</span>
        {/* One pass has no share to show -- it was seen in the one round there was. What
            carries the weight there is how sure the model was, so that is what is shown. */}
        {top.window === 1 ? (
          <span
            className="finding-strength"
            title={`${top.confidence ? `The model was ${Math.round(top.confidence[1] * 100)}% sure. ` : "A label the model did not find. "}${
              image.trust !== undefined ? `This image's labelling scores ${image.trust.toFixed(2)} of 1, decided by its worst box.` : ""}`}
          >
            {top.confidence ? `${Math.round(top.confidence[1] * 100)}% sure` : "not found"}
            {image.trust !== undefined && <span className="finding-trust">{image.trust.toFixed(2)}</span>}
          </span>
        ) : (
          <span className="finding-strength" title="Share of judged epochs it was seen in">{Math.round(top.share * 100)}%</span>
        )}
      </span>
      <span className="sample-foot">
        <span className="truncate">{file}</span>
        <span>{image.findings.length > 1 ? `+${image.findings.length - 1} more` : ""}</span>
      </span>
    </button>
  );
}

/** A crop around one finding, drawn in the image's own pixel space so boxes cannot drift. */
export function CloseUp({ image, project, dataset, findingIndex, context = 3 }: {
  image: FlaggedImage;
  project: string;
  dataset: string | null;
  findingIndex: number;
  /** How many times the finding's size to show around it. */
  context?: number;
}) {
  const f = image.findings[findingIndex]!;
  const W = image.width!, H = image.height!;
  const view = cropView(f.box, W, H, context, 4 / 3);
  const color = RULE.get(f.rule)!.color;
  const stroke = Number(view.split(" ")[3]) / 90;
  return (
    <svg viewBox={view} preserveAspectRatio="xMidYMid slice" aria-hidden="true">
      <image href={api.mediaUrl(image.image!, 640, project, dataset ?? undefined)} x={0} y={0} width={W} height={H} preserveAspectRatio="none" />
      {f.predicted_box && <rect {...rectOf(f.predicted_box)} fill="none" stroke={color} strokeWidth={stroke} strokeDasharray={`${stroke * 3} ${stroke * 2}`} />}
      <rect {...rectOf(f.box)} fill="none" stroke={color} strokeWidth={stroke * 1.4} strokeDasharray={f.rule === "missing_label" ? `${stroke * 3} ${stroke * 2}` : undefined} />
    </svg>
  );
}


/** What the pass was able to judge, and what it left alone.
 *
 * A model finds some of a dataset's classes well and others barely at all, and a label of a
 * class it cannot find is not a label it found wrong. Saying which classes those were is the
 * difference between a check a reader can act on and a list they have to second-guess.
 */
function Competence({ split }: { split: FindingsSplit }) {
  const competence = split.competence!;
  const name = (label: string) => split.classes[label] ?? `class ${label}`;
  const judged = new Set(competence.judged.map(String));
  const left = Object.keys(competence.labels)
    .filter((label) => !judged.has(label) && (competence.labels[label] ?? 0) > 0)
    .sort((a, b) => (competence.labels[b] ?? 0) - (competence.labels[a] ?? 0));
  if (left.length === 0) {
    return (
      <p className="small muted">
        The model finds every class of this set well enough to be asked about all of them.
      </p>
    );
  }
  return (
    <p className="small muted">
      It finds {formatNumber(competence.judged.length)} of{" "}
      {plural(Object.keys(competence.labels).length, "class", "classes")} in this set reliably.
      Labels of the others were left alone rather than reported as missed — it cannot find them
      here, so its silence says nothing:{" "}
      {left.slice(0, 6).map((label, at) => (
        <span key={label}>
          {at > 0 ? ", " : ""}
          <span className="strong">{name(label)}</span>{" "}
          <span className="faint">{Math.round((competence.recall[label] ?? 0) * 100)}% found</span>
        </span>
      ))}
      {left.length > 6 ? ` and ${formatNumber(left.length - 6)} more` : ""}.
      Its own predictions are still reported wherever it makes them.
    </p>
  );
}
