/** Projects, Tables and Runs -- the three navigation views.
 *
 * Each row is one object. Double-click opens it, which is the convention the whole
 * dashboard follows: single click selects, double click opens.
 */

import type { ObjectEntry } from "../api/types";
import { useStore } from "../store/store";

function formatDate(value: string): string {
  if (!value) return "";
  return value.replace("T", " ").slice(0, 16);
}

export function ProjectsView() {
  const projects = useStore((s) => s.projects);
  const openProject = useStore((s) => s.openProject);

  if (projects.length === 0) {
    return (
      <div className="empty">
        <div className="title">No projects indexed</div>
        <div>Create a Table or Run, then reindex.</div>
        <code>granum service</code>
      </div>
    );
  }

  return (
    <table className="grid">
      <thead>
        <tr>
          <th>Project</th>
          <th style={{ width: 90 }}>Tables</th>
          <th style={{ width: 90 }}>Runs</th>
        </tr>
      </thead>
      <tbody>
        {projects.map((project) => (
          <tr
            key={project.name}
            className="clickable"
            onDoubleClick={() => void openProject(project.name)}
          >
            <td>{project.name}</td>
            <td className="num">{project.tables}</td>
            <td className="num">{project.runs}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

/** Depth of a Table in its revision chain, drawn as dots in the lineage column. */
function useDepths(entries: ObjectEntry[]): Map<string, number> {
  const byUrl = new Map(entries.map((e) => [e.url, e]));
  const depths = new Map<string, number>();
  const resolve = (entry: ObjectEntry, guard = 0): number => {
    if (depths.has(entry.url)) return depths.get(entry.url)!;
    if (guard > 32 || entry.parents.length === 0) {
      depths.set(entry.url, 0);
      return 0;
    }
    const parent = byUrl.get(entry.parents[0]!);
    const depth = parent ? resolve(parent, guard + 1) + 1 : 0;
    depths.set(entry.url, depth);
    return depth;
  };
  for (const entry of entries) resolve(entry);
  return depths;
}

export function TablesView() {
  const tables = useStore((s) => s.tables);
  const openTable = useStore((s) => s.openTable);
  const depths = useDepths(tables);

  if (tables.length === 0) {
    return <div className="empty"><div className="title">No tables in this project</div></div>;
  }

  return (
    <table className="grid">
      <thead>
        <tr>
          <th>Dataset</th>
          <th>Table</th>
          <th style={{ width: 110 }}>Lineage</th>
          <th style={{ width: 90 }}>Rows</th>
          <th style={{ width: 150 }}>Created</th>
          <th>Description</th>
        </tr>
      </thead>
      <tbody>
        {tables.map((table) => {
          const depth = depths.get(table.url) ?? 0;
          return (
            <tr
              key={table.url}
              className="clickable"
              onDoubleClick={() => void openTable(table.url, table.name)}
              title={table.url}
            >
              <td className="muted">{table.dataset_name}</td>
              <td>{table.name}</td>
              <td>
                <span className="lineage">
                  {Array.from({ length: depth }).map((_, i) => (
                    <span key={i} className="edge" />
                  ))}
                  <span className={`node${depth === 0 ? " root" : ""}`} />
                  {depth > 0 && <span className="muted">rev {depth}</span>}
                </span>
              </td>
              <td className="num">{table.row_count.toLocaleString()}</td>
              <td className="muted">{formatDate(table.created)}</td>
              <td className="muted">{table.description}</td>
            </tr>
          );
        })}
      </tbody>
    </table>
  );
}

export function RunsView() {
  const runs = useStore((s) => s.runs);
  const openRun = useStore((s) => s.openRun);

  if (runs.length === 0) {
    return (
      <div className="empty">
        <div className="title">No runs in this project</div>
        <div>Collect metrics from a training script, then reindex.</div>
      </div>
    );
  }

  // Parameters that differ between runs, and every logged scalar: the columns that make
  // "which run was better, and what changed" answerable without opening each one.
  const parameterKeys = [...new Set(runs.flatMap((r) => Object.keys(r.parameters ?? {})))].filter(
    (key) => new Set(runs.map((r) => JSON.stringify(r.parameters?.[key]))).size > 1,
  );
  const metricKeys = [...new Set(runs.flatMap((r) => Object.keys(r.last_metrics ?? {})))].filter(
    (key) => key !== "epoch" && runs.some((r) => typeof r.last_metrics?.[key] === "number"),
  );
  const format = (value: unknown) =>
    typeof value === "number" && !Number.isInteger(value) ? value.toFixed(4) : value === undefined ? "" : String(value);

  return (
    <table className="grid">
      <thead>
        <tr>
          <th>Run</th>
          {parameterKeys.map((key) => <th key={`p-${key}`} title="hyperparameter">{key}</th>)}
          {metricKeys.map((key) => <th key={`m-${key}`} title="last logged value">{key}</th>)}
          <th style={{ width: 150 }}>Created</th>
          <th>Description</th>
        </tr>
      </thead>
      <tbody>
        {runs.map((run) => (
          <tr
            key={run.url}
            className="clickable"
            onDoubleClick={() => void openRun(run.url, run.name)}
            title={run.url}
          >
            <td>{run.name}</td>
            {parameterKeys.map((key) => <td key={`p-${key}`} className="muted">{format(run.parameters?.[key])}</td>)}
            {metricKeys.map((key) => <td key={`m-${key}`} className="num">{format(run.last_metrics?.[key])}</td>)}
            <td className="muted">{formatDate(run.created)}</td>
            <td className="muted">{run.description}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}
