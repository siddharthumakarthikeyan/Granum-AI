/** Left navigation: which project, which part of it, and whether the service is healthy. */

import { Icon, Mark, formatNumber } from "../components/ui";
import { navigate, routeHref, routeProject, type Route } from "../router";
import { useStore } from "../store/store";

const SECTIONS = [
  { name: "overview", label: "Overview", icon: "overview" },
  { name: "datasets", label: "Datasets", icon: "datasets" },
  { name: "review", label: "Review", icon: "review" },
  { name: "runs", label: "Runs", icon: "runs" },
] as const;

function sectionOf(route: Route): string {
  if (route.name === "table" || route.name === "report") return "datasets";
  if (route.name === "run" || route.name === "learning") return "runs";
  if (route.name === "removed") return "datasets";
  return route.name;
}

export function Sidebar({ route }: { route: Route }) {
  const projects = useStore((s) => s.projects);
  const health = useStore((s) => s.health);
  const tables = useStore((s) => s.tables);
  const runs = useStore((s) => s.runs);
  const project = routeProject(route);
  const active = sectionOf(route);
  const datasetCount = new Set(tables.map((t) => t.dataset_name)).size;

  return (
    <nav className="sidebar" aria-label="Main">
      <a className="sidebar-brand" href="#/">
        <Mark size={22} />
        <span>GRANUM</span>
      </a>

      <div className="sidebar-project">
        <div className="select-wrap">
          <select
            id="project-switcher"
            aria-label="Project"
            value={project ?? ""}
            onChange={(event) => {
              const name = event.target.value;
              navigate(name ? { name: "overview", project: name } : { name: "home" });
            }}
          >
            <option value="">All projects</option>
            {projects.map((p) => (
              <option key={p.name} value={p.name}>{p.name}</option>
            ))}
          </select>
        </div>
      </div>

      {project && (
        <div className="sidebar-group">
          <ul className="sidebar-nav">
            {SECTIONS.map((section) => {
              const count = section.name === "datasets" ? datasetCount : section.name === "runs" ? runs.length : null;
              return (
                <li key={section.name}>
                  <a
                    href={routeHref({ name: section.name, project })}
                    className={active === section.name ? "active" : ""}
                    aria-current={active === section.name ? "page" : undefined}
                  >
                    <Icon name={section.icon} />
                    <span>{section.label}</span>
                    {count !== null && count > 0 && <span className="nav-count">{formatNumber(count)}</span>}
                  </a>
                </li>
              );
            })}
          </ul>
        </div>
      )}

      <div className="sidebar-group">
        <ul className="sidebar-nav">
          <li>
            <a
              className={route.name === "import" ? "active" : ""}
              href={routeHref({ name: "import", project: project ?? undefined })}
            >
              <Icon name="import" />
              <span>Import data</span>
            </a>
          </li>
        </ul>
      </div>

      <div className="sidebar-spacer" />

      <div className="sidebar-status" title={health ? `Scan roots:\n${health.roots.join("\n")}\n\nImport folders:\n${health.data_roots.join("\n")}` : undefined}>
        <span className={`status-dot${health ? " ok" : ""}`} />
        <span>{health ? `Local service, v${health.version}` : "Connecting"}</span>
      </div>
    </nav>
  );
}
