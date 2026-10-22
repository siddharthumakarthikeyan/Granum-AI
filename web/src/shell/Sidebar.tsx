/** Persistent workspace navigation, with shortcuts to the user's own projects. */
import { useEffect, useRef, useState } from "react";
import { api } from "../api/client";
import { Icon, Mark, formatNumber } from "../components/ui";
import { navigate, routeHref, routeProject, type Route } from "../router";
import { useStore } from "../store/store";
import { openWorkspaceSearch, projectTone, usePinnedProjects, useRecentProjects, workspaceSearchShortcut } from "./preferences";

const SECTIONS = [
  { name: "overview", label: "Overview", icon: "overview", group: "Project" },
  { name: "images", label: "Images", icon: "images", group: "Data" },
  { name: "datasets", label: "Datasets", icon: "datasets", group: "Data" },
  { name: "health", label: "Data health", icon: "shield", group: "Data" },
  { name: "runs", label: "Runs", icon: "runs", group: "Models" },
  { name: "evaluation", label: "Evaluation", icon: "target", group: "Models" },
  { name: "findings", label: "Findings", icon: "findings", group: "Models" },
] as const;
function sectionOf(route: Route): string {
  if (route.name === "table" || route.name === "report") return "datasets";
  if (route.name === "run" || route.name === "learning" || route.name === "compare") return "runs";
  if (route.name === "removed") return "images";
  return route.name;
}
export function Sidebar({ route }: { route: Route }) {
  const projects = useStore((s) => s.projects);
  const health = useStore((s) => s.health);
  const licence = useStore((s) => s.licence);
  const tables = useStore((s) => s.tables);
  const runs = useStore((s) => s.runs);
  const loadedProject = useStore((s) => s.loadedProject);
  const pinned = usePinnedProjects().filter((name) => projects.some((p) => p.name === name));
  const recent = useRecentProjects().filter((name) => projects.some((p) => p.name === name) && !pinned.includes(name));
  const [menuOpen, setMenuOpen] = useState(false);
  const navigation = useRef<HTMLElement>(null);
  const project = routeProject(route);
  const active = sectionOf(route);
  useEffect(() => setMenuOpen(false), [route]);
  useEffect(() => {
    if (!menuOpen) return;
    const close = (event: KeyboardEvent) => {
      if (event.key === "Escape") { setMenuOpen(false); document.getElementById("navigation-toggle")?.focus(); }
    };
    const outside = (event: PointerEvent) => { if (!navigation.current?.contains(event.target as Node)) setMenuOpen(false); };
    window.addEventListener("keydown", close);
    document.addEventListener("pointerdown", outside);
    return () => { window.removeEventListener("keydown", close); document.removeEventListener("pointerdown", outside); };
  }, [menuOpen]);
  const [datasetCount, setDatasetCount] = useState<number | null>(null);
  useEffect(() => {
    setDatasetCount(null);
    if (!project) return;
    let alive = true;
    api.releases(project).then(({ releases }) => { if (alive) setDatasetCount(releases.length); }).catch(() => undefined);
    return () => { alive = false; };
  }, [project, tables]);
  const projectLinks = (names: string[]) => <ul className="sidebar-nav sidebar-project-links">{names.slice(0, 5).map((name) => <li key={name}><a href={routeHref({ name: "overview", project: name })} title={name}>
    <span className={`sidebar-project-dot tone-${projectTone(name)}`} aria-hidden="true" /><span>{name}</span>
  </a></li>)}</ul>;
  return <nav ref={navigation} className="sidebar" aria-label="Main" data-menu-open={menuOpen}>
    <div className="sidebar-brand-row"><a className="sidebar-brand" href="#/" aria-label="Granum projects"><Mark size={27} /><span>granum<span className="sidebar-ai">AI</span></span></a>
      <button id="navigation-toggle" className="icon-button sidebar-toggle" aria-label={menuOpen ? "Close navigation" : "Open navigation"} aria-expanded={menuOpen} aria-controls="sidebar-navigation" onClick={() => setMenuOpen(!menuOpen)}><Icon name={menuOpen ? "close" : "list"} size={20} /></button>
    </div>
    <div id="sidebar-navigation" className="sidebar-navigation">
      <div className="sidebar-workspace"><span className="workspace-emblem"><Icon name="layers" size={18} /></span><span><strong>My workspace</strong><small>Local workspace</small></span></div>
      {project && <div className="sidebar-project"><label className="sidebar-heading" htmlFor="project-switcher">Current project</label><div className="select-wrap"><select id="project-switcher" aria-label="Project" value={project} onChange={(event) => { const name = event.target.value; navigate(name ? { name: "overview", project: name } : { name: "home" }); }}><option value="">All projects</option>{projects.map((p) => <option key={p.name} value={p.name}>{p.name}</option>)}</select></div></div>}
      <div className="sidebar-group sidebar-global"><ul className="sidebar-nav">
        <li><button className="sidebar-search" aria-label="Search workspace" title="Search workspace (Ctrl or Command K)" onClick={() => { setMenuOpen(false); openWorkspaceSearch(); }}><Icon name="search" /><span>Search</span><kbd>{workspaceSearchShortcut()}</kbd></button></li>
        <li><a href={routeHref({ name: "home" })} className={route.name === "home" ? "active" : ""} aria-label="All projects" title="All projects" aria-current={route.name === "home" ? "page" : undefined}><Icon name="folder" /><span>All projects</span><span className="nav-count">{formatNumber(projects.length)}</span></a></li>
        <li><a href={routeHref({ name: "import" })} className={route.name === "import" ? "active" : ""} aria-label="Create project" title="Create project" aria-current={route.name === "import" ? "page" : undefined}><Icon name="plus" /><span>Create project</span></a></li>
      </ul></div>
      {project ? ["Project", "Data", "Models"].map((group) => <div className="sidebar-group" key={group}><span className="sidebar-heading">{group}</span><ul className="sidebar-nav">{SECTIONS.filter((section) => section.group === group).map((section) => {
        const count = loadedProject !== project ? null : section.name === "datasets" ? datasetCount : section.name === "runs" ? runs.length : null;
        return <li key={section.name}><a href={routeHref({ name: section.name, project })} className={active === section.name ? "active" : ""} aria-label={section.label} title={section.label} aria-current={active === section.name ? "page" : undefined}><Icon name={section.icon} /><span>{section.label}</span>{count !== null && count > 0 && <span className="nav-count">{formatNumber(count)}</span>}</a></li>;
      })}</ul></div>) : <>
        {pinned.length > 0 && <div className="sidebar-group"><span className="sidebar-heading">Pinned projects</span>{projectLinks(pinned)}</div>}
        {(recent.length > 0 || projects.some((p) => !pinned.includes(p.name))) && <div className="sidebar-group"><span className="sidebar-heading">{recent.length ? "Recently opened" : "Your projects"}</span>{projectLinks(recent.length ? recent : projects.map((p) => p.name).filter((name) => !pinned.includes(name)))}</div>}
      </>}
      <div className="sidebar-spacer" />
      <div className="sidebar-footer"><a className="sidebar-help" href="https://granum.app/docs/course/start" target="_blank" rel="noreferrer" aria-label="Open the Granum guide" title="Documentation"><Icon name="file" size={16} /><span>Documentation</span><Icon name="open" size={13} /></a>
        {licence && licence.state !== "unrestricted" && <a className={`sidebar-licence${route.name === "licence" ? " active" : ""}${licence.mode !== "full" ? " off" : ""}`} href={routeHref({ name: "licence" })}><Icon name="shield" size={15} /><span>Licence</span><span className="sidebar-licence-state">{licence.mode !== "full" ? "Read-only" : licence.days_left != null ? `${Math.floor(licence.days_left)} d left` : "Active"}</span></a>}
        <div className="sidebar-status" title={health ? `Connected service, v${health.version}\nScan roots:\n${health.roots.join("\n")}\n\nImport folders:\n${health.data_roots.join("\n")}` : "Connecting to the local service"}><span className={`status-dot${health ? " ok" : ""}`} /><span>{health ? "Service connected" : "Connecting…"}</span>{health && <span className="sidebar-version">v{health.version}</span>}</div>
      </div>
    </div>
  </nav>;
}
