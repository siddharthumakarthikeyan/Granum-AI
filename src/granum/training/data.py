"""Task-specific input contracts shared by the dashboard and training workers."""
from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

import fsspec
import numpy as np

from granum.core.schemas import CategoricalLabelListSchema, CategoricalLabelSchema
from granum.core.url import Url
from granum.errors import GranumError
from granum.formats._common import geometry_column, image_column, kept_rows, root_producer
from granum.formats.semantic import semantic_pixels
from granum.formats.vision import extra_of, mask_array


def contract(table: Any, task: str) -> dict[str, Any]:
    image = image_column(table)
    labels = [name for name in table.columns
              if isinstance(table.schema[name], CategoricalLabelSchema) and not isinstance(table.schema[name], CategoricalLabelListSchema)]
    column = labels[0] if task == "classify" and len(labels) == 1 else geometry_column(table, None)
    value_map = table.schema[column].value_map
    if not value_map:
        raise GranumError("Training needs a declared class vocabulary.")
    origin = root_producer(table, "from_coco")
    semantic = origin.get("top_level", {}).get("granum_semantic", {})
    pose = dict(origin.get("yolo") or origin.get("top_level", {}).get("granum_yolo") or {})
    layouts = {len(c["keypoints"]) for c in origin.get("categories", []) if c.get("keypoints")}
    if "kpt_shape" not in pose and len(layouts) == 1:
        pose["kpt_shape"] = [next(iter(layouts)), 3]
    return {"image": image, "column": column, "classes": sorted(value_map),
            "names": {int(k): v.internal_name for k, v in value_map.items()},
            "scalar_label": column in labels, "ignore_index": semantic.get("ignore_index", 65535),
            "pose": pose}


def classification_label(row: dict[str, Any], spec: dict[str, Any]) -> int:
    if spec["scalar_label"]:
        label = row[spec["column"]]
    else:
        geometry = row[spec["column"]] or {}
        objects = geometry.get("instances", [])
        if len(objects) != 1 or objects[0].get("iscrowd"):
            raise GranumError("Classification needs exactly one whole-image label per image.")
        box = objects[0].get("vertices", [])
        width, height = geometry.get("width", 0), geometry.get("height", 0)
        if (len(box) != 4 or not np.isfinite([*box, width, height]).all() or min(width, height) <= 0
                or not (0 <= box[0] <= .02 * width and 0 <= box[1] <= .02 * height
                        and .98 * width <= box[2] <= width and .98 * height <= box[3] <= height)):
            raise GranumError("Classification requires whole-image labels, not object boxes.")
        label = objects[0].get("label")
    if isinstance(label, bool) or not isinstance(label, int) or label not in spec["classes"]:
        raise GranumError("An image has a missing or unknown classification label.")
    return label


def validate_training(tables: dict[str, Any], task: str, *, check_media: bool = True) -> dict[str, Any]:
    """Reject task mismatch and split leakage before allocating a model or GPU.

    Byte-identical files under different names are leakage too. Only positive-weight
    training samples are used; evaluation always includes its complete frozen split.
    """
    from PIL import Image

    if "train" not in tables or "valid" not in tables:
        raise GranumError("Choose training and validation splits.")
    reference = contract(tables["train"], task)
    seen_paths: dict[str, str] = {}
    seen_hashes: dict[str, str] = {}
    counts: dict[str, int] = {}
    observed: set[int] = set()
    labelled_keypoints = 0
    for split, table in tables.items():
        spec = contract(table, task)
        if spec["names"] != reference["names"]:
            raise GranumError(f"{split}: class IDs and names must match the training split.")
        if task == "semantic" and spec["ignore_index"] != reference["ignore_index"]:
            raise GranumError(f"{split}: semantic ignore_index must match the training split.")
        rows = table.to_arrow().to_pylist()
        included = kept_rows(table, 0) if split == "train" else list(range(len(rows)))
        if not included:
            raise GranumError(f"{split}: no usable images remain.")
        counts[split] = len(included)
        for index in included:
            row = rows[index]
            source = Url(row[spec["image"]])
            path = str(Path(source.path).resolve()) if source.scheme == "file" else source.resolved
            previous = seen_paths.setdefault(path, split)
            if previous != split:
                raise GranumError(f"Data leakage: {split} and {previous} share an image.")
            if check_media:
                with fsspec.open(source.resolved, "rb") as stream:
                    digest = hashlib.file_digest(stream, "sha256").hexdigest() if hasattr(hashlib, "file_digest") else _digest(stream)
                previous = seen_hashes.setdefault(digest, split)
                if previous != split:
                    raise GranumError(f"Data leakage: {split} and {previous} contain byte-identical images.")
                with fsspec.open(source.resolved, "rb") as stream, Image.open(stream) as picture:
                    actual_size = picture.size
                    picture.verify()
            if task == "classify":
                label = classification_label(row, spec)
                if split == "train":
                    observed.add(label)
                continue
            geometry = row[spec["column"]] or {}
            width, height = int(geometry.get("width", 0)), int(geometry.get("height", 0))
            if min(width, height) <= 0 or (check_media and (width, height) != actual_size):
                raise GranumError(f"{split} row {index}: annotation dimensions must match the image.")
            if task == "semantic":
                pixels = semantic_pixels(geometry, set(spec["classes"]), spec["ignore_index"])
                usable = set(np.unique(pixels)) - {spec["ignore_index"]}
                if not usable:
                    raise GranumError(f"{split} row {index}: the semantic mask has no labelled pixels.")
                if split == "train":
                    observed.update(usable)
                continue
            for obj in geometry.get("instances", []):
                if obj.get("iscrowd"):
                    continue
                if obj.get("label") not in spec["classes"]:
                    raise GranumError(f"{split} row {index}: unknown object class.")
                vertices = obj.get("vertices", [])
                if len(vertices) != 4 or not np.isfinite(vertices).all() or not (0 <= vertices[0] < vertices[2] <= width and 0 <= vertices[1] < vertices[3] <= height):
                    raise GranumError(f"{split} row {index}: object box is outside the image or empty.")
                extra = extra_of(obj)
                if task == "segment" and not mask_array(obj.get("segmentation"), width, height).any():
                    raise GranumError(f"{split} row {index}: instance segmentation needs a nonempty mask for every object.")
                if task == "pose":
                    points = extra.get("keypoints", [])
                    count = (spec["pose"].get("kpt_shape") or [0])[0]
                    if not count or len(points) != count * 3 or not np.isfinite(points).all() or any(v not in (0, 1, 2) for v in points[2::3]):
                        raise GranumError(f"{split} row {index}: pose needs declared, consistent keypoints and visibility 0, 1 or 2.")
                    for x, y, visible in zip(points[::3], points[1::3], points[2::3]):
                        if visible and not (0 <= x <= width and 0 <= y <= height):
                            raise GranumError(f"{split} row {index}: labelled keypoint is outside the image.")
                    if split == "train":
                        labelled_keypoints += sum(v > 0 for v in points[2::3])
                if task == "obb":
                    points = extra.get("obb", [])
                    if len(points) != 8 or not np.isfinite(points).all():
                        raise GranumError(f"{split} row {index}: oriented training needs four oriented corners per object.")
    if task in ("classify", "semantic") and len(observed) < 2:
        raise GranumError("Training needs at least two represented classes, including background for semantic segmentation.")
    if task == "pose" and not labelled_keypoints:
        raise GranumError("Pose training needs labelled keypoints in the training split.")
    return {"task": task, "splits": counts, "classes": reference["names"], "split_overlap": False,
            "media_sha256_checked": check_media}


def _digest(stream: Any) -> str:
    digest = hashlib.sha256()
    for chunk in iter(lambda: stream.read(1024 * 1024), b""):
        digest.update(chunk)
    return digest.hexdigest()
