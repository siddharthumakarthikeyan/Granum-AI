"""COCO detection annotations <-> Table.

Import keeps everything an export needs to reproduce the file: category ids are used as
class indices as-is (COCO ids are not contiguous), annotation ids, ``iscrowd``, ``area``
and segmentation ride along as instance properties, other image fields are kept in a
hidden column, and ``info`` / ``licenses`` / category extras are recorded on the Table's
producer. Editing a box does not update its ``area`` or segmentation -- those describe the
original mask, which a box edit cannot know about.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from granum.core.config import Config
from granum.core.objects.table import WEIGHT_COLUMN, Table
from granum.core.schemas import (
    ImageSchema,
    Int64Schema,
    SampleWeightSchema,
    StringSchema,
    TableSchema,
    ValueMapEntry,
)
from granum.core.schemas.geometry import BoundingBoxes2DSchema
from granum.core.url import Url
from granum.errors import TableError
from granum.formats._common import (
    clean_number,
    geometry_column,
    image_column,
    kept_rows,
    place_image,
    root_producer,
)

BOX_COLUMN = "bbs"
IMAGE_EXTRA_COLUMN = "coco_image"
_ANNOTATION_KNOWN = {"id", "image_id", "category_id", "bbox", "area", "iscrowd", "segmentation"}
_IMAGE_KNOWN = {"id", "width", "height"}


def table_from_coco(
    annotations: Url | str,
    image_folder: Url | str | None = None,
    *,
    project_name: str = "default",
    dataset_name: str | None = None,
    table_name: str = "initial",
    description: str = "",
    add_weight_column: bool = True,
    config: Config | None = None,
) -> Table:
    """Build a detection Table from a COCO ``instances_*.json`` file.

    ``image_folder`` defaults to the directory holding the annotation file; each image's
    path is ``image_folder / file_name``.
    """
    source = Url(annotations)
    try:
        coco = json.loads(source.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        raise TableError(f"could not read COCO annotations from {source}: {exc}") from exc
    return table_from_coco_data(
        coco,
        source=source,
        image_folder=image_folder,
        project_name=project_name,
        dataset_name=dataset_name,
        table_name=table_name,
        description=description,
        add_weight_column=add_weight_column,
        config=config,
    )


def table_from_coco_data(
    coco: dict[str, Any],
    *,
    source: Url | str,
    image_folder: Url | str | None = None,
    project_name: str = "default",
    dataset_name: str | None = None,
    table_name: str = "initial",
    description: str = "",
    add_weight_column: bool = True,
    extra_columns: dict[str, list[Any]] | None = None,
    producer_args: dict[str, Any] | None = None,
    config: Config | None = None,
) -> Table:
    """Build a detection Table from an already-parsed COCO document.

    ``source`` is where the document came from, recorded for export and provenance.
    ``extra_columns`` adds hidden-by-default string columns, one value per image in
    ``coco["images"]`` order; ``producer_args`` is merged into the recorded producer.
    """
    source = Url(source)
    for key in ("images", "annotations", "categories"):
        if key not in coco:
            raise TableError(f"{source} is not COCO detection data: no {key!r} key")

    folder = Url(image_folder) if image_folder is not None else source.parent

    categories = coco["categories"]
    value_map = {int(c["id"]): ValueMapEntry(internal_name=str(c["name"])) for c in categories}

    by_image: dict[int, list[dict[str, Any]]] = {}
    for annotation in coco["annotations"]:
        by_image.setdefault(int(annotation["image_id"]), []).append(annotation)

    # Box-only exports carry "segmentation": [] on every annotation. Storing that per box
    # costs a fifth of a detection table's size, so it is recorded once instead and
    # written back on export.
    has_segmentation = any(a.get("segmentation") not in (None, [], "") for a in coco["annotations"])
    empty_segmentation = not has_segmentation and any("segmentation" in a for a in coco["annotations"])
    has_extra = any(set(a) - _ANNOTATION_KNOWN for a in coco["annotations"])
    properties = {"annotation_id": "int64", "iscrowd": "bool", "area": "float64"}
    if has_segmentation:
        properties["segmentation"] = "string"
    if has_extra:
        properties["coco_extra"] = "string"

    images, image_ids, boxes, extras = [], [], [], []
    known_ids = {int(i["id"]) for i in coco["images"]}
    orphans = [a["id"] for a in coco["annotations"] if int(a["image_id"]) not in known_ids]
    if orphans:
        raise TableError(f"{len(orphans)} annotation(s) refer to images not in the file, e.g. id {orphans[0]}")

    for image in coco["images"]:
        image_id = int(image["id"])
        instances = []
        for annotation in by_image.get(image_id, []):
            if "bbox" not in annotation:
                raise TableError(f"annotation {annotation.get('id')} has no bbox")
            x, y, w, h = (float(v) for v in annotation["bbox"])
            category = int(annotation["category_id"])
            if category not in value_map:
                raise TableError(f"annotation {annotation.get('id')} uses unknown category {category}")
            instance: dict[str, Any] = {
                "vertices": [x, y, x + w, y + h],
                "label": category,
                "annotation_id": int(annotation["id"]) if "id" in annotation else None,
                "iscrowd": bool(annotation.get("iscrowd", 0)) if "iscrowd" in annotation else None,
                "area": float(annotation["area"]) if "area" in annotation else None,
            }
            if has_segmentation:
                instance["segmentation"] = (
                    json.dumps(annotation["segmentation"], separators=(",", ":"))
                    if "segmentation" in annotation else None
                )
            if has_extra:
                extra = {k: v for k, v in annotation.items() if k not in _ANNOTATION_KNOWN}
                instance["coco_extra"] = json.dumps(extra, separators=(",", ":")) if extra else None
            instances.append(instance)
        images.append(str(folder / image["file_name"]))
        image_ids.append(image_id)
        boxes.append({"width": float(image["width"]), "height": float(image["height"]), "instances": instances})
        extras.append(json.dumps({k: v for k, v in image.items() if k not in _IMAGE_KNOWN}, separators=(",", ":")))

    columns = {
        "image": ImageSchema(sample_type="url"),
        "image_id": Int64Schema(),
        BOX_COLUMN: BoundingBoxes2DSchema(value_map=value_map, instance_properties=properties),
        IMAGE_EXTRA_COLUMN: StringSchema(default_visible=False, description="COCO image fields kept for export"),
    }
    data: dict[str, list[Any]] = {"image": images, "image_id": image_ids, BOX_COLUMN: boxes, IMAGE_EXTRA_COLUMN: extras}
    for name, values in (extra_columns or {}).items():
        if len(values) != len(images):
            raise TableError(f"extra column {name!r} has {len(values)} values for {len(images)} images")
        columns[name] = StringSchema(default_visible=False)
        data[name] = list(values)
    if add_weight_column:
        columns[WEIGHT_COLUMN] = SampleWeightSchema()
        data[WEIGHT_COLUMN] = [1.0] * len(images)

    return Table._write(
        data=data,
        schema=TableSchema(columns),
        project_name=project_name,
        dataset_name=dataset_name or source.parent.name or "coco",
        table_name=table_name,
        description=description or f"Imported from {source.name}",
        producer={
            "op": "from_coco",
            "args": {
                "source": str(source.aliased()),
                "info": coco.get("info"),
                "licenses": coco.get("licenses"),
                "categories": categories,
                "top_level": {k: v for k, v in coco.items() if k not in {"images", "annotations", "categories", "info", "licenses"}},
                "empty_segmentation": empty_segmentation,
                **(producer_args or {}),
            },
        },
        config=config,
    )


def export_coco(
    table: Table,
    output: str | Path,
    *,
    column: str | None = None,
    image_strategy: str | None = None,
    images_dir: str | Path | None = None,
    weight_threshold: float | None = 0.0,
) -> Path:
    """Write a Table's boxes as a COCO detection file.

    ``image_strategy`` of ``None`` references images where they are; ``"copy"``,
    ``"symlink"`` or ``"hardlink"`` places them in ``images_dir`` (default: beside the
    output file) under their original file names. Rows with weight at or below
    ``weight_threshold`` are left out; pass ``None`` to export every row.
    """
    output = Path(output)
    box_column = geometry_column(table, column)
    picture_column = image_column(table)
    schema: BoundingBoxes2DSchema = table.schema[box_column]  # type: ignore[assignment]
    origin = root_producer(table, "from_coco")
    arrow = table.to_arrow()

    original_categories = {int(c["id"]): c for c in origin.get("categories") or []}
    categories = []
    for index in sorted(schema.value_map):
        entry = dict(original_categories.get(index, {}))
        entry.update({"id": index, "name": schema.value_map[index].internal_name})
        categories.append(entry)

    target_images = Path(images_dir) if images_dir is not None else output.parent
    images_out, annotations_out = [], []
    used_ids = {
        inst.get("annotation_id")
        for value in arrow.column(box_column).to_pylist() if value
        for inst in value["instances"] if inst.get("annotation_id") is not None
    }
    next_id = max((i for i in used_ids if isinstance(i, int)), default=0) + 1
    seen_ids: set[int] = set()

    image_ids = arrow.column("image_id").to_pylist() if "image_id" in table.columns else None
    extras = arrow.column(IMAGE_EXTRA_COLUMN).to_pylist() if IMAGE_EXTRA_COLUMN in table.columns else None
    paths = arrow.column(picture_column).to_pylist()
    values = arrow.column(box_column).to_pylist()

    for row in kept_rows(table, weight_threshold):
        value = values[row] or {"width": 0.0, "height": 0.0, "instances": []}
        image: dict[str, Any] = {"id": int(image_ids[row]) if image_ids else row + 1}
        extra = json.loads(extras[row]) if extras and extras[row] else {}
        file_name = extra.pop("file_name", None) or Path(Url(paths[row]).resolved).name
        if image_strategy is not None:
            file_name = Path(Url(paths[row]).resolved).name
            place_image(paths[row], target_images / file_name, image_strategy)
        image.update({"file_name": file_name})
        image.update(extra)
        image.update({"width": clean_number(value["width"]), "height": clean_number(value["height"])})
        images_out.append(image)

        for instance in value["instances"]:
            x0, y0, x1, y1 = instance["vertices"]
            annotation_id = instance.get("annotation_id")
            if annotation_id is None or annotation_id in seen_ids:  # new or pasted boxes
                annotation_id = next_id
                next_id += 1
            seen_ids.add(annotation_id)
            annotation: dict[str, Any] = {"id": annotation_id, "image_id": image["id"], "category_id": instance["label"]}
            if instance.get("segmentation") is not None:
                annotation["segmentation"] = json.loads(instance["segmentation"])
            elif origin.get("empty_segmentation"):
                annotation["segmentation"] = []
            annotation["area"] = (
                clean_number(instance["area"]) if instance.get("area") is not None
                else clean_number((x1 - x0) * (y1 - y0))
            )
            annotation["bbox"] = [clean_number(x0), clean_number(y0), clean_number(x1 - x0), clean_number(y1 - y0)]
            annotation["iscrowd"] = int(bool(instance.get("iscrowd"))) if instance.get("iscrowd") is not None else 0
            if instance.get("coco_extra"):
                annotation.update(json.loads(instance["coco_extra"]))
            annotations_out.append(annotation)

    document: dict[str, Any] = {}
    if origin.get("info") is not None:
        document["info"] = origin["info"]
    if origin.get("licenses") is not None:
        document["licenses"] = origin["licenses"]
    document.update(origin.get("top_level") or {})
    document.update({"images": images_out, "annotations": annotations_out, "categories": categories})

    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(document))
    return output
