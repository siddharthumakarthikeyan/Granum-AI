/** Copies and cross-split leaks, as a mode of the Images tab.
 *
 * Two questions a dataset owes an answer to before anything is trained on it: is the same
 * picture in here more than once, and is anything in the validation or test set also in the
 * training set? Both are read off one neighbour graph over image vectors, so both are shown
 * together, with the images side by side rather than as a list of paths -- the only way to
 * settle whether two files really are the same photograph is to look at them.
 *
 * Nothing here deletes anything. Images are selected, and the page's decision tray does the
 * rest, so a copy removed from this view goes to the removed set like every other deletion
 * and can be put back.
 *
 * The exporter's own copies of one picture — a flip, a colour shift, whatever augmentation was
 * switched on when the dataset was exported — are not duplicates and are never offered for
 * removal: they are training data somebody asked for. They have their own tab, so what Granum
 * decided is a copy of what can be checked rather than taken on trust.
 */

import { useMemo, useState } from "react";
import { api } from "../api/client";
import type { EmbeddingStatus, ImageRow, Job } from "../api/types";
import { EmptyState, Icon, formatNumber, formatWhen, plural } from "../components/ui";
import { fileName } from "../review/status";
import type { CopyGroup, ExportSet, LeakRow, readReport } from "./similar";
import { leakSide, leakSides, redundantImages } from "./similar";

/** Groups or pairs added to the page at a time: enough to scroll, few enough to draw. */
const PAGE = 24;

export type SimilarTab = "copies" | "exports" | "leaks";

export type Joined = ReturnType<typeof readReport>;

interface Props {
  project: string;
  dataset: string;
  /** What vectors the dataset has, or null while that is still being asked. */
  status: EmbeddingStatus | null;
  /** The neighbour graph, joined to the images the dataset holds now. */
  joined: Joined | null;
  /** The unit every threshold is a share of, and the thresholds themselves. */
  scale: number;
  duplicateAt: number;
  leakAt: number;
  reading: boolean;
  error: string | null;
  job: Job<{ status: EmbeddingStatus["status"]; unreadable: number }> | null;
  onCompute: () => void;
  onCancelJob: () => void;
  tab: SimilarTab;
  onTab: (tab: SimilarTab) => void;
  selected: Set<string>;
  onSelect: (images: string[], on: boolean) => void;
  /** Open one image full screen, stepping through the group or pair it came from. */
  onOpen: (image: string, scope: ImageRow[]) => void;
}

export function DuplicatesView(props: Props) {
  const { status, joined, reading, error, job } = props;

  if (error) {
    return (
      <div className="similar-body">
        <p className="form-error">{error}</p>
        <button className="button" onClick={props.onCompute}><Icon name="refresh" size={15} />Look again</button>
      </div>
    );
  }
  if (job && job.status === "running") return <Embedding job={job} onCancel={props.onCancelJob} />;
  if (status && status.status === null) return <NoVectors status={status} onCompute={props.onCompute} />;
  if (!joined || reading || !status) return <Reading images={status?.images ?? 0} />;
  return <Graph {...props} status={status} joined={joined} />;
}

/** Before anything has been embedded: what this would do, and what it would cost. */
function NoVectors({ status, onCompute }: { status: EmbeddingStatus; onCompute: () => void }) {
  const embedder = status.available;
  return (
    <div className="similar-body">
      <EmptyState
        title="Look for copies and leaks"
        action={<button className="button primary" onClick={onCompute}><Icon name="search" size={15} />Look through {formatNumber(status.images)} images</button>}
      >
        <p>
          Granum reads every image once and compares them by content, which finds the same picture
          exported twice under different names, and images that sit in both the training set and a
          set you measure with.
        </p>
        <p className="muted small">
          {embedder.name} · {embedder.dimensions} numbers per image
          {embedder.semantic ? "" : " · colour and edge layout only, so it finds copies and resizes but does not judge what is in a picture"}.
          Images are read, not changed. Around a minute for every 4,000 images on a processor.
        </p>
      </EmptyState>
    </div>
  );
}

function Embedding({ job, onCancel }: { job: Job<unknown>; onCancel: () => void }) {
  const share = job.total ? job.done / job.total : 0;
  return (
    <div className="similar-body">
      <div className="panel similar-progress">
        <div className="similar-progress-text">
          <span>{job.phase}</span>
          <span className="tabular muted">{formatNumber(job.done)} / {formatNumber(job.total)}</span>
        </div>
        <div className="progress"><div className="progress-fill" style={{ width: `${share * 100}%` }} /></div>
        <div className="similar-progress-text">
          <span className="muted small">The vectors are kept, so this is asked for once per dataset.</span>
          <button className="button subtle" onClick={onCancel}>Cancel</button>
        </div>
      </div>
    </div>
  );
}

function Reading({ images }: { images: number }) {
  return (
    <div className="similar-body">
      <div className="panel similar-progress">
        <span>Comparing {images ? formatNumber(images) : ""} images with each other…</span>
        <div className="progress indeterminate"><div className="progress-fill" /></div>
        <span className="muted small">A second or two the first time; instant afterwards.</span>
      </div>
    </div>
  );
}

function Graph({ project, dataset, status, joined, scale, duplicateAt, leakAt, tab, onTab, selected, onSelect, onOpen, onCompute }:
  Props & { status: EmbeddingStatus; joined: Joined }) {
  const [shown, setShown] = useState(PAGE);
  const vectors = status.status!;
  const sides = useMemo(() => leakSides(joined.leaks), [joined.leaks]);
  const rows: (CopyGroup | ExportSet | LeakRow)[] =
    tab === "copies" ? joined.groups : tab === "exports" ? joined.exports : joined.leaks;
  const more = tab === "copies" ? joined.moreGroups : tab === "exports" ? joined.moreExports : joined.moreLeaks;

  const switchTab = (next: SimilarTab) => {
    setShown(PAGE);
    onTab(next);
  };

  return (
    <div className="similar-body">
      <div className="panel similar-summary">
        <div className="similar-counts">
          <Count label="Distinct pictures" value={joined.found.sources} of={vectors.images} />
          <Count label="Pictures that repeat another" value={joined.found.redundant} />
          <Count label="Cross-split leaks" value={joined.found.leaks} tone={joined.found.leaks ? "warn" : undefined} />
        </div>
        {joined.found.exported > 0 && (
          <p className="muted small similar-policy">
            {formatNumber(joined.found.exportedImages)} images are the exporter's copies
            of {formatNumber(joined.found.exported)} pictures — an augmented export writes each
            picture out several times. They are not counted as repeats and are never offered for
            removal; see <strong>Exported copies</strong>.
          </p>
        )}
        <p className="muted small similar-policy">
          Two images are grouped when they are closer than {Math.round(duplicateAt * 100)}% of the distance
          between two images picked at random from this dataset, and counted as a leak when they are
          closer than {Math.round(leakAt * 100)}% of it and sit in different sets — whichever side of a
          split a picture's copies were dealt into. That typical distance is {scale.toFixed(2)} here.
          Grouping carries along a chain, so a group can hold a run of frames each close to the last;
          the spread on each group says how alike its least alike pair really is.
        </p>
        {(joined.moreGroups > 0 || joined.moreExports > 0 || joined.moreLeaks > 0) && (
          <p className="muted small similar-policy">
            Listing the first {formatNumber(joined.groups.length)} groups,
            {" "}{formatNumber(joined.exports.length)} copy sets
            and {formatNumber(joined.leaks.length)} pairs. Deal with these and read again for the rest.
          </p>
        )}
        <div className="similar-source">
          <span className="muted small">
            {vectors.embedder.name} · {formatNumber(vectors.images)} images read {formatWhen(vectors.created)}
          </span>
          {!vectors.embedder.semantic && (
            <span className="tag warn" title={vectors.embedder.detail}>Colour and edges only</span>
          )}
          {status.missing > 0 && (
            <span className="tag warn">{plural(status.missing, "image")} added since, not yet read</span>
          )}
          {vectors.stale && <span className="tag warn">Made by an older rule set</span>}
          <button className="button subtle small" onClick={onCompute} title="Read the images again, including any added since">
            <Icon name="refresh" size={14} />Read again
          </button>
        </div>
      </div>

      <div className="ribbon similar-tabs">
        <div className="segmented" role="group" aria-label="What to show">
          <button className={tab === "copies" ? "on" : ""} onClick={() => switchTab("copies")}>
            Repeats<span className="split-toggle-count">{formatNumber(joined.groups.length)}</span>
          </button>
          <button className={tab === "exports" ? "on" : ""} onClick={() => switchTab("exports")}>
            Exported copies<span className="split-toggle-count">{formatNumber(joined.exports.length)}</span>
          </button>
          <button className={tab === "leaks" ? "on" : ""} onClick={() => switchTab("leaks")}>
            Leaks<span className="split-toggle-count">{formatNumber(joined.leaks.length)}</span>
          </button>
        </div>
        <span className="spacer" />
        {tab === "copies" ? (
          <button
            className="button subtle"
            disabled={joined.redundant === 0}
            onClick={() => onSelect(redundantImages(joined.groups), true)}
            title="In each group listed here, keep one picture and the exporter's copies of it, and select the rest"
          >
            Select {formatNumber(joined.redundant)} repeats
          </button>
        ) : tab === "exports" ? (
          <span className="muted small">
            One picture, written out more than once. Nothing to remove here — this is the
            augmentation the export was asked for.
          </span>
        ) : (
          sides.map((side) => (
            <button
              key={side.set}
              className="button subtle"
              onClick={() => onSelect(leakSide(joined.leaks, side.set), true)}
              title={`Select the leaked images that sit in ${side.set}`}
            >
              Select {side.set}<span className="split-toggle-count">{formatNumber(side.images)}</span>
            </button>
          ))
        )}
      </div>

      {rows.length === 0 ? (
        <p className="muted qa-empty">
          {tab === "copies"
            ? "No picture in this dataset repeats another picture."
            : tab === "exports"
              ? "Every picture in this dataset is in it once. Nothing was exported more than one time."
              : "No image in one set is a near copy of an image in another. Scores measured on these sets mean what they say."}
        </p>
      ) : (
        <div className={tab === "leaks" ? "leak-list" : "copy-list"}>
          {tab === "copies" && joined.groups.slice(0, shown).map((group) => (
            <CopyGroupRow key={group.id} group={group} project={project} dataset={dataset}
              selected={selected} onSelect={onSelect} onOpen={onOpen} />
          ))}
          {tab === "exports" && joined.exports.slice(0, shown).map((group) => (
            <ExportSetRow key={group.id} group={group} project={project} dataset={dataset}
              selected={selected} onSelect={onSelect} onOpen={onOpen} />
          ))}
          {tab === "leaks" && joined.leaks.slice(0, shown).map((leak) => (
            <LeakPairRow key={leak.id} leak={leak} project={project} dataset={dataset}
              selected={selected} onSelect={onSelect} onOpen={onOpen} />
          ))}
        </div>
      )}

      {rows.length > shown && (
        <div className="qa-more">
          <button className="button" onClick={() => setShown(shown + PAGE)}>
            Show {formatNumber(Math.min(PAGE, rows.length - shown))} more
          </button>
          <span className="muted small">
            {formatNumber(Math.min(shown, rows.length))} of {formatNumber(rows.length)}
            {more > 0 && ` · ${formatNumber(more)} more not sent`}
          </span>
        </div>
      )}
    </div>
  );
}

function Count({ label, value, of, more, tone }: { label: string; value: number; of?: number; more?: number; tone?: string }) {
  return (
    <div className="similar-count">
      <span className={`similar-count-value tabular${tone ? ` ${tone}` : ""}`}>{formatNumber(value)}</span>
      <span className="muted small">
        {label}
        {of ? ` of ${formatNumber(of)}` : ""}
        {more ? ` (${formatNumber(more)} more)` : ""}
      </span>
    </div>
  );
}

function CopyGroupRow({ group, project, dataset, selected, onSelect, onOpen }: {
  group: CopyGroup;
  project: string;
  dataset: string;
  selected: Set<string>;
  onSelect: (images: string[], on: boolean) => void;
  onOpen: (image: string, scope: ImageRow[]) => void;
}) {
  const keeper = group.images[0]!.family;
  const repeats = group.images.filter((image) => image.family !== keeper).map((image) => image.item.image);
  const allPicked = repeats.every((image) => selected.has(image));
  const items = group.images.map((image) => image.item);
  return (
    <div className="copy-group">
      <div className="copy-group-head">
        <span className="strong">{formatNumber(group.sources)} pictures</span>
        {group.images.length > group.sources && (
          <span className="muted small" title="The exporter's copies of them, which go with the picture they came from">
            {formatNumber(group.images.length)} images
          </span>
        )}
        <span
          className="muted small"
          title="How far apart the two least alike images of this group are, as a share of the distance between two images of this dataset picked at random"
        >
          {group.spread <= 0.05 ? "the same shot" : `spread ${Math.round(group.spread * 100)}%`}
        </span>
        <span className="muted small">{group.sets.join(" · ")}</span>
        {group.crossesSets && <span className="tag warn" title="The same picture is in more than one set, so it also leaks">Across sets</span>}
        <span className="spacer" />
        <button
          className="button subtle small"
          onClick={() => onSelect(repeats, !allPicked)}
          title={`Keep ${fileName(group.images[0]!.item.image)} and the exporter's copies of it, and select the other ${group.sources - 1} pictures`}
        >
          {allPicked ? "Unselect the rest" : `Select the other ${formatNumber(group.sources - 1)}`}
        </button>
      </div>
      <div className="copy-strip">
        {group.images.map((image) => (
          <SimilarTile
            key={image.item.image}
            item={image.item}
            project={project}
            dataset={dataset}
            keeper={image.family === keeper}
            checked={selected.has(image.item.image)}
            onToggle={() => onSelect([image.item.image], !selected.has(image.item.image))}
            onOpen={() => onOpen(image.item.image, items)}
          />
        ))}
      </div>
    </div>
  );
}

/** One picture the exporter wrote out more than once: shown to be checked, not to be removed. */
function ExportSetRow({ group, project, dataset, selected, onSelect, onOpen }: {
  group: ExportSet;
  project: string;
  dataset: string;
  selected: Set<string>;
  onSelect: (images: string[], on: boolean) => void;
  onOpen: (image: string, scope: ImageRow[]) => void;
}) {
  return (
    <div className="copy-group">
      <div className="copy-group-head">
        <span className="strong">{formatNumber(group.images.length)} copies</span>
        <span className="mono small truncate" title={group.source}>{fileName(group.source)}</span>
        <span className="muted small">{group.sets.join(" · ")}</span>
        {group.crossesSets && (
          <span className="tag block" title="One picture, with its copies dealt into different sets: whatever they look like, this is a leak">
            Split through it
          </span>
        )}
      </div>
      <div className="copy-strip">
        {group.images.map((item) => (
          <SimilarTile
            key={item.image}
            item={item}
            project={project}
            dataset={dataset}
            checked={selected.has(item.image)}
            onToggle={() => onSelect([item.image], !selected.has(item.image))}
            onOpen={() => onOpen(item.image, group.images)}
          />
        ))}
      </div>
    </div>
  );
}

function LeakPairRow({ leak, project, dataset, selected, onSelect, onOpen }: {
  leak: LeakRow;
  project: string;
  dataset: string;
  selected: Set<string>;
  onSelect: (images: string[], on: boolean) => void;
  onOpen: (image: string, scope: ImageRow[]) => void;
}) {
  const pair = [leak.a, leak.b];
  const tile = (image: ImageRow) => (
    <SimilarTile
      item={image}
      project={project}
      dataset={dataset}
      wide
      checked={selected.has(image.image)}
      onToggle={() => onSelect([image.image], !selected.has(image.image))}
      onOpen={() => onOpen(image.image, pair)}
    />
  );
  return (
    <div className="leak-pair">
      {tile(leak.a)}
      <div className="leak-verdict">
        <span className={`tag ${leak.sameImage || leak.sameSource ? "block" : "warn"}`}>
          {leak.sameSource ? "One picture, both sets" : leak.sameImage ? "The same image" : "Nearly the same"}
        </span>
        <span className="faint small tabular">
          {leak.distance === 0 ? "identical" : `${(leak.share * 100).toFixed(leak.share < 0.1 ? 1 : 0)}% of typical`}
        </span>
        <span className="faint small">{leak.a.set} · {leak.b.set}</span>
      </div>
      {tile(leak.b)}
    </div>
  );
}

/** One image in a group or a pair: pick it to act on it, click it to look properly. */
function SimilarTile({ item, project, dataset, keeper, wide, checked, onToggle, onOpen }: {
  item: ImageRow;
  project: string;
  dataset: string;
  keeper?: boolean;
  /** A leak is two images to compare, so each gets the room a strip of copies cannot. */
  wide?: boolean;
  checked: boolean;
  onToggle: () => void;
  onOpen: () => void;
}) {
  return (
    <div className={`similar-tile${wide ? " wide" : ""}${checked ? " selected" : ""}`} title={item.image}>
      <button className="image-card-frame" onClick={onOpen} aria-label={`Open ${fileName(item.image)}`}>
        <img loading="lazy" src={api.mediaUrl(item.image, 240, project, dataset)} alt="" />
        {keeper && <span className="similar-keep">Keep</span>}
      </button>
      <label className="image-check" onClick={(event) => event.stopPropagation()}>
        <input type="checkbox" checked={checked} onChange={onToggle} aria-label={`Select ${fileName(item.image)}`} />
      </label>
      <span className="image-card-foot">
        <span className="set-chip">{item.set}</span>
        <span className="mono small truncate">{fileName(item.image)}</span>
      </span>
    </div>
  );
}
