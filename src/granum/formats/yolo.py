"""YOLO detection datasets <-> Table.

Follows the Ultralytics layout: a dataset YAML names the splits and classes; each image
``.../images/x.jpg`` has labels in ``.../labels/x.txt``, one ``class cx cy w h`` line per box
with coordinates normalised to the image size. An image without a label file is a
background image with no boxes, not an error.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml

from granum.core.config import Config
from granum.core.objects.table import WEIGHT_COLUMN, Table
from granum.core.schemas import ImageSchema, SampleWeightSchema, TableSchema, ValueMapEntry
from granum.core.schemas.geometry import BoundingBoxes2DSchema
from granum.core.url import Url
from granum.errors import TableError
from granum.formats._common import geometry_column, image_column, kept_rows, place_image

BOX_COLUMN = "bbs"
IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".bmp", ".webp", ".tif", ".tiff", ".dng", ".mpo"}
TASKS = ("detect",)
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


def table_from_yolo(
    data_yaml: Url | str,
    split: str = "train",
    *,
    task: str = "detect",
    root: str | Path | None = None,
    project_name: str = "default",
    dataset_name: str | None = None,
    table_name: str | None = None,
    description: str = "",
    add_weight_column: bool = True,
    config: Config | None = None,
) -> Table:
    """Build a detection Table from one split of a YOLO dataset."""
    if task not in TASKS:
        raise TableError(f"task {task!r} is not supported yet; supported: {TASKS}")
    yaml_path = Path(Url(data_yaml).resolved)
    document = yaml.safe_load(yaml_path.read_text()) or {}
    if not document.get(split):
        raise TableError(f"{yaml_path.name} has no {split!r} split")
    dataset_root = _resolve_root(document, yaml_path, root)
    names = _names(document)
    images = _split_images(dataset_root, document[split])
    if not images:
        raise TableError(f"no images found for split {split!r} under {dataset_root}")

    boxes = []
    for image_path in images:
        width, height = _image_size(image_path)
        instances = []
        label_file = _label_path(image_path)
        if os.path.exists(label_file):
            for number, line in enumerate(Path(label_file).read_text().splitlines(), start=1):
                parts = line.split()
                if not parts:
                    continue
                if len(parts) != 5:
                    raise TableError(
                        f"{label_file}:{number}: expected 'class cx cy w h', got {len(parts)} values "
                        f"(segmentation and pose labels are not supported yet)"
                    )
                cls = int(parts[0])
                if cls not in names:
                    raise TableError(f"{label_file}:{number}: class {cls} is not in the dataset names")
                cx, cy, bw, bh = (float(v) for v in parts[1:])
                instances.append({
                    "vertices": [
                        (cx - bw / 2) * width, (cy - bh / 2) * height,
                        (cx + bw / 2) * width, (cy + bh / 2) * height,
                    ],
                    "label": cls,
                })
        boxes.append({"width": float(width), "height": float(height), "instances": instances})

    columns = {
        "image": ImageSchema(sample_type="url"),
        BOX_COLUMN: BoundingBoxes2DSchema(value_map={k: ValueMapEntry(v) for k, v in names.items()}),
    }
    data: dict[str, list[Any]] = {"image": images, BOX_COLUMN: boxes}
    if add_weight_column:
        columns[WEIGHT_COLUMN] = SampleWeightSchema()
        data[WEIGHT_COLUMN] = [1.0] * len(images)

    return Table._write(
        data=data,
        schema=TableSchema(columns),
        project_name=project_name,
        dataset_name=dataset_name or dataset_root.name,
        table_name=table_name or split,
        description=description or f"YOLO split {split!r} from {yaml_path.name}",
        producer={"op": "from_yolo", "args": {"yaml": str(yaml_path), "split": split, "task": task}},
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
    skip_ignored: bool = True,
) -> Path:
    """Write one or more Tables as a YOLO dataset and return its ``data.yaml``.

    YOLO has no notion of a region to ignore, so boxes flagged ``iscrowd`` are left out
    unless ``skip_ignored=False``: training on them as a class teaches the model to
    detect "areas nobody labelled".

    ``splits`` maps split names (``train``, ``val``, ...) to Tables; a single Table is
    written as ``train``. Class ids are renumbered 0..K-1 in the order of the source ids,
    since YOLO requires contiguous ids -- COCO category ids are not. Rows with weight at
    or below ``weight_threshold`` are excluded.
    """
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

    for split, table in tables.items():
        box_column = geometry_column(table, column)
        arrow = table.to_arrow()
        paths = arrow.column(image_column(table)).to_pylist()
        values = arrow.column(box_column).to_pylist()
        used: set[str] = set()
        for row in kept_rows(table, weight_threshold):
            source = Url(paths[row]).resolved
            name = Path(source).name
            if name in used:  # same file name from two source folders
                name = f"{row}_{name}"
            used.add(name)
            place_image(paths[row], output / "images" / split / name, image_strategy)

            value = values[row] or {"width": 0, "height": 0, "instances": []}
            width, height = value["width"] or 1.0, value["height"] or 1.0
            lines = []
            for instance in value["instances"]:
                if skip_ignored and instance.get("iscrowd"):
                    continue
                x0, y0, x1, y1 = instance["vertices"]
                lines.append(" ".join([
                    str(remap[instance["label"]]),
                    _format((x0 + x1) / 2 / width), _format((y0 + y1) / 2 / height),
                    _format((x1 - x0) / width), _format((y1 - y0) / height),
                ]))
            label_file = output / "labels" / split / (Path(name).stem + ".txt")
            label_file.parent.mkdir(parents=True, exist_ok=True)
            label_file.write_text("\n".join(lines) + ("\n" if lines else ""))

    data_yaml = output / "data.yaml"
    data_yaml.write_text(yaml.safe_dump({
        "path": str(output.resolve()),
        **{split: f"images/{split}" for split in tables},
        "names": {remap[k]: value_map[k].internal_name for k in sorted(value_map)},
    }, sort_keys=False))
    return data_yaml
