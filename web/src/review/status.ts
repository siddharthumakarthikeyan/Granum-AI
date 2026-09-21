/** Review statuses as the Images tab shows them: reviewed reads as Verified. */

import type { QaState, QaStatus } from "../api/types";

export type MoveAction = "isolate" | "delete" | "return";

/** What to call an image on screen: the whole path is its identity, the name is its label. */
export const fileName = (image: string): string => image.split("/").pop() ?? image;

export const STATUS_LABEL: Record<QaStatus, string> = { unreviewed: "Unverified", reviewed: "Verified", rework: "Rework" };

export function statusOf(statuses: Record<string, QaState>, image: string): QaStatus {
  return statuses[image]?.status ?? "unreviewed";
}

const NAME_KEY = "granum.reviewer";

export function readReviewer(): string {
  try {
    return window.localStorage.getItem(NAME_KEY) ?? "";
  } catch {
    return "";
  }
}

export function saveReviewer(name: string): void {
  try {
    window.localStorage.setItem(NAME_KEY, name);
  } catch {
    /* the name is a convenience; without storage it lasts the session */
  }
}
