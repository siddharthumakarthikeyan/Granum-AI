// @vitest-environment jsdom
import "fake-indexeddb/auto";
import { describe, expect, it } from "vitest";
import { deleteEditorDraft, editorDraftKey, loadEditorDraft, saveEditorDraft, type EditorDraft } from "./editorDrafts";

function draft(key: string, token = "one"): EditorDraft {
  return { key, token, base: "revision-one", version: 1, savedAt: new Date().toISOString(), data: {
    polygons: [[0, 1, 2, 3, 4, 5]], labels: { 0: "new class" }, extra: { keypoints: [1, 2, 2] }, comment: "pending review",
  } };
}

describe("durable annotation drafts", () => {
  it("round-trips full annotations, schema changes and pending comments across connections", async () => {
    const saved = draft("roundtrip");
    await saveEditorDraft(saved, null);
    expect(await loadEditorDraft(saved.key)).toEqual(saved);
    await deleteEditorDraft(saved.key, saved.token);
    expect(await loadEditorDraft(saved.key)).toBeNull();
  });
  it("rejects stale writers and does not let another tab delete newer edits", async () => {
    await saveEditorDraft(draft("tabs"), null);
    await saveEditorDraft(draft("tabs", "two"), "one");
    await expect(saveEditorDraft(draft("tabs", "three"), "one")).rejects.toThrow("another tab");
    await expect(deleteEditorDraft("tabs", "one")).rejects.toThrow();
    expect((await loadEditorDraft("tabs"))?.token).toBe("two");
  });
  it("separates editors, projects and images but retains the source revision", async () => {
    const a = editorDraftKey("review", "p", "d", "image");
    expect(a).not.toBe(editorDraftKey("annotations", "p", "d", "image"));
    expect(a).not.toBe(editorDraftKey("review", "other", "d", "image"));
    await saveEditorDraft(draft(a), null);
    expect((await loadEditorDraft(a))?.base).toBe("revision-one");
  });
});