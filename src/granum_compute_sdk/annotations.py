"""First-party annotation inspection. Box overlap is a proxy, not measured occlusion."""
from __future__ import annotations

import math

from . import Context, Result


def run(context: Context) -> Result:
    columns = {key: [] for key in ("object_count", "small_object_count", "border_touch_count", "max_box_iou")}
    for index, sample in enumerate(context.samples):
        geometry = sample.values["annotations"] or {}
        width, height = geometry.get("width", 0), geometry.get("height", 0)
        if not isinstance(width, (int, float)) or not isinstance(height, (int, float)) or not math.isfinite(width * height) or min(width, height) <= 0:
            raise ValueError(f"sample {sample.id} needs positive image dimensions")
        boxes = []
        for instance in geometry.get("instances", []):
            # COCO crowd regions are excluded from individual-object statistics.
            if instance.get("iscrowd"):
                continue
            vertices = instance.get("vertices", [])
            if len(vertices) != 4 or any(not isinstance(v, (int, float)) or not math.isfinite(v) for v in vertices):
                raise ValueError(f"sample {sample.id} has an invalid box")
            x, y, right, bottom = vertices
            if right <= x or bottom <= y:
                raise ValueError(f"sample {sample.id} has an empty box")
            boxes.append((x, y, right, bottom, (right - x) * (bottom - y)))
        if len(boxes) > 2000:
            raise ValueError(f"sample {sample.id} exceeds the 2,000-box overlap budget")
        maximum = 0.0
        for i, a in enumerate(boxes):
            for b in boxes[i + 1:]:
                area = max(0, min(a[2], b[2]) - max(a[0], b[0])) * max(0, min(a[3], b[3]) - max(a[1], b[1]))
                maximum = max(maximum, area / (a[4] + b[4] - area))
        margin = context.parameters["border_margin"]
        columns["object_count"].append(len(boxes))
        columns["small_object_count"].append(sum(b[4] < context.parameters["small_area"] for b in boxes))
        columns["border_touch_count"].append(sum(b[0] <= margin or b[1] <= margin or b[2] >= width - margin or b[3] >= height - margin for b in boxes))
        columns["max_box_iou"].append(maximum)
        if index % 100 == 0 or index + 1 == len(context.samples):
            context.progress(index + 1, len(context.samples), "Inspecting annotations")
    return Result([sample.id for sample in context.samples], columns,
                  {"images": len(context.samples), "objects": sum(columns["object_count"]),
                   "overlap_note": "Box IoU is an overlap proxy; it does not measure visibility or occlusion."})
