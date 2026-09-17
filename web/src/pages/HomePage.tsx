/** Every project on this machine, and the way in for someone who has none yet. */

import { useState } from "react";
import type { ProjectSummary } from "../api/types";
import { DeleteProjectDialog } from "../components/DeleteProjectDialog";
import { RenameProjectDialog } from "../components/RenameProjectDialog";
import { EmptyState, Icon, PageHeader, formatNumber } from "../components/ui";
import { navigate, routeHref } from "../router";
import { useStore } from "../store/store";

export function HomePage() {
  const projects = useStore((s) => s.projects);
  const health = useStore((s) => s.health);
  const [deleting, setDeleting] = useState<ProjectSummary | null>(null);
  const [renaming, setRenaming] = useState<string | null>(null);

  if (projects.length === 0) {
    return (
      <div className="page page-narrow">
        <EmptyState
          title="No projects"
          action={<a className="button primary" href={routeHref({ name: "import" })}><Icon name="import" />Import a COCO dataset</a>}
        >
          <p>Import annotations and images to create a project, or log one from a training script with the Granum SDK. Data stays on this machine.</p>
        </EmptyState>
      </div>
    );
  }

  return (
    <div className="page">
      <PageHeader
        title="Projects"
        subtitle={health?.roots[0] ? <span className="mono">{health.roots[0]}</span> : undefined}
        actions={<a className="button" href={routeHref({ name: "import" })}><Icon name="import" />Import</a>}
      />
      <div className="data-table-wrap">
        <table className="data-table">
          <thead>
            <tr>
              <th>Project</th>
              <th className="num">Versions</th>
              <th className="num">Runs</th>
              <th className="actions" aria-label="Actions" />
            </tr>
          </thead>
          <tbody>
            {projects.map((project) => (
              <tr key={project.name} className="clickable" onClick={() => navigate({ name: "overview", project: project.name })}>
                <td><a className="cell-title" href={routeHref({ name: "overview", project: project.name })}>{project.name}</a></td>
                <td className="num">{formatNumber(project.tables)}</td>
                <td className="num">{formatNumber(project.runs)}</td>
                <td className="actions">
                  <button
                    className="icon-button row-delete row-rename"
                    title={`Rename ${project.name}`}
                    aria-label={`Rename ${project.name}`}
                    onClick={(e) => {
                      e.stopPropagation();
                      setRenaming(project.name);
                    }}
                  >
                    <Icon name="pencil" size={15} />
                  </button>
                  <button
                    className="icon-button row-delete"
                    title={`Delete ${project.name}`}
                    aria-label={`Delete ${project.name}`}
                    onClick={(e) => {
                      e.stopPropagation();
                      setDeleting(project);
                    }}
                  >
                    <Icon name="trash" size={15} />
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {deleting && <DeleteProjectDialog project={deleting} onClose={() => setDeleting(null)} />}
      {renaming && <RenameProjectDialog project={renaming} onClose={() => setRenaming(null)} />}
    </div>
  );
}
