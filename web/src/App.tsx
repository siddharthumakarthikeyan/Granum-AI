import { useEffect } from "react";
import { EmptyState } from "./components/ui";
import { ImportPage } from "./importing/ImportPage";
import { SavedReportPage } from "./importing/SavedReportPage";
import { DatasetsPage } from "./pages/DatasetsPage";
import { HomePage } from "./pages/HomePage";
import { LearningPage } from "./pages/LearningPage";
import { RemovedPage } from "./pages/RemovedPage";
import { ProjectOverview } from "./pages/ProjectOverview";
import { RunsPage } from "./pages/RunsPage";
import { ReviewPage } from "./review/ReviewPage";
import { routeProject, useRoute } from "./router";
import { Sidebar } from "./shell/Sidebar";
import { Workspace } from "./shell/Workspace";
import { useStore } from "./store/store";

export default function App() {
  const route = useRoute();
  const boot = useStore((s) => s.boot);
  const error = useStore((s) => s.error);
  const serviceOk = useStore((s) => s.serviceOk);
  const project = useStore((s) => s.project);
  const loadedProject = useStore((s) => s.loadedProject);
  const openProject = useStore((s) => s.openProject);
  const refreshProject = useStore((s) => s.refreshProject);

  const undoStack = useStore((s) => s.undoStack);

  const routedProject = routeProject(route);
  const inWorkspace = route.name === "table" || route.name === "run";

  useEffect(() => {
    void boot();
  }, [boot]);

  useEffect(() => {
    if (!routedProject) return;
    if (routedProject !== project || routedProject !== loadedProject) void openProject(routedProject);
    // Revisiting a project page refreshes its lists in the background.
    else if (route.name !== "table" && route.name !== "run") void refreshProject();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [routedProject, route.name]);

  useEffect(() => {
    const titles: Record<string, string> = {
      home: "Projects", overview: routedProject ?? "", datasets: "Datasets", runs: "Runs", review: "Review",
      import: "Import", report: "Import report", table: "Dataset", run: "Run", learning: "How images were learned", removed: "Removed images",
    };
    document.title = `${titles[route.name]}${routedProject && route.name !== "overview" ? ` - ${routedProject}` : ""} - Granum`;
  }, [route, routedProject]);

  // Uncommitted edits live only in this tab; warn before they are lost.
  useEffect(() => {
    if (undoStack.length === 0) return;
    const warn = (event: BeforeUnloadEvent) => {
      event.preventDefault();
      event.returnValue = "";
    };
    window.addEventListener("beforeunload", warn);
    return () => window.removeEventListener("beforeunload", warn);
  }, [undoStack.length]);

  if (!serviceOk) {
    return (
      <div className="app-offline">
        <EmptyState title="The Granum service is not reachable">
          <p>{error}</p>
          <p>Start it on this machine, then reload this page:</p>
          <pre className="code-block">granum service</pre>
        </EmptyState>
      </div>
    );
  }

  return (
    <div className={`app${inWorkspace ? " app-workspace" : ""}`}>
      <Sidebar route={route} />
      <main className="app-main">
        {route.name === "home" && <HomePage />}
        {route.name === "overview" && <ProjectOverview project={route.project} />}
        {route.name === "datasets" && <DatasetsPage project={route.project} />}
        {route.name === "runs" && <RunsPage project={route.project} />}
        {route.name === "review" && <ReviewPage project={route.project} dataset={route.dataset} />}
        {route.name === "import" && <ImportPage project={route.project} />}
        {route.name === "removed" && <RemovedPage project={route.project} dataset={route.dataset} />}
        {route.name === "learning" && <LearningPage project={route.project} url={route.url} />}
        {route.name === "report" && <SavedReportPage project={route.project} id={route.id} />}
        {(route.name === "table" || route.name === "run") && (
          <Workspace key={route.name} kind={route.name} project={route.project} url={route.url} />
        )}
      </main>
    </div>
  );
}
