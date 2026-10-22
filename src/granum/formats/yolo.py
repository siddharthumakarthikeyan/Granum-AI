"""YOLO detection datasets <-> Table.

Follows the Ultralytics layout: a dataset YAML names the splits and classes; each image
``.../images/x.jpg`` has labels in ``.../labels/x.txt``, one ``class cx cy w h`` line per box
with coordinates normalised to the image size. An image without a label file is a
background image with no boxes, not an error.
"""

from __future__ import annotations

import math
import os
from pathlib import Path
from typing import Any

import yaml

from granum.core.config import Config
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
from granum.formats.vision import extra_of, polygon_area, polygon_bounds, yolo_polygon

BOX_COLUMN = "bbs"
IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".bmp", ".webp", ".tif", ".tiff", ".dng", ".mpo"}
TASKS = ("detect", "segment", "pose", "obb")
TASK_IDS = {"detect": "object_detection", "segment": "instance_segmentation", "pose": "keypoint_detection", "obb": "oriented_object_detection"}
POSE_KEYS = ("kpt_shape", "flip_idx", "kpt_names", "kpt_oks_sigmas", "skeleton")
_EXIF_ORIENTATION = 274


def _image_size(path: str) -> tuple[int, int]:
    """Width and height as a model sees them: EXIF rotation applied, pixels not decoded."""
    from PIL import Image

    with Image.open(path) as image:
        width, height = image.size
        try:
            if image.getexif().get(_EXIF_ORIENTATION) in (5, 6, 7, 8):
                width, height = height, width
        except Exception:  # noqa: BLE001 - unreadable EXIF is not an unreadable image
            pass
    return width, height


def _label_path(image_path: str) -> str:
    head, sep, tail = image_path.rpartition(f"{os.sep}images{os.sep}")
    if not sep:
        raise TableError(f"{image_path} is not under an 'images' directory, so its labels cannot be found")
    return os.path.splitext(f"{head}{os.sep}labels{os.sep}{tail}")[0] + ".txt"


def _resolve_root(document: dict[str, Any], yaml_path: Path, root: str | Path | None) -> Path:
    if root is not None:
        return Path(root)
    declared = document.get("path")
    if not declared:
        return yaml_path.parent
    declared = Path(declared)
    if declared.is_absolute():
        return declared
    for base in (yaml_path.parent, yaml_path.parent.parent, Path.cwd()):
        if (base / declared).exists():
            return base / declared
    raise TableError(
        f"dataset root {declared} (from 'path' in {yaml_path.name}) was not found next to the YAML; pass root=..."
    )


def _split_images(root: Path, entry: Any) -> list[str]:
    entries = entry if isinstance(entry, list) else [entry]
    images: list[str] = []
    for item in entries:
        location = root / str(item)
        if location.is_dir():
            images += sorted(
                str(p) for p in location.rglob("*") if p.suffix.lower() in IMAGE_SUFFIXES
            )
        elif location.suffix == ".txt" and location.exists():
            for line in location.read_text().splitlines():
                line = line.strip()
                if line:
                    candidate = Path(line)
                    images.append(str(candidate if candidate.is_absolute() else (location.parent / candidate).resolve()))
        else:
            raise TableError(f"split entry {item!r} is neither a directory nor a .txt list under {root}")
    return images


def _names(document: dict[str, Any]) -> dict[int, str]:
    names = document.get("names")
    if isinstance(names, dict):
        return {int(k): str(v) for k, v in names.items()}
    if isinstance(names, list):
        return dict(enumerate(str(n) for n in names))
    raise TableError("the dataset YAML has no 'names' mapping of class ids to names")


def _validate_pose(metadata: dict[str, Any]) -> None:
    shape = metadata.get("kpt_shape")
    if (not isinstance(shape, list) or len(shape) != 2 or type(shape[0]) is not int
        or not 1 <= shape[0] <= 4096 or type(shape[1]) is not int or shape[1] not in (2, 3)):
        raise TableError("pose datasets need kpt_shape: [number_of_points, 2 or 3] (at most 4096 points)")
    count = shape[0]
    flips = metadata.get("flip_idx")
    if flips is not None and flips != [] and (not isinstance(flips, list) or len(flips) != count
        or any(type(i) is not int for i in flips) or sorted(flips) != list(range(count))
        or any(flips[flips[i]] != i for i in range(count))):
        raise TableError("flip_idx must be an involutive permutation of the keypoint indices")
    sigmas = metadata.get("kpt_oks_sigmas")
    if sigmas is not None and (not isinstance(sigmas, list) or len(sigmas) != count
        or any(type(v) not in (int, float) or not math.isfinite(v) or v <= 0 for v in sigmas)):
        raise TableError("kpt_oks_sigmas needs one finite, positive sigma per keypoint")
    names = metadata.get("kpt_names")
    if names is not None and (not isinstance(names, dict) or any(
        not isinstance(value, list) or len(value) != count
        or any(not isinstance(name, str) or not name.strip() for name in value)
        or len(set(value)) != count for value in names.values()
    )):
        raise TableError("kpt_names needs one unique name per keypoint, for each class")


def read_yolo(data_yaml: Url | str, split: str = "train", *, task: str | None = None,
              root: str | Path | None = None) -> tuple[dict[str, Any], dict[str, Any]]:
    """Read every label, or fail with its file and line. Never discard an unknown layout."""
    path = Path(Url(data_yaml).resolved)
    document = yaml.safe_load(path.read_text()) or {}
    if not isinstance(document, dict) or not document.get(split):
        raise TableError(f"{path.name} has no {split!r} split")
    task = task or document.get("task") or ("pose" if document.get("kpt_shape") else "detect")
    if task not in TASKS:
        raise TableError(f"task {task!r} is not supported; supported: {TASKS}")
    names = _names(document)
    dataset_root = _resolve_root(document, path, root)
    images = _split_images(dataset_root, document[split])
    if not images:
        raise TableError(f"no images found for split {split!r} under {dataset_root}")
    pose = {k: document[k] for k in POSE_KEYS if k in document}
    if task == "pose":
        _validate_pose(pose)
    categories = [{"id": key, "name": name} for key, name in sorted(names.items())]
    for category in categories:
        points = (pose.get("kpt_names") or {}).get(category["id"], (pose.get("kpt_names") or {}).get(str(category["id"])))
        if points:
            category["keypoints"] = points
        if pose.get("skeleton"):
            category["skeleton"] = pose["skeleton"]
    coco: dict[str, Any] = {"images": [], "annotations": [], "categories": categories,
                            "granum_yolo": {"task": task, **pose}}
    for image_id, picture in enumerate(images, 1):
        width, height = _image_size(picture)
        coco["images"].append({"id": image_id, "file_name": os.path.relpath(Path(picture).resolve(), path.parent.resolve()), "width": width, "height": height})
        label_file = Path(_label_path(picture))
        if not label_file.exists():
            continue
        for number, line in enumerate(label_file.read_text().splitlines(), 1):
            parts = line.split()
            if not parts:
                continue
            where = f"{label_file}:{number}"
            try:
                label, coords = int(parts[0]), [float(v) for v in parts[1:]]
            except ValueError as exc:
                raise TableError(f"{where}: label must be an integer and coordinates numeric") from exc
            if label not in names:
                raise TableError(f"{where}: class {label} is not in the dataset names")
            if not all(math.isfinite(v) for v in coords):
                raise TableError(f"{where}: coordinates must be finite")
            annotation: dict[str, Any] = {"id": len(coco["annotations"]) + 1, "image_id": image_id, "category_id": label, "iscrowd": 0}
            if task in ("detect", "pose"):
                expected = 4 if task == "detect" else 4 + pose["kpt_shape"][0] * pose["kpt_shape"][1]
                if len(coords) != expected:
                    raise TableError(f"{where}: expected 'class cx cy w h'" + (" plus keypoints" if task == "pose" else "") + f" ({expected + 1} values) for {task}; choose the matching YOLO task")
                cx, cy, bw, bh = coords[:4]
                if min(cx, cy, bw, bh) < 0 or max(cx, cy, bw, bh) > 1 or min(bw, bh) <= 0:
                    raise TableError(f"{where}: box coordinates must be normalized, with positive width and height")
                bbox = [(cx - bw / 2) * width, (cy - bh / 2) * height, bw * width, bh * height]
                if task == "pose":
                    count, dims = pose["kpt_shape"]
                    keypoints = []
                    for at in range(count):
                        point = coords[4 + at * dims:4 + (at + 1) * dims]
                        x, y = point[:2]
                        visibility = point[2] if dims == 3 else (0 if x == 0 and y == 0 else 2)
                        if visibility not in (0, 1, 2) or not 0 <= x <= 1 or not 0 <= y <= 1:
                            raise TableError(f"{where}: invalid keypoint coordinates or visibility (0, 1, 2)")
                        keypoints.extend([x * width, y * height, int(visibility)])
                    annotation.update(keypoints=keypoints, num_keypoints=sum(v > 0 for v in keypoints[2::3]))
            else:
                if len(coords) % 2 or (task == "obb" and len(coords) != 8) or len(coords) < 6:
                    raise TableError(f"{where}: {task} needs " + ("four corners" if task == "obb" else "at least three polygon points"))
                if any(v < 0 or v > 1 for v in coords):
                    raise TableError(f"{where}: coordinates must be normalized to [0, 1]")
                points = [v * (width if i % 2 == 0 else height) for i, v in enumerate(coords)]
                x0, y0, x1, y1 = polygon_bounds(points)
                bbox = [x0, y0, x1 - x0, y1 - y0]
                if polygon_area(points) <= 0:
                    raise TableError(f"{where}: polygon has no area")
                annotation.update({"obb" if task == "obb" else "segmentation": points if task == "obb" else [points], "area": polygon_area(points)})
            annotation.update(bbox=bbox)
            annotation.setdefault("area", bbox[2] * bbox[3])
            coco["annotations"].append(annotation)
    return coco, {"yaml": str(path), "split": split, "task": task, "tasks": [TASK_IDS[task]], "yolo": pose, "root": str(dataset_root)}


def table_from_yolo(
    data_yaml: Url | str,
    split: str = "train",
    *,
    task: str | None = None,
    root: str | Path | None = None,
    project_name: str = "default",
    dataset_name: str | None = None,
    table_name: str | None = None,
    description: str = "",
    add_weight_column: bool = True,
    config: Config | None = None,
) -> Table:
    """Build a Table retaining masks, keypoints, pose metadata and oriented corners."""
    from granum.formats.coco import table_from_coco_data

    coco, args = read_yolo(data_yaml, split, task=task, root=root)
    return table_from_coco_data(
        coco, source=data_yaml,
        project_name=project_name,
        dataset_name=dataset_name or Path(args["root"]).name,
        table_name=table_name or split,
        description=description or f"YOLO {args['task']} split {split!r}",
        producer_args=args,
        add_weight_column=add_weight_column,
        config=config,
    )


def _format(value: float) -> str:
    text = f"{value:.6f}".rstrip("0").rstrip(".")
    return text if text not in ("", "-0") else "0"


def export_yolo(
    splits: Table | dict[str, Table],
    output_dir: str | Path,
    *,
    column: str | None = None,
    image_strategy: str = "symlink",
    weight_threshold: float | None = 0.0,
    split_weight_thresholds: dict[str, float | None] | None = None,
    skip_ignored: bool = True,
    task: str = "detect",
    pose: dict[str, Any] | None = None,
) -> Path:
    """Write one or more Tables as a YOLO dataset and return its ``data.yaml``.

    YOLO has no notion of a region to ignore, so boxes flagged ``iscrowd`` are left out
    unless ``skip_ignored=False``: training on them as a class teaches the model to
    detect "areas nobody labelled".

    ``splits`` maps split names (``train``, ``val``, ...) to Tables; a single Table is
    written as ``train``. Class ids are renumbered 0..K-1 in the order of the source ids,
    since YOLO requires contiguous ids -- COCO category ids are not. Rows with weight at
    or below ``weight_threshold`` are excluded. ``split_weight_thresholds`` overrides
    that policy per split; use ``{"val": None}`` to retain every evaluation image.
    """
    if task not in TASKS:
        raise TableError(f"unsupported YOLO task {task!r}; choose {TASKS}")
    tables = {"train": splits} if isinstance(splits, Table) else dict(splits)
    if not tables:
        raise TableError("nothing to export: no splits given")
    output = Path(output_dir)

    value_map = None
    for table in tables.values():
        schema = table.schema[geometry_column(table, column)]
        if value_map is None:
            value_map = schema.value_map  # type: ignore[attr-defined]
        elif {k: v.internal_name for k, v in schema.value_map.items()} != {k: v.internal_name for k, v in value_map.items()}:  # type: ignore[attr-defined]
            raise TableError("splits disagree on classes; export them separately")
    assert value_map is not None
    remap = {source: target for target, source in enumerate(sorted(value_map))}
    metadata = dict(pose or {})
    if task == "pose":
        for table in tables.values():
            origin = root_producer(table, "from_coco")
            stored = origin.get("yolo") or (origin.get("top_level") or {}).get("granum_yolo") or {}
            for key in POSE_KEYS:
                if key in stored:
                    if key in metadata and metadata[key] != stored[key]:
                        raise TableError(f"splits disagree on pose metadata {key!r}")
                    metadata[key] = stored[key]
            for category in origin.get("categories") or []:
                if category.get("keypoints"):
                    metadata.setdefault("kpt_names", {})[int(category["id"])] = category["keypoints"]
                    metadata.setdefault("kpt_shape", [len(category["keypoints"]), 3])
                if category.get("skeleton"):
                    metadata.setdefault("skeleton", category["skeleton"])
        if "kpt_shape" not in metadata:
            sizes = {len(extra_of(i).get("keypoints") or []) // 3 for t in tables.values()
                     for value in t.to_arrow().column(geometry_column(t, column)).to_pylist() if value
                     for i in value["instances"] if not (skip_ignored and i.get("iscrowd"))}
            if len(sizes) != 1 or 0 in sizes:
                raise TableError("pose export needs one consistent, nonempty keypoint layout")
            metadata["kpt_shape"] = [sizes.pop(), 3]
        if metadata.get("kpt_names"):
            metadata["kpt_names"] = {remap[int(k)]: v for k, v in metadata["kpt_names"].items() if int(k) in remap}
        _validate_pose(metadata)

    for split, table in tables.items():
        if not split or Path(split).name != split or split in (".", ".."):
            raise TableError("split names must be simple directory names")
        box_column = geometry_column(table, column)
        arrow = table.to_arrow()
        paths = arrow.column(image_column(table)).to_pylist()
        values = arrow.column(box_column).to_pylist()
        used: set[str] = set()
        for row in kept_rows(table, (split_weight_thresholds or {}).get(split, weight_threshold)):
            source = Url(paths[row]).resolved
            name = Path(source).name
            # Labels use only the stem: image.jpg and image.png must not share a label.
            while Path(name).stem in used:
                name = f"{row}_{name}"
            used.add(Path(name).stem)
            place_image(paths[row], output / "images" / split / name, image_strategy)

            value = values[row] or {"width": 0, "height": 0, "instances": []}
            width, height = value["width"] or 1.0, value["height"] or 1.0
            lines = []
            for instance in value["instances"]:
                if skip_ignored and instance.get("iscrowd"):
                    continue
                x0, y0, x1, y1 = instance["vertices"]
                coords = [(x0 + x1) / 2 / width, (y0 + y1) / 2 / height, (x1 - x0) / width, (y1 - y0) / height]
                extra = extra_of(instance)
                if task == "segment":
                    points = yolo_polygon(instance.get("segmentation"), int(width), int(height))
                    coords = [v / (width if i % 2 == 0 else height) for i, v in enumerate(points)]
                elif task == "obb":
                    points = extra.get("obb")
                    if not isinstance(points, list) or len(points) != 8:
                        raise TableError(f"row {row} has no oriented corners; draw an oriented box before exporting")
                    coords = [v / (width if i % 2 == 0 else height) for i, v in enumerate(points)]
                elif task == "pose":
                    count, dims = metadata["kpt_shape"]
                    points = extra.get("keypoints") or []
                    if len(points) != count * 3:
                        raise TableError(f"row {row} needs {count} keypoints per object; unlabelled points use visibility 0")
                    for at in range(count):
                        coords.extend([points[at * 3] / width, points[at * 3 + 1] / height])
                        if dims == 3:
                            coords.append(points[at * 3 + 2])
                if not all(math.isfinite(v) for v in coords):
                    raise TableError(f"row {row} contains nonfinite coordinates")
                coordinate_values = coords if task != "pose" else coords[:4] + [
                    value for at, value in enumerate(coords[4:]) if dims != 3 or at % 3 != 2
                ]
                if any(value < -1e-7 or value > 1 + 1e-7 for value in coordinate_values):
                    raise TableError(f"row {row} has {task} coordinates outside the image; correct its annotations before YOLO export")
                if task in ("detect", "pose") and min(coords[2:4]) <= 0:
                    raise TableError(f"row {row} has a box with no area")
                if task == "pose" and dims == 3 and any(v not in (0, 1, 2) for v in coords[6::3]):
                    raise TableError(f"row {row} has invalid keypoint visibility; use 0, 1 or 2")
                lines.append(" ".join([str(remap[instance["label"]]), *(_format(v) for v in coords)]))
            label_file = output / "labels" / split / (Path(name).stem + ".txt")
            label_file.parent.mkdir(parents=True, exist_ok=True)
            label_file.write_text("\n".join(lines) + ("\n" if lines else ""))

    data_yaml = output / "data.yaml"
    data_yaml.write_text(yaml.safe_dump({
        "path": str(output.resolve()),
        **{split: f"images/{split}" for split in tables},
        "names": {remap[k]: value_map[k].internal_name for k in sorted(value_map)},
        "task": task,
        **metadata,
    }, sort_keys=False))
    return data_yaml
