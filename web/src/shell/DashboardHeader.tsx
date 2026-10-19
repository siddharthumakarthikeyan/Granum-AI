import { Icon } from "../components/ui";
import { routeHref, routeProject, type Route } from "../router";
import { openWorkspaceSearch, workspaceSearchShortcut } from "./preferences";
const LABELS: Record<Route["name"], string> = {
  home: "Projects", licence: "Licence", overview: "Overview", datasets: "Datasets", runs: "Runs",
  images: "Images", import: "Import data", report: "Import report", table: "Dataset", run: "Run",
  learning: "Learning dynamics", findings: "Findings", evaluation: "Evaluation", health: "Data health",
  compare: "Compare runs", removed: "Removed images",
};
export function DashboardHeader({ route }: { route: Route }) {
  const project = routeProject(route);
  return <header className="dashboard-topbar">
    <nav className="dashboard-breadcrumb" aria-label="Breadcrumb"><a className="breadcrumb-home" href={routeHref({ name: "home" })}><Icon name="layers" size={15} /><span>Workspace</span></a><span className="breadcrumb-divider">/</span>
      {project && <><a className="breadcrumb-project" href={routeHref({ name: "overview", project })} title={project}>{project}</a><span className="breadcrumb-divider">/</span></>}
      <span aria-current="page">{LABELS[route.name]}</span>
    </nav>
    <button className="topbar-search" onClick={openWorkspaceSearch} aria-label="Search workspace" title="Search workspace (Ctrl or Command K)"><Icon name="search" size={15} /><span>Search anything…</span><kbd>{workspaceSearchShortcut()}</kbd></button>
  </header>;
}
