"""Per-sample and per-box metrics for object detection.

For every image the collector matches predictions to ground truth (COCO rule, see
``granum.core.datatypes.match_boxes``) and writes:

- ``bbs_predicted``: the predicted boxes, each with ``confidence``, ``iou`` (best IoU with a
  same-class ground-truth box) and ``matched`` (true positive or not). Filtering these
  per box is how "unmatched confident predictions" -- often objects nobody labelled --
  become one click away.
- ``gt_match``: for each ground-truth box, the index of the prediction that matched it,
  or -1. A -1 is a missed object.
- ``tp``, ``fp``, ``fn``, ``precision``, ``recall``, ``f1`` per image.

Ground-truth boxes flagged ``iscrowd`` are *areas to skip* (COCO crowd regions, VisDrone
"ignored regions"): they are never matched, never counted as missed (``gt_match`` is -2),
and a prediction lying mostly inside one (intersection over the prediction's own area of
at least 0.5) is marked ``ignored`` and counted as neither a true nor a false positive.

A predictor returns, per image, ``{"boxes": (N, 4) xyxy pixels, "scores": (N,),
"labels": (N,)}`` with labels as class indices of the ground-truth column.
"""

from __future__ import annotations

from typing import Any

import numpy as np

from granum.core.datatypes.bounding_boxes import match_boxes
from granum.core.schemas import FractionSchema, Int32ListSchema, Int32Schema, Schema
from granum.core.schemas.geometry import BoundingBoxes2DSchema
from granum.metrics.collectors import CollectorError, MetricsCollector
from granum.metrics.predictor import Prediction

PREDICTED_PROPERTIES = {"confidence": "float32", "iou": "float32", "matched": "bool", "ignored": "bool"}
SKIPPED_GT = -2
IGNORE_OVERLAP = 0.5


def _overlap_of_first(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    """For every box in ``a`` and ``b``: intersection area over the area of the ``a`` box."""
    if len(a) == 0 or len(b) == 0:
        return np.zeros((len(a), len(b)))
    lt = np.maximum(a[:, None, :2], b[None, :, :2])
    rb = np.minimum(a[:, None, 2:], b[None, :, 2:])
    wh = np.clip(rb - lt, 0, None)
    inter = wh[..., 0] * wh[..., 1]
    area = np.clip(a[:, 2] - a[:, 0], 0, None) * np.clip(a[:, 3] - a[:, 1], 0, None)
    return np.divide(inter, area[:, None], out=np.zeros_like(inter), where=area[:, None] > 0)


class DetectionMetricsCollector(MetricsCollector):
    def __init__(
        self,
        gt_column: str = "bbs",
        *,
        value_map: Any = None,
        iou_threshold: float = 0.5,
        class_aware: bool = True,
        predicted_column: str = "bbs_predicted",
        store_boxes: bool = True,
    ) -> None:
        #: False records only the per-image counts and scores: cheap enough to collect
        #: every epoch for learning dynamics, while predicted boxes are kept for fewer epochs.
        self.store_boxes = store_boxes
        self.gt_column = gt_column
        self.value_map = value_map
        self.iou_threshold = iou_threshold
        self.class_aware = class_aware
        self.predicted_column = predicted_column

    def column_schemas(self) -> dict[str, Schema]:
        schemas = self._all_schemas()
        if not self.store_boxes:
            schemas.pop(self.predicted_column)
            schemas.pop("gt_match")
        return schemas

    def _all_schemas(self) -> dict[str, Schema]:
        return {
            self.predicted_column: BoundingBoxes2DSchema(
                value_map=self.value_map,
                instance_properties=PREDICTED_PROPERTIES,
                writable=False,
                description=f"Model predictions matched at IoU {self.iou_threshold}",
            ),
            "gt_match": Int32ListSchema(description="Per ground-truth box: matching prediction index, or -1"),
            "tp": Int32Schema(description="True positives"),
            "fp": Int32Schema(description="False positives"),
            "fn": Int32Schema(description="Missed ground-truth boxes"),
            "precision": FractionSchema(),
            "recall": FractionSchema(),
            "f1": FractionSchema(),
        }

    def collect(self, batch: dict[str, list[Any]], prediction: Prediction | None) -> dict[str, list[Any]]:
        if prediction is None:
            raise CollectorError("DetectionMetricsCollector needs a predictor")
        if self.gt_column not in batch:
            raise CollectorError(f"the batch has no {self.gt_column!r} column; pass gt_column=")
        # A bare callable predictor hands back its output directly.
        outputs = prediction.outputs if isinstance(prediction, Prediction) else prediction
        if len(outputs) != len(batch[self.gt_column]):
            raise CollectorError(f"predictor returned {len(outputs)} results for {len(batch[self.gt_column])} images")

        out: dict[str, list[Any]] = {name: [] for name in self.column_schemas()}
        for truth, predicted in zip(batch[self.gt_column], outputs):
            truth = truth or {"width": 0.0, "height": 0.0, "instances": []}
            all_boxes = np.array([i["vertices"] for i in truth["instances"]], dtype=np.float64).reshape(-1, 4)
            all_labels = np.array([i["label"] for i in truth["instances"]], dtype=np.int64)
            skip = np.array([bool(i.get("iscrowd")) for i in truth["instances"]], dtype=bool)
            kept = np.flatnonzero(~skip)
            gt_boxes, gt_labels = all_boxes[kept], all_labels[kept]
            boxes = np.asarray(predicted.get("boxes", []), dtype=np.float64).reshape(-1, 4)
            # An early, barely trained model can return a box with its corners crossed by a
            # fraction of a pixel; order them so the box is valid to store and match.
            boxes = np.concatenate([np.minimum(boxes[:, :2], boxes[:, 2:]), np.maximum(boxes[:, :2], boxes[:, 2:])], axis=1)
            scores = np.asarray(predicted.get("scores", []), dtype=np.float64).reshape(-1)
            labels = np.asarray(predicted.get("labels", []), dtype=np.int64).reshape(-1)
            if not (len(boxes) == len(scores) == len(labels)):
                raise CollectorError("prediction boxes, scores and labels differ in length")

            result = match_boxes(
                gt_boxes, gt_labels, boxes, labels, scores,
                iou_threshold=self.iou_threshold, class_aware=self.class_aware,
            )
            overlap = _overlap_of_first(boxes, all_boxes[skip])
            ignored = (result.pred_match < 0) & (overlap.max(axis=1) >= IGNORE_OVERLAP if overlap.size else np.zeros(len(boxes), dtype=bool))
            tp = int((result.pred_match >= 0).sum())
            fp = int(((result.pred_match < 0) & ~ignored).sum())
            fn = int((result.gt_match < 0).sum())
            if self.store_boxes:
                out[self.predicted_column].append({
                    "width": truth["width"],
                    "height": truth["height"],
                    "instances": [
                        {
                            "vertices": [float(v) for v in boxes[i]],
                            "label": int(labels[i]),
                            "confidence": float(scores[i]),
                            "iou": float(result.pred_iou[i]),
                            "matched": bool(result.pred_match[i] >= 0),
                            "ignored": bool(ignored[i]),
                        }
                        for i in np.argsort(-scores, kind="stable")
                    ],
                })
                # gt_match refers to predictions in the stored (confidence-sorted) order
                order = np.argsort(-scores, kind="stable")
                position = np.empty(len(order), dtype=np.int64)
                position[order] = np.arange(len(order))
                full_match = np.full(len(all_boxes), SKIPPED_GT, dtype=np.int64)
                full_match[kept] = [int(position[p]) if p >= 0 else -1 for p in result.gt_match]
                out["gt_match"].append([int(v) for v in full_match])
            precision = tp / (tp + fp) if tp + fp else 1.0
            recall = tp / (tp + fn) if tp + fn else 1.0
            out["tp"].append(tp)
            out["fp"].append(fp)
            out["fn"].append(fn)
            out["precision"].append(precision)
            out["recall"].append(recall)
            out["f1"].append(2 * precision * recall / (precision + recall) if precision + recall else 0.0)
        return out
