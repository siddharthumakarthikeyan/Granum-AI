"""Lossless semantic class-ID PNG datasets, backed by Granum's editable COCO masks.

A ``semantic.json`` manifest contains ``format: granum-semantic-masks``, ``version: 1``,
``categories: [{id, name}]``, an ``ignore_index`` (default 255), and
``images: [{file_name: 'images/a.png', mask: 'masks/a.png'}]``. Paths are relative to
the manifest. RGB masks additionally need each category's ``color: [r,g,b]`` and
an explicit ``ignore_color``. Palette PNGs retain their numeric palette indices.
"""
from __future__ import annotations

import json
import os
from collections.abc import Callable
from pathlib import Path
from typing import Any

import numpy as np

from granum.core.objects.table import Table
from granum.core.url import Url
from granum.errors import TableError
from granum.formats._common import (
    geometry_column,
    image_column,
    kept_rows,
    place_image,
    root_producer,
)
from granum.formats.coco import table_from_coco_data
from granum.formats.vision import encode_mask, mask_array


def _class_id(value: Any) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= 65535:
        raise TableError("semantic class IDs and ignore_index must be integers between 0 and 65535")
    return value


def _color(value: Any) -> tuple[int, int, int]:
    if not isinstance(value, list) or len(value) != 3 or any(isinstance(v, bool) or not isinstance(v, int) or not 0 <= v <= 255 for v in value):
        raise TableError("RGB masks require an RGB color for every class and ignore_color")
    return tuple(value)


def semantic_to_coco(manifest: str | Path, *, images_dir: str | Path | None = None,
                     check_path: Callable[[str], Any] | None = None) -> dict[str, Any]:
    from PIL import Image

    path = Path(manifest)
    document = json.loads(path.read_text())
    if not isinstance(document, dict) or document.get("format") != "granum-semantic-masks" or document.get("version") != 1:
        raise TableError("expected a version 1 granum-semantic-masks manifest")
    categories, entries = document.get("categories"), document.get("images")
    if not isinstance(categories, list) or not 1 <= len(categories) <= 4096:
        raise TableError("provide between 1 and 4096 semantic categories")
    if not isinstance(entries, list) or not entries:
        raise TableError("provide images with a file_name and a mask")
    ignore = _class_id(document.get("ignore_index", 255))
    labels: set[int] = set()
    for category in categories:
        if not isinstance(category, dict):
            raise TableError("each semantic category needs an id and a name")
        label = _class_id(category.get("id"))
        if label == ignore or label in labels or not isinstance(category.get("name"), str) or not category["name"].strip():
            raise TableError("semantic categories need unique IDs and names, distinct from ignore_index")
        labels.add(label)
    folder = Path(images_dir) if images_dir is not None else path.parent
    images, annotations = [], []
    seen: set[Path] = set()
    for index, entry in enumerate(entries):
        if not isinstance(entry, dict) or not all(isinstance(entry.get(key), str) and entry[key] for key in ("file_name", "mask")):
            raise TableError("each semantic image needs file_name and mask paths")
        image_path, mask_path = (folder / entry["file_name"]).resolve(), (path.parent / entry["mask"]).resolve()
        if check_path is not None:
            check_path(str(image_path))
            check_path(str(mask_path))
        if image_path in seen:
            raise TableError(f"duplicate semantic image: {image_path.name}")
        seen.add(image_path)
        with Image.open(image_path) as image, Image.open(mask_path) as mask:
            if mask.format != "PNG":
                raise TableError("use lossless PNG files for semantic masks")
            width, height = image.size
            if mask.size != image.size or width * height > 100_000_000:
                raise TableError(f"{mask_path.name}: mask dimensions must match the image and fit within 100 million pixels")
            pixels = np.asarray(mask)
            if pixels.ndim == 3:
                if pixels.shape[2] != 3:
                    raise TableError("use RGB, grayscale or palette PNG masks; alpha channels are not class labels")
                pixels_rgb = pixels
                pixels = np.full((height, width), -1, dtype=np.int32)
                colors = {_color(document.get("ignore_color")): ignore}
                for category in categories:
                    color = _color(category.get("color"))
                    if color in colors:
                        raise TableError("semantic RGB colors must be unique, including ignore_color")
                    colors[color] = category["id"]
                for color, label in colors.items():
                    pixels[np.all(pixels_rgb == color, axis=2)] = label
            if pixels.ndim != 2 or pixels.dtype.kind not in "uib":
                raise TableError("semantic masks must contain integer class IDs")
            unknown = set(np.unique(pixels).tolist()) - labels - {ignore}
            if unknown:
                raise TableError(f"{mask_path.name}: unknown class IDs or RGB colors: {sorted(unknown)[:8]}")
            images.append({"id": index, "file_name": os.path.relpath(image_path, folder), "width": width, "height": height})
            for label in sorted(labels & set(np.unique(pixels).tolist())):
                binary = pixels == label
                ys, xs = np.nonzero(binary)
                annotations.append({"id": len(annotations), "image_id": index, "category_id": label,
                                    "bbox": [int(xs.min()), int(ys.min()), int(xs.max() - xs.min() + 1), int(ys.max() - ys.min() + 1)],
                                    "area": int(binary.sum()), "iscrowd": 0, "segmentation": encode_mask(binary)})
    return {"images": images, "annotations": annotations, "categories": categories,
            "granum_semantic": {"ignore_index": ignore}, "info": {"description": "Semantic class-ID masks"}}


def table_from_semantic_masks(manifest: str | Path, **kwargs: Any) -> Table:
    path = Path(manifest)
    return table_from_coco_data(semantic_to_coco(path), source=str(path), image_folder=str(path.parent),
                                producer_args={"tasks": ["semantic_segmentation"]}, **kwargs)


def semantic_pixels(value: dict[str, Any], classes: set[int], ignore_index: int) -> np.ndarray:
    """Rasterize editable regions; different classes must never silently overwrite."""
    width, height = int(value.get("width") or 0), int(value.get("height") or 0)
    if min(width, height) <= 0 or width * height > 100_000_000:
        raise TableError("semantic masks need known dimensions up to 100 million pixels")
    pixels = np.full((height, width), ignore_index, dtype=np.uint16)
    ignored = np.zeros((height, width), dtype=bool)
    for instance in value.get("instances", []):
        binary = mask_array(instance.get("segmentation"), width, height).astype(bool)
        if not binary.any():
            raise TableError("each semantic object needs a nonempty mask")
        if instance.get("iscrowd"):
            ignored |= binary
            continue
        label = instance.get("label")
        if label not in classes:
            raise TableError(f"semantic object has an unknown class: {label}")
        if np.any(binary & (pixels != ignore_index) & (pixels != label)):
            raise TableError("different semantic classes overlap; correct their masks before exporting")
        pixels[binary] = label
    pixels[ignored] = ignore_index
    return pixels


def export_semantic_masks(table: Table, output: str | Path, *, column: str | None = None,
                          image_strategy: str | None = "copy", weight_threshold: float | None = 0.0,
                          ignore_index: int | None = None) -> Path:
    from PIL import Image

    geometry, pictures = geometry_column(table, column), image_column(table)
    categories = [{"id": _class_id(int(label)), "name": entry.internal_name} for label, entry in table.schema[geometry].value_map.items()]
    classes = {c["id"] for c in categories}
    original = root_producer(table, "from_coco").get("top_level", {}).get("granum_semantic", {})
    if ignore_index is None:
        ignore_index = original.get("ignore_index")
        if ignore_index is None:
            ignore_index = next((i for i in [255, 65535, *range(65536)] if i not in classes), None)
    ignore_index = _class_id(ignore_index)
    if ignore_index in classes:
        raise TableError("ignore_index must differ from every semantic class ID")
    out = Path(output)
    if out.exists() and any(out.iterdir()):
        raise TableError("choose an empty directory for the semantic export")
    rows = table.to_arrow().to_pylist()
    included = kept_rows(table, weight_threshold)
    # Validate all label maps before copying any images or creating mask files.
    for row in included:
        semantic_pixels(rows[row][geometry], classes, ignore_index)
    (out / "masks").mkdir(parents=True, exist_ok=True)
    images = []
    for row in included:
        source = rows[row][pictures]
        image_name = f"{row:06d}-{Path(Url(source).resolved).name}"
        image_path = str(Path("images") / image_name) if image_strategy else Url(source).resolved
        if image_strategy:
            place_image(source, out / image_path, image_strategy)
        mask_path = Path("masks") / f"{row:06d}.png"
        pixels = semantic_pixels(rows[row][geometry], classes, ignore_index)
        if max([ignore_index, *classes]) < 256:
            pixels = pixels.astype(np.uint8)
        Image.fromarray(pixels).save(out / mask_path)
        images.append({"file_name": image_path, "mask": str(mask_path)})
    manifest = out / "semantic.json"
    manifest.write_text(json.dumps({"format": "granum-semantic-masks", "version": 1, "ignore_index": ignore_index,
                                    "categories": categories, "images": images}, indent=2))
    return manifest
