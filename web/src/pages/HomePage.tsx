/** The project library and a concise view of work across the workspace. */
import { useEffect, useMemo, useRef, useState } from "react";
import { api } from "../api/client";
import type { ProjectCard, ProjectSummary } from "../api/types";
import { ActionMenu } from "../components/ActionMenu";
import { DashboardMetric } from "../components/DashboardMetric";
import { DeleteProjectDialog } from "../components/DeleteProjectDialog";
import { RenameProjectDialog } from "../components/RenameProjectDialog";
import { EmptyState, Icon, Mark, PageHeader, RunStatus, formatNumber, formatWhen, plural } from "../components/ui";
import { taskLabel } from "../importing/tasks";
import { navigate, routeHref } from "../router";
import { projectTone, togglePinnedProject, usePinnedProjects } from "../shell/preferences";
import { useStore } from "../store/store";

type Sort = "recent" | "name" | "images";
type View = "cards" | "list";
type Filter = "all" | "pinned" | "review";
const VIEW_KEY = "granum.projects.view";
function readView(): View {
  try { return localStorage.getItem(VIEW_KEY) === "list" ? "list" : "cards"; } catch { return "cards"; }
}
function placeholder(project: ProjectSummary): ProjectCard {
  return { name: project.name, tasks: [], datasets: 0, sets: [], images: 0, verified: 0, boxes: 0, classes: 0,
    versions: 0, runs: project.runs, last_run: null, updated: null, covers: [] };
}

export function HomePage() {
  const projects = useStore((s) => s.projects);
  const health = useStore((s) => s.health);
  const licence = useStore((s) => s.licence);
  const pinned = usePinnedProjects();
  const [cards, setCards] = useState<ProjectCard[] | null>(null);
  const [summaryError, setSummaryError] = useState(false);
  const [preferenceError, setPreferenceError] = useState(false);
  const [refresh, setRefresh] = useState(0);
  const [query, setQuery] = useState("");
  const [sort, setSort] = useState<Sort>("recent");
  const [task, setTask] = useState("");
  const [filter, setFilter] = useState<Filter>("all");
  const [view, setView] = useState<View>(readView);
  const [deleting, setDeleting] = useState<ProjectSummary | null>(null);
  const [renaming, setRenaming] = useState<string | null>(null);
  const search = useRef<HTMLInputElement>(null);

  useEffect(() => {
    let alive = true;
    setCards(null);
    setSummaryError(false);
    api.projectCards().then((result) => { if (alive) setCards(result); }).catch(() => { if (alive) setSummaryError(true); });
    return () => { alive = false; };
  }, [projects, refresh]);
  useEffect(() => {
    const focusSearch = (event: KeyboardEvent) => {
      const target = event.target as HTMLElement | null;
      if (event.key !== "/" || event.ctrlKey || event.metaKey || event.altKey ||
        target?.closest("input, textarea, select, [contenteditable], [role='dialog']") ||
        document.querySelector('[aria-modal="true"], dialog[open]')) return;
      if (search.current) { event.preventDefault(); search.current.focus(); }
    };
    window.addEventListener("keydown", focusSearch);
    return () => window.removeEventListener("keydown", focusSearch);
  }, []);
  const changeView = (next: View) => {
    setView(next);
    try { localStorage.setItem(VIEW_KEY, next); } catch { /* The view still changes in this tab. */ }
  };
  const byName = useMemo(() => new Map((cards ?? []).map((card) => [card.name, card])), [cards]);
  const all = useMemo(() => projects.map((project) => byName.get(project.name) ?? placeholder(project)), [projects, byName]);
  const complete = cards !== null && projects.every((project) => byName.has(project.name));
  const tasks = useMemo(() => [...new Set(all.flatMap((card) => card.tasks))].sort(), [all]);
  const shown = useMemo(() => {
    const needle = query.trim().toLowerCase();
    const matching = all.filter((card) => (!needle || card.name.toLowerCase().includes(needle)) &&
      (!task || card.tasks.some((value) => value === task)) && (filter !== "pinned" || pinned.includes(card.name)) &&
      (filter !== "review" || card.images > card.verified));
    const order: Record<Sort, (a: ProjectCard, b: ProjectCard) => number> = {
      recent: (a, b) => (b.updated ?? "").localeCompare(a.updated ?? "") || a.name.localeCompare(b.name),
      name: (a, b) => a.name.localeCompare(b.name),
      images: (a, b) => b.images - a.images || a.name.localeCompare(b.name),
    };
    return matching.sort(order[sort]);
  }, [all, query, sort, task, filter, pinned]);
  const totals = all.reduce((total, card) => ({ images: total.images + card.images, boxes: total.boxes + card.boxes,
    verified: total.verified + card.verified, datasets: total.datasets + card.datasets }), { images: 0, boxes: 0, verified: 0, datasets: 0 });
  const coverage = totals.images ? Math.min(100, Math.floor(totals.verified / totals.images * 100)) : 0;
  const runCount = projects.reduce((total, project) => total + project.runs, 0);
  const recent = all.filter((card) => card.last_run).sort((a, b) => b.last_run!.created.localeCompare(a.last_run!.created)).slice(0, 4);
  const reviewQueue = all.filter((card) => card.images > card.verified).sort((a, b) => (b.images - b.verified) - (a.images - a.verified));
  const limit = licence?.max_projects ?? null;
  const examples = new Set((cards ?? []).filter((card) => card.example).map((card) => card.name));
  const counted = projects.filter((project) => !examples.has(project.name)).length;
  const blocked = licence?.mode === "read_only" ? "Granum is read-only"
    : limit !== null && counted >= limit ? `Your plan allows ${plural(limit, "project")}` : null;
  const createButton = blocked ? <a className="button" href={routeHref({ name: "licence" })} title={blocked}><Icon name="lock" />View project limit</a>
    : <a className="button primary" href={routeHref({ name: "import" })}><Icon name="plus" />Create project</a>;
  const actions: RowActions = {
    rename: setRenaming,
    remove: (name) => setDeleting(projects.find((project) => project.name === name) ?? null),
    pin: (name) => setPreferenceError(!togglePinnedProject(name)),
    pinned,
  };
  const clearFilters = () => { setQuery(""); setTask(""); setFilter("all"); search.current?.focus(); };

  if (!health && projects.length === 0) {
    return <div className="page projects-page" aria-busy="true"><PageHeader title="Projects" subtitle="Connecting to your workspace…" />
      <div className="project-grid" role="status" aria-label="Loading projects">{[0, 1, 2].map((i) => <div className="project-skeleton" key={i}><div /><span /><span /></div>)}</div></div>;
  }
  return <div className="page projects-page">
    <PageHeader title="Projects" subtitle="Your data, reviews, and experiments, together." actions={createButton} />
    {projects.length === 0 ? <section className="workspace-welcome">
      <div className="welcome-art" aria-hidden="true"><div /><div /><span><Mark size={54} /></span></div>
      <span className="dashboard-eyebrow">YOUR WORKSPACE IS READY</span>
      <h2>Great models start with great data.</h2>
      <p>Create a project to bring your images, annotations, and experiments into one place.</p>
      <div className="empty-actions">{createButton}<a className="button" href={routeHref({ name: "import", example: true })}>Explore an example<Icon name="chevron" size={14} /></a></div>
      <span className="welcome-note">The generated example includes label problems to explore and does not count against your plan.</span>
      <div className="welcome-steps">{[["import", "01", "Connect your data"], ["review", "02", "Review every detail"], ["runs", "03", "Measure what improves"]].map(([icon, step, label]) => <div key={step}><Icon name={icon!} size={18} /><span>{step}</span><strong>{label}</strong></div>)}</div>
    </section> : <>
      <dl className="dashboard-metrics" aria-label="Workspace statistics">
        <DashboardMetric label="Total images" value={complete ? formatNumber(totals.images) : "—"} icon="images" detail={complete ? `Across ${plural(totals.datasets, "source dataset")}` : summaryError ? "Summary unavailable" : "Loading summary…"} />
        <DashboardMetric label="Annotations" value={complete ? formatNumber(totals.boxes) : "—"} icon="datasets" detail="Objects in your source datasets" />
        <DashboardMetric label="Review coverage" value={complete ? `${coverage}%` : "—"} icon="review" accent detail={complete ? `${formatNumber(totals.verified)} images verified` : "Waiting for project summaries"} />
        <DashboardMetric label="Training runs" value={formatNumber(runCount)} icon="runs" detail={`Across ${plural(projects.length, "project")}`} />
      </dl>
      {(summaryError || (cards !== null && !complete)) && <div className="dashboard-notice" role="status"><Icon name="warn" size={16} /><span>Some summaries are unavailable. You can still open your projects.</span><button className="button subtle" onClick={() => setRefresh((value) => value + 1)}><Icon name="refresh" />Retry</button></div>}
      {preferenceError && <div className="dashboard-notice" role="status"><Icon name="warn" size={16} /><span>Your browser could not save pinned projects. Allow site storage and try again.</span><button className="icon-button" aria-label="Dismiss pin error" onClick={() => setPreferenceError(false)}><Icon name="close" /></button></div>}
      <section className="projects-library" aria-label="Project library">
        <div className="project-library-tabs" role="group" aria-label="Filter projects">
          <button className={filter === "all" ? "active" : ""} aria-pressed={filter === "all"} onClick={() => setFilter("all")}>All projects<span>{projects.length}</span></button>
          <button className={filter === "pinned" ? "active" : ""} aria-pressed={filter === "pinned"} onClick={() => setFilter("pinned")}>Pinned<span>{all.filter((card) => pinned.includes(card.name)).length}</span></button>
          <button className={filter === "review" ? "active" : ""} aria-pressed={filter === "review"} onClick={() => setFilter("review")}>Needs review{complete && <span>{reviewQueue.length}</span>}</button>
        </div>
        <div className="projects-toolbar">
          <label className="projects-search"><Icon name="search" size={17} /><input ref={search} type="search" placeholder="Search projects…" value={query} onChange={(event) => setQuery(event.target.value)} aria-label="Search projects" /><kbd aria-hidden="true">/</kbd></label>
          <div className="project-toolbar-filters">
            {tasks.length > 0 && <label className="projects-sort"><select aria-label="Project task" value={task} onChange={(event) => setTask(event.target.value)}><option value="">All tasks</option>{tasks.map((value) => <option key={value} value={value}>{taskLabel(value)}</option>)}</select></label>}
            <label className="projects-sort"><select aria-label="Sort projects" value={sort} onChange={(event) => setSort(event.target.value as Sort)}><option value="recent">Last updated</option><option value="name">Name</option><option value="images">Most images</option></select></label>
            <div className="segmented" role="group" aria-label="View">
              <button className={view === "cards" ? "on" : ""} aria-pressed={view === "cards"} onClick={() => changeView("cards")} title="Cards" aria-label="Cards"><Icon name="grid" size={16} /></button>
              <button className={view === "list" ? "on" : ""} aria-pressed={view === "list"} onClick={() => changeView("list")} title="List" aria-label="List"><Icon name="list" size={16} /></button>
            </div>
          </div>
        </div>
        {shown.length === 0 ? <div className="projects-no-results" role="status"><span className="empty-state-icon"><Icon name={filter === "pinned" ? "folder" : "search"} size={24} /></span><EmptyState title={filter === "pinned" && !query && !task ? "Keep your current work close" : "No matching projects"} action={<button className="button" onClick={clearFilters}>Show all projects</button>}><p>{filter === "pinned" && !query && !task ? "Pin a project from its menu to find it here and in your sidebar." : "Try another search or clear your filters."}</p></EmptyState></div>
          : view === "cards" ? <div className="project-grid">{shown.map((card) => <ProjectTile key={card.name} card={card} loading={!byName.has(card.name)} pending={cards === null && !summaryError} {...actions} />)}</div>
          : <ProjectList cards={shown} known={byName} {...actions} />}
        <div className="projects-library-foot"><span>{shown.length === projects.length ? plural(projects.length, "project") : `${shown.length} of ${plural(projects.length, "project")}`}</span><span>Open workspace search <kbd>Ctrl / ⌘ K</kbd></span></div>
      </section>
      {complete && <div className="workspace-activity">
        <section className="activity-section" aria-label="Latest runs">
          <div className="dashboard-section-head"><h2><Icon name="runs" size={17} />Latest runs</h2><span className="muted small">Most recent per project</span></div>
          {recent.length > 0 ? <div className="activity-list">{recent.map((card) => <a key={card.name} href={routeHref({ name: "runs", project: card.name })}>
            <span className={`project-monogram tone-${projectTone(card.name)}`}><Icon name="runs" size={17} /></span><span className="activity-detail"><strong title={card.last_run!.name}>{card.last_run!.name}</strong><span>{card.name} · {formatWhen(card.last_run!.created)}</span></span><RunStatus status={card.last_run!.status} /><Icon name="chevron" size={14} />
          </a>)}</div> : <div className="activity-empty"><Icon name="runs" size={20} /><div><strong>A place for every experiment</strong><p>Recorded training runs will appear here.</p></div></div>}
        </section>
        <section className="activity-section" aria-label="Review queue">
          <div className="dashboard-section-head"><h2><Icon name="review" size={17} />Ready for review</h2><span className="muted small">{plural(Math.max(0, totals.images - totals.verified), "image")} remaining</span></div>
          {reviewQueue.length > 0 ? <div className="activity-list">{reviewQueue.slice(0, 4).map((card) => <a key={card.name} href={routeHref({ name: "images", project: card.name, review: true })}>
            <span className={`project-monogram tone-${projectTone(card.name)}`}><Icon name="images" size={17} /></span><span className="activity-detail"><strong>{card.name}</strong><span>{plural(card.images - card.verified, "image")} to verify</span></span><span className="activity-action">Review<Icon name="chevron" size={14} /></span>
          </a>)}</div> : <div className="activity-empty"><Icon name="check" size={20} /><div><strong>{totals.images ? "Every image is verified" : "Your review queue is clear"}</strong><p>{totals.images ? "You're ready for the next dataset approval." : "Import images to start reviewing your data."}</p></div></div>}
        </section>
      </div>}
    </>}
    {deleting && <DeleteProjectDialog project={deleting} onClose={() => setDeleting(null)} />}
    {renaming && <RenameProjectDialog project={renaming} onClose={() => setRenaming(null)} />}
  </div>;
}

interface RowActions { rename: (name: string) => void; remove: (name: string) => void; pin: (name: string) => void; pinned: string[] }
function ProjectActions({ name, rename, remove, pin, pinned }: { name: string } & RowActions) {
  return <ActionMenu label={`Actions for ${name}`} actions={[
    { label: pinned.includes(name) ? "Unpin project" : "Pin project", icon: "star", onSelect: () => pin(name) },
    { label: "Rename project", icon: "pencil", onSelect: () => rename(name) },
    { label: "Delete project", icon: "trash", danger: true, onSelect: () => remove(name) },
  ]} />;
}
function Cover({ card, loading, unavailable }: { card: ProjectCard; loading: boolean; unavailable: boolean }) {
  const cover = card.covers[0];
  const [failed, setFailed] = useState(false);
  useEffect(() => setFailed(false), [cover?.image, cover?.dataset]);
  return <div className={`project-cover${loading ? " loading" : ""}${!cover || failed ? " empty" : ""}`}>
    {cover && !failed ? <img loading="lazy" src={api.mediaUrl(cover.image, 640, card.name, cover.dataset)} alt="" onError={() => setFailed(true)} />
      : !loading && <><Icon name="images" size={30} /><span>{failed || unavailable ? "Preview unavailable" : "Your data starts here"}</span></>}
    {cover && !failed && <span className="project-cover-caption"><Icon name="images" size={13} />{plural(card.datasets, "source dataset")}</span>}
    {card.example && <span className="project-example-badge">Example project</span>}
  </div>;
}
function compact(value: number): string { return value < 10000 ? formatNumber(value) : new Intl.NumberFormat("en-US", { notation: "compact", maximumFractionDigits: 1 }).format(value); }
function Verified({ card, label = true }: { card: ProjectCard; label?: boolean }) {
  const share = card.images ? Math.min(1, Math.max(0, card.verified / card.images)) : 0;
  const pct = share === 0 ? 0 : share < 0.01 ? "<1" : Math.floor(share * 100);
  return <div className="project-verified" title={`${formatNumber(card.verified)} of ${formatNumber(card.images)} images verified`}>
    <div className="project-verified-label">{label && <span>Review progress</span>}<span>{pct}% verified</span></div>
    <div className="progress"><div className={`progress-fill${share === 1 ? " done" : ""}`} style={{ width: `${share * 100}%` }} /></div>
  </div>;
}
function ProjectTile({ card, loading, pending, ...actions }: { card: ProjectCard; loading: boolean; pending: boolean } & RowActions) {
  const href = routeHref({ name: "overview", project: card.name });
  const stats: [string, number][] = [["Images", card.images], ["Objects", card.boxes], ["Classes", card.classes]];
  return <article className="project-card">
    <a className="project-cover-link" href={href} aria-label={`Open ${card.name}`}><Cover card={card} loading={loading && pending} unavailable={loading && !pending} /></a>
    <div className="project-card-body">
      <div className="project-card-head"><span className={`project-monogram tone-${projectTone(card.name)}`}><Icon name="folder" size={18} /></span>
        <div className="project-identity"><h3 title={card.name}><a href={href}>{card.name}</a></h3><span>{loading ? pending ? "Loading summary…" : "Summary unavailable" : card.tasks.length ? card.tasks.map(taskLabel).join(" · ") : "Ready for your first dataset"}</span></div>
        {actions.pinned.includes(card.name) && <span className="project-pin" title="Pinned project" aria-label="Pinned"><Icon name="star" size={12} /></span>}
        <ProjectActions name={card.name} {...actions} />
      </div>
      <dl className="project-stats">{stats.map(([label, value]) => <div key={label}><dt>{label}</dt><dd title={loading ? undefined : formatNumber(value)}>{loading ? "—" : compact(value)}</dd></div>)}</dl>
      {!loading && card.images > 0 ? <Verified card={card} /> : <div className="project-review-empty">{loading ? pending ? "Loading project summary…" : "Project summary unavailable" : "Import images to begin your review"}</div>}
    </div>
    <div className="project-card-foot"><span className="project-run-summary"><Icon name="runs" size={14} />{plural(card.runs, "run")}</span><span title={card.updated ?? undefined}>{card.updated ? `Updated ${formatWhen(card.updated)}` : loading ? "—" : "No activity yet"}</span></div>
  </article>;
}
function ProjectList({ cards, known, ...actions }: { cards: ProjectCard[]; known: Map<string, ProjectCard> } & RowActions) {
  return <div className="data-table-wrap"><table className="data-table project-table"><thead><tr><th>Project</th><th>Task</th><th className="num">Images</th><th className="num">Objects</th><th>Review progress</th><th className="num">Runs</th><th>Updated</th><th className="actions" aria-label="Actions" /></tr></thead>
    <tbody>{cards.map((card) => { const cover = card.covers[0]; const num = (value: number) => known.has(card.name) ? formatNumber(value) : "—";
      return <tr key={card.name} className="clickable" onClick={(event) => { if (!(event.target as HTMLElement).closest("a, button")) navigate({ name: "overview", project: card.name }); }}>
        <td><a className="project-row-title" href={routeHref({ name: "overview", project: card.name })}>{cover ? <img loading="lazy" src={api.mediaUrl(cover.image, 96, card.name, cover.dataset)} alt="" /> : <span className={`project-monogram tone-${projectTone(card.name)}`}><Icon name="folder" /></span>}<span className="cell-title">{card.name}</span>{actions.pinned.includes(card.name) && <span className="project-pin" aria-label="Pinned"><Icon name="star" size={12} /></span>}</a></td>
        <td className="muted">{card.tasks.map(taskLabel).join(", ") || "—"}</td><td className="num">{num(card.images)}</td><td className="num">{num(card.boxes)}</td><td className="project-row-verified">{card.images > 0 ? <Verified card={card} label={false} /> : "—"}</td><td className="num">{num(card.runs)}</td><td className="muted nowrap" title={card.updated ?? undefined}>{formatWhen(card.updated ?? undefined)}</td><td className="actions"><ProjectActions name={card.name} {...actions} /></td>
      </tr>; })}</tbody></table></div>;
}
