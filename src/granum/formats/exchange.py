"""The other formats a dataset arrives in and has to leave in.

Granum keeps one representation — a Table with a geometry column — and everything else is a
conversion at the edge. This module holds the edges that are not COCO or YOLO:

**Out**: Pascal VOC XML, KITTI text, a flat CSV of boxes, CVAT-for-images XML, Label Studio
JSON tasks, and a folder per class for classification sets.

**In**: the same formats read back to COCO, because the import path (preflight, media modes,
findings, the wizard) is built on COCO and a second path would be a second thing to trust.
A converter here does one job: turn somebody else's layout into the COCO dict the importer
already knows how to check.

Two rules run through all of it. Coordinates are absolute pixels in Granum, so every format
that stores them otherwise is converted at the boundary and never halfway. And an export
says where it came from: a box a model drafted carries its source and confidence wherever
the format has room for them, so nobody downstream mistakes a draft for a label.
"""

from __future__ import annotations

import csv as csv_module
import json
import re
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

from granum.core.objects.table import Table
from granum.core.prelabel import CONFIDENCE, MODEL, SOURCE
from granum.core.url import Url
from granum.errors import TableError
from granum.formats._common import (
    clean_number,
    geometry_column,
    image_column,
    kept_rows,
    place_image,
)

#: Formats a dataset can be written in, with what each is for.
EXPORTS: list[dict[str, str]] = [
    {"id": "coco", "name": "COCO", "detail": "One JSON file of images and annotations. The most widely read."},
    {"id": "yolo", "name": "YOLO", "detail": "images/ and labels/ folders with a data.yaml. What Ultralytics trains from."},
    {"id": "voc", "name": "Pascal VOC", "detail": "One XML file per image. Old, simple, still everywhere."},
    {"id": "kitti", "name": "KITTI", "detail": "One text file per image. Used by autonomous-driving toolchains."},
    {"id": "csv", "name": "CSV", "detail": "One row per box. For a spreadsheet, a script, or a quick count."},
    {"id": "cvat", "name": "CVAT for images", "detail": "The XML CVAT imports, to carry on labelling there."},
    {"id": "label-studio", "name": "Label Studio", "detail": "JSON tasks with pre-annotations, to review there."},
    {"id": "folders", "name": "Folder per class", "detail": "Classification layout: each image filed under its class."},
]

#: Formats a dataset can be read from, converted to COCO for the importer to check.
IMPORTS: list[dict[str, str]] = [
    {"id": "yolo", "name": "YOLO", "detail": "A data.yaml naming splits and classes."},
    {"id": "voc", "name": "Pascal VOC", "detail": "A folder of XML annotations beside the images."},
    {"id": "kitti", "name": "KITTI", "detail": "A folder of label .txt files beside the images."},
    {"id": "csv", "name": "CSV", "detail": "A file with one row per box, or one row per image for classification."},
    {"id": "folders", "name": "Folder per class", "detail": "Classification: one folder per class, images inside."},
]

IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".bmp", ".webp", ".tif", ".tiff"}


def _instances(value: Any, *, skip_ignored: bool = True) -> list[dict[str, Any]]:
    out = []
    for instance in (value or {}).get("instances") or []:
        if skip_ignored and instance.get("iscrowd"):
            continue
        if len(instance.get("vertices") or []) != 4:
            continue
        out.append(instance)
    return out


def _rows(table: Table, column: str | None, weight_threshold: float | None):
    """Every row to export: its image, its geometry, and where it sits in the table."""
    box_column = geometry_column(table, column)
    picture = image_column(table)
    arrow = table.to_arrow()
    paths = arrow.column(picture).to_pylist()
    values = arrow.column(box_column).to_pylist()
    names = {int(k): v.internal_name for k, v in (table.schema[box_column].value_map or {}).items()}
    for row in kept_rows(table, weight_threshold):
        yield row, paths[row], values[row] or {"width": 0.0, "height": 0.0, "instances": []}, names


def _unique_names(table: Table, column: str | None, weight_threshold: float | None) -> dict[int, str]:
    """A file name per row that no two rows share: two folders can hold one name."""
    used: set[str] = set()
    out: dict[int, str] = {}
    for row, path, _value, _names in _rows(table, column, weight_threshold):
        name = Path(Url(path).resolved).name
        if name in used:
            name = f"{row}_{name}"
        used.add(name)
        out[row] = name
    return out


# ---------------------------------------------------------------------------
# out
# ---------------------------------------------------------------------------


def export_voc(table: Table, output: str | Path, *, column: str | None = None,
               image_strategy: str | None = None, weight_threshold: float | None = 0.0) -> Path:
    """One VOC XML per image, in ``Annotations/``, with ``JPEGImages/`` beside it if asked."""
    out = Path(output)
    (out / "Annotations").mkdir(parents=True, exist_ok=True)
    names = _unique_names(table, column, weight_threshold)
    written = 0
    for row, path, value, classes in _rows(table, column, weight_threshold):
        name = names[row]
        if image_strategy:
            place_image(path, out / "JPEGImages" / name, image_strategy)
        annotation = ET.Element("annotation")
        ET.SubElement(annotation, "folder").text = "JPEGImages"
        ET.SubElement(annotation, "filename").text = name
        ET.SubElement(annotation, "path").text = str(Url(path).resolved)
        size = ET.SubElement(annotation, "size")
        ET.SubElement(size, "width").text = str(int(value.get("width") or 0))
        ET.SubElement(size, "height").text = str(int(value.get("height") or 0))
        ET.SubElement(size, "depth").text = "3"
        ET.SubElement(annotation, "segmented").text = "0"
        for instance in _instances(value, skip_ignored=False):
            item = ET.SubElement(annotation, "object")
            ET.SubElement(item, "name").text = classes.get(int(instance["label"]), str(instance["label"]))
            ET.SubElement(item, "pose").text = "Unspecified"
            ET.SubElement(item, "truncated").text = "0"
            # VOC's "difficult" is the nearest thing it has to an area nobody labelled.
            ET.SubElement(item, "difficult").text = "1" if instance.get("iscrowd") else "0"
            if instance.get(SOURCE):
                ET.SubElement(item, "source").text = str(instance[SOURCE])
            if instance.get(CONFIDENCE) is not None:
                ET.SubElement(item, "confidence").text = f"{float(instance[CONFIDENCE]):.4f}"
            box = ET.SubElement(item, "bndbox")
            x0, y0, x1, y1 = (float(v) for v in instance["vertices"])
            for tag, number in (("xmin", x0), ("ymin", y0), ("xmax", x1), ("ymax", y1)):
                ET.SubElement(box, tag).text = str(clean_number(number))
        ET.ElementTree(annotation).write(out / "Annotations" / f"{Path(name).stem}.xml",
                                         encoding="utf-8", xml_declaration=True)
        written += 1
    return out


def export_kitti(table: Table, output: str | Path, *, column: str | None = None,
                 image_strategy: str | None = None, weight_threshold: float | None = 0.0) -> Path:
    """One KITTI label file per image: ``type 0 0 0 x0 y0 x1 y1 0 0 0 0 0 0 0``."""
    out = Path(output)
    (out / "label_2").mkdir(parents=True, exist_ok=True)
    names = _unique_names(table, column, weight_threshold)
    for row, path, value, classes in _rows(table, column, weight_threshold):
        name = names[row]
        if image_strategy:
            place_image(path, out / "image_2" / name, image_strategy)
        lines = []
        for instance in _instances(value):
            x0, y0, x1, y1 = (float(v) for v in instance["vertices"])
            label = classes.get(int(instance["label"]), str(instance["label"])).replace(" ", "_")
            lines.append(
                f"{label} 0.00 0 0.00 {x0:.2f} {y0:.2f} {x1:.2f} {y1:.2f} "
                f"0.00 0.00 0.00 0.00 0.00 0.00 0.00"
            )
        (out / "label_2" / f"{Path(name).stem}.txt").write_text("\n".join(lines) + ("\n" if lines else ""))
    return out


def export_csv(table: Table, output: str | Path, *, column: str | None = None,
               weight_threshold: float | None = 0.0) -> Path:
    """One row per box: image, class, box, and where the box came from.

    An image with no boxes gets a row with an empty class, so a CSV of a dataset is a
    complete list of its images rather than only of its objects.
    """
    out = Path(output)
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", newline="", encoding="utf-8") as handle:
        writer = csv_module.writer(handle)
        writer.writerow(["image", "width", "height", "class", "x_min", "y_min", "x_max", "y_max",
                         "source", "confidence", "ignore"])
        for _row, path, value, classes in _rows(table, column, weight_threshold):
            image = str(Url(path).resolved)
            width, height = int(value.get("width") or 0), int(value.get("height") or 0)
            instances = _instances(value, skip_ignored=False)
            if not instances:
                writer.writerow([image, width, height, "", "", "", "", "", "", "", ""])
            for instance in instances:
                x0, y0, x1, y1 = (clean_number(v) for v in instance["vertices"])
                writer.writerow([
                    image, width, height,
                    classes.get(int(instance["label"]), str(instance["label"])),
                    x0, y0, x1, y1,
                    instance.get(SOURCE) or "",
                    "" if instance.get(CONFIDENCE) is None else round(float(instance[CONFIDENCE]), 4),
                    1 if instance.get("iscrowd") else 0,
                ])
    return out


def export_cvat(table: Table, output: str | Path, *, column: str | None = None,
                weight_threshold: float | None = 0.0, task_name: str | None = None) -> Path:
    """CVAT-for-images 1.1 XML: what CVAT reads to carry on labelling where this left off."""
    out = Path(output)
    out.parent.mkdir(parents=True, exist_ok=True)
    box_column = geometry_column(table, column)
    classes = {int(k): v.internal_name for k, v in (table.schema[box_column].value_map or {}).items()}
    root = ET.Element("annotations")
    ET.SubElement(root, "version").text = "1.1"
    meta = ET.SubElement(root, "meta")
    task = ET.SubElement(meta, "task")
    ET.SubElement(task, "name").text = task_name or f"{table.dataset_name}/{table.name}"
    ET.SubElement(task, "mode").text = "annotation"
    labels = ET.SubElement(task, "labels")
    for name in classes.values():
        entry = ET.SubElement(labels, "label")
        ET.SubElement(entry, "name").text = name
        ET.SubElement(entry, "attributes")
    for position, (row, path, value, names) in enumerate(_rows(table, column, weight_threshold)):
        image = ET.SubElement(root, "image", {
            "id": str(position), "name": Path(Url(path).resolved).name,
            "width": str(int(value.get("width") or 0)), "height": str(int(value.get("height") or 0)),
        })
        for instance in _instances(value, skip_ignored=False):
            x0, y0, x1, y1 = (float(v) for v in instance["vertices"])
            box = ET.SubElement(image, "box", {
                "label": names.get(int(instance["label"]), str(instance["label"])),
                "occluded": "0",
                "source": MODEL if instance.get(SOURCE) == MODEL else "manual",
                "xtl": f"{x0:.2f}", "ytl": f"{y0:.2f}", "xbr": f"{x1:.2f}", "ybr": f"{y1:.2f}",
                "z_order": "0",
            })
            if instance.get(CONFIDENCE) is not None:
                attribute = ET.SubElement(box, "attribute", {"name": "confidence"})
                attribute.text = f"{float(instance[CONFIDENCE]):.4f}"
        _ = row
    ET.ElementTree(root).write(out, encoding="utf-8", xml_declaration=True)
    return out


def export_label_studio(table: Table, output: str | Path, *, column: str | None = None,
                        weight_threshold: float | None = 0.0, as_predictions: bool = False) -> Path:
    """Label Studio tasks: one per image, boxes as rectangle results in percent.

    ``as_predictions`` puts the boxes under ``predictions`` rather than ``annotations``,
    which is what Label Studio treats as a model's suggestion to be corrected -- the right
    place for anything a model drafted.
    """
    out = Path(output)
    out.parent.mkdir(parents=True, exist_ok=True)
    tasks = []
    for _row, path, value, classes in _rows(table, column, weight_threshold):
        width = float(value.get("width") or 0) or 1.0
        height = float(value.get("height") or 0) or 1.0
        results = []
        for at, instance in enumerate(_instances(value, skip_ignored=False)):
            x0, y0, x1, y1 = (float(v) for v in instance["vertices"])
            results.append({
                "id": f"box{at}",
                "type": "rectanglelabels",
                "from_name": "label",
                "to_name": "image",
                "original_width": int(width),
                "original_height": int(height),
                "image_rotation": 0,
                "value": {
                    "x": round(x0 / width * 100, 4),
                    "y": round(y0 / height * 100, 4),
                    "width": round((x1 - x0) / width * 100, 4),
                    "height": round((y1 - y0) / height * 100, 4),
                    "rotation": 0,
                    "rectanglelabels": [classes.get(int(instance["label"]), str(instance["label"]))],
                },
                **({"score": round(float(instance[CONFIDENCE]), 4)} if instance.get(CONFIDENCE) is not None else {}),
            })
        drafted = any(i.get(SOURCE) == MODEL for i in _instances(value, skip_ignored=False))
        block = {"result": results, **({"model_version": "granum"} if as_predictions or drafted else {})}
        tasks.append({
            "data": {"image": str(Url(path).resolved)},
            **({"predictions": [block]} if as_predictions or drafted else {"annotations": [block]}),
        })
    out.write_text(json.dumps(tasks, indent=1))
    return out


def export_folders(table: Table, output: str | Path, *, column: str | None = None,
                   image_strategy: str = "symlink", weight_threshold: float | None = 0.0) -> Path:
    """A folder per class with its images in it: the classification layout.

    A detection set has no one class per image, so the class used is the one that covers
    most of the picture -- and an image with no labels goes under ``unlabelled`` rather
    than being dropped, because a classification tree that silently loses images is worse
    than one that says what it could not decide.
    """
    out = Path(output)
    names = _unique_names(table, column, weight_threshold)
    for row, path, value, classes in _rows(table, column, weight_threshold):
        instances = _instances(value)
        if instances:
            biggest = max(instances, key=lambda i: abs((i["vertices"][2] - i["vertices"][0])
                                                       * (i["vertices"][3] - i["vertices"][1])))
            folder = classes.get(int(biggest["label"]), str(biggest["label"]))
        else:
            folder = "unlabelled"
        place_image(path, out / re.sub(r"[^\w.-]+", "_", folder) / names[row], image_strategy)
    return out


EXPORTERS = {
    "voc": export_voc,
    "kitti": export_kitti,
    "csv": export_csv,
    "cvat": export_cvat,
    "label-studio": export_label_studio,
    "folders": export_folders,
}


# ---------------------------------------------------------------------------
# in: everything becomes COCO, which the importer already knows how to check
# ---------------------------------------------------------------------------


def _coco(images: list[dict[str, Any]], annotations: list[dict[str, Any]],
          classes: list[str], source: str) -> dict[str, Any]:
    return {
        "info": {"description": f"converted from {source} by Granum"},
        "images": images,
        "annotations": annotations,
        "categories": [{"id": i + 1, "name": name} for i, name in enumerate(classes)],
    }


def _image_size(path: Path) -> tuple[int, int]:
    from PIL import Image

    with Image.open(path) as handle:
        return int(handle.width), int(handle.height)


def _images_beside(folder: Path) -> dict[str, Path]:
    """Every image under a folder, by stem: annotations name them without the extension."""
    found: dict[str, Path] = {}
    for path in sorted(folder.rglob("*")):
        if path.suffix.lower() in IMAGE_SUFFIXES and path.is_file():
            found.setdefault(path.stem, path)
    return found


def voc_to_coco(folder: str | Path, *, images_dir: str | Path | None = None) -> dict[str, Any]:
    """Read a folder of Pascal VOC XML files into a COCO dict."""
    root = Path(folder)
    annotations_dir = root / "Annotations" if (root / "Annotations").is_dir() else root
    files = sorted(annotations_dir.glob("*.xml"))
    if not files:
        raise TableError(f"no VOC XML files in {annotations_dir}")
    pictures = _images_beside(Path(images_dir) if images_dir else root)
    classes: list[str] = []
    images: list[dict[str, Any]] = []
    boxes: list[dict[str, Any]] = []
    for at, file in enumerate(files, start=1):
        try:
            tree = ET.parse(file)
        except ET.ParseError as exc:
            raise TableError(f"{file.name} is not readable XML: {exc}") from exc
        node = tree.getroot()
        name = (node.findtext("filename") or f"{file.stem}.jpg").strip()
        picture = pictures.get(Path(name).stem) or pictures.get(file.stem)
        width = int(float(node.findtext("size/width") or 0))
        height = int(float(node.findtext("size/height") or 0))
        if (not width or not height) and picture is not None:
            width, height = _image_size(picture)
        images.append({"id": at, "file_name": str(picture) if picture else name,
                       "width": width, "height": height})
        for item in node.findall("object"):
            label = (item.findtext("name") or "").strip() or "object"
            if label not in classes:
                classes.append(label)
            box = item.find("bndbox")
            if box is None:
                continue
            x0 = float(box.findtext("xmin") or 0)
            y0 = float(box.findtext("ymin") or 0)
            x1 = float(box.findtext("xmax") or 0)
            y1 = float(box.findtext("ymax") or 0)
            boxes.append({
                "id": len(boxes) + 1, "image_id": at,
                "category_id": classes.index(label) + 1,
                "bbox": [x0, y0, x1 - x0, y1 - y0],
                "area": max(x1 - x0, 0) * max(y1 - y0, 0),
                "iscrowd": 1 if (item.findtext("difficult") or "0").strip() == "1" else 0,
            })
    return _coco(images, boxes, classes, "Pascal VOC")


def kitti_to_coco(folder: str | Path, *, images_dir: str | Path | None = None) -> dict[str, Any]:
    """Read a folder of KITTI label files into a COCO dict."""
    root = Path(folder)
    labels_dir = next((root / name for name in ("label_2", "labels", "label")
                       if (root / name).is_dir()), root)
    files = sorted(labels_dir.glob("*.txt"))
    if not files:
        raise TableError(f"no KITTI label files in {labels_dir}")
    pictures = _images_beside(Path(images_dir) if images_dir else root)
    classes: list[str] = []
    images: list[dict[str, Any]] = []
    boxes: list[dict[str, Any]] = []
    for at, file in enumerate(files, start=1):
        picture = pictures.get(file.stem)
        width, height = _image_size(picture) if picture else (0, 0)
        images.append({"id": at, "file_name": str(picture) if picture else f"{file.stem}.png",
                       "width": width, "height": height})
        for number, line in enumerate(file.read_text().splitlines(), start=1):
            parts = line.split()
            if not parts:
                continue
            if len(parts) < 8:
                raise TableError(f"{file.name}:{number}: a KITTI line has at least 8 fields, got {len(parts)}")
            label = parts[0]
            if label.lower() == "dontcare":
                continue
            if label not in classes:
                classes.append(label)
            x0, y0, x1, y1 = (float(v) for v in parts[4:8])
            boxes.append({
                "id": len(boxes) + 1, "image_id": at,
                "category_id": classes.index(label) + 1,
                "bbox": [x0, y0, x1 - x0, y1 - y0],
                "area": max(x1 - x0, 0) * max(y1 - y0, 0),
                "iscrowd": 0,
            })
    return _coco(images, boxes, classes, "KITTI")


#: The column names a CSV of boxes may use, in the order they are looked for.
CSV_IMAGE = ("image", "image_path", "filename", "file", "path", "image_name")
CSV_LABEL = ("class", "label", "category", "class_name")
CSV_BOX = (("x_min", "y_min", "x_max", "y_max"), ("xmin", "ymin", "xmax", "ymax"),
           ("x0", "y0", "x1", "y1"), ("left", "top", "right", "bottom"))


def csv_to_coco(file: str | Path, *, images_dir: str | Path | None = None) -> dict[str, Any]:
    """Read a CSV of boxes -- or of one class per image -- into a COCO dict.

    Column names are matched case-insensitively against the usual spellings, because every
    tool that writes a CSV of boxes picks its own. A file with no box columns is read as
    classification: one row per image, one class each.
    """
    path = Path(file)
    with path.open(newline="", encoding="utf-8-sig") as handle:
        rows = list(csv_module.DictReader(handle))
    if not rows:
        raise TableError(f"{path.name} has no rows")
    header = {name.strip().lower(): name for name in rows[0] if name}
    image_key = next((header[name] for name in CSV_IMAGE if name in header), None)
    if image_key is None:
        raise TableError(f"{path.name} needs a column naming the image: one of {list(CSV_IMAGE)}")
    label_key = next((header[name] for name in CSV_LABEL if name in header), None)
    box_keys = next((tuple(header[name] for name in group) for group in CSV_BOX
                     if all(name in header for name in group)), None)

    base = Path(images_dir) if images_dir else path.parent
    classes: list[str] = []
    images: list[dict[str, Any]] = []
    boxes: list[dict[str, Any]] = []
    seen: dict[str, int] = {}
    for row in rows:
        name = (row.get(image_key) or "").strip()
        if not name:
            continue
        resolved = Path(name) if Path(name).is_absolute() else base / name
        if name not in seen:
            width, height = (_image_size(resolved) if resolved.exists() else (0, 0))
            seen[name] = len(images) + 1
            images.append({"id": seen[name], "file_name": str(resolved), "width": width, "height": height})
        label = (row.get(label_key) or "").strip() if label_key else ""
        if not label:
            continue
        if label not in classes:
            classes.append(label)
        if box_keys is None:
            # Classification: the class is about the whole picture.
            entry = images[seen[name] - 1]
            width, height = float(entry["width"] or 0), float(entry["height"] or 0)
            boxes.append({"id": len(boxes) + 1, "image_id": seen[name],
                          "category_id": classes.index(label) + 1,
                          "bbox": [0.0, 0.0, width, height], "area": width * height, "iscrowd": 0})
            continue
        try:
            x0, y0, x1, y1 = (float(row[key]) for key in box_keys)
        except (TypeError, ValueError) as exc:
            raise TableError(f"{path.name}: a box column is not a number: {exc}") from exc
        boxes.append({"id": len(boxes) + 1, "image_id": seen[name],
                      "category_id": classes.index(label) + 1,
                      "bbox": [x0, y0, x1 - x0, y1 - y0],
                      "area": max(x1 - x0, 0) * max(y1 - y0, 0), "iscrowd": 0})
    return _coco(images, boxes, classes, "CSV")


def folders_to_coco(folder: str | Path) -> dict[str, Any]:
    """Read a folder-per-class tree into a COCO dict: one box covering each whole image."""
    root = Path(folder)
    classes = sorted(child.name for child in root.iterdir()
                     if child.is_dir() and any(p.suffix.lower() in IMAGE_SUFFIXES for p in child.rglob("*")))
    if not classes:
        raise TableError(f"{root} has no folders of images to read as classes")
    images: list[dict[str, Any]] = []
    boxes: list[dict[str, Any]] = []
    for name in classes:
        for picture in sorted((root / name).rglob("*")):
            if picture.suffix.lower() not in IMAGE_SUFFIXES or not picture.is_file():
                continue
            width, height = _image_size(picture)
            images.append({"id": len(images) + 1, "file_name": str(picture), "width": width, "height": height})
            boxes.append({"id": len(boxes) + 1, "image_id": len(images),
                          "category_id": classes.index(name) + 1,
                          "bbox": [0.0, 0.0, float(width), float(height)],
                          "area": float(width * height), "iscrowd": 0})
    return _coco(images, boxes, classes, "folders of classes")


def yolo_to_coco(data_yaml: str | Path, split: str = "train") -> dict[str, Any]:
    """Read one split of a YOLO dataset into a COCO dict."""
    import yaml as yaml_module

    from granum.formats.yolo import _image_size as yolo_image_size
    from granum.formats.yolo import _label_path, _names, _resolve_root, _split_images

    path = Path(data_yaml)
    document = yaml_module.safe_load(path.read_text()) or {}
    if not document.get(split):
        raise TableError(f"{path.name} has no {split!r} split")
    root = _resolve_root(document, path, None)
    names = _names(document)
    classes = [names[key] for key in sorted(names)]
    order = {key: at for at, key in enumerate(sorted(names))}
    images: list[dict[str, Any]] = []
    boxes: list[dict[str, Any]] = []
    for picture in _split_images(root, document[split]):
        width, height = yolo_image_size(picture)
        images.append({"id": len(images) + 1, "file_name": picture, "width": width, "height": height})
        label_file = Path(_label_path(picture))
        if not label_file.exists():
            continue
        for line in label_file.read_text().splitlines():
            parts = line.split()
            if len(parts) != 5:
                continue
            key = int(parts[0])
            cx, cy, bw, bh = (float(v) for v in parts[1:])
            x0, y0 = (cx - bw / 2) * width, (cy - bh / 2) * height
            boxes.append({"id": len(boxes) + 1, "image_id": len(images),
                          "category_id": order.get(key, 0) + 1,
                          "bbox": [x0, y0, bw * width, bh * height],
                          "area": bw * width * bh * height, "iscrowd": 0})
    return _coco(images, boxes, classes, "YOLO")


CONVERTERS = {
    "voc": voc_to_coco,
    "kitti": kitti_to_coco,
    "csv": csv_to_coco,
    "folders": folders_to_coco,
    "yolo": yolo_to_coco,
}
