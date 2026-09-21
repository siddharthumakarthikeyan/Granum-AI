"""What a dataset's labels are for: the computer-vision tasks, chosen when a project is created.

A project can serve several tasks (boxes and masks on the same objects serve detection and
instance segmentation). Preflight suggests one from what the annotation files hold (masks,
keypoints, panoptic segments, full-image labels) and checks the chosen ones against them;
the choice is recorded in the producer of every imported table (``producer.args.tasks``).
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

#: Task id -> display name, in the order the import form lists them.
TASKS: dict[str, str] = {
    "object_detection": "Object detection",
    "instance_segmentation": "Instance segmentation",
    "semantic_segmentation": "Semantic segmentation",
    "panoptic_segmentation": "Panoptic segmentation",
    "keypoint_detection": "Keypoint detection",
    "classification": "Classification",
}
DEFAULT_TASK = "object_detection"


def _has_mask(annotation: dict[str, Any]) -> bool:
    segmentation = annotation.get("segmentation")
    if isinstance(segmentation, dict):  # RLE
        return bool(segmentation.get("counts"))
    return isinstance(segmentation, list) and any(isinstance(p, list) and len(p) >= 6 for p in segmentation)


def _has_keypoints(annotation: dict[str, Any]) -> bool:
    points = annotation.get("keypoints")
    if isinstance(points, list) and len(points) >= 3:
        # COCO keypoints are x, y, visibility triples; v = 0 means not labelled.
        return any(isinstance(v, (int, float)) and v > 0 for v in points[2::3])
    return bool(annotation.get("num_keypoints"))


def _covers_image(annotation: dict[str, Any], image: dict[str, Any] | None) -> bool:
    box = annotation.get("bbox")
    if not image or not isinstance(box, list) or len(box) != 4:
        return False
    try:
        width, height = float(image["width"]), float(image["height"])
        x, y, w, h = (float(v) for v in box)
    except (KeyError, TypeError, ValueError):
        return False
    return width > 0 and height > 0 and x <= 0.02 * width and y <= 0.02 * height and w >= 0.96 * width and h >= 0.96 * height


def detect_task(splits: Iterable[Any]) -> dict[str, Any]:
    """Suggest a task from parsed COCO splits (``ParsedSplit``), with the counts behind it."""
    counts = {"annotations": 0, "masks": 0, "keypoints": 0, "panoptic": 0, "full_image": 0,
              "labelled_images": 0, "repeated_class_images": 0}
    keypoint_categories = False
    for split in splits:
        coco = split.coco
        keypoint_categories |= any(isinstance(c, dict) and c.get("keypoints") for c in coco.get("categories", []))
        for image_id, image_annotations in split.annotations_by_image.items():
            if not image_annotations:
                continue
            counts["labelled_images"] += 1
            image = split.image_by_id.get(image_id)
            seen: set[Any] = set()
            repeated = False
            for annotation in image_annotations:
                counts["annotations"] += 1
                counts["masks"] += _has_mask(annotation)
                counts["keypoints"] += _has_keypoints(annotation)
                counts["panoptic"] += "segments_info" in annotation
                category = annotation.get("category_id")
                repeated |= category in seen
                seen.add(category)
            if len(image_annotations) == 1 and _covers_image(image_annotations[0], image):
                counts["full_image"] += 1
            counts["repeated_class_images"] += repeated

    total = counts["annotations"]
    if counts["panoptic"]:
        task, reason = "panoptic_segmentation", "annotations carry panoptic segments_info"
    elif counts["keypoints"] or (keypoint_categories and total):
        task, reason = "keypoint_detection", f"{counts['keypoints']:,} annotations have keypoints"
    elif counts["masks"] and counts["masks"] >= 0.5 * total:
        if counts["repeated_class_images"] == 0 and counts["labelled_images"] > 1:
            task, reason = "semantic_segmentation", "masks, with at most one region per class in each image"
        else:
            task, reason = "instance_segmentation", f"{counts['masks']:,} of {total:,} annotations have masks"
    elif counts["labelled_images"] and counts["full_image"] >= 0.9 * counts["labelled_images"]:
        task, reason = "classification", "each image has one label covering the whole image"
    else:
        task, reason = DEFAULT_TASK, "boxes without masks or keypoints" if total else "no annotations to go by"
    return {"detected": task, "reason": reason, "counts": counts}


def task_warning(task: str, counts: dict[str, int]) -> str | None:
    """Why the chosen task does not fit the labels, if it does not."""
    name = TASKS.get(task, task)
    if task == "object_detection" and not counts.get("annotations"):
        return f"{name}: the annotation files have no boxes."
    if task in ("instance_segmentation", "semantic_segmentation") and not counts.get("masks"):
        return f"{name}: the annotation files have no segmentation masks; only boxes will be imported."
    if task == "panoptic_segmentation" and not counts.get("panoptic"):
        return f"{name}: the annotation files have no panoptic segments."
    if task == "keypoint_detection" and not counts.get("keypoints"):
        return f"{name}: the annotation files have no keypoints."
    if task == "classification" and counts.get("labelled_images") and counts.get("full_image", 0) < 0.9 * counts["labelled_images"]:
        return f"{name}: most images have boxes around objects, not one label for the whole image."
    return None


def normalize_tasks(tasks: Iterable[str] | str | None) -> list[str]:
    """Known task ids, in TASKS order, without repeats."""
    if isinstance(tasks, str):
        tasks = [tasks]
    chosen = set(tasks or [])
    unknown = chosen - set(TASKS)
    if unknown:
        raise ValueError(f"unknown task {sorted(unknown)[0]!r}; tasks are {list(TASKS)}")
    return [t for t in TASKS if t in chosen]


def tasks_of(args: dict[str, Any]) -> list[str]:
    """The tasks a table's producer records; the single ``task`` of earlier imports counts too."""
    tasks = args.get("tasks")
    if isinstance(tasks, list) and tasks:
        return [t for t in tasks if t in TASKS]
    return [args["task"]] if args.get("task") in TASKS else []
