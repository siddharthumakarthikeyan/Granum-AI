/** Every project on this machine, and the way in for someone who has none yet. */

import { useEffect, useMemo, useState } from "react";
import { api } from "../api/client";
import type { ProjectCard, ProjectSummary } from "../api/types";
import { DeleteProjectDialog } from "../components/DeleteProjectDialog";
import { RenameProjectDialog } from "../components/RenameProjectDialog";
import { EmptyState, Icon, PageHeader, RunStatus, formatNumber, formatWhen, plural } from "../components/ui";
import { taskLabel } from "../importing/tasks";
import { navigate, routeHref } from "../router";
import { useStore } from "../store/store";

type Sort = "recent" | "name" | "images";
type View = "cards" | "list";

const VIEW_KEY = "granum.projects.view";

function readView(): View {
  try {
    return localStorage.getItem(VIEW_KEY) === "list" ? "list" : "cards";
  } catch {
    return "cards";
  }
}

/** A card for a project the summary has not reached yet (just created, or the summary failed). */
function placeholder(project: ProjectSummary): ProjectCard {
  return {
    name: project.name, tasks: [], datasets: 0, sets: [], images: 0, verified: 0, boxes: 0, classes: 0,
    versions: 0, runs: project.runs, last_run: null, updated: null, covers: [],
  };
}

export function HomePage() {
  const projects = useStore((s) => s.projects);
  const health = useStore((s) => s.health);
  const licence = useStore((s) => s.licence);
  const [cards, setCards] = useState<ProjectCard[] | null>(null);
  const [query, setQuery] = useState("");
  const [sort, setSort] = useState<Sort>("recent");
  const [view, setView] = useState<View>(readView);
  const [deleting, setDeleting] = useState<ProjectSummary | null>(null);
  const [renaming, setRenaming] = useState<string | null>(null);

  // The store's list changes after a create, rename or delete; the summary follows it.
  useEffect(() => {
    let alive = true;
    api.projectCards().then((result) => alive && setCards(result)).catch(() => alive && setCards([]));
    return () => {
      alive = false;
    };
  }, [projects]);

  const changeView = (next: View) => {
    setView(next);
    try {
      localStorage.setItem(VIEW_KEY, next);
    } catch {
      // the choice just is not remembered
    }
  };

  const shown = useMemo(() => {
    const byName = new Map((cards ?? []).map((c) => [c.name, c]));
    const all = projects.map((p) => byName.get(p.name) ?? placeholder(p));
    const needle = query.trim().toLowerCase();
    const matching = needle ? all.filter((c) => c.name.toLowerCase().includes(needle)) : all;
    const order: Record<Sort, (a: ProjectCard, b: ProjectCard) => number> = {
      recent: (a, b) => (b.updated ?? "").localeCompare(a.updated ?? "") || a.name.localeCompare(b.name),
      name: (a, b) => a.name.localeCompare(b.name),
      images: (a, b) => b.images - a.images || a.name.localeCompare(b.name),
    };
    return [...matching].sort(order[sort]);
  }, [cards, projects, query, sort]);

  // The licence decides whether another project fits; the service refuses it too.
  const limit = licence?.max_projects ?? null;
  // The generated example does not count against the plan.
  const examples = new Set((cards ?? []).filter((c) => c.example).map((c) => c.name));
  const counted = projects.filter((p) => !examples.has(p.name)).length;
  const blocked = licence?.mode === "read_only" ? "Granum is read-only"
    : limit !== null && counted >= limit ? `Your plan allows ${limit} project${limit === 1 ? "" : "s"}`
      : null;
  const createButton = blocked ? (
    <a className="button primary disabled" href={routeHref({ name: "licence" })} title={`${blocked}. See Licence.`} aria-disabled="true">
      <Icon name="lock" />Create project
    </a>
  ) : (
    <a className="button primary" href={routeHref({ name: "import" })}><Icon name="plus" />Create project</a>
  );

  if (projects.length === 0) {
    return (
      <div className="page page-narrow">
        <EmptyState
          title="No projects"
          action={<span className="empty-actions">{createButton}<a className="button" href={routeHref({ name: "import", example: true })}>Try the example project</a></span>}
        >
          <p>A project holds data for one or more task types. Data stays on this machine.</p>
          <p className="muted small">The example is a generated dataset of coloured shapes with some deliberate label problems. It does not count against your plan.</p>
        </EmptyState>
      </div>
    );
  }

  const totals = shown.reduce((t, c) => ({ images: t.images + c.images, boxes: t.boxes + c.boxes }), { images: 0, boxes: 0 });
  const summaryOf = (name: string) => projects.find((p) => p.name === name)!;
  const actions = {
    rename: (name: string) => setRenaming(name),
    remove: (name: string) => setDeleting(summaryOf(name)),
  };

  return (
    <div className="page projects-page">
      <PageHeader
        title="Projects"
        subtitle={
          <>
            {limit !== null ? `${formatNumber(counted)} of ${plural(limit, "project")}` : plural(projects.length, "project")}
            {cards && <> · {plural(totals.images, "image")} · {plural(totals.boxes, "object")}</>}
            {health?.roots[0] && <> · <span className="mono">{health.roots[0]}</span></>}
          </>
        }
        actions={createButton}
      />

      <div className="projects-toolbar">
        <label className="projects-search">
          <Icon name="search" size={15} />
          <input type="search" placeholder="Search projects" value={query} onChange={(e) => setQuery(e.target.value)} aria-label="Search projects" />
        </label>
        <span className="spacer" />
        <label className="inline-field projects-sort">
          <span className="muted small">Sort</span>
          <select value={sort} onChange={(e) => setSort(e.target.value as Sort)}>
            <option value="recent">Last updated</option>
            <option value="name">Name</option>
            <option value="images">Most images</option>
          </select>
        </label>
        <div className="segmented" role="group" aria-label="View">
          <button className={view === "cards" ? "on" : ""} onClick={() => changeView("cards")} title="Cards" aria-label="Cards"><Icon name="grid" size={14} /></button>
          <button className={view === "list" ? "on" : ""} onClick={() => changeView("list")} title="List" aria-label="List"><Icon name="list" size={14} /></button>
        </div>
      </div>

      {shown.length === 0 ? (
        <p className="muted projects-none">No project matches “{query}”.</p>
      ) : view === "cards" ? (
        <div className="project-grid">
          {shown.map((card) => <ProjectTile key={card.name} card={card} loading={cards === null} {...actions} />)}
          {!query && !blocked && (
            <a className="project-new" href={routeHref({ name: "import" })}>
              <Icon name="plus" size={22} />
              <span>Create project</span>
              <span className="muted small">Import images and labels from a folder, or from other projects</span>
            </a>
          )}
        </div>
      ) : (
        <ProjectList cards={shown} loading={cards === null} {...actions} />
      )}

      {deleting && <DeleteProjectDialog project={deleting} onClose={() => setDeleting(null)} />}
      {renaming && <RenameProjectDialog project={renaming} onClose={() => setRenaming(null)} />}
    </div>
  );
}

interface RowActions {
  rename: (name: string) => void;
  remove: (name: string) => void;
}

function RowButtons({ name, rename, remove }: { name: string } & RowActions) {
  return (
    <span className="project-actions">
      <button
        className="icon-button"
        title={`Rename ${name}`}
        aria-label={`Rename ${name}`}
        onClick={(e) => {
          e.preventDefault();
          e.stopPropagation();
          rename(name);
        }}
      >
        <Icon name="pencil" size={15} />
      </button>
      <button
        className="icon-button project-delete"
        title={`Delete ${name}`}
        aria-label={`Delete ${name}`}
        onClick={(e) => {
          e.preventDefault();
          e.stopPropagation();
          remove(name);
        }}
      >
        <Icon name="trash" size={15} />
      </button>
    </span>
  );
}

function Covers({ card, loading }: { card: ProjectCard; loading: boolean }) {
  const covers = card.covers.slice(0, 4);
  if (covers.length === 0) {
    return (
      <div className={`project-covers empty${loading ? " loading" : ""}`}>
        {!loading && <Icon name="images" size={28} />}
      </div>
    );
  }
  return (
    <div className={`project-covers n${covers.length}`}>
      {covers.map((cover, i) => (
        <img key={cover.image} loading="lazy" src={api.mediaUrl(cover.image, i === 0 ? 480 : 240, card.name, cover.dataset)} alt="" />
      ))}
    </div>
  );
}

/** 12.4k, 701k, 1.2M: numbers that fit a narrow stat cell. */
function compact(value: number): string {
  return value < 10000 ? formatNumber(value) : new Intl.NumberFormat("en-US", { notation: "compact", maximumFractionDigits: 1 }).format(value);
}

function Verified({ card, label = true }: { card: ProjectCard; label?: boolean }) {
  const share = card.images ? card.verified / card.images : 0;
  const pct = share === 0 ? 0 : share < 0.01 ? "<1" : Math.floor(share * 100);
  return (
    <div className="project-verified" title={`${formatNumber(card.verified)} of ${formatNumber(card.images)} images verified`}>
      <div className="project-verified-label">
        {label && <span>Verified</span>}
        <span className="mono">{pct}%</span>
      </div>
      <div className="progress"><div className={`progress-fill${share === 1 ? " done" : ""}`} style={{ width: `${share * 100}%` }} /></div>
    </div>
  );
}

function ProjectTile({ card, loading, rename, remove }: { card: ProjectCard; loading: boolean } & RowActions) {
  const href = routeHref({ name: "overview", project: card.name });
  const stats: [string, number][] = [
    ["Images", card.images],
    ["Objects", card.boxes],
    ["Classes", card.classes],
    ["Versions", card.versions],
  ];
  return (
    <a className="project-card" href={href}>
      <Covers card={card} loading={loading} />
      <div className="project-card-body">
        <div className="project-card-head">
          <h2 title={card.name}>{card.name}</h2>
          <RowButtons name={card.name} rename={rename} remove={remove} />
        </div>
        <div className="project-tags">
          {card.example && <span className="project-task project-example" title="Generated example; does not count against your plan">Example</span>}
          {card.tasks.map((task) => <span key={task} className="project-task">{taskLabel(task)}</span>)}
          {card.sets.map((set) => <span key={set} className="project-set">{set}</span>)}
        </div>
        <dl className="project-stats">
          {stats.map(([label, value]) => (
            <div key={label}>
              <dt>{label}</dt>
              <dd title={formatNumber(value)}>{loading ? "–" : compact(value)}</dd>
            </div>
          ))}
        </dl>
        {card.images > 0 && <Verified card={card} />}
      </div>
      <div className="project-card-foot">
        {card.last_run ? (
          <>
            <RunStatus status={card.last_run.status} />
            <span className="muted">{plural(card.runs, "run")}</span>
          </>
        ) : (
          <span className="muted">{loading ? "" : "No training runs"}</span>
        )}
        <span className="spacer" />
        {card.updated && <span className="muted" title={card.updated}>Updated {formatWhen(card.updated)}</span>}
      </div>
    </a>
  );
}

function ProjectList({ cards, loading, rename, remove }: { cards: ProjectCard[]; loading: boolean } & RowActions) {
  return (
    <div className="data-table-wrap">
      <table className="data-table project-table">
        <thead>
          <tr>
            <th>Project</th>
            <th>Type</th>
            <th className="num">Images</th>
            <th className="num">Objects</th>
            <th className="num">Classes</th>
            <th>Verified</th>
            <th className="num">Versions</th>
            <th className="num">Runs</th>
            <th>Updated</th>
            <th className="actions" aria-label="Actions" />
          </tr>
        </thead>
        <tbody>
          {cards.map((card) => {
            const [cover] = card.covers;
            const num = (value: number) => (loading ? "–" : formatNumber(value));
            return (
              <tr key={card.name} className="clickable" onClick={() => navigate({ name: "overview", project: card.name })}>
                <td>
                  <a className="project-row-title" href={routeHref({ name: "overview", project: card.name })}>
                    {cover ? <img loading="lazy" src={api.mediaUrl(cover.image, 96, card.name, cover.dataset)} alt="" /> : <span className="project-row-blank" />}
                    <span className="cell-title">{card.name}</span>
                  </a>
                </td>
                <td className="muted">{card.tasks.map(taskLabel).join(", ")}</td>
                <td className="num">{num(card.images)}</td>
                <td className="num">{num(card.boxes)}</td>
                <td className="num">{num(card.classes)}</td>
                <td className="project-row-verified">{card.images > 0 && <Verified card={card} label={false} />}</td>
                <td className="num">{num(card.versions)}</td>
                <td className="num">{num(card.runs)}</td>
                <td className="muted nowrap" title={card.updated ?? undefined}>{formatWhen(card.updated ?? undefined)}</td>
                <td className="actions"><RowButtons name={card.name} rename={rename} remove={remove} /></td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
