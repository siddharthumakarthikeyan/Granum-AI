/** The inspection workspace for one Table or Run: filters, charts and rows, plus provenance. */

import { useCallback, useEffect, useRef, useState } from "react";
import { ChartsPanel } from "../charts/ChartsPanel";
import { Splitter } from "../components/Splitter";
import { Icon, formatNumber, formatWhen, tail } from "../components/ui";
import { CommitDialog } from "../editing/CommitDialog";
import { EditBar } from "../editing/EditBar";
import { FiltersPanel } from "../panels/FiltersPanel";
import { RowsPanel } from "../panels/RowsPanel";
import { describeOp } from "../pages/datasets";
import { navigate, routeHref } from "../router";
import { draftKey, loadDraft, removeDraft, type Draft } from "../store/drafts";
import { loadReviews } from "../store/reviews";
import { useStore } from "../store/store";

export function Workspace({ kind, project, url }: { kind: "table" | "run"; project: string; url: string }) {
  const sourceUrl = useStore((s) => s.sourceUrl);
  const sourceKind = useStore((s) => s.sourceKind);
  const sourceName = useStore((s) => s.sourceName);
  const loading = useStore((s) => s.loading);
  const error = useStore((s) => s.error);
  const rows = useStore((s) => s.rows);
  const run = useStore((s) => s.run);
  const tables = useStore((s) => s.tables);
  const runs = useStore((s) => s.runs);
  const openTable = useStore((s) => s.openTable);
  const openRun = useStore((s) => s.openRun);
  const undoStack = useStore((s) => s.undoStack);
  const discardAll = useStore((s) => s.discardAll);
  const restoreEdits = useStore((s) => s.restoreEdits);
  const address = useStore((s) => s.address);
  const [draft, setDraft] = useState<Draft | null>(null);

  const [commitOpen, setCommitOpen] = useState(false);
  const [filtersWidth, setFiltersWidth] = useState(270);
  // The chart area (the image inspector by default) takes 70% of the height until the
  // divider is dragged; it is kept as a share so resizing the window keeps the balance.
  const [chartsShare, setChartsShare] = useState(0.7);
  const [mainColumn, setMainColumn] = useState<HTMLDivElement | null>(null);
  const [mainHeight, setMainHeight] = useState(0);
  useEffect(() => {
    if (!mainColumn) return;
    const observer = new ResizeObserver(([entry]) => entry && setMainHeight(entry.contentRect.height));
    observer.observe(mainColumn);
    return () => observer.disconnect();
  }, [mainColumn]);
  const chartsHeight = Math.max(160, Math.round((mainHeight || 800) * chartsShare));
  const chartCount = useStore((s) => s.charts.length);
  const [toast, setToast] = useState<string | null>(null);
  const requested = useRef<string | null>(null);
  const [helpOpen, setHelpOpen] = useState(false);
  const closeHelp = () => {
    setHelpOpen(false);
    try {
      window.localStorage.setItem("granum.workspace-help-seen", "1");
    } catch {
      // the guide simply shows again next time
    }
  };

  const showToast = useCallback((message: string) => {
    setToast(message);
    window.setTimeout(() => setToast(null), 2600);
  }, []);

  const selectAllRows = useStore((s) => s.selectAllRows);
  const clearSelection = useStore((s) => s.clearSelection);
  const moveCursor = useStore((s) => s.moveCursor);
  const clearFilters = useStore((s) => s.clearFilters);
  const undo = useStore((s) => s.undo);
  const redo = useStore((s) => s.redo);
  const toggleWeights = useStore((s) => s.toggleWeights);

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      const target = event.target as HTMLElement | null;
      if (target && /^(INPUT|TEXTAREA|SELECT)$/.test(target.tagName)) return;
      if ((event.ctrlKey || event.metaKey) && !event.altKey) {
        const key = event.key.toLowerCase();
        if (key === "z" && !event.shiftKey) {
          undo();
          event.preventDefault();
        } else if ((key === "z" && event.shiftKey) || key === "y") {
          redo();
          event.preventDefault();
        } else if (key === "s") {
          setCommitOpen(true);
          event.preventDefault();
        }
        return;
      }
      if (event.altKey) return;
      switch (event.key) {
        case "Escape":
          clearSelection();
          break;
        case "a":
        case "A":
          selectAllRows();
          event.preventDefault();
          break;
        case "d":
        case "D":
          clearFilters();
          showToast("Filters cleared");
          break;
        case "w":
        case "W": {
          const problem = toggleWeights([...useStore.getState().selection.rows]);
          if (problem) showToast(problem);
          break;
        }
        case "ArrowDown":
          moveCursor(1);
          event.preventDefault();
          break;
        case "ArrowUp":
          moveCursor(-1);
          event.preventDefault();
          break;
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [clearFilters, clearSelection, moveCursor, redo, selectAllRows, showToast, toggleWeights, undo]);

  // Route -> store: open what the address names, unless it is already open.
  useEffect(() => {
    if (url === sourceUrl && kind === sourceKind) {
      requested.current = url;
      return;
    }
    if (url === requested.current) return;
    if (undoStack.length > 0 && sourceUrl) {
      const leave = window.confirm(`Discard ${undoStack.length} uncommitted change${undoStack.length === 1 ? "" : "s"} to ${sourceName}?`);
      if (!leave) {
        navigate({ name: sourceKind === "run" ? "run" : "table", project, url: sourceUrl }, { replace: true });
        return;
      }
      discardAll();
    }
    requested.current = url;
    const entry = (kind === "table" ? tables : runs).find((e) => e.url === url);
    const name = entry?.name ?? tail(url);
    void (kind === "table" ? openTable(url, name) : openRun(url, name));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [kind, url]);

  // Store -> route: a commit reopens the new revision; keep the address pointing at it.
  useEffect(() => {
    if (!sourceUrl || sourceKind !== kind || sourceUrl === url || requested.current === sourceUrl) return;
    if (requested.current !== url) return;
    requested.current = sourceUrl;
    navigate({ name: kind, project, url: sourceUrl }, { replace: true });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sourceUrl]);

  const ready = sourceUrl === url && sourceKind === kind;

  // Show review decisions once the object and the project's table list are loaded.
  const tablesLoaded = tables.length > 0;
  useEffect(() => {
    if (ready && tablesLoaded) void loadReviews();
  }, [ready, url, tablesLoaded]);

  // Offer to recover edits left unsaved the last time this object was open.
  useEffect(() => {
    setDraft(null);
    if (!ready) return;
    let cancelled = false;
    void loadDraft(draftKey(kind, url)).then((found) => {
      if (!cancelled && found && useStore.getState().undoStack.length === 0) setDraft(found);
    });
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [ready, kind, url]);

  const draftStale = Boolean(
    draft && kind === "run" && JSON.stringify(draft.sources) !== JSON.stringify(address?.sources ?? []),
  );
  const draftCount = draft ? draft.batches.reduce((n, b) => n + b.changes.length, 0) : 0;
  const restoreDraft = () => {
    if (!draft) return;
    restoreEdits(draft.batches);
    setDraft(null);
    showToast(`Restored ${draftCount} unsaved change${draftCount === 1 ? "" : "s"}`);
  };
  const dropDraft = () => {
    if (!draft) return;
    void removeDraft(draft.key);
    setDraft(null);
  };
  const entry = (kind === "table" ? tables : runs).find((e) => e.url === url);
  const listHref = routeHref({ name: kind === "table" ? "datasets" : "runs", project });

  return (
    <div className="workspace-shell">
      <header className="workspace-header">
        <a className="back-link" href={listHref}>
          <Icon name="back" size={14} />
          {kind === "table" ? "Datasets" : "Runs"}
        </a>
        <div className="workspace-title">
          <h1>
            {kind === "table" && entry && <span className="muted">{entry.dataset_name} / </span>}
            {ready ? sourceName : entry?.name ?? tail(url)}
          </h1>
          <span className="workspace-meta muted">
            {kind === "table"
              ? `${describeOp(entry?.op)}${ready ? `, ${formatNumber(rows.length)} images` : ""}`
              : ready && run
                ? `${formatNumber(rows.length)} rows, one per image per epoch`
                : ""}
          </span>
        </div>
        <span className="spacer" />
        {kind === "run" && entry?.parameters?.tracks_learning === true && (
          <a className="button subtle" href={routeHref({ name: "learning", project, url })}>Sample dynamics</a>
        )}
        {loading && <span className="loading-note muted"><span className="spinner" />Loading</span>}
        <button className={`button subtle${helpOpen ? " on" : ""}`} onClick={() => (helpOpen ? closeHelp() : setHelpOpen(true))} aria-expanded={helpOpen}>
          <kbd>?</kbd> Shortcuts
        </button>
        {ready && <EditBar onCommit={() => setCommitOpen(true)} />}
      </header>

      {ready && draft && (
        <div className="draft-banner" role="alert">
          <Icon name="refresh" />
          <div className="draft-text">
            {draftStale ? (
              <>
                <span className="strong">You have {draftCount} unsaved changes from {formatWhen(draft.savedAt)}, but they can't be restored.</span>{" "}
                The data behind this run has changed since then.
              </>
            ) : (
              <>
                <span className="strong">You have {draftCount} unsaved change{draftCount === 1 ? "" : "s"} from {formatWhen(draft.savedAt)}.</span>{" "}
                They were kept in this browser when the page closed. Restore them to continue where you left off.
              </>
            )}
          </div>
          {!draftStale && <button className="button primary" onClick={restoreDraft}>Restore changes</button>}
          <button className="button subtle" onClick={dropDraft}>Discard them</button>
        </div>
      )}

      {helpOpen && (
        <section className="workspace-help" aria-label="Keyboard shortcuts">
          <dl className="shortcut-list">
            <div><dt>Click, Ctrl+click, Shift+click</dt><dd>Select, add, range</dd></div>
            <div><dt>↑ ↓</dt><dd>Move selection</dd></div>
            <div><dt>A / Esc</dt><dd>Select all / clear</dd></div>
            <div><dt>Double-click cell</dt><dd>Edit value</dd></div>
            <div><dt>W</dt><dd>Toggle weight</dd></div>
            <div><dt>Ctrl+Z / Ctrl+Shift+Z</dt><dd>Undo / redo</dd></div>
            <div><dt>Shift+click header</dt><dd>Sort</dd></div>
            <div><dt>D</dt><dd>Clear filters</dd></div>
          </dl>
          {kind === "run" && <p className="faint small workspace-help-note">One row per image per epoch; sort by loss or F1 to find hard samples.</p>}
          <button className="icon-button workspace-help-close" onClick={closeHelp} aria-label="Close shortcuts">
            <Icon name="close" size={14} />
          </button>
        </section>
      )}

      {ready && kind === "run" && run?.inputs?.some((i) => i.joined !== i.collected_on || i.newer_revision_skipped) && (
        <div className="provenance" role="note">
          <Icon name="info" className="provenance-icon" />
          <div>
            {/* One note per input version, not per metrics table (a run has one per epoch and split). */}
            {(() => {
              const unique = [...new Map(run.inputs.map((input) => [`${input.collected_on}|${input.joined}`, input])).values()];
              const pinned = unique.filter((input) => input.joined === input.collected_on);
              const moved = unique.filter((input) => input.joined !== input.collected_on);
              return (
                <>
                  {pinned.length > 0 && (
                    <p>
                      Showing the versions this run used: {pinned.map((input, i) => (
                        <span key={input.collected_on}>{i > 0 && ", "}<span className="mono">{tail(input.collected_on)}</span></span>
                      ))}. Newer versions add or remove rows and cannot be aligned.
                    </p>
                  )}
                  {moved.map((input) => (
                    <p key={`${input.collected_on}|${input.joined}`}>
                      Labels from <span className="mono">{tail(input.joined)}</span>; the run used <span className="mono">{tail(input.collected_on)}</span>.
                      {input.changed_columns && input.changed_columns.length > 0 && (
                        <> Changed: {input.changed_columns.map((c, i) => (
                          <span key={c}>{i > 0 && ", "}<span className="mono">{c}</span> (training value in <span className="mono">{c}@collected</span>)</span>
                        ))}.</>
                      )}
                    </p>
                  ))}
                </>
              );
            })()}
          </div>
        </div>
      )}

      {error && !loading && (
        <div className="workspace-error" role="alert">
          <Icon name="warn" />
          <span>{error}</span>
        </div>
      )}

      {ready ? (
        <div className="workspace">
          <div style={{ width: filtersWidth, flex: "0 0 auto", minWidth: 200 }} className="workspace-filters">
            <FiltersPanel />
          </div>
          <Splitter direction="vertical" onResize={(d) => setFiltersWidth((w) => Math.max(200, w + d))} />
          <div className="main-column" ref={setMainColumn}>
            <div style={{ height: chartCount ? chartsHeight : "auto", flex: "0 0 auto", display: "flex", minHeight: 0 }}>
              <ChartsPanel onToast={showToast} />
            </div>
            {chartCount > 0 && (
              <Splitter
                direction="horizontal"
                onResize={(d) => setChartsShare((share) => Math.min(0.9, Math.max(0.15, share + d / Math.max(1, mainHeight))))}
              />
            )}
            <RowsPanel onToast={showToast} />
          </div>
        </div>
      ) : (
        !error && (
          <div className="workspace-loading">
            <span className="spinner" />
            <span>Loading {kind === "table" ? "images" : "results"}{entry ? ` (${formatNumber(entry.row_count)})` : ""}. Large datasets can take a little while.</span>
          </div>
        )
      )}

      {toast && <div className="toast" role="status">{toast}</div>}
      {commitOpen && <CommitDialog onClose={() => setCommitOpen(false)} onToast={showToast} />}
    </div>
  );
}
