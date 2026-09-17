/** Copy the current selection as CSV, JSON or raw text. */

import type { Row } from "../api/types";

export type CopyFormat = "csv" | "json" | "text";

function escapeCsv(value: unknown): string {
  const text = value === null || value === undefined ? "" : String(value);
  return /[",\n]/.test(text) ? `"${text.replace(/"/g, '""')}"` : text;
}

export function formatSelection(
  rows: Row[],
  indices: number[],
  columns: string[],
  format: CopyFormat,
): string {
  const selected = indices.map((index) => rows[index]).filter(Boolean) as Row[];

  if (format === "json") {
    return JSON.stringify(
      selected.map((row) => Object.fromEntries(columns.map((c) => [c, row[c]]))),
      null,
      2,
    );
  }
  if (format === "csv") {
    const header = columns.map(escapeCsv).join(",");
    const body = selected.map((row) => columns.map((c) => escapeCsv(row[c])).join(","));
    return [header, ...body].join("\n");
  }
  return selected.map((row) => columns.map((c) => String(row[c] ?? "")).join("\t")).join("\n");
}

export async function copyToClipboard(text: string): Promise<boolean> {
  try {
    await navigator.clipboard.writeText(text);
    return true;
  } catch {
    return false;
  }
}
