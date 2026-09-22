import { useEffect, useState } from "react";
import { EmptyState, Icon } from "./components/ui";
import { ComparePage } from "./compare/ComparePage";
import { FindingsPage } from "./findings/FindingsPage";
import { ImportPage } from "./importing/ImportPage";
import { SavedReportPage } from "./importing/SavedReportPage";
import { DatasetsPage } from "./pages/DatasetsPage";
import { HomePage } from "./pages/HomePage";
import { LicencePage } from "./pages/LicencePage";
import { EvaluationPage } from "./runs/EvaluationPage";
import { HealthPage } from "./pages/HealthPage";
import { ImagesPage } from "./images/ImagesPage";
import { LearningPage } from "./pages/LearningPage";
import { RemovedPage } from "./pages/RemovedPage";
import { ProjectOverview } from "./pages/ProjectOverview";
import { RunsPage } from "./pages/RunsPage";
import { routeHref, routeProject, useRoute } from "./router";
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
  const licence = useStore((s) => s.licence);
  const refreshLicence = useStore((s) => s.refreshLicence);
  const refreshProject = useStore((s) => s.refreshProject);

  const undoStack = useStore((s) => s.undoStack);

  const routedProject = routeProject(route);
  const inWorkspace = route.name === "table" || route.name === "run";

  useEffect(() => {
    void boot();
  }, [boot]);

  // A change refused by the licence is announced above everything, full-screen views included.
  const [refused, setRefused] = useState<string | null>(null);
  useEffect(() => {
    let timer = 0;
    const onRefused = (event: Event) => {
      const detail = (event as CustomEvent<string>).detail;
      if (!detail) return;
      setRefused(detail);
      window.clearTimeout(timer);
      timer = window.setTimeout(() => setRefused(null), 6000);
    };
    window.addEventListener("granum:licence", onRefused);
    return () => {
      window.removeEventListener("granum:licence", onRefused);
      window.clearTimeout(timer);
    };
  }, []);

  // The licence can change while a page is open (a key installed, a plan ending, the
  // service restarting): check again every minute and whenever the window comes back.
  useEffect(() => {
    const check = () => {
      if (document.visibilityState === "visible") void refreshLicence();
    };
    const timer = window.setInterval(check, 60 * 1000);
    window.addEventListener("focus", check);
    document.addEventListener("visibilitychange", check);
    return () => {
      window.clearInterval(timer);
      window.removeEventListener("focus", check);
      document.removeEventListener("visibilitychange", check);
    };
  }, [refreshLicence]);

  useEffect(() => {
    if (!routedProject) return;
    if (routedProject !== project || routedProject !== loadedProject) void openProject(routedProject);
    // Revisiting a project page refreshes its lists in the background.
    else if (route.name !== "table" && route.name !== "run") void refreshProject();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [routedProject, route.name]);

  useEffect(() => {
    const titles: Record<string, string> = {
      home: "Projects", licence: "Licence", overview: routedProject ?? "", datasets: "Datasets", runs: "Runs", images: "Images",
      import: "Import", report: "Import report", table: "Dataset", run: "Run", learning: "How images were learned", findings: "Findings", evaluation: "Evaluation", health: "Health", compare: "Compare runs", removed: "Removed images",
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
        {licence?.mode === "read_only" && route.name !== "licence" && (
          <div className="licence-banner" role="status">
            <Icon name="lock" size={14} />
            <span><strong>Read-only.</strong> {licence.reason}</span>
            <a href={routeHref({ name: "licence" })}>Licence</a>
          </div>
        )}
        {route.name === "home" && <HomePage />}
        {route.name === "licence" && <LicencePage />}
        {route.name === "overview" && <ProjectOverview project={route.project} />}
        {route.name === "health" && <HealthPage project={route.project} dataset={route.dataset} />}
        {route.name === "evaluation" && <EvaluationPage project={route.project} url={route.url} />}
        {route.name === "images" && <ImagesPage project={route.project} dataset={route.dataset} review={Boolean(route.review)} edit={Boolean(route.edit)} similar={Boolean(route.similar)} patches={Boolean(route.patches)} stats={Boolean(route.stats)} like={route.like} open={route.open} />}
        {route.name === "datasets" && <DatasetsPage project={route.project} />}
        {route.name === "runs" && <RunsPage project={route.project} />}
        {route.name === "import" && <ImportPage project={route.project} example={route.example} />}
        {route.name === "removed" && <RemovedPage project={route.project} dataset={route.dataset} />}
        {route.name === "learning" && <LearningPage project={route.project} url={route.url} />}
        {route.name === "findings" && <FindingsPage project={route.project} url={route.url} />}
        {route.name === "compare" && <ComparePage project={route.project} baseline={route.baseline} candidate={route.candidate} split={route.split} />}
        {route.name === "report" && <SavedReportPage project={route.project} id={route.id} />}
        {(route.name === "table" || route.name === "run") && (
          <Workspace key={route.name} kind={route.name} project={route.project} url={route.url} />
        )}
      </main>
      {refused && (
        <div className="licence-refused" role="alert">
          <Icon name="lock" size={15} />
          <span>{refused}</span>
          <a href={routeHref({ name: "licence" })} onClick={() => setRefused(null)}>Licence</a>
          <button className="icon-button" aria-label="Dismiss" onClick={() => setRefused(null)}><Icon name="close" size={13} /></button>
        </div>
      )}
    </div>
  );
}
