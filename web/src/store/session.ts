/** Session columns: Edited, Visited, Selected.
 *
 * Filterable like any column, never persisted, never sent to the service. They answer
 * the reviewing questions a Table cannot: "show me only what I've changed", "what have
 * I not looked at yet".
 *
 * Their values live here rather than in the rows, because selection changes on every
 * click and rewriting 80k row objects per click is not an option. Filter caches key on
 * `version` -- but only while a session filter is active, so ordinary clicks do not
 * invalidate anything.
 */

import type { ColumnInfo } from "../api/types";
import { isActive } from "./filtering";
import type { Filter } from "./types";

export const SESSION_COLUMNS = ["Edited", "Visited", "Selected"] as const;
export type SessionColumn = (typeof SESSION_COLUMNS)[number];

interface SessionState {
  Edited: Set<number>;
  Visited: Set<number>;
  Selected: Set<number>;
  version: number;
}

let state: SessionState = {
  Edited: new Set(), Visited: new Set(), Selected: new Set(), version: 0,
};

export function isSessionColumn(name: string): name is SessionColumn {
  return (SESSION_COLUMNS as readonly string[]).includes(name);
}

export function setSession(next: Partial<Omit<SessionState, "version">>): void {
  const changed = (Object.keys(next) as SessionColumn[]).some((k) => next[k] !== state[k]);
  if (!changed) return;
  state = { ...state, ...next, version: state.version + 1 };
}

export function sessionValue(column: SessionColumn, index: number): boolean {
  return state[column].has(index);
}

export function sessionVersion(): number {
  return state.version;
}

/** Cache key contribution: the session version if any active filter depends on it. */
export function sessionKeyFor(filters: Filter[]): number {
  return filters.some((f) => isActive(f) && isSessionColumn(f.column)) ? state.version : 0;
}

export function sessionColumnInfos(): ColumnInfo[] {
  return SESSION_COLUMNS.map((name) => ({
    name, kind: "bool", writable: false, default_visible: false, number_role: null, source: "session",
  }));
}
