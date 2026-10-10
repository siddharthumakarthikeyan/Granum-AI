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

/** How one box of an image is addressed by a tag.
 *
 * The same rule as `granum.core.tags.object_key`, and it has to be: the browser writes a key
 * the service reads back. By annotation id where the import gave the box one, because that
 * survives the boxes being reordered, and by position where it did not — kept apart by their
 * prefix so that box 3 of an unnumbered image cannot collide with annotation 3.
 */
export function objectKey(box: Record<string, unknown> | undefined, index: number): string {
  const annotation = box?.annotation_id;
  return typeof annotation === "number" && Number.isFinite(annotation) ? `a${annotation}` : `i${index}`;
}
