"""Per-image and per-class semantic metrics with lossless prediction overlays."""
from __future__ import annotations

from typing import Any

import numpy as np

from granum.core.schemas import FractionSchema, Int64Schema, Schema
from granum.core.schemas.geometry import BoundingBoxes2DSchema
from granum.formats.semantic import semantic_pixels
from granum.formats.vision import encode_mask
from granum.metrics.collectors import CollectorError, MetricsCollector
from granum.metrics.predictor import Prediction
from granum.metrics.vision import semantic_scores


class SemanticMetricsCollector(MetricsCollector):
    """Collect class-ID predictions at the original image resolution.

    Each prediction is a 2D integer label map. ``ignore_index`` pixels in the ground
    truth are excluded. Class intersections/unions permit correct aggregation across
    differently sized images; an absent class has no IoU rather than a perfect score.
    """

    def __init__(self, value_map: dict[int, Any], *, gt_column: str = "bbs", ignore_index: int = 255,
                 predicted_column: str = "bbs_predicted", store_masks: bool = True) -> None:
        if not value_map or ignore_index in value_map:
            raise CollectorError("provide semantic classes and a distinct ignore_index")
        if any(type(label) is not int or not 0 <= label <= 65535 for label in [ignore_index, *value_map]):
            raise CollectorError("semantic class IDs and ignore_index must be integers between 0 and 65535")
        self.value_map, self.gt_column, self.ignore_index = value_map, gt_column, ignore_index
        self.predicted_column, self.store_masks = predicted_column, store_masks

    def column_schemas(self) -> dict[str, Schema]:
        result: dict[str, Schema] = {"pixel_accuracy": FractionSchema(), "mean_iou": FractionSchema(),
                                     "pixel_correct": Int64Schema(), "pixel_count": Int64Schema()}
        for label in self.value_map:
            result.update({f"class_{label}_iou": FractionSchema(description=f"Pixel IoU for {self.value_map[label].internal_name}; absent classes are null."),
                           f"class_{label}_intersection": Int64Schema(), f"class_{label}_union": Int64Schema()})
        if self.store_masks:
            result[self.predicted_column] = BoundingBoxes2DSchema(value_map=self.value_map, writable=False,
                                                                  instance_properties={"segmentation": "string", "area": "float64"})
        return result

    def collect(self, batch: dict[str, list[Any]], prediction: Prediction | None) -> dict[str, list[Any]]:
        import json

        outputs = prediction.outputs if isinstance(prediction, Prediction) else prediction
        if outputs is None or self.gt_column not in batch or len(outputs) != len(batch[self.gt_column]):
            raise CollectorError("semantic predictions must have one label map per input image")
        out: dict[str, list[Any]] = {key: [] for key in self.column_schemas()}
        for geometry, output in zip(batch[self.gt_column], outputs):
            truth = semantic_pixels(geometry, set(self.value_map), self.ignore_index)
            pixels = np.asarray(output)
            scores = semantic_scores(pixels, truth, list(self.value_map), ignore_index=self.ignore_index)
            valid = truth != self.ignore_index
            out["pixel_accuracy"].append(scores["pixel_accuracy"])
            out["mean_iou"].append(scores["mean_iou"])
            out["pixel_count"].append(int(valid.sum()))
            out["pixel_correct"].append(int(((pixels == truth) & valid).sum()))
            instances = []
            for label in self.value_map:
                counts = scores["classes"].get(label)
                out[f"class_{label}_iou"].append(counts["iou"] if counts else None)
                out[f"class_{label}_intersection"].append(counts["intersection"] if counts else 0)
                out[f"class_{label}_union"].append(counts["union"] if counts else 0)
                if self.store_masks:
                    mask = pixels == label
                    if mask.any():
                        ys, xs = np.nonzero(mask)
                        instances.append({"label": label, "vertices": [int(xs.min()), int(ys.min()), int(xs.max() + 1), int(ys.max() + 1)],
                                          "area": int(mask.sum()), "segmentation": json.dumps(encode_mask(mask))})
            if self.store_masks:
                out[self.predicted_column].append({"width": geometry["width"], "height": geometry["height"], "instances": instances})
        return out
