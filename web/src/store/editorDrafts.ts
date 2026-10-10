/** Transaction-confirmed, revision-bound drafts. No silent quota/permission failures. */
export interface EditorDraft<T = unknown> {
  key: string;
  version: 1;
  base: string;
  savedAt: string;
  token: string;
  data: T;
}

export function editorDraftKey(editor: string, project: string, dataset: string, image: string): string {
  return JSON.stringify([editor, project, dataset, image]);
}

function database(): Promise<IDBDatabase> {
  return new Promise((resolve, reject) => {
    if (typeof indexedDB === "undefined") return reject(new Error("Browser draft storage is unavailable."));
    const request = indexedDB.open("granum-editor-drafts", 1);
    request.onupgradeneeded = () => request.result.createObjectStore("drafts", { keyPath: "key" });
    request.onsuccess = () => resolve(request.result);
    request.onerror = () => reject(new Error("Cannot open browser draft storage."));
    request.onblocked = () => reject(new Error("Close other Granum tabs to enable draft storage."));
  });
}

/** Complete only on transaction commit, not the earlier request-success event. */
async function transaction<T>(mode: IDBTransactionMode, act: (store: IDBObjectStore, result: (value: T) => void) => void): Promise<T> {
  const db = await database();
  return new Promise<T>((resolve, reject) => {
    const tx = db.transaction("drafts", mode);
    let value: T;
    tx.oncomplete = () => { db.close(); resolve(value); };
    tx.onabort = tx.onerror = () => { db.close(); reject(new Error("Draft not saved: storage is full, unavailable, or another tab changed this draft. Export your edits before leaving.")); };
    try { act(tx.objectStore("drafts"), (next) => { value = next; }); }
    catch (error) { tx.abort(); reject(error); }
  });
}

export function loadEditorDraft<T>(key: string): Promise<EditorDraft<T> | null> {
  return transaction("readonly", (store, done) => {
    store.get(key).onsuccess = (event) => done((event.target as IDBRequest).result ?? null);
  });
}

/** Optimistic token check prevents two tabs from silently overwriting each other's work. */
export function saveEditorDraft<T>(draft: EditorDraft<T>, expected: string | null): Promise<void> {
  return transaction("readwrite", (store, done) => {
    const read = store.get(draft.key);
    read.onsuccess = () => {
      if ((read.result?.token ?? null) !== expected) { store.transaction.abort(); return; }
      store.put(draft);
      done(undefined);
    };
  });
}

export function deleteEditorDraft(key: string, expected: string | null): Promise<void> {
  return transaction("readwrite", (store, done) => {
    const read = store.get(key);
    read.onsuccess = () => {
      if ((read.result?.token ?? null) !== expected) { store.transaction.abort(); return; }
      store.delete(key);
      done(undefined);
    };
  });
}