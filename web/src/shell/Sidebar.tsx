/** Left navigation: which project, which part of it, and whether the service is healthy. */

import { useEffect, useState } from "react";
import { api } from "../api/client";
import { Icon, Mark, formatNumber } from "../components/ui";
import { navigate, routeHref, routeProject, type Route } from "../router";
import { useStore } from "../store/store";

const SECTIONS = [
  { name: "overview", label: "Overview", icon: "overview" },
  { name: "images", label: "Images", icon: "images" },
  { name: "health", label: "Health", icon: "shield" },
  { name: "datasets", label: "Datasets", icon: "datasets" },
  { name: "runs", label: "Runs", icon: "runs" },
  { name: "evaluation", label: "Evaluation", icon: "target" },
  { name: "findings", label: "Findings", icon: "findings" },
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
  const project = routeProject(route);
  const active = sectionOf(route);
  // Datasets are the dataset versions made for training; creating one refreshes the tables.
  const [datasetCount, setDatasetCount] = useState<number | null>(null);
  useEffect(() => {
    if (!project) return;
    let alive = true;
    api.releases(project).then(({ releases }) => alive && setDatasetCount(releases.length)).catch(() => undefined);
    return () => {
      alive = false;
    };
  }, [project, tables]);

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
              href={routeHref({ name: "import" })}
            >
              <Icon name="plus" />
              <span>Create project</span>
            </a>
          </li>
        </ul>
      </div>

      <div className="sidebar-spacer" />

      <a className={`sidebar-licence${route.name === "licence" ? " active" : ""}${licence && licence.mode !== "full" ? " off" : ""}`} href={routeHref({ name: "licence" })}>
        <Icon name="shield" size={15} />
        <span>Licence</span>
        <span className="sidebar-licence-state">
          {!licence ? "" : licence.mode !== "full" ? "Read-only"
            : licence.state === "unrestricted" ? "" : licence.days_left != null ? `${Math.floor(licence.days_left)} d left` : "Active"}
        </span>
      </a>

      <div className="sidebar-status" title={health ? `Scan roots:\n${health.roots.join("\n")}\n\nImport folders:\n${health.data_roots.join("\n")}` : undefined}>
        <span className={`status-dot${health ? " ok" : ""}`} />
        <span>{health ? `Local service, v${health.version}` : "Connecting"}</span>
      </div>
    </nav>
  );
}
