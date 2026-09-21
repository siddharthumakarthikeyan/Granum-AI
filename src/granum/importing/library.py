"""Pulling images from existing projects into a new one.

The classes of every project are listed together, matched by name across projects. A pull
picks projects and classes, and writes one COCO file per split holding the images that
contain any of those classes. Classes are chosen per project, so a class can come from
every project that has it or from particular ones only. The files then go through
preflight and import like any other source, so duplicates, leakage and bad boxes are
caught the same way.
"""

from __future__ import annotations

import json
import os
import shutil
import time
from collections.abc import Iterable
from typing import Any

import numpy as np
import pyarrow as pa
import pyarrow.compute as pc

from granum.core.objects.table import Table
from granum.core.schemas import Geometry2DSchema
from granum.core.url import Url
from granum.errors import GranumError

#: Pull folders older than this are removed when the next pull is written.
KEEP_PULLS_SECONDS = 7 * 24 * 3600


class PullError(GranumError):
    """Images could not be pulled from the chosen projects."""


def class_key(name: str) -> str:
    """Classes match across projects by name, ignoring case and spacing."""
    return " ".join(str(name).split()).casefold()


def box_column(table: Table) -> str | None:
    return next((n for n in table.columns if isinstance(table.schema[n], Geometry2DSchema)), None)


def count_instances(column: Any, rows: int) -> tuple[list[int], list[list[int]]] | None:
    """Objects per row and the classes each row uses, ignoring crowd regions, in arrow.

    The aerial train set holds 425,000 boxes; walking them as Python dicts took seconds.
    None if the column is not shaped as expected, and the caller walks it instead.
    """
    flat = _flatten(column, rows)
    if flat is None:
        return None
    parents, labels, keep = flat
    objects = np.bincount(parents[keep], minlength=rows).tolist()
    labelled = keep & (labels >= 0)
    pairs = np.unique(np.stack([parents[labelled], labels[labelled]]), axis=1)
    classes: list[list[int]] = [[] for _ in range(rows)]
    for row, label in pairs.T.tolist():
        classes[row].append(label)
    return objects, classes


def _flatten(column: Any, rows: int) -> tuple[np.ndarray, np.ndarray, np.ndarray] | None:
    """Per box: its row, its label (-1 when unlabelled) and whether it is not a crowd region."""
    try:
        values = column.combine_chunks() if hasattr(column, "combine_chunks") else column
        instances = pc.struct_field(values, "instances")
        if len(instances) != rows:
            return None
        flat = pc.list_flatten(instances)
        parents = pc.list_parent_indices(instances).to_numpy(zero_copy_only=False)
        names = {flat.type.field(i).name for i in range(flat.type.num_fields)}
        if "label" not in names:
            return None
        labels = pc.fill_null(pc.cast(pc.struct_field(flat, "label"), pa.int64()), -1).to_numpy(zero_copy_only=False)
        keep = np.ones(len(flat), dtype=bool)
        if "iscrowd" in names:
            crowd = pc.fill_null(pc.cast(pc.struct_field(flat, "iscrowd"), pa.bool_()), False)
            keep &= ~crowd.to_numpy(zero_copy_only=False)
    except (pa.ArrowException, KeyError, TypeError, ValueError):
        return None
    return parents, labels, keep


def table_classes(table: Table) -> dict[str, dict[str, Any]]:
    """Class key -> {name, images, boxes} for one set version."""
    column = box_column(table)
    if column is None:
        return {}
    value_map = table.schema[column].value_map or {}
    arrow = table.to_arrow()
    flat = _flatten(arrow.column(column), len(arrow))
    out: dict[str, dict[str, Any]] = {}
    if flat is None:
        return out
    parents, labels, keep = flat
    labelled = keep & (labels >= 0)
    boxes = np.bincount(labels[labelled], minlength=0) if labelled.any() else np.array([], dtype=np.int64)
    pairs = np.unique(np.stack([parents[labelled], labels[labelled]]), axis=1) if labelled.any() else np.zeros((2, 0), dtype=np.int64)
    images = np.bincount(pairs[1], minlength=len(boxes)) if pairs.size else np.zeros(len(boxes), dtype=np.int64)
    for label, entry in value_map.items():
        name = entry.display_name or entry.internal_name
        n_boxes = int(boxes[label]) if 0 <= label < len(boxes) else 0
        n_images = int(images[label]) if 0 <= label < len(images) else 0
        key = class_key(name)
        known = out.setdefault(key, {"name": name, "images": 0, "boxes": 0})
        known["images"] += n_images
        known["boxes"] += n_boxes
    return out


def _local_path(image: str) -> str:
    url = Url(image)
    if url.scheme != "file":
        raise PullError(f"only images on this computer can be pulled; {image} is not")
    return os.path.normpath(url.path)


def pull(sets: Iterable[tuple[str, Table, Iterable[str] | None]], *, keep_other_labels: bool, out_dir: Url) -> dict[str, Any]:
    """Write COCO files, one per split, of the images holding any of the chosen classes.

    ``sets`` are (project, set version, class keys) triples: the classes wanted from that
    project, None or empty for every image. Each set's split name (train, valid, ...) is the
    split its images land in. Unless ``keep_other_labels``, only boxes of the chosen classes
    are kept. An image found twice (in two projects, or two splits) is taken once, where first seen.
    """
    categories: dict[str, dict[str, Any]] = {}
    splits: dict[str, dict[str, Any]] = {}
    seen: set[str] = set()
    duplicates = 0
    from_projects: set[str] = set()

    for project, table, classes in sets:
        wanted = {class_key(c) for c in classes or []}
        column = box_column(table)
        if column is None:
            continue
        from granum.core.curation import CurationError, image_column

        try:
            picture = image_column(table)
        except CurationError:
            continue
        value_map = table.schema[column].value_map or {}
        names = {label: (entry.display_name or entry.internal_name) for label, entry in value_map.items()}
        arrow = table.to_arrow()
        paths = arrow.column(picture).to_pylist()
        values = arrow.column(column).to_pylist()
        split = splits.setdefault(table.base_name, {"images": [], "annotations": []})
        for path, value in zip(paths, values):
            if not path or not value:
                continue
            instances = value.get("instances") or []
            chosen = [i for i in instances if class_key(names.get(i.get("label"), "")) in wanted] if wanted else instances
            if wanted and not any(not i.get("iscrowd") for i in chosen):
                continue
            local = _local_path(path)
            if local in seen:
                duplicates += 1
                continue
            seen.add(local)
            from_projects.add(project)
            image_id = len(split["images"]) + 1
            split["images"].append({"id": image_id, "path": local, "width": value.get("width"), "height": value.get("height")})
            for instance in (instances if keep_other_labels else chosen):
                name = names.get(instance.get("label"))
                if name is None:
                    continue
                category = categories.setdefault(class_key(name), {"id": len(categories) + 1, "name": name})
                x0, y0, x1, y1 = instance["vertices"]
                annotation: dict[str, Any] = {
                    "image_id": image_id, "category_id": category["id"],
                    "bbox": [x0, y0, x1 - x0, y1 - y0],
                    "area": instance.get("area") if instance.get("area") is not None else (x1 - x0) * (y1 - y0),
                    "iscrowd": int(bool(instance.get("iscrowd"))),
                }
                if instance.get("segmentation"):
                    annotation["segmentation"] = json.loads(instance["segmentation"])
                if instance.get("coco_extra"):
                    annotation.update(json.loads(instance["coco_extra"]))
                split["annotations"].append(annotation)

    splits = {name: s for name, s in splits.items() if s["images"]}
    if not splits:
        raise PullError("no image in the chosen projects has the chosen classes")

    _clean_old(out_dir.parent)
    sources = []
    for name, split in splits.items():
        paths = [image["path"] for image in split["images"]]
        try:
            folder = os.path.commonpath(paths) if len(paths) > 1 else os.path.dirname(paths[0])
        except ValueError as exc:  # different drives on Windows
            raise PullError(f"the {name} images are on different drives and cannot be pulled together") from exc
        if folder in paths:
            folder = os.path.dirname(folder)
        images = [
            {"id": image["id"], "file_name": os.path.relpath(image["path"], folder).replace(os.sep, "/"),
             "width": image["width"], "height": image["height"]}
            for image in split["images"]
        ]
        for n, annotation in enumerate(split["annotations"], start=1):
            annotation["id"] = n
        document = {"images": images, "annotations": split["annotations"],
                    "categories": sorted(categories.values(), key=lambda c: c["id"])}
        target = out_dir / name / "_annotations.coco.json"
        target.parent.mkdir()
        target.write_text(json.dumps(document))
        sources.append({"split": name, "annotations": str(target), "images": folder,
                        "count": len(images), "boxes": len(split["annotations"])})
    return {
        "sources": sources,
        "images": sum(s["count"] for s in sources),
        "boxes": sum(s["boxes"] for s in sources),
        "duplicates": duplicates,
        "projects": sorted(from_projects),
    }


def _clean_old(folder: Url) -> None:
    if folder.scheme != "file" or not os.path.isdir(folder.path):
        return
    now = time.time()
    for name in os.listdir(folder.path):
        path = os.path.join(folder.path, name)
        try:
            if os.path.isdir(path) and now - os.path.getmtime(path) > KEEP_PULLS_SECONDS:
                shutil.rmtree(path, ignore_errors=True)
        except OSError:
            continue
