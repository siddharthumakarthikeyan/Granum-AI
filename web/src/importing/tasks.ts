/** Computer-vision tasks a project's labels can be for (granum.importing.tasks). */

import type { TaskId } from "../api/types";

export const TASKS: { id: TaskId; label: string }[] = [
  { id: "object_detection", label: "Object detection" },
  { id: "instance_segmentation", label: "Instance segmentation" },
  { id: "semantic_segmentation", label: "Semantic segmentation" },
  { id: "panoptic_segmentation", label: "Panoptic segmentation" },
  { id: "keypoint_detection", label: "Keypoint detection" },
  { id: "classification", label: "Classification" },
];

export function taskLabel(task: TaskId): string {
  return TASKS.find((t) => t.id === task)?.label ?? task;
}

/** "Object detection + Instance segmentation"; projects from before tasks read as detection. */
export function tasksLabel(tasks: TaskId[] | undefined | null): string {
  return tasks && tasks.length ? tasks.map(taskLabel).join(" + ") : "Object detection";
}

/** Tasks in the order they are listed. */
export function sortTasks(tasks: Iterable<TaskId>): TaskId[] {
  const chosen = new Set(tasks);
  return TASKS.map((t) => t.id).filter((id) => chosen.has(id));
}

/** Why a chosen task does not fit the labels found, if it does not (mirrors task_warning). */
export function taskWarning(task: TaskId, counts: Record<string, number> | undefined): string | null {
  if (!counts) return null;
  const name = taskLabel(task);
  if (task === "object_detection" && !counts.annotations) return `${name}: the annotation files have no boxes.`;
  if ((task === "instance_segmentation" || task === "semantic_segmentation") && !counts.masks) {
    return `${name}: the annotation files have no segmentation masks; only boxes will be imported.`;
  }
  if (task === "panoptic_segmentation" && !counts.panoptic) return `${name}: the annotation files have no panoptic segments.`;
  if (task === "keypoint_detection" && !counts.keypoints) return `${name}: the annotation files have no keypoints.`;
  if (task === "classification" && counts.labelled_images && (counts.full_image ?? 0) < 0.9 * counts.labelled_images) {
    return `${name}: most images have boxes around objects, not one label for the whole image.`;
  }
  return null;
}

/** Training fits box detectors; it can use a project that has detection-style labels. */
export function trainsOnBoxes(tasks: TaskId[] | undefined | null): boolean {
  return !tasks || tasks.length === 0 || tasks.some((t) => t === "object_detection" || t === "instance_segmentation");
}
