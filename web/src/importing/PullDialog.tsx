/** Pull images from existing projects, by class.
 *
 * What is pulled is a set of (project, class) picks. Ticking a class in the right-hand
 * list picks it in every project that has it; opening a project on the left picks classes
 * from that project alone, or the whole project (every image, unlabelled ones too).
 */

import { useEffect, useMemo, useRef, useState } from "react";
import { api } from "../api/client";
import type { LibraryClass, LibraryProject, PullResult, TaskId } from "../api/types";
import { Modal } from "../components/Modal";
import { Icon, formatNumber, plural } from "../components/ui";
import { labelColor } from "../images/labelColors";
import { tasksLabel } from "./tasks";

const pair = (project: string, key: string) => `${project}\u0000${key}`;

export function PullDialog({ onClose, onPulled }: {
  onClose: () => void;
  /** ``description``: what was pulled, in words; ``tasks``: the types of the projects pulled from. */
  onPulled: (result: PullResult, description: string, tasks: TaskId[]) => void;
}) {
  const [projects, setProjects] = useState<LibraryProject[] | null>(null);
  const [classes, setClasses] = useState<LibraryClass[]>([]);
  const [picks, setPicks] = useState<Set<string>>(new Set());
  const [whole, setWhole] = useState<Set<string>>(new Set());
  const [open, setOpen] = useState<Set<string>>(new Set());
  const [search, setSearch] = useState("");
  const [keepOthers, setKeepOthers] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api.library()
      .then((library) => {
        setProjects(library.projects);
        setClasses(library.classes);
        if (library.projects.length === 1) setOpen(new Set([library.projects[0]!.name]));
      })
      .catch((e: Error) => setError(e.message));
  }, []);

  const colorOf = useMemo(() => new Map(classes.map((c, i) => [c.key, labelColor(i)])), [classes]);
  const nameOf = useMemo(() => new Map(classes.map((c) => [c.key, c.name])), [classes]);
  const matches = (name: string) => !search.trim() || name.toLowerCase().includes(search.trim().toLowerCase());

  /** A class is picked in a project when that pair is picked or the whole project is. */
  const isPicked = (project: string, key: string) => whole.has(project) || picks.has(pair(project, key));
  const holders = (key: string) => (projects ?? []).filter((p) => p.classes.some((c) => c.key === key));

  const toggleClassEverywhere = (key: string) => {
    const owners = holders(key);
    const all = owners.every((p) => isPicked(p.name, key));
    setPicks((was) => {
      const next = new Set(was);
      for (const p of owners) {
        if (all) next.delete(pair(p.name, key));
        else next.add(pair(p.name, key));
      }
      return next;
    });
    // Unpicking a class breaks up a whole-project pick into its other classes.
    if (all) {
      const broken = owners.filter((p) => whole.has(p.name));
      if (broken.length) {
        setWhole((was) => new Set([...was].filter((n) => !broken.some((p) => p.name === n))));
        setPicks((was) => {
          const next = new Set(was);
          for (const p of broken) for (const c of p.classes) if (c.key !== key) next.add(pair(p.name, c.key));
          return next;
        });
      }
    }
  };

  const toggleWhole = (project: LibraryProject) => {
    const on = whole.has(project.name);
    setWhole((was) => {
      const next = new Set(was);
      if (on) next.delete(project.name);
      else next.add(project.name);
      return next;
    });
    // Whole or nothing: clear the project's single-class picks either way.
    setPicks((was) => new Set([...was].filter((p) => !p.startsWith(`${project.name}\u0000`))));
  };

  const togglePair = (project: LibraryProject, key: string) => {
    if (whole.has(project.name)) {
      // Unpick one class of a whole project: keep the rest as single picks.
      setWhole((was) => new Set([...was].filter((n) => n !== project.name)));
      setPicks((was) => {
        const next = new Set(was);
        for (const c of project.classes) if (c.key !== key) next.add(pair(project.name, c.key));
        return next;
      });
      return;
    }
    setPicks((was) => {
      const next = new Set(was);
      const id = pair(project.name, key);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  // What will be pulled, per project: [] for the whole project, else its class keys.
  const selection = useMemo(() => {
    const out: Record<string, string[]> = {};
    for (const p of projects ?? []) {
      if (whole.has(p.name)) out[p.name] = [];
      else {
        const keys = p.classes.filter((c) => picks.has(pair(p.name, c.key))).map((c) => c.key);
        if (keys.length) out[p.name] = keys;
      }
    }
    return out;
  }, [projects, picks, whole]);

  const upTo = (projects ?? []).reduce((n, p) => {
    const keys = selection[p.name];
    if (!keys) return n;
    if (keys.length === 0) return n + p.images;
    return n + Math.min(p.images, p.classes.filter((c) => keys.includes(c.key)).reduce((m, c) => m + c.images, 0));
  }, 0);

  /** "bus, truck from all projects; car from aerial-valid; aerial-test (whole)". */
  const description = useMemo(() => {
    const parts: string[] = [];
    const byClass = new Map<string, string[]>();
    for (const [project, keys] of Object.entries(selection)) {
      if (keys.length === 0) parts.push(`all of ${project}`);
      for (const key of keys) byClass.set(key, [...(byClass.get(key) ?? []), project]);
    }
    const everywhere = [...byClass].filter(([key, from]) => from.length === holders(key).length && holders(key).length > 1).map(([key]) => nameOf.get(key) ?? key);
    if (everywhere.length) parts.push(`${everywhere.join(", ")} from all projects`);
    const byProject = new Map<string, string[]>();
    for (const [key, from] of byClass) {
      if (from.length === holders(key).length && holders(key).length > 1) continue;
      for (const project of from) byProject.set(project, [...(byProject.get(project) ?? []), nameOf.get(key) ?? key]);
    }
    for (const [project, names] of byProject) parts.push(`${names.join(", ")} from ${project}`);
    return parts.join("; ");
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selection, nameOf]);

  const pull = async () => {
    setBusy(true);
    setError(null);
    try {
      const result = await api.pullFromProjects({ selection, keep_other_labels: keepOthers });
      const types = new Set((projects ?? []).filter((p) => p.name in selection).flatMap((p) => p.tasks));
      onPulled(result, description, [...types]);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
      setBusy(false);
    }
  };

  const chosen = Object.keys(selection).length;

  return (
    <Modal
      title="Import from existing projects"
      onClose={onClose}
      width={900}
      footer={
        <>
          <span className="muted small truncate pull-summary" title={description}>
            {chosen === 0 ? "Pick classes, from all projects or from one" : `Up to ${formatNumber(upTo)} images · ${description}`}
          </span>
          <span className="spacer" />
          <button onClick={onClose}>Cancel</button>
          <button className="primary" disabled={busy || chosen === 0} onClick={() => void pull()}>
            {busy ? "Pulling" : "Pull images"}
          </button>
        </>
      }
    >
      <input type="search" className="pull-search" placeholder="Search classes" value={search} onChange={(e) => setSearch(e.target.value)} />
      <div className="pull-columns">
        <section className="pull-column">
          <h3 className="qa-side-title">Classes in all projects <span className="faint">{formatNumber(classes.length)}</span></h3>
          {!projects && !error && <p className="muted small"><span className="spinner" /> Reading projects</p>}
          <ul className="pull-list">
            {classes.filter((c) => matches(c.name)).map((c) => {
              const owners = holders(c.key);
              const count = owners.filter((p) => isPicked(p.name, c.key)).length;
              return (
                <li key={c.key}>
                  <label className={count ? "on" : ""} title={`In ${c.projects?.join(", ")}`}>
                    <Check checked={count > 0 && count === owners.length} mixed={count > 0 && count < owners.length} onChange={() => toggleClassEverywhere(c.key)} />
                    <span className="class-swatch" style={{ background: colorOf.get(c.key) }} />
                    <span className="truncate">{c.name}</span>
                    <span className="faint small">{plural(owners.length, "project")}</span>
                    <span className="faint small tabular pull-count">{formatNumber(c.images)}</span>
                  </label>
                </li>
              );
            })}
          </ul>
        </section>

        <section className="pull-column">
          <h3 className="qa-side-title">By project <span className="faint">{projects ? formatNumber(projects.length) : ""}</span></h3>
          {projects && projects.length === 0 && <p className="muted small">No project has images yet.</p>}
          <ul className="pull-list">
            {projects?.map((project) => {
              const expanded = open.has(project.name) || Boolean(search.trim());
              const picked = project.classes.filter((c) => isPicked(project.name, c.key)).length;
              const shown = project.classes.filter((c) => matches(c.name));
              if (search.trim() && shown.length === 0) return null;
              return (
                <li key={project.name} className="pull-project-group">
                  <div className={`pull-project-row${picked ? " on" : ""}`}>
                    <button
                      className="icon-button pull-expand"
                      aria-expanded={expanded}
                      aria-label={expanded ? `Hide classes of ${project.name}` : `Show classes of ${project.name}`}
                      onClick={() => setOpen((was) => {
                        const next = new Set(was);
                        if (next.has(project.name)) next.delete(project.name);
                        else next.add(project.name);
                        return next;
                      })}
                    >
                      <Icon name="chevron" size={13} className={expanded ? "chevron-down" : ""} />
                    </button>
                    <label title="Every image of this project">
                      <Check checked={whole.has(project.name)} mixed={!whole.has(project.name) && picked > 0} onChange={() => toggleWhole(project)} />
                      <span className="pull-project">
                        <span className="strong truncate">{project.name}</span>
                        <span className="faint small">
                          {tasksLabel(project.tasks)} · {formatNumber(project.images)} images
                          {whole.has(project.name) ? " · all images" : picked ? ` · ${plural(picked, "class", "classes")} picked` : ""}
                        </span>
                      </span>
                    </label>
                  </div>
                  {expanded && (
                    <ul className="pull-sublist">
                      {shown.map((c) => (
                        <li key={c.key}>
                          <label className={isPicked(project.name, c.key) ? "on" : ""}>
                            <Check checked={isPicked(project.name, c.key)} onChange={() => togglePair(project, c.key)} />
                            <span className="class-swatch" style={{ background: colorOf.get(c.key) }} />
                            <span className="truncate">{c.name}</span>
                            <span className="faint small tabular pull-count">{formatNumber(c.images)}</span>
                          </label>
                        </li>
                      ))}
                    </ul>
                  )}
                </li>
              );
            })}
          </ul>
        </section>
      </div>
      <label className="pull-keep">
        <input type="checkbox" checked={keepOthers} onChange={(e) => setKeepOthers(e.target.checked)} />
        <span>Keep the other labels on pulled images <span className="faint small">(otherwise only the picked classes' boxes come along)</span></span>
      </label>
      {error && <p className="form-error">{error}</p>}
    </Modal>
  );
}

/** A checkbox that can also show "some" (indeterminate). */
function Check({ checked, mixed = false, onChange }: { checked: boolean; mixed?: boolean; onChange: () => void }) {
  const ref = useRef<HTMLInputElement>(null);
  useEffect(() => {
    if (ref.current) ref.current.indeterminate = mixed;
  }, [mixed]);
  return <input ref={ref} type="checkbox" checked={checked} onChange={onChange} />;
}
