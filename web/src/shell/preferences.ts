import { useMemo, useSyncExternalStore } from "react";

const CHANGE = "granum:workspace-preferences";
const PINNED = "granum.projects.pinned";
const RECENT = "granum.projects.recent";

function snapshot(key: string): string {
  try { return localStorage.getItem(key) ?? "[]"; } catch { return "[]"; }
}
function names(value: string): string[] {
  try {
    const parsed: unknown = JSON.parse(value);
    return Array.isArray(parsed) ? [...new Set(parsed.filter((name): name is string => typeof name === "string"))] : [];
  } catch { return []; }
}
function subscribe(callback: () => void) {
  window.addEventListener("storage", callback);
  window.addEventListener(CHANGE, callback);
  return () => { window.removeEventListener("storage", callback); window.removeEventListener(CHANGE, callback); };
}
function save(key: string, value: string[]): boolean {
  try { localStorage.setItem(key, JSON.stringify(value)); window.dispatchEvent(new Event(CHANGE)); return true; }
  catch { return false; }
}
function useNames(key: string) {
  const value = useSyncExternalStore(subscribe, () => snapshot(key), () => "[]");
  return useMemo(() => names(value), [value]);
}
export const usePinnedProjects = () => useNames(PINNED);
export const useRecentProjects = () => useNames(RECENT);
export function togglePinnedProject(name: string): boolean {
  const current = names(snapshot(PINNED));
  return save(PINNED, current.includes(name) ? current.filter((item) => item !== name) : [...current, name]);
}
export function rememberProject(name: string) {
  save(RECENT, [name, ...names(snapshot(RECENT)).filter((item) => item !== name)].slice(0, 8));
}
export function renameProjectPreferences(from: string, to: string) {
  for (const key of [PINNED, RECENT]) {
    const current = names(snapshot(key));
    if (current.includes(from)) save(key, [...new Set(current.map((name) => name === from ? to : name))]);
  }
}
export function forgetProject(name: string) {
  for (const key of [PINNED, RECENT]) save(key, names(snapshot(key)).filter((item) => item !== name));
}
export function workspaceSearchShortcut() {
  return /Mac|iPhone|iPad/.test(navigator.platform) ? "⌘ K" : "Ctrl K";
}
export function projectTone(name: string): string {
  const hash = Array.from(name).reduce((value, letter) => (value * 31 + letter.charCodeAt(0)) | 0, 0);
  return ["cyan", "violet", "amber", "green"][Math.abs(hash) % 4]!;
}
export function openWorkspaceSearch() { window.dispatchEvent(new Event("granum:open-search")); }
