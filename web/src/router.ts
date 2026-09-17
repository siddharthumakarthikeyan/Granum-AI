/** Hash routes, so every screen has an address: reload, back and a pasted link all work.
 *
 * The hash keeps the dashboard a set of static files the service can serve from any
 * path, with no server-side route table to keep in step.
 */

import { useSyncExternalStore } from "react";

export type Route =
  | { name: "home" }
  | { name: "overview"; project: string }
  | { name: "datasets"; project: string }
  | { name: "runs"; project: string }
  | { name: "review"; project: string; dataset?: string }
  | { name: "import"; project?: string }
  | { name: "report"; project: string; id: string }
  | { name: "table"; project: string; url: string }
  | { name: "run"; project: string; url: string }
  | { name: "learning"; project: string; url: string }
  | { name: "removed"; project: string; dataset: string };

export function parseRoute(hash: string): Route {
  const [path = "", query = ""] = hash.replace(/^#/, "").split("?");
  const parts = path.split("/").filter(Boolean).map(decodeURIComponent);
  const params = new URLSearchParams(query);
  if (parts[0] === "import") {
    const project = params.get("project");
    return project ? { name: "import", project } : { name: "import" };
  }
  if (parts[0] === "p" && parts[1]) {
    const project = parts[1];
    switch (parts[2]) {
      case "datasets":
        return { name: "datasets", project };
      case "runs":
        return { name: "runs", project };
      case "review":
        return params.get("dataset") ? { name: "review", project, dataset: params.get("dataset")! } : { name: "review", project };
      case "imports":
        if (parts[3]) return { name: "report", project, id: parts[3] };
        return { name: "overview", project };
      case "table":
        if (params.get("url")) return { name: "table", project, url: params.get("url")! };
        return { name: "datasets", project };
      case "run":
        if (params.get("url")) return { name: "run", project, url: params.get("url")! };
        return { name: "runs", project };
      case "removed":
        if (params.get("dataset")) return { name: "removed", project, dataset: params.get("dataset")! };
        return { name: "datasets", project };
      case "learning":
        if (params.get("url")) return { name: "learning", project, url: params.get("url")! };
        return { name: "runs", project };
      default:
        return { name: "overview", project };
    }
  }
  return { name: "home" };
}

export function routeHref(route: Route): string {
  const p = (project: string) => `#/p/${encodeURIComponent(project)}`;
  switch (route.name) {
    case "home":
      return "#/";
    case "overview":
      return p(route.project);
    case "datasets":
      return `${p(route.project)}/datasets`;
    case "runs":
      return `${p(route.project)}/runs`;
    case "review":
      return `${p(route.project)}/review${route.dataset ? `?dataset=${encodeURIComponent(route.dataset)}` : ""}`;
    case "import":
      return route.project ? `#/import?project=${encodeURIComponent(route.project)}` : "#/import";
    case "report":
      return `${p(route.project)}/imports/${encodeURIComponent(route.id)}`;
    case "table":
      return `${p(route.project)}/table?url=${encodeURIComponent(route.url)}`;
    case "run":
      return `${p(route.project)}/run?url=${encodeURIComponent(route.url)}`;
    case "removed":
      return `${p(route.project)}/removed?dataset=${encodeURIComponent(route.dataset)}`;
    case "learning":
      return `${p(route.project)}/learning?url=${encodeURIComponent(route.url)}`;
  }
}

export function navigate(route: Route, { replace = false } = {}): void {
  const href = routeHref(route);
  if (window.location.hash === href) return;
  if (replace) window.history.replaceState(null, "", href);
  else window.location.hash = href;
  if (replace) window.dispatchEvent(new HashChangeEvent("hashchange"));
}

function subscribe(callback: () => void): () => void {
  window.addEventListener("hashchange", callback);
  return () => window.removeEventListener("hashchange", callback);
}

let cachedHash: string | null = null;
let cachedRoute: Route = { name: "home" };

function snapshot(): Route {
  const hash = window.location.hash;
  if (hash !== cachedHash) {
    cachedHash = hash;
    cachedRoute = parseRoute(hash);
  }
  return cachedRoute;
}

export function useRoute(): Route {
  return useSyncExternalStore(subscribe, snapshot, snapshot);
}

export function routeProject(route: Route): string | null {
  return "project" in route && route.project ? route.project : null;
}
