// @vitest-environment jsdom
import "fake-indexeddb/auto";
import { act, cleanup, render, renderHook, screen, waitFor } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { loadEditorDraft, saveEditorDraft } from "./editorDrafts";
import { useEditorDraft } from "./useEditorDraft";

afterEach(cleanup);

it("writes on edits and keeps them across an editor remount", async () => {
  const restore = vi.fn();
  const first = renderHook(() => useEditorDraft("reload", "v1", { label: 2, undo: [1] }, true, restore));
  await waitFor(async () => expect((await loadEditorDraft("reload"))?.data).toEqual({ label: 2, undo: [1] }));
  first.unmount();
  const next = renderHook(() => useEditorDraft("reload", "v1", { label: 1, undo: [] as number[] }, false, restore));
  await waitFor(() => expect(next.result.current.banner.props.children[1]).toBeTruthy());
  render(next.result.current.banner);
  await waitFor(() => expect(screen.getByText("Recover edits")).toBeTruthy());
  act(() => screen.getByText("Recover edits").click());
  expect(restore).toHaveBeenCalledWith({ label: 2, undo: [1] });
});

it("blocks automatic replay on another base and clears only on explicit completion", async () => {
  await saveEditorDraft({ key: "stale", token: "one", version: 1, base: "old", savedAt: new Date().toISOString(), data: { label: 2 } }, null);
  const hook = renderHook(() => useEditorDraft("stale", "new", { label: 1 }, false, vi.fn()));
  await waitFor(() => expect(hook.result.current.banner.props.children[1]).toBeTruthy());
  render(hook.result.current.banner);
  expect((screen.getByText("Recover edits") as HTMLButtonElement).disabled).toBe(true);
  expect(await loadEditorDraft("stale")).not.toBeNull();
  await act(() => hook.result.current.clear());
  expect(await loadEditorDraft("stale")).toBeNull();
});