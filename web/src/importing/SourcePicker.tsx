/** Step one: create the project (name and type) and pick its data, or add data to one.
 *
 * The data comes from a folder chosen in a picker over the folders the service may read;
 * train, valid and test annotation files inside it are found together.
 */

import { useEffect, useState } from "react";
import { api } from "../api/client";
import type { BrowseResult, ImportSource, TaskId } from "../api/types";
import { Modal } from "../components/Modal";
import { Icon, formatNumber, plural, tail } from "../components/ui";
import { useStore } from "../store/store";
import { useImport, type MediaMode } from "./importStore";
import { PullDialog } from "./PullDialog";
import { TASKS, sortTasks, tasksLabel } from "./tasks";

const MEDIA_CHOICES: { id: MediaMode; label: string; detail: string }[] = [
  { id: "full", label: "All images", detail: "Decode every image: missing, corrupt, duplicate, size mismatch." },
  { id: "sample", label: "Sample, 200 per split", detail: "Faster; image issues outside the sample are not found." },
  { id: "none", label: "Annotations only", detail: "Images are not opened." },
];

const TASK_DETAIL: Record<TaskId, string> = {
  object_detection: "Boxes around objects",
  instance_segmentation: "A mask per object",
  semantic_segmentation: "A class per pixel",
  panoptic_segmentation: "Things and stuff, per pixel",
  keypoint_detection: "Points on each object",
  classification: "One label per image",
};

export function SourcePicker({ project }: { project?: string }) {
  const sources = useImport((s) => s.sources);
  const setSources = useImport((s) => s.setSources);
  const media = useImport((s) => s.media);
  const setMedia = useImport((s) => s.setMedia);
  const projectName = useImport((s) => s.projectName);
  const setProjectName = useImport((s) => s.setProjectName);
  const tasks = useImport((s) => s.tasks);
  const setTasks = useImport((s) => s.setTasks);
  const runPreflight = useImport((s) => s.runPreflight);
  const error = useImport((s) => s.error);
  const projects = useStore((s) => s.projects);
  const tables = useStore((s) => s.tables);
  const [picking, setPicking] = useState(false);
  const [pulling, setPulling] = useState(false);
  const pulled = useImport((s) => s.pulled);
  const setPulled = useImport((s) => s.setPulled);
  const loadExample = useImport((s) => s.loadExample);

  // Adding to an existing project: its name and type are fixed.
  const existing = project ? tables.find((t) => t.project_name === project && t.tasks?.length)?.tasks ?? ["object_detection" as TaskId] : null;
  const existingKey = existing?.join(",");
  useEffect(() => {
    if (existing && tasks.join(",") !== existingKey) setTasks(existing);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [existingKey, tasks, setTasks]);
  const toggleTask = (id: TaskId) => setTasks(sortTasks(tasks.includes(id) ? tasks.filter((t) => t !== id) : [...tasks, id]));

  const name = projectName.trim();
  const taken = !project && projects.some((p) => p.name === name);
  const splitNames = sources.map((s) => s.split.trim());
  const invalid = splitNames.some((n) => !n) || new Set(splitNames).size !== splitNames.length;
  const problem = !name ? "Name the project." : taken ? "A project with this name exists." : tasks.length === 0 ? "Choose the project type."
    : sources.length === 0 ? "Choose the data source." : invalid ? "Split names must be unique and non-empty." : null;
  const folder = sources.length ? sources[0]!.annotations.split("/").slice(0, sources.length > 1 ? -2 : -1).join("/") : null;

  return (
    <div className="create-project">
      <section className="panel-card create-section">
        <h2 className="card-title">{project ? `Add data to ${project}` : "Project"}</h2>
        {project ? (
          <p className="muted">
            <span className="strong">{tasksLabel(existing)}</span> project. New data joins it as another dataset.
          </p>
        ) : (
          <label className="field">
            <span>Name</span>
            <input type="text" value={projectName} autoFocus maxLength={80} placeholder="e.g. aerial-people"
              onChange={(e) => setProjectName(e.target.value)} />
            {taken && <span className="small warn-text">A project with this name exists.</span>}
          </label>
        )}
      </section>

      {!project && (
        <section className="panel-card create-section">
          <div className="create-section-head">
            <h2 className="card-title">Project type</h2>
            <span className="muted small">Choose one or more; checked against the data before import</span>
          </div>
          <div className="task-grid" role="group" aria-label="Project type">
            {TASKS.map((option) => (
              <label key={option.id} className={`task-card${tasks.includes(option.id) ? " checked" : ""}`}>
                <input type="checkbox" checked={tasks.includes(option.id)} onChange={() => toggleTask(option.id)} />
                {tasks.includes(option.id) && <span className="task-check"><Icon name="check" size={11} /></span>}
                <TaskGlyph task={option.id} />
                <span className="task-card-text">
                  <span className="strong">{option.label}</span>
                  <span className="faint small">{TASK_DETAIL[option.id]}</span>
                </span>
              </label>
            ))}
          </div>
        </section>
      )}

      <section className="panel-card create-section">
        <div className="create-section-head">
          <h2 className="card-title">Data source</h2>
          <span className="muted small">COCO annotations; one file per split</span>
        </div>
        {sources.length === 0 ? (
          <div className="source-options">
            <button className="button select-folder" onClick={() => setPicking(true)}>
              <Icon name="folder" size={18} />Select folder
            </button>
            <button className="button select-folder" onClick={() => setPulling(true)}>
              <Icon name="layers" size={18} />Import from existing projects
            </button>
            {!project && (
              <button className="button select-folder" onClick={() => void loadExample()}>
                <Icon name="grid" size={18} />Use the example dataset
              </button>
            )}
          </div>
        ) : (
          <>
            {pulled ? (
              <div className="source-folder">
                <Icon name="layers" />
                <span className="truncate">
                  <span className="strong">{formatNumber(pulled.images)} images</span>
                  <span className="muted"> · {pulled.description}</span>
                </span>
                <button className="button subtle" onClick={() => setPulling(true)}>Change</button>
                <button className="button subtle" onClick={() => { setSources([]); setPulled(null); }}>Clear</button>
              </div>
            ) : (
              <div className="source-folder">
                <Icon name="folder" />
                <span className="mono truncate" title={folder ?? undefined}>{folder}</span>
                <button className="button subtle" onClick={() => setPicking(true)}>Change</button>
                <button className="button subtle" onClick={() => { setSources([]); setPulled(null); }}>Clear</button>
              </div>
            )}
            <ul className="split-list">
              {sources.map((source, i) => (
                <li key={source.annotations}>
                  <input
                    aria-label="Split name"
                    title="The name this split will have in Granum, such as train or valid"
                    className="split-name"
                    value={source.split}
                    onChange={(e) => setSources(sources.map((s, j) => (j === i ? { ...s, split: e.target.value } : s)))}
                  />
                  <span className="mono small split-path" title={source.annotations}>{tail(source.annotations, 2)}</span>
                  <button className="icon-button" aria-label={`Remove ${source.split}`} onClick={() => setSources(sources.filter((_, j) => j !== i))}>
                    <Icon name="close" size={14} />
                  </button>
                </li>
              ))}
            </ul>
          </>
        )}
      </section>

      <section className="panel-card create-section">
        <h2 className="card-title">Image check</h2>
        <div className="media-choices" role="radiogroup" aria-label="Image check">
          {MEDIA_CHOICES.map((choice) => (
            <label key={choice.id} className={`radio-row${media === choice.id ? " checked" : ""}`}>
              <input type="radio" name="media" checked={media === choice.id} onChange={() => setMedia(choice.id)} />
              <span>
                <span className="strong">{choice.label}</span>
                <span className="muted small block">{choice.detail}</span>
              </span>
            </label>
          ))}
        </div>
      </section>

      <div className="create-actions">
        {error && <p className="form-error">{error}</p>}
        {problem && (sources.length > 0 || name) && <span className="muted small">{problem}</span>}
        <span className="spacer" />
        <button className="button primary large create-submit" disabled={Boolean(problem)} onClick={() => void runPreflight()}>
          {project ? "Check data" : "Create project"}
        </button>
      </div>

      {pulling && (
        <PullDialog
          onClose={() => setPulling(false)}
          onPulled={(result, description, sourceTasks) => {
            setSources(result.sources.map(({ split, annotations, images }) => ({ split, annotations, images })));
            setPulled({ description, images: result.images });
            // No type chosen yet: take the type of the projects pulled from.
            if (tasks.length === 0 && sourceTasks.length) setTasks(sortTasks(sourceTasks));
            setPulling(false);
          }}
        />
      )}
      {picking && (
        <FolderPicker
          start={folder}
          onClose={() => setPicking(false)}
          onPick={(picked) => {
            setSources(uniqueSplits(picked));
            setPulled(null);
            setPicking(false);
          }}
        />
      )}
    </div>
  );
}

/** What a detected layout is called on screen. COCO is the default and says nothing. */
const FORMAT_NAMES: Record<string, string> = {
  yolo: "YOLO", voc: "Pascal VOC", kitti: "KITTI", csv: "CSV", folders: "Folder per class",
};

/** Split names made unique: two files both called train become train and train-2. */
function uniqueSplits(sources: ImportSource[]): ImportSource[] {
  const out: ImportSource[] = [];
  for (const source of sources) {
    let split = source.split;
    let n = 2;
    while (out.some((s) => s.split === split)) split = `${source.split}-${n++}`;
    out.push({ ...source, split });
  }
  return out;
}

/** A folder browser in a dialog: open folders until the dataset's splits are found. */
function FolderPicker({ start, onClose, onPick }: {
  start: string | null;
  onClose: () => void;
  onPick: (sources: ImportSource[]) => void;
}) {
  const [listing, setListing] = useState<BrowseResult | null>(null);
  const [browseError, setBrowseError] = useState<string | null>(null);
  const [unpicked, setUnpicked] = useState<Set<string>>(new Set());

  const browse = (path?: string) => {
    setBrowseError(null);
    setUnpicked(new Set());
    api.browse(path).then(setListing).catch((e: Error) => setBrowseError(e.message));
  };
  useEffect(() => {
    browse(start || undefined);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const detected = listing?.detected ?? [];
  const picked = detected.filter((d) => !unpicked.has(d.annotations));
  const detectedRoot = detected.length > 1 ? detected[0]!.annotations.split("/").slice(0, -2).join("/") : null;

  return (
    <Modal
      title="Select data folder"
      onClose={onClose}
      width={680}
      footer={
        <>
          <span className="muted small">
            {detected.length ? `${plural(detected.length, "split")} found${detectedRoot ? ` in ${tail(detectedRoot, 1)}` : ""}` : "Open the dataset folder or one of its split folders"}
          </span>
          <span className="spacer" />
          <button onClick={onClose}>Cancel</button>
          <button className="primary" disabled={picked.length === 0} onClick={() => onPick(picked)}>
            {picked.length > 1 ? `Use ${picked.length} splits` : "Select folder"}
          </button>
        </>
      }
    >
      <div className="folder-picker">
        <div className="browser-head">
          <button
            className="icon-button"
            disabled={!listing?.parent && listing?.path === null}
            onClick={() => browse(listing?.parent ?? undefined)}
            title="Up one folder"
            aria-label="Up one folder"
          >
            <Icon name="up" />
          </button>
          <span className="browser-path mono">{listing?.path ?? "Data roots"}</span>
        </div>
        {browseError && <p className="form-error">{browseError}</p>}
        {detected.length > 0 && (
          <ul className="detected-sets">
            {detected.map((d) => (
              <li key={d.annotations}>
                <label>
                  <input
                    type="checkbox"
                    checked={!unpicked.has(d.annotations)}
                    onChange={(e) => {
                      const next = new Set(unpicked);
                      if (e.target.checked) next.delete(d.annotations);
                      else next.add(d.annotations);
                      setUnpicked(next);
                    }}
                  />
                  <span className="strong">{d.split}</span>
                  <span className="mono small muted split-path" title={d.annotations}>
                    {d.format && d.format !== "coco" && (
                      <span className="tag detected-format" title={`Read as ${FORMAT_NAMES[d.format] ?? d.format}, then checked like any other import`}>
                        {FORMAT_NAMES[d.format] ?? d.format}
                      </span>
                    )}
                    {tail(d.annotations, 2)}
                  </span>
                </label>
              </li>
            ))}
          </ul>
        )}
        <ul className="browser-list">
          {listing?.entries.map((entry) => (
            <li key={entry.path}>
              {entry.type === "dir" ? (
                <button className="browser-entry" onClick={() => browse(entry.path)}>
                  <Icon name="folder" />
                  <span>{entry.name}</span>
                  <Icon name="chevron" className="row-chevron" />
                </button>
              ) : (
                <button
                  className="browser-entry"
                  onClick={() => onPick([{ split: tail(entry.path, 2).split("/")[0] ?? "train", annotations: entry.path }])}
                  title="Use this annotation file"
                >
                  <Icon name="file" />
                  <span>{entry.name}</span>
                  <span className="muted small">Use file</span>
                </button>
              )}
            </li>
          ))}
          {listing && listing.entries.length === 0 && <li className="muted browser-empty">No subfolders or label files here.</li>}
        </ul>
        {listing?.images ? <p className="muted small browser-foot">{listing.images.toLocaleString()} images in this folder</p> : null}
      </div>
    </Modal>
  );
}

/** A small drawing of what each task labels. */
function TaskGlyph({ task }: { task: TaskId }) {
  const common = { fill: "none", stroke: "currentColor", strokeWidth: 1.6, strokeLinejoin: "round" as const, strokeLinecap: "round" as const };
  return (
    <svg className="task-glyph" viewBox="0 0 32 32" aria-hidden="true">
      <rect x="2.5" y="4.5" width="27" height="23" rx="2.5" {...common} opacity={0.35} />
      {task === "object_detection" && <><rect x="7" y="10" width="9" height="11" {...common} /><rect x="18" y="14" width="7" height="8" {...common} /></>}
      {task === "instance_segmentation" && <><path d="M8 20c0-5 2-9 5-9s4 4 3 7-2 4-4 4-4 0-4-2z" fill="currentColor" opacity={0.55} /><path d="M18 22c0-4 1-7 4-7s3 3 3 5-1 3-3 3-4 0-4-1z" fill="currentColor" opacity={0.3} /></>}
      {task === "semantic_segmentation" && <><path d="M2.5 18h27v7a2.5 2.5 0 0 1-2.5 2.5H5a2.5 2.5 0 0 1-2.5-2.5z" fill="currentColor" opacity={0.3} /><path d="M2.5 18c6-3 10 1 15-2s8 0 12 1" {...common} /></>}
      {task === "panoptic_segmentation" && <><path d="M2.5 19h27v6a2.5 2.5 0 0 1-2.5 2.5H5a2.5 2.5 0 0 1-2.5-2.5z" fill="currentColor" opacity={0.22} /><path d="M9 18c0-4 1.5-7 4-7s3 3 3 5-1 2-3.5 2z" fill="currentColor" opacity={0.6} /><path d="M19 18c0-3 1-5 3-5s2.5 2 2.5 4-1 1-2.5 1z" fill="currentColor" opacity={0.4} /></>}
      {task === "keypoint_detection" && <><path d="M16 9v6m0 0-5 4m5-4 5 4m-5-4v5l-4 5m4-5 4 5" {...common} /><circle cx="16" cy="8.5" r="1.8" fill="currentColor" /></>}
      {task === "classification" && <><path d="M7 21l5-6 4 4 3-3 6 5" {...common} /><rect x="17" y="7.5" width="9" height="5" rx="1.5" fill="currentColor" opacity={0.55} /></>}
    </svg>
  );
}
