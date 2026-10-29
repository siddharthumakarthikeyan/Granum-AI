import { useEffect, useId, useMemo, useRef, useState } from "react";
import { Icon } from "../components/ui";
import { navigate, routeProject, type Route } from "../router";
import { useStore } from "../store/store";
import { usePinnedProjects } from "./preferences";

interface Command { id: string; label: string; detail: string; icon: string; route: Route }

export function CommandPalette({ route }: { route: Route }) {
  const projects = useStore((state) => state.projects);
  const pinned = usePinnedProjects();
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const [active, setActive] = useState(0);
  const dialog = useRef<HTMLDialogElement>(null);
  const input = useRef<HTMLInputElement>(null);
  const previousFocus = useRef<HTMLElement | null>(null);
  const id = useId();
  const project = routeProject(route);
  const commands = useMemo<Command[]>(() => [
    { id: "home", label: "All projects", detail: "Workspace", icon: "folder", route: { name: "home" } },
    { id: "new", label: "Create project", detail: "Import data", icon: "plus", route: { name: "import" } },
    ...(project ? [
      { id: "overview", label: "Project overview", detail: project, icon: "overview", route: { name: "overview", project } as Route },
      { id: "review", label: "Review images", detail: project, icon: "review", route: { name: "images", project, review: true } as Route },
      { id: "datasets", label: "Dataset versions", detail: project, icon: "datasets", route: { name: "datasets", project } as Route },
      { id: "runs", label: "Training runs", detail: project, icon: "runs", route: { name: "runs", project } as Route },
      { id: "health", label: "Data health", detail: project, icon: "shield", route: { name: "health", project } as Route },
    ] : []),
    ...[...projects].sort((a, b) => Number(pinned.includes(b.name)) - Number(pinned.includes(a.name)) || a.name.localeCompare(b.name))
      .map((item) => ({ id: `project-${item.name}`, label: item.name, detail: pinned.includes(item.name) ? "Pinned project" : "Project", icon: pinned.includes(item.name) ? "star" : "folder", route: { name: "overview", project: item.name } as Route })),
  ], [projects, project, pinned]);
  const results = commands.filter((command) => `${command.label} ${command.detail}`.toLowerCase().includes(query.trim().toLowerCase())).slice(0, 30);
  const selected = results[Math.min(active, Math.max(0, results.length - 1))];

  useEffect(() => {
    const show = () => {
      if (document.querySelector('[aria-modal="true"], dialog[open]')) return;
      previousFocus.current = document.activeElement as HTMLElement;
      setQuery(""); setActive(0); setOpen(true);
    };
    const shortcut = (event: KeyboardEvent) => {
      if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "k") { event.preventDefault(); show(); }
    };
    window.addEventListener("granum:open-search", show);
    window.addEventListener("keydown", shortcut);
    return () => { window.removeEventListener("granum:open-search", show); window.removeEventListener("keydown", shortcut); };
  }, []);
  useEffect(() => {
    if (!open) return;
    dialog.current?.showModal(); input.current?.focus();
    return () => previousFocus.current?.focus();
  }, [open]);
  useEffect(() => { if (open && selected) document.getElementById(`${id}-${encodeURIComponent(selected.id)}`)?.scrollIntoView({ block: "nearest" }); }, [open, selected?.id, id]);

  const choose = (command: Command) => { setOpen(false); navigate(command.route); };
  if (!open) return null;
  return (
    <dialog ref={dialog} className="workspace-command" aria-label="Search workspace" onCancel={() => setOpen(false)} onClose={() => setOpen(false)}
      onClick={(event) => { if (event.target === event.currentTarget) setOpen(false); }}>
      <div className="command-surface">
        <div className="command-input"><Icon name="search" size={21} />
          <input ref={input} role="combobox" aria-label="Search projects and actions" aria-expanded="true" aria-controls={`${id}-results`}
            aria-activedescendant={selected ? `${id}-${encodeURIComponent(selected.id)}` : undefined} aria-autocomplete="list" value={query}
            placeholder="Search projects or jump to…" onChange={(event) => { setQuery(event.target.value); setActive(0); }} onKeyDown={(event) => {
              if (event.key === "ArrowDown" || event.key === "ArrowUp") {
                event.preventDefault(); setActive((value) => results.length ? (value + (event.key === "ArrowDown" ? 1 : -1) + results.length) % results.length : 0);
              }
              if (event.key === "Enter" && selected) { event.preventDefault(); choose(selected); }
            }} />
          <button className="command-escape" onClick={() => setOpen(false)} aria-label="Close workspace search">Esc</button>
        </div>
        <div className="command-label">{query ? "Search results" : "Quick navigation"}</div>
        <div className="command-results" id={`${id}-results`} role="listbox" aria-label="Projects and actions">
          {results.map((command, index) => <button key={command.id} id={`${id}-${encodeURIComponent(command.id)}`} role="option" aria-selected={selected?.id === command.id}
            tabIndex={-1} onPointerMove={() => setActive(index)} onClick={() => choose(command)}>
            <Icon name={command.icon} size={18} /><span>{command.label}<small>{command.detail}</small></span><span className="command-enter" aria-hidden="true">↵</span>
          </button>)}
          {results.length === 0 && <p className="command-no-results">No projects or actions match “{query}”.</p>}
        </div>
        <div className="command-footer"><span><kbd>↑</kbd><kbd>↓</kbd> to navigate</span><span><kbd>↵</kbd> to open</span><span>Granum workspace</span></div>
      </div>
    </dialog>
  );
}
