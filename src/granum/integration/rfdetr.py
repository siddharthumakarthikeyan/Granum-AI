"""RF-DETR (Roboflow): per-box metrics from a trained model, and a training hook.

RF-DETR trains through PyTorch Lightning and reads COCO datasets laid out Roboflow-style
(``train/_annotations.coco.json`` beside its images). :func:`export_rfdetr_dataset` writes
that layout from Tables; :class:`RFDETRPredictor` maps the model's 0-based class indices
back to the Table's classes by name, as the YOLO predictor does.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np

from granum.core.objects.table import Table
from granum.core.schemas.geometry import BoundingBoxes2DSchema
from granum.core.url import Url
from granum.formats._common import (
    clean_number,
    geometry_column,
    image_column,
    kept_rows,
    place_image,
)
from granum.integration.ultralytics import IntegrationError

VARIANTS = {
    "nano": "RFDETRNano",
    "small": "RFDETRSmall",
    "medium": "RFDETRMedium",
    "base": "RFDETRBase",
    "large": "RFDETRLarge",
}


def load_rfdetr(variant: str, weights: str | Path | None = None) -> Any:
    import rfdetr

    if variant not in VARIANTS:
        raise IntegrationError(f"unknown RF-DETR variant {variant!r}; choose one of {sorted(VARIANTS)}")
    cls = getattr(rfdetr, VARIANTS[variant])
    return cls(pretrain_weights=str(weights)) if weights else cls()


def export_rfdetr_dataset(splits: dict[str, Table], output: str | Path, *, image_strategy: str = "symlink") -> Path:
    """Write Tables as a Roboflow-style COCO dataset RF-DETR can train on.

    Split names map to RF-DETR's ``train`` / ``valid`` / ``test`` folders. Classes get
    contiguous ids in the Table's class order and no supercategory, so RF-DETR cannot
    mistake a class for a parent category. Rows with weight 0 and boxes flagged
    ``iscrowd`` (areas to skip) are left out.
    """
    output = Path(output)
    value_map = None
    for table in splits.values():
        schema: BoundingBoxes2DSchema = table.schema[geometry_column(table, None)]  # type: ignore[assignment]
        names = {k: v.internal_name for k, v in schema.value_map.items()}
        if value_map is None:
            value_map = names
        elif names != value_map:
            raise IntegrationError("splits disagree on classes")
    assert value_map is not None
    order = sorted(value_map)
    remap = {source: target for target, source in enumerate(order)}
    categories = [{"id": remap[k], "name": value_map[k], "supercategory": "none"} for k in order]

    for split, table in splits.items():
        folder = output / split
        folder.mkdir(parents=True, exist_ok=True)
        box_column = geometry_column(table, None)
        arrow = table.to_arrow()
        paths = arrow.column(image_column(table)).to_pylist()
        values = arrow.column(box_column).to_pylist()
        images, annotations, used = [], [], set()
        for row in kept_rows(table, 0.0):
            name = Path(Url(paths[row]).resolved).name
            if name in used:
                name = f"{row}_{name}"
            used.add(name)
            place_image(paths[row], folder / name, image_strategy)
            value = values[row] or {"width": 0, "height": 0, "instances": []}
            image_id = len(images)
            images.append({"id": image_id, "file_name": name, "width": int(value["width"]), "height": int(value["height"])})
            for instance in value["instances"]:
                if instance.get("iscrowd"):
                    continue
                x0, y0, x1, y1 = instance["vertices"]
                annotations.append({
                    "id": len(annotations) + 1, "image_id": image_id, "category_id": remap[instance["label"]],
                    "bbox": [clean_number(x0), clean_number(y0), clean_number(x1 - x0), clean_number(y1 - y0)],
                    "area": clean_number((x1 - x0) * (y1 - y0)), "iscrowd": 0,
                })
        (folder / "_annotations.coco.json").write_text(json.dumps({
            "images": images, "annotations": annotations, "categories": categories,
        }))
    return output


class RFDETRPredictor:
    """Calls an RF-DETR model on a batch's image paths."""

    def __init__(self, model: Any, value_map: dict[int, Any], *, image_column: str = "image", conf: float = 0.25) -> None:
        self.model = model
        by_name = {entry.internal_name: key for key, entry in value_map.items()}
        self.class_map = {i: by_name[name] for i, name in enumerate(model.class_names) if name in by_name}
        self.image_column = image_column
        self.conf = conf

    def __call__(self, batch: dict[str, list[Any]]) -> list[dict[str, np.ndarray]]:
        from PIL import Image

        images = []
        for path in batch[self.image_column]:
            with Image.open(Url(path).resolved) as image:
                images.append(image.convert("RGB"))
        detections = self.model.predict(images, threshold=self.conf, include_source_image=False)
        if not isinstance(detections, list):
            detections = [detections]
        outputs = []
        for detected in detections:
            class_ids = np.asarray(detected.class_id, dtype=np.int64)
            keep = np.array([c in self.class_map for c in class_ids], dtype=bool)
            outputs.append({
                "boxes": np.asarray(detected.xyxy, dtype=np.float64)[keep].reshape(-1, 4),
                "scores": np.asarray(detected.confidence, dtype=np.float64)[keep],
                "labels": np.array([self.class_map[int(c)] for c in class_ids[keep]], dtype=np.int64),
            })
        return outputs
