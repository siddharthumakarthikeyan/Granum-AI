/** Step one: find the annotation files, one per split, under the folders the service may read. */

import { useEffect, useState } from "react";
import { api } from "../api/client";
import type { BrowseResult, ImportSource } from "../api/types";
import { Icon, plural, tail } from "../components/ui";
import { useImport, type MediaMode } from "./importStore";

const MEDIA_CHOICES: { id: MediaMode; label: string; detail: string }[] = [
  { id: "full", label: "All images", detail: "Decode every image: missing, corrupt, duplicate, size mismatch." },
  { id: "sample", label: "Sample, 200 per split", detail: "Faster; image issues outside the sample are not found." },
  { id: "none", label: "Annotations only", detail: "Images are not opened." },
];

export function SourcePicker() {
  const sources = useImport((s) => s.sources);
  const setSources = useImport((s) => s.setSources);
  const media = useImport((s) => s.media);
  const setMedia = useImport((s) => s.setMedia);
  const runPreflight = useImport((s) => s.runPreflight);
  const error = useImport((s) => s.error);

  const [listing, setListing] = useState<BrowseResult | null>(null);
  const [browseError, setBrowseError] = useState<string | null>(null);

  const browse = (path?: string) => {
    setBrowseError(null);
    api.browse(path).then(setListing).catch((e: Error) => setBrowseError(e.message));
  };
  useEffect(() => {
    const last = sources[0]?.annotations.split("/").slice(0, -2).join("/");
    browse(last || undefined);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Several sets are added in one update, so each sees the ones added before it.
  const add = (...added: ImportSource[]) => {
    let next = sources;
    for (const source of added) {
      const others = next.filter((s) => s.annotations !== source.annotations);
      let split = source.split;
      let n = 2;
      while (others.some((s) => s.split === split)) split = `${source.split}-${n++}`;
      next = [...others, { ...source, split }];
    }
    setSources(next);
  };
  const detected = listing?.detected ?? [];
  const [unpicked, setUnpicked] = useState<Set<string>>(new Set());
  const picked = detected.filter((d) => !unpicked.has(d.annotations));
  const detectedRoot = detected.length > 1 ? detected[0]!.annotations.split("/").slice(0, -2).join("/") : null;
  const splitNames = sources.map((s) => s.split.trim());
  const invalid = splitNames.some((name) => !name) || new Set(splitNames).size !== splitNames.length;

  return (
    <div className="import-choose">
      <section className="panel-card browser">
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
          <span className="browser-path mono">{listing?.path ?? "Import roots"}</span>
        </div>
        <div className="browser-help small">Open the dataset folder or any of its split folders; train, valid and test are found together. A <span className="mono">.json</span> can also be added on its own.</div>
        {browseError && <p className="form-error">{browseError}</p>}
        {detected.length > 0 && (
          <div className="detected">
            <div className="detected-head">
              <span className="strong">
                {detected.length === 1 ? "1 set found" : `${detected.length} sets found`}
                {detectedRoot && <span className="mono muted"> in {tail(detectedRoot, 1)}</span>}
              </span>
              <button className="button primary" disabled={picked.length === 0} onClick={() => add(...picked)}>
                {picked.length === detected.length && detected.length > 1 ? "Add all sets" : `Add ${plural(picked.length, "set")}`}
              </button>
            </div>
            <ul className="detected-sets">
              {detected.map((d) => (
                <li key={d.annotations}>
                  <label className={sources.some((s) => s.annotations === d.annotations) ? "added" : ""}>
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
                    <span className="mono small muted split-path" title={d.annotations}>{tail(d.annotations, 2)}</span>
                    {sources.some((s) => s.annotations === d.annotations) && <span className="small faint">added</span>}
                  </label>
                </li>
              ))}
            </ul>
          </div>
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
                  onClick={() => add({ split: tail(entry.path, 2).split("/")[0] ?? "train", annotations: entry.path })}
                  title="Add this file as a split"
                >
                  <Icon name="file" />
                  <span>{entry.name}</span>
                  <span className="muted small">Add</span>
                </button>
              )}
            </li>
          ))}
          {listing && listing.entries.length === 0 && <li className="muted browser-empty">This folder has no subfolders or label files.</li>}
        </ul>
        {listing?.images ? <p className="muted small browser-foot">{listing.images.toLocaleString()} images in this folder</p> : null}
      </section>

      <section className="import-side">
        <div className="panel-card">
          <h2 className="card-title">Splits</h2>
          {sources.length === 0 ? (
            <p className="faint">None selected</p>
          ) : (
            <ul className="split-list">
              {sources.map((source, i) => (
                <li key={source.annotations}>
                  <input
                    aria-label="Set name"
                    title="The name this set will have in Granum, such as train or valid"
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
          )}
          {invalid && <p className="form-error">Split names must be unique and non-empty.</p>}
        </div>

        <fieldset className="panel-card">
          <legend className="card-title">Image validation</legend>
          {MEDIA_CHOICES.map((choice) => (
            <label key={choice.id} className={`radio-row${media === choice.id ? " checked" : ""}`}>
              <input type="radio" name="media" checked={media === choice.id} onChange={() => setMedia(choice.id)} />
              <span>
                <span className="strong">{choice.label}</span>
                <span className="muted small block">{choice.detail}</span>
              </span>
            </label>
          ))}
        </fieldset>

        {error && <p className="form-error">{error}</p>}
        <button className="button primary large" disabled={sources.length === 0 || invalid} onClick={() => void runPreflight()}>
          Run preflight
        </button>
      </section>
    </div>
  );
}
