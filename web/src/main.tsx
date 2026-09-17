import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import App from "./App";
import { useStore } from "./store/store";
import "@fontsource/ibm-plex-sans/400.css";
import "@fontsource/ibm-plex-sans/500.css";
import "@fontsource/ibm-plex-sans/600.css";
import "@fontsource/ibm-plex-sans-condensed/500.css";
import "@fontsource/ibm-plex-sans-condensed/600.css";
import "@fontsource/ibm-plex-mono/400.css";
import "@fontsource/ibm-plex-mono/500.css";
import "./styles/app.css";
import "./styles/product.css";

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <App />
  </StrictMode>,
);

const bench = new URLSearchParams(window.location.search).get("bench");
if (import.meta.env.DEV && bench) {
  // After App's own boot has settled, so the injected rows are not overwritten.
  window.setTimeout(() => {
    void import("./bench").then((m) => m.loadBench(Number(bench) || 1_000_000));
  }, 300);
}

if (import.meta.env.DEV) {
  // Handle for scripted end-to-end checks and console debugging. Not in production builds.
  (window as unknown as { __granumStore: typeof useStore }).__granumStore = useStore;
}
