"""Bounding boxes as values, plus the geometry every detection feature needs.

A Table stores boxes as plain dicts (see ``BoundingBoxes2DSchema``). ``BoundingBoxes2D``
is the convenient view over one such value: numpy arrays in, numpy arrays out, and a
``.schema()`` factory so a column declaration reads like the data it holds.

Matching follows the COCO evaluation rule so numbers agree with tools people already
trust: predictions are taken in descending confidence, each claims the unclaimed ground
truth box of the same class with the highest IoU, and a claim needs IoU >= threshold.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Any

import numpy as np

from granum.core.schemas.geometry import BoundingBoxes2DSchema


@dataclass
class BoundingBoxes2D:
    """One image's boxes. ``boxes`` is ``(N, 4)`` xyxy pixels; ``labels`` is ``(N,)``."""

    width: float
    height: float
    boxes: np.ndarray = field(default_factory=lambda: np.zeros((0, 4)))
    labels: np.ndarray = field(default_factory=lambda: np.zeros((0,), dtype=np.int64))
    properties: dict[str, list[Any]] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.boxes = np.asarray(self.boxes, dtype=np.float64).reshape(-1, 4)
        self.labels = np.asarray(self.labels, dtype=np.int64).reshape(-1)
        if len(self.labels) != len(self.boxes):
            raise ValueError(f"{len(self.boxes)} boxes but {len(self.labels)} labels")
        for name, values in self.properties.items():
            if len(values) != len(self.boxes):
                raise ValueError(f"property {name!r} has {len(values)} values for {len(self.boxes)} boxes")

    def __len__(self) -> int:
        return len(self.boxes)

    @staticmethod
    def schema(
        classes: Iterable[str] | None = None,
        *,
        value_map: Any = None,
        instance_properties: dict[str, str] | None = None,
        **kwargs: Any,
    ) -> BoundingBoxes2DSchema:
        return BoundingBoxes2DSchema(
            classes=classes, value_map=value_map, instance_properties=instance_properties, **kwargs
        )

    @classmethod
    def from_value(cls, value: dict[str, Any]) -> BoundingBoxes2D:
        instances = value.get("instances") or []
        names = sorted({k for inst in instances for k in inst} - {"vertices", "label"})
        return cls(
            width=float(value.get("width") or 0.0),
            height=float(value.get("height") or 0.0),
            boxes=[inst["vertices"] for inst in instances] or np.zeros((0, 4)),
            labels=[inst["label"] for inst in instances],
            properties={name: [inst.get(name) for inst in instances] for name in names},
        )

    def to_value(self) -> dict[str, Any]:
        instances = []
        for i in range(len(self)):
            instance: dict[str, Any] = {"vertices": [float(v) for v in self.boxes[i]], "label": int(self.labels[i])}
            for name, values in self.properties.items():
                instance[name] = values[i]
            instances.append(instance)
        return {"width": float(self.width), "height": float(self.height), "instances": instances}


# ---------------------------------------------------------------------------
# geometry
# ---------------------------------------------------------------------------


def box_iou(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    """IoU between every box in ``a`` (N, 4) and every box in ``b`` (M, 4), xyxy."""
    a = np.asarray(a, dtype=np.float64).reshape(-1, 4)
    b = np.asarray(b, dtype=np.float64).reshape(-1, 4)
    if len(a) == 0 or len(b) == 0:
        return np.zeros((len(a), len(b)))
    area_a = np.clip(a[:, 2] - a[:, 0], 0, None) * np.clip(a[:, 3] - a[:, 1], 0, None)
    area_b = np.clip(b[:, 2] - b[:, 0], 0, None) * np.clip(b[:, 3] - b[:, 1], 0, None)
    lt = np.maximum(a[:, None, :2], b[None, :, :2])
    rb = np.minimum(a[:, None, 2:], b[None, :, 2:])
    wh = np.clip(rb - lt, 0, None)
    inter = wh[..., 0] * wh[..., 1]
    union = area_a[:, None] + area_b[None, :] - inter
    return np.divide(inter, union, out=np.zeros_like(inter), where=union > 0)


@dataclass
class MatchResult:
    """How predictions and ground truth of one image paired up."""

    #: For each prediction: index of the matched ground-truth box, or -1.
    pred_match: np.ndarray
    #: For each prediction: best IoU with any same-class ground-truth box (matched or not).
    pred_iou: np.ndarray
    #: For each ground-truth box: index of the prediction that matched it, or -1.
    gt_match: np.ndarray

    @property
    def tp(self) -> int:
        return int((self.pred_match >= 0).sum())

    @property
    def fp(self) -> int:
        return int((self.pred_match < 0).sum())

    @property
    def fn(self) -> int:
        return int((self.gt_match < 0).sum())

    @property
    def precision(self) -> float:
        total = self.tp + self.fp
        return self.tp / total if total else 1.0

    @property
    def recall(self) -> float:
        total = self.tp + self.fn
        return self.tp / total if total else 1.0

    @property
    def f1(self) -> float:
        p, r = self.precision, self.recall
        return 2 * p * r / (p + r) if (p + r) else 0.0


def match_boxes(
    gt_boxes: np.ndarray,
    gt_labels: np.ndarray,
    pred_boxes: np.ndarray,
    pred_labels: np.ndarray,
    pred_scores: np.ndarray | None = None,
    *,
    iou_threshold: float = 0.5,
    class_aware: bool = True,
) -> MatchResult:
    """Greedy COCO-style matching of predictions to ground truth.

    An image with no ground truth and no predictions is perfect (precision and recall 1),
    which keeps empty images from dragging averages to zero.
    """
    gt_boxes = np.asarray(gt_boxes, dtype=np.float64).reshape(-1, 4)
    pred_boxes = np.asarray(pred_boxes, dtype=np.float64).reshape(-1, 4)
    gt_labels = np.asarray(gt_labels).reshape(-1)
    pred_labels = np.asarray(pred_labels).reshape(-1)
    scores = np.ones(len(pred_boxes)) if pred_scores is None else np.asarray(pred_scores, dtype=np.float64)

    iou = box_iou(pred_boxes, gt_boxes)
    if class_aware and iou.size:
        iou = np.where(pred_labels[:, None] == gt_labels[None, :], iou, 0.0)

    pred_match = np.full(len(pred_boxes), -1, dtype=np.int64)
    gt_match = np.full(len(gt_boxes), -1, dtype=np.int64)
    pred_iou = iou.max(axis=1) if iou.size else np.zeros(len(pred_boxes))

    for p in np.argsort(-scores, kind="stable"):
        if not len(gt_boxes):
            break
        candidates = np.where(gt_match < 0, iou[p], -1.0)
        g = int(np.argmax(candidates))
        if candidates[g] >= iou_threshold:
            pred_match[p] = g
            gt_match[g] = p
    return MatchResult(pred_match=pred_match, pred_iou=pred_iou, gt_match=gt_match)


def nms(
    boxes: np.ndarray,
    scores: np.ndarray,
    labels: np.ndarray | None = None,
    *,
    iou_threshold: float = 0.5,
    class_aware: bool = True,
) -> np.ndarray:
    """Indices of boxes kept by non-maximum suppression, highest score first."""
    boxes = np.asarray(boxes, dtype=np.float64).reshape(-1, 4)
    scores = np.asarray(scores, dtype=np.float64).reshape(-1)
    labels = np.zeros(len(boxes), dtype=np.int64) if labels is None or not class_aware else np.asarray(labels)
    order = np.argsort(-scores, kind="stable")
    keep: list[int] = []
    suppressed = np.zeros(len(boxes), dtype=bool)
    iou = box_iou(boxes, boxes)
    for i in order:
        if suppressed[i]:
            continue
        keep.append(int(i))
        same = labels == labels[i]
        suppressed |= same & (iou[i] > iou_threshold)
    return np.asarray(keep, dtype=np.int64)
