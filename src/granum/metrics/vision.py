"""Task-specific similarities: rotated polygon IoU, masks and COCO keypoint OKS."""

from __future__ import annotations

from typing import Any

import numpy as np

from granum.errors import GranumError
from granum.formats.vision import extra_of, mask_array, polygon_area

COCO_KEYPOINT_SIGMAS = np.array([.26, .25, .25, .35, .35, .79, .79, .72, .72, .62, .62, 1.07, 1.07, .87, .87, .89, .89]) / 10


def polygon_intersection(a: Any, b: Any) -> np.ndarray:
    """Convex clipping, independent of rotation and clockwise/counterclockwise order."""
    subject = np.asarray(a, dtype=float).reshape(-1, 2)
    clip = np.asarray(b, dtype=float).reshape(-1, 2)
    if len(subject) < 3 or len(clip) < 3 or not np.isfinite(subject).all() or not np.isfinite(clip).all():
        raise GranumError("oriented IoU needs finite polygons with at least three points")
    signed = np.dot(clip[:, 0], np.roll(clip[:, 1], -1)) - np.dot(clip[:, 1], np.roll(clip[:, 0], -1))
    orientation = 1 if signed >= 0 else -1
    for start, end in zip(clip, np.roll(clip, -1, axis=0)):
        if not len(subject):
            break
        edge = end - start

        def side(point: np.ndarray, start: np.ndarray = start, edge: np.ndarray = edge) -> float:
            p = point - start
            return float(orientation * (edge[0] * p[1] - edge[1] * p[0]))

        points = []
        previous, last_side = subject[-1], side(subject[-1])
        for point in subject:
            now = side(point)
            if (now >= 0) != (last_side >= 0):
                points.append(previous + (point - previous) * last_side / (last_side - now))
            if now >= 0:
                points.append(point)
            previous, last_side = point, now
        subject = np.asarray(points, dtype=float).reshape(-1, 2)
    return subject


def oriented_iou(predicted: Any, truth: Any, *, crowd: bool = False) -> float:
    intersection = polygon_area(polygon_intersection(predicted, truth))
    area = polygon_area(predicted)
    denominator = area if crowd else area + polygon_area(truth) - intersection
    return min(1.0, max(0.0, intersection / denominator)) if denominator > 0 else 0.0


def mask_scores(predicted: Any, truth: Any, *, ignore: Any = None) -> dict[str, float]:
    pred, target = np.asarray(predicted, dtype=bool), np.asarray(truth, dtype=bool)
    if pred.shape != target.shape or pred.ndim != 2:
        raise GranumError("mask metrics need two equally sized images")
    valid = np.ones(pred.shape, dtype=bool) if ignore is None else ~np.asarray(ignore, dtype=bool)
    if valid.shape != pred.shape:
        raise GranumError("ignore mask dimensions do not match")
    pred, target = pred & valid, target & valid
    intersection = int((pred & target).sum())
    union, area = int((pred | target).sum()), int(pred.sum() + target.sum())
    return {"iou": intersection / union if union else 1.0, "dice": 2 * intersection / area if area else 1.0,
            "intersection": intersection, "union": union}


def keypoint_oks(predicted: Any, truth: Any, area: float, sigmas: Any = None) -> tuple[float | None, list[float | None]]:
    """COCO OKS; unlabelled truth points do not affect the average.

    Returns no score when the object has no labelled points. A caller must exclude that
    object from positives, rather than treating it as either a perfect match or a miss.
    """
    target = np.asarray(truth, dtype=float).reshape(-1, 3)
    pred = np.asarray(predicted, dtype=float)
    if pred.ndim == 1:
        pred = pred.reshape(-1, 3)
    if pred.ndim != 2 or pred.shape[1] not in (2, 3) or len(pred) != len(target) or not len(target):
        raise GranumError("prediction and truth must use the same keypoint layout")
    if not np.isfinite(target).all() or not np.isfinite(pred).all() or not np.isfinite(area) or area <= 0:
        raise GranumError("keypoint metrics need finite coordinates and a positive object area")
    scales = np.asarray(sigmas if sigmas is not None else COCO_KEYPOINT_SIGMAS if len(target) == 17 else np.full(len(target), 1 / len(target)), dtype=float)
    if scales.shape != (len(target),) or not np.isfinite(scales).all() or np.any(scales <= 0):
        raise GranumError("one positive OKS sigma is required for each keypoint")
    distances = ((pred[:, :2] - target[:, :2]) ** 2).sum(axis=1)
    values = np.exp(-distances / ((2 * scales) ** 2 * area * 2))
    visible = target[:, 2] > 0
    per_point = [float(v) if labelled else None for v, labelled in zip(values, visible)]
    return (float(values[visible].mean()) if visible.any() else None), per_point


def semantic_scores(predicted: Any, truth: Any, classes: list[int], *, ignore_index: int | None = None) -> dict[str, Any]:
    pred, target = np.asarray(predicted), np.asarray(truth)
    if pred.shape != target.shape or pred.ndim != 2:
        raise GranumError("semantic metrics need two equally sized class-id images")
    allowed = set(classes)
    if len(allowed) != len(classes) or not allowed or any(isinstance(c, bool) or not isinstance(c, (int, np.integer)) for c in classes):
        raise GranumError("semantic metrics need distinct integer class IDs")
    target_allowed = allowed | ({ignore_index} if ignore_index is not None else set())
    if pred.dtype.kind not in "uib" or target.dtype.kind not in "uib" or set(np.unique(pred)) - allowed or set(np.unique(target)) - target_allowed:
        raise GranumError("semantic metrics received unknown or noninteger class IDs")
    valid = target != ignore_index if ignore_index is not None else np.ones(target.shape, dtype=bool)
    scores = {}
    for label in classes:
        counts = mask_scores((pred == label) & valid, (target == label) & valid)
        if counts["union"]:
            scores[label] = counts
    return {"pixel_accuracy": float((pred[valid] == target[valid]).mean()) if valid.any() else None,
            "mean_iou": float(np.mean([v["iou"] for v in scores.values()])) if scores else None, "classes": scores}


def similarities(task: str, truth: dict[str, Any], predicted: dict[str, Any], *, sigmas: Any = None) -> tuple[np.ndarray, np.ndarray]:
    """Prediction x ground-truth matrices of matching and crowd-overlap scores."""
    instances = truth["instances"]
    n = len(predicted.get("scores", []))
    scores, crowd = np.zeros((n, len(instances))), np.zeros((n, len(instances)))
    if task == "segment":
        width, height = int(truth["width"]), int(truth["height"])
        values = predicted.get("segmentations", [])
        if len(values) != n:
            raise GranumError("every segmentation prediction needs a mask")
        targets = [mask_array(i.get("segmentation"), width, height).astype(bool) for i in instances]
        if any(not target.any() for target in targets):
            raise GranumError("every segmentation ground-truth object needs a nonempty mask; remove empty objects or supply their masks")
        for p, value in enumerate(values):
            mask = mask_array(value, width, height).astype(bool)
            for g, target in enumerate(targets):
                counts = mask_scores(mask, target)
                scores[p, g] = counts["iou"]
                crowd[p, g] = counts["intersection"] / mask.sum() if mask.any() else 0.0
    elif task == "obb":
        values = predicted.get("obb", [])
        if len(values) != n:
            raise GranumError("every oriented prediction needs four corners")
        for p, value in enumerate(values):
            for g, instance in enumerate(instances):
                corners = extra_of(instance).get("obb")
                if corners is None:
                    raise GranumError("oriented ground truth is missing its four corners")
                scores[p, g], crowd[p, g] = oriented_iou(value, corners), oriented_iou(value, corners, crowd=True)
    elif task == "pose":
        values = predicted.get("keypoints", [])
        if len(values) != n:
            raise GranumError("every pose prediction needs keypoints")
        for p, value in enumerate(values):
            for g, instance in enumerate(instances):
                target = extra_of(instance).get("keypoints", [])
                if not any(v > 0 for v in target[2::3]):
                    continue
                box = instance["vertices"]
                area = instance.get("area") or (box[2] - box[0]) * (box[3] - box[1])
                scores[p, g] = keypoint_oks(value, target, area, sigmas)[0] or 0.0
    else:
        raise GranumError(f"unknown vision task {task!r}")
    return scores, crowd
