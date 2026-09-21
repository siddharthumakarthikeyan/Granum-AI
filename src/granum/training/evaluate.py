"""One scoring method for every detector, so runs from different frameworks compare.

YOLO, RT-DETR and RF-DETR each report their own validation numbers, computed with
different confidence thresholds, matching rules and averaging. Those numbers do not
compare across frameworks. This module predicts with any Granum predictor, matches
boxes with Granum's own rules (areas to skip excluded) and computes:

``map50``      mean over classes of average precision at IoU 0.5 (COCO 101-point
               interpolation), from predictions at confidence >= ``min_confidence``
``precision``, ``recall``, ``f1``   over all boxes at confidence >= ``operating_confidence``

Because predictions below ``min_confidence`` are not kept, mAP here can be slightly lower
than a framework's own figure. It is the same for every run, which is what a comparison needs.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Any

import numpy as np

from granum.core.objects.table import Table
from granum.core.schemas.geometry import BoundingBoxes2DSchema
from granum.metrics.detection import DetectionMetricsCollector

EVAL_CONFIDENCE = 0.01
#: Bumped when a change here would make new scores incomparable with recorded ones.
SCORER_VERSION = "granum-detection-1"


def evaluator_policy(*, operating_confidence: float = 0.25, iou_threshold: float = 0.5) -> dict[str, Any]:
    """The scoring rules, as a run records them.

    Two runs' scores are the same kind of number only if this matches on both sides, so it
    is recorded with the run rather than assumed later (see
    :func:`granum.metrics.comparison.compatibility_checks`).
    """
    return {
        "scorer": SCORER_VERSION,
        "operating_confidence": operating_confidence,
        "match_iou": iou_threshold,
        "min_confidence": EVAL_CONFIDENCE,
    }


def average_precision(scores: list[float], hits: list[bool], positives: int) -> float:
    """COCO-style AP: precision interpolated at 101 recall points."""
    if positives == 0:
        return float("nan")
    if not scores:
        return 0.0
    order = np.argsort(-np.asarray(scores), kind="stable")
    tp = np.asarray(hits, dtype=np.float64)[order]
    cum_tp = np.cumsum(tp)
    cum_fp = np.cumsum(1.0 - tp)
    recall = cum_tp / positives
    precision = cum_tp / np.maximum(cum_tp + cum_fp, 1e-12)
    for i in range(len(precision) - 2, -1, -1):
        precision[i] = max(precision[i], precision[i + 1])
    points = np.linspace(0, 1, 101)
    positions = np.searchsorted(recall, points, side="left")
    return float(np.mean([precision[p] if p < len(precision) else 0.0 for p in positions]))


def score_detector(
    predictor: Any,
    table: Table,
    *,
    operating_confidence: float = 0.25,
    iou_threshold: float = 0.5,
    batch_size: int = 16,
) -> dict[str, float]:
    """Framework-neutral detection scores for ``predictor`` on ``table``'s current labels."""
    column = next(n for n in table.columns if isinstance(table.schema[n], BoundingBoxes2DSchema))
    collector = DetectionMetricsCollector(column, iou_threshold=iou_threshold)
    arrow = table.to_arrow()
    images = arrow.column("image").to_pylist()
    truths = arrow.column(column).to_pylist()

    per_class_scores: dict[int, list[float]] = defaultdict(list)
    per_class_hits: dict[int, list[bool]] = defaultdict(list)
    positives: dict[int, int] = defaultdict(int)
    tp = fp = fn = 0
    for start in range(0, len(images), batch_size):
        batch = {"image": images[start:start + batch_size], column: truths[start:start + batch_size]}
        out = collector.collect(batch, predictor(batch))
        for truth, predicted in zip(batch[column], out[collector.predicted_column]):
            for instance in (truth or {}).get("instances", []):
                if not instance.get("iscrowd"):
                    positives[int(instance["label"])] += 1
            for instance in predicted["instances"]:
                if instance["ignored"]:
                    continue
                per_class_scores[instance["label"]].append(instance["confidence"])
                per_class_hits[instance["label"]].append(instance["matched"])
                if instance["confidence"] >= operating_confidence:
                    tp += int(instance["matched"])
                    fp += int(not instance["matched"])
        # Missed boxes at the operating point: every non-skipped box without a match there.
        for _truth, predicted, matches in zip(batch[column], out[collector.predicted_column], out["gt_match"]):
            confident = {i for i, p in enumerate(predicted["instances"]) if p["confidence"] >= operating_confidence}
            fn += sum(1 for m in matches if m == -1 or (m >= 0 and m not in confident))

    aps = [average_precision(per_class_scores[c], per_class_hits[c], positives[c]) for c in positives]
    aps = [a for a in aps if not np.isnan(a)]
    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / (tp + fn) if tp + fn else 0.0
    return {
        "map50": float(np.mean(aps)) if aps else 0.0,
        "precision": precision,
        "recall": recall,
        "f1": 2 * precision * recall / (precision + recall) if precision + recall else 0.0,
        "images": len(images),
    }
