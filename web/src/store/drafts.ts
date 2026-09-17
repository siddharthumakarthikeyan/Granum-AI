/** Unsaved edits kept in this browser, so a reload, crash or closed tab loses nothing.
 *
 * A draft is the undo stack for one open Table or Run, written to IndexedDB shortly after
 * every change and removed once the edits are saved or discarded. Tables are immutable,
 * so replaying a draft onto the same Table URL is exact. A Run draft also records which
 * input revisions it edited; if the Run now shows different ones, the draft is stale and
 * is offered for discarding only.
 *
 * Drafts never leave the browser. Anyone using this browser profile can read them, which
 * the recovery banner says, with a control to delete them.
 */

import type { Batch } from "./editing";

const DB_NAME = "granum-drafts";
const STORE = "drafts";
const SAVE_DELAY_MS = 400;

export interface Draft {
  key: string;
  kind: "table" | "run";
  url: string;
  name: string;
  sources: string[];
  savedAt: string;
  batches: Batch[];
}

export function draftKey(kind: "table" | "run", url: string): string {
  return `${kind}|${url}`;
}

let opening: Promise<IDBDatabase | null> | null = null;

function database(): Promise<IDBDatabase | null> {
  if (opening) return opening;
  opening = new Promise((resolve) => {
    try {
      if (typeof indexedDB === "undefined") return resolve(null);
      const request = indexedDB.open(DB_NAME, 1);
      request.onupgradeneeded = () => request.result.createObjectStore(STORE, { keyPath: "key" });
      request.onsuccess = () => resolve(request.result);
      request.onerror = () => resolve(null);
      request.onblocked = () => resolve(null);
    } catch {
      resolve(null);
    }
  });
  return opening;
}

async function run<T>(mode: IDBTransactionMode, action: (store: IDBObjectStore) => IDBRequest<T>): Promise<T | null> {
  const db = await database();
  if (!db) return null;
  return new Promise((resolve) => {
    try {
      const request = action(db.transaction(STORE, mode).objectStore(STORE));
      request.onsuccess = () => resolve(request.result);
      request.onerror = () => resolve(null);
    } catch {
      resolve(null);
    }
  });
}

export async function loadDraft(key: string): Promise<Draft | null> {
  const draft = await run<Draft | undefined>("readonly", (store) => store.get(key));
  return draft && draft.batches.length > 0 ? draft : null;
}

export async function removeDraft(key: string): Promise<void> {
  await run("readwrite", (store) => store.delete(key));
}

export async function writeDraft(draft: Draft): Promise<void> {
  if (draft.batches.length === 0) {
    await removeDraft(draft.key);
    return;
  }
  // Batches hold plain JSON values, but a structured clone must not choke on anything odd.
  const clean = JSON.parse(JSON.stringify(draft)) as Draft;
  await run("readwrite", (store) => store.put(clean));
}

const timers = new Map<string, ReturnType<typeof setTimeout>>();
const latest = new Map<string, Draft>();

/** Save soon; repeated calls for the same key within the delay write once. */
export function scheduleDraft(draft: Draft): void {
  latest.set(draft.key, draft);
  const existing = timers.get(draft.key);
  if (existing !== undefined) globalThis.clearTimeout(existing);
  timers.set(
    draft.key,
    globalThis.setTimeout(() => {
      timers.delete(draft.key);
      const pending = latest.get(draft.key);
      latest.delete(draft.key);
      if (pending) void writeDraft(pending);
    }, SAVE_DELAY_MS),
  );
}

/** Write any scheduled draft now, e.g. before the page unloads. */
export function flushDrafts(): void {
  for (const [key, timer] of timers) {
    globalThis.clearTimeout(timer);
    const pending = latest.get(key);
    if (pending) void writeDraft(pending);
  }
  timers.clear();
  latest.clear();
}
