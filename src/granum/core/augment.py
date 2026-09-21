"""Augmented copies of training images, written when a dataset version is created.

A recipe names the augmentations to use and their ranges. Every training image gets
``copies`` new images, each with its own random draw from the recipe; the originals stay.
Only a train set is augmented -- validation and test must stay real images, or their
scores stop meaning anything.

Geometry (flips, 90-degree turns, crop, rotation, shear) is composed into one affine
transform, so the image is resampled once and every label is mapped by the same matrix:
boxes through their corners, mask polygons point by point (then clipped to the frame),
keypoints point by point (those pushed out of the frame become unlabelled). A box whose
visible part falls under :data:`MIN_VISIBLE` of its transformed size is dropped, as a
crop that leaves a sliver of an object would teach the model a wrong box.
Run-length masks cannot be transformed here; under a geometric change they are dropped
and counted.

Colour changes (hue, saturation, brightness, exposure, grayscale), blur, noise and
cutout change pixels only.
"""

from __future__ import annotations

import hashlib
import io
import json
import math
import os
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from threading import Event
from typing import Any

import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq

from granum.core.config import get_config
from granum.core.layout import ROW_CACHE_FILENAME, ProjectLayout, sanitize
from granum.core.objects.base import write_object_payload
from granum.core.objects.table import Table, _unique_url
from granum.core.schemas import Geometry2DSchema, StringSchema
from granum.core.url import Url
from granum.errors import GranumError

#: Column naming the image each augmented copy was made from (empty for originals).
AUGMENTED_FROM = "augmented_from"
#: Boxes that keep less than this share of their transformed area inside the frame are dropped.
MIN_VISIBLE = 0.15
MAX_COPIES = 10

#: name -> (field, low, high) bounds of every numeric setting, and the unit it is in.
BOUNDS: dict[str, dict[str, tuple[float, float]]] = {
    "crop": {"min": (0, 90), "max": (0, 90)},
    "rotation": {"min": (-180, 180), "max": (-180, 180)},
    "shear": {"horizontal": (0, 45), "vertical": (0, 45)},
    "grayscale": {"percent": (0, 100)},
    "hue": {"min": (-180, 180), "max": (-180, 180)},
    "saturation": {"min": (-100, 100), "max": (-100, 100)},
    "brightness": {"min": (-90, 90), "max": (-90, 90)},
    "exposure": {"min": (-90, 90), "max": (-90, 90)},
    "blur": {"max": (0, 20)},
    "noise": {"max": (0, 50)},
    "cutout": {"count": (1, 20), "size": (1, 50)},
}
SWITCHES: dict[str, tuple[str, ...]] = {
    "flip": ("horizontal", "vertical"),
    "rotate90": ("clockwise", "counterclockwise", "upside_down"),
}
GEOMETRIC = ("flip", "rotate90", "crop", "rotation", "shear")


class AugmentError(GranumError):
    """A recipe that cannot be used, or augmentation that could not finish."""


def normalize_recipe(raw: dict[str, Any] | None) -> dict[str, Any] | None:
    """The recipe checked and tidied, or None when it asks for nothing.

    Unknown augmentations, settings out of range and min above max are refused, so what
    is recorded on the dataset version is exactly what was applied.
    """
    if not raw:
        return None
    if not isinstance(raw, dict):
        raise AugmentError("augmentation must be an object")
    copies = raw.get("copies", 2)
    if not isinstance(copies, int) or isinstance(copies, bool) or not 1 <= copies <= MAX_COPIES:
        raise AugmentError(f"copies must be a whole number from 1 to {MAX_COPIES}")
    out: dict[str, Any] = {"copies": copies}
    for name, value in raw.items():
        if name == "copies":
            continue
        if name in SWITCHES:
            if not isinstance(value, dict):
                raise AugmentError(f"{name} must be an object")
            unknown = set(value) - set(SWITCHES[name])
            if unknown:
                raise AugmentError(f"{name} has no option {sorted(unknown)[0]!r}")
            chosen = {k: True for k in SWITCHES[name] if value.get(k) is True}
            if chosen:
                out[name] = chosen
            continue
        if name not in BOUNDS:
            raise AugmentError(f"unknown augmentation {name!r}")
        if not isinstance(value, dict):
            raise AugmentError(f"{name} must be an object")
        unknown = set(value) - set(BOUNDS[name])
        if unknown:
            raise AugmentError(f"{name} has no setting {sorted(unknown)[0]!r}")
        settings: dict[str, float] = {}
        for key, (low, high) in BOUNDS[name].items():
            number = value.get(key)
            if isinstance(number, bool) or not isinstance(number, (int, float)) or not math.isfinite(number):
                raise AugmentError(f"{name} needs a number for {key}")
            if not low <= number <= high:
                raise AugmentError(f"{name} {key} must be between {low:g} and {high:g}")
            settings[key] = float(number)
        if "min" in settings and "max" in settings and settings["min"] > settings["max"]:
            raise AugmentError(f"{name}: min must not be above max")
        out[name] = settings
    if len(out) == 1:
        return None
    return out


def describe(recipe: dict[str, Any]) -> list[str]:
    """One short phrase per augmentation, for descriptions and logs."""
    parts = []
    for name, value in recipe.items():
        if name == "copies":
            continue
        if name in SWITCHES:
            parts.append(f"{name}: {', '.join(value)}")
        elif "min" in value and "max" in value:
            parts.append(f"{name} {value['min']:g} to {value['max']:g}")
        else:
            parts.append(f"{name} " + ", ".join(f"{k} {v:g}" for k, v in value.items()))
    return parts


# -- one draw -------------------------------------------------------------------


@dataclass
class Draw:
    """The random choices for one augmented image."""

    matrix: np.ndarray  # 3x3, source pixel -> output pixel
    size: tuple[int, int]  # output width, height
    geometric: bool
    grayscale: bool = False
    hue: float = 0.0  # degrees
    saturation: float = 0.0  # percent
    brightness: float = 0.0  # percent
    exposure: float = 0.0  # percent
    blur: float = 0.0  # pixels at full size
    noise: float = 0.0  # percent of pixels
    noise_seed: int = 0
    cutouts: list[tuple[float, float, float, float]] = field(default_factory=list)  # fractions x0, y0, x1, y1


def _uniform(rng: np.random.Generator, setting: dict[str, float]) -> float:
    return float(rng.uniform(setting["min"], setting["max"])) if setting["max"] > setting["min"] else setting["min"]


def draw(recipe: dict[str, Any], width: int, height: int, rng: np.random.Generator, *, fixed: str | None = None) -> Draw:
    """Pick one augmentation from ``recipe`` for an image of ``width`` x ``height``.

    With ``fixed`` ("min" or "max") nothing is left to chance: every chosen augmentation is
    applied at that end of its range (flips and turns always, the first chosen turn, a centred
    crop, blur and noise at their maximum), to show what a setting does.
    """
    if fixed not in (None, "min", "max"):
        raise AugmentError("fixed must be 'min' or 'max'")

    def pick(setting: dict[str, float]) -> float:
        return setting[fixed] if fixed else _uniform(rng, setting)

    def chance() -> float:
        return 0.0 if fixed else float(rng.random())

    m = np.eye(3)
    w, h = float(width), float(height)
    geometric = False

    def then(step: np.ndarray) -> None:
        nonlocal m, geometric
        m = step @ m
        geometric = True

    flip = recipe.get("flip", {})
    if flip.get("horizontal") and chance() < 0.5:
        then(np.array([[-1, 0, w], [0, 1, 0], [0, 0, 1.0]]))
    if flip.get("vertical") and chance() < 0.5:
        then(np.array([[1, 0, 0], [0, -1, h], [0, 0, 1.0]]))

    turns = [k for k in ("clockwise", "counterclockwise", "upside_down") if recipe.get("rotate90", {}).get(k)]
    if turns:
        # Each chosen turn, or none, equally likely.
        chosen = 0 if fixed else int(rng.integers(0, len(turns) + 1))
        if chosen < len(turns):
            turn = turns[chosen]
            if turn == "clockwise":
                then(np.array([[0, -1, h], [1, 0, 0], [0, 0, 1.0]]))
                w, h = h, w
            elif turn == "counterclockwise":
                then(np.array([[0, 1, 0], [-1, 0, w], [0, 0, 1.0]]))
                w, h = h, w
            else:
                then(np.array([[-1, 0, w], [0, -1, h], [0, 0, 1.0]]))

    if "crop" in recipe:
        cut = pick(recipe["crop"]) / 100
        if cut > 0:
            scale = 1 / (1 - cut)
            ox = (w - w / scale) / 2 if fixed else float(rng.uniform(0, w - w / scale))
            oy = (h - h / scale) / 2 if fixed else float(rng.uniform(0, h - h / scale))
            then(np.array([[scale, 0, -ox * scale], [0, scale, -oy * scale], [0, 0, 1.0]]))

    cx, cy = w / 2, h / 2
    to_center = np.array([[1, 0, -cx], [0, 1, -cy], [0, 0, 1.0]])
    back = np.array([[1, 0, cx], [0, 1, cy], [0, 0, 1.0]])
    if "rotation" in recipe:
        angle = math.radians(pick(recipe["rotation"]))
        if angle:
            c, s = math.cos(angle), math.sin(angle)
            then(back @ np.array([[c, -s, 0], [s, c, 0], [0, 0, 1.0]]) @ to_center)
    if "shear" in recipe:
        def lean() -> float:
            return (1.0 if fixed == "max" else -1.0) if fixed else float(rng.uniform(-1, 1))

        sx = math.tan(math.radians(lean() * recipe["shear"]["horizontal"]))
        sy = math.tan(math.radians(lean() * recipe["shear"]["vertical"]))
        if sx or sy:
            then(back @ np.array([[1, sx, 0], [sy, 1, 0], [0, 0, 1.0]]) @ to_center)

    out = Draw(matrix=m, size=(round(w), round(h)), geometric=geometric)
    if "grayscale" in recipe:
        out.grayscale = bool(fixed) or bool(rng.random() * 100 < recipe["grayscale"]["percent"])
    for name in ("hue", "saturation", "brightness", "exposure"):
        if name in recipe:
            setattr(out, name, pick(recipe[name]))
    if "blur" in recipe:
        out.blur = recipe["blur"]["max"] if fixed else float(rng.uniform(0, recipe["blur"]["max"]))
    if "noise" in recipe:
        out.noise = recipe["noise"]["max"] if fixed else float(rng.uniform(0, recipe["noise"]["max"]))
        out.noise_seed = int(rng.integers(0, 2**31))
    if "cutout" in recipe:
        side = recipe["cutout"]["size"] / 100
        for _ in range(int(recipe["cutout"]["count"])):
            x, y = float(rng.uniform(0, 1 - side)), float(rng.uniform(0, 1 - side))
            out.cutouts.append((x, y, x + side, y + side))
    return out


# -- pixels -----------------------------------------------------------------------


def apply_image(image: Any, d: Draw, *, scale: float = 1.0) -> Any:
    """``image`` (PIL, RGB, in label coordinates times ``scale``) with the draw applied."""
    from PIL import Image, ImageEnhance, ImageFilter

    if d.geometric:
        # Scale into and out of label space, so a preview at reduced size warps the same way.
        s = np.diag([scale, scale, 1.0])
        forward = s @ d.matrix @ np.linalg.inv(s)
        inverse = np.linalg.inv(forward)
        size = (max(1, round(d.size[0] * scale)), max(1, round(d.size[1] * scale)))
        image = image.transform(size, Image.AFFINE, tuple(inverse[:2].ravel()), resample=Image.BILINEAR, fillcolor=(0, 0, 0))
    if d.hue or d.saturation:
        hsv = np.asarray(image.convert("HSV"), dtype=np.int16)
        if d.hue:
            hsv[..., 0] = (hsv[..., 0] + round(d.hue / 360 * 256)) % 256
        if d.saturation:
            hsv[..., 1] = np.clip(hsv[..., 1] * (1 + d.saturation / 100), 0, 255)
        image = Image.fromarray(hsv.astype(np.uint8), "HSV").convert("RGB")
    if d.brightness:
        image = ImageEnhance.Brightness(image).enhance(1 + d.brightness / 100)
    if d.exposure:
        # Exposure bends the tone curve: dark areas move most, white stays white.
        gamma = 1 / (1 + d.exposure / 100)
        lut = [min(255, round(255 * (i / 255) ** gamma)) for i in range(256)]
        image = image.point(lut * 3)
    if d.grayscale:
        image = image.convert("L").convert("RGB")
    if d.blur > 0.05:
        image = image.filter(ImageFilter.GaussianBlur(d.blur * scale))
    if d.noise > 0 or d.cutouts:
        pixels = np.array(image)
        rng = np.random.default_rng(d.noise_seed)
        if d.noise > 0:
            hit = rng.random(pixels.shape[:2]) < d.noise / 100
            pixels[hit] = rng.integers(0, 256, size=(int(hit.sum()), 3), dtype=np.uint8)
        height, width = pixels.shape[:2]
        for x0, y0, x1, y1 in d.cutouts:
            pixels[round(y0 * height):round(y1 * height), round(x0 * width):round(x1 * width)] = 0
        image = Image.fromarray(pixels)
    return image


# -- labels -----------------------------------------------------------------------


def _map(points: np.ndarray, m: np.ndarray) -> np.ndarray:
    """(n, 2) points through the 3x3 matrix."""
    return points @ m[:2, :2].T + m[:2, 2]


def _clip_polygon(points: list[tuple[float, float]], width: float, height: float) -> list[tuple[float, float]]:
    """Sutherland-Hodgman against the image frame."""
    def clip(pts: list[tuple[float, float]], inside: Callable[[tuple[float, float]], bool],
             cross: Callable[[tuple[float, float], tuple[float, float]], tuple[float, float]]) -> list[tuple[float, float]]:
        out: list[tuple[float, float]] = []
        for i, current in enumerate(pts):
            previous = pts[i - 1]
            if inside(current):
                if not inside(previous):
                    out.append(cross(previous, current))
                out.append(current)
            elif inside(previous):
                out.append(cross(previous, current))
        return out

    def at_x(x: float) -> Callable[[tuple[float, float], tuple[float, float]], tuple[float, float]]:
        return lambda a, b: (x, a[1] + (b[1] - a[1]) * (x - a[0]) / ((b[0] - a[0]) or 1e-12))

    def at_y(y: float) -> Callable[[tuple[float, float], tuple[float, float]], tuple[float, float]]:
        return lambda a, b: (a[0] + (b[0] - a[0]) * (y - a[1]) / ((b[1] - a[1]) or 1e-12), y)

    for inside, cross in (
        (lambda p: p[0] >= 0, at_x(0)),
        (lambda p: p[0] <= width, at_x(width)),
        (lambda p: p[1] >= 0, at_y(0)),
        (lambda p: p[1] <= height, at_y(height)),
    ):
        if not points:
            break
        points = clip(points, inside, cross)
    return points


def _polygon_area(flat: list[float]) -> float:
    xs, ys = flat[0::2], flat[1::2]
    return abs(sum(xs[i] * ys[(i + 1) % len(xs)] - xs[(i + 1) % len(xs)] * ys[i] for i in range(len(xs)))) / 2


@dataclass
class LabelStats:
    dropped_boxes: int = 0
    dropped_masks: int = 0


def apply_instances(instances: list[dict[str, Any]], d: Draw, stats: LabelStats | None = None) -> list[dict[str, Any]]:
    """Instances (vertices, and optional segmentation / coco_extra JSON) mapped through the draw."""
    if not d.geometric:
        return [dict(i) for i in instances]
    width, height = d.size
    m = d.matrix
    out = []
    for instance in instances:
        instance = dict(instance)
        x0, y0, x1, y1 = (float(v) for v in instance["vertices"][:4])
        corners = _map(np.array([[x0, y0], [x1, y0], [x1, y1], [x0, y1]]), m)
        full = (corners[:, 0].min(), corners[:, 1].min(), corners[:, 0].max(), corners[:, 1].max())

        polygons: list[list[float]] | None = None
        segmentation = instance.get("segmentation")
        if isinstance(segmentation, str) and segmentation:
            try:
                parsed = json.loads(segmentation)
            except ValueError:
                parsed = None
            if isinstance(parsed, list):
                polygons = []
                for polygon in parsed:
                    if not isinstance(polygon, list) or len(polygon) < 6:
                        continue
                    mapped = _map(np.array(polygon, dtype=float).reshape(-1, 2), m)
                    clipped = _clip_polygon([(float(x), float(y)) for x, y in mapped], width, height)
                    if len(clipped) >= 3:
                        polygons.append([round(v, 2) for p in clipped for v in p])
                instance["segmentation"] = json.dumps(polygons) if polygons else None
            elif parsed is not None:
                instance["segmentation"] = None  # a run-length mask cannot follow the transform
                if stats:
                    stats.dropped_masks += 1

        if polygons:
            xs = [v for p in polygons for v in p[0::2]]
            ys = [v for p in polygons for v in p[1::2]]
            box = (min(xs), min(ys), max(xs), max(ys))
        else:
            box = (max(0.0, full[0]), max(0.0, full[1]), min(float(width), full[2]), min(float(height), full[3]))
        full_area = max(1e-9, (full[2] - full[0]) * (full[3] - full[1]))
        visible = max(0.0, box[2] - box[0]) * max(0.0, box[3] - box[1])
        if box[2] - box[0] < 1 or box[3] - box[1] < 1 or (not polygons and visible / full_area < MIN_VISIBLE):
            if stats:
                stats.dropped_boxes += 1
            continue
        instance["vertices"] = [round(float(v), 2) for v in box]

        extra = instance.get("coco_extra")
        if isinstance(extra, str) and extra:
            try:
                parsed_extra = json.loads(extra)
            except ValueError:
                parsed_extra = None
            if isinstance(parsed_extra, dict) and isinstance(parsed_extra.get("keypoints"), list):
                points = [float(v) for v in parsed_extra["keypoints"]]
                moved = []
                for k in range(0, len(points) - 2, 3):
                    x, y, v = points[k:k + 3]
                    if v <= 0:
                        moved += [0, 0, 0]
                        continue
                    (px, py), = _map(np.array([[x, y]]), m)
                    moved += [round(float(px), 2), round(float(py), 2), int(v)] if 0 <= px <= width and 0 <= py <= height else [0, 0, 0]
                parsed_extra["keypoints"] = moved
                if "num_keypoints" in parsed_extra:
                    parsed_extra["num_keypoints"] = sum(1 for k in range(2, len(moved), 3) if moved[k] > 0)
                instance["coco_extra"] = json.dumps(parsed_extra)

        if "area" in instance:
            instance["area"] = round(sum(_polygon_area(p) for p in polygons), 2) if polygons else round(visible, 2)
        out.append(instance)
    return out


# -- a whole set --------------------------------------------------------------------


def box_column(table: Table) -> str | None:
    return next((n for n in table.columns if isinstance(table.schema[n], Geometry2DSchema)), None)


def load_image(url: str, width: int, height: int) -> Any:
    """The image as RGB, oriented as it is shown, at the size its labels are in."""
    from PIL import Image, ImageOps

    image = Image.open(io.BytesIO(Url(url).read_bytes()))
    image = ImageOps.exif_transpose(image).convert("RGB")
    if width and height and image.size != (width, height):
        image = image.resize((width, height), Image.BILINEAR)
    return image


def augmented_folder(table: Table, release_id: str) -> Url:
    layout = ProjectLayout(get_config().project_root)
    return layout.project(table.project_name) / "releases" / sanitize(table.dataset_name) / release_id


def write_augmented_set(
    source: Table,
    recipe: dict[str, Any],
    *,
    release_id: str,
    release_name: str,
    keep: set[str] | None = None,
    progress: Callable[[int, int], None] | None = None,
    cancel: Event | None = None,
    seed: int = 0,
    workers: int | None = None,
) -> tuple[Table, dict[str, int]]:
    """A frozen copy of ``source`` (only ``keep`` images, if given) plus augmented copies.

    New images are JPEGs under the dataset version's folder; each new row names its
    original in :data:`AUGMENTED_FROM`. Returns the table and counts: originals,
    augmented, dropped boxes, dropped masks.
    """
    from granum.core.curation import RELEASE_OP, image_column

    column = box_column(source)
    image_col = image_column(source)
    arrow = source.to_arrow()
    images = arrow.column(image_col).to_pylist()
    rows = [i for i, image in enumerate(images) if keep is None or image in keep]
    if not rows:
        raise AugmentError(f"{source.name} has no images to augment")
    originals = arrow.take(pa.array(rows, type=pa.int64()))
    schema = source.schema
    if AUGMENTED_FROM not in schema:
        schema = schema.with_column(AUGMENTED_FROM, StringSchema(description="Image this augmented copy was made from", writable=False))
    if AUGMENTED_FROM not in originals.column_names:
        originals = originals.append_column(AUGMENTED_FROM, pa.nulls(originals.num_rows, pa.string()))
    records = originals.to_pylist()
    copies = int(recipe["copies"])

    folder = augmented_folder(source, release_id)
    target = _unique_url(folder, source.base_name)
    media_dir = folder / "images" / sanitize(source.base_name)
    media_dir.mkdir()
    local = media_dir.scheme == "file"

    stats = LabelStats()
    total = len(records) * copies
    done = 0
    next_id = 1 + max((int(i) for i in arrow.column("image_id").to_pylist() if isinstance(i, int)), default=0) if "image_id" in arrow.column_names else 0

    def make(task: tuple[int, int]) -> dict[str, Any] | None:
        index, copy = task
        if cancel is not None and cancel.is_set():
            return None
        record = records[index]
        geometry = record.get(column) if column else None
        width = int((geometry or {}).get("width") or 0)
        height = int((geometry or {}).get("height") or 0)
        image = load_image(record[image_col], width, height)
        if not width or not height:
            width, height = image.size
        rng = np.random.default_rng([seed, rows[index], copy])
        d = draw(recipe, width, height, rng)
        out_image = apply_image(image, d)
        buffer = io.BytesIO()
        out_image.save(buffer, "JPEG", quality=92)
        data = buffer.getvalue()
        stem = sanitize(os.path.splitext(os.path.basename(str(record[image_col])))[0])[:80]
        path = media_dir / f"{rows[index]:06d}_{stem}_aug{copy + 1}.jpg"
        if local:
            with open(path.path, "wb") as handle:
                handle.write(data)
        else:
            path.write_bytes(data)

        row = dict(record)
        row[image_col] = str(path)
        if column and geometry is not None:
            local_stats = LabelStats()
            row[column] = {**geometry, "width": float(d.size[0]), "height": float(d.size[1]),
                           "instances": apply_instances(geometry.get("instances") or [], d, local_stats)}
            stats.dropped_boxes += local_stats.dropped_boxes
            stats.dropped_masks += local_stats.dropped_masks
        if "content_hash" in row:
            row["content_hash"] = hashlib.sha1(data).hexdigest()
        row[AUGMENTED_FROM] = record[image_col]
        if isinstance(row.get("coco_image"), str) and row["coco_image"]:
            try:
                coco = json.loads(row["coco_image"])
                coco.update({"file_name": os.path.basename(path.path if local else str(path)),
                             "width": d.size[0], "height": d.size[1]})
                row["coco_image"] = json.dumps(coco)
            except ValueError:
                pass
        return row

    tasks = [(i, c) for c in range(copies) for i in range(len(records))]
    made: list[dict[str, Any] | None] = [None] * len(tasks)
    with ThreadPoolExecutor(max_workers=workers or min(8, os.cpu_count() or 2)) as pool:
        for position, row in enumerate(pool.map(make, tasks)):
            made[position] = row
            done += 1
            if progress and (done % 25 == 0 or done == total):
                progress(done, total)
    if cancel is not None and cancel.is_set():
        _remove_tree(folder)
        raise AugmentError("augmentation was cancelled")

    new_rows = [r for r in made if r is not None]
    for row in new_rows:
        if "image_id" in row:
            row["image_id"] = next_id
            next_id += 1
    combined = pa.concat_tables([originals, pa.Table.from_pylist(new_rows, schema=originals.schema)])
    counts = {"originals": len(records), "augmented": len(new_rows),
              "dropped_boxes": stats.dropped_boxes, "dropped_masks": stats.dropped_masks}
    table = Table(
        url=target,
        name=target.name,
        base_name=source.base_name,
        project_name=source.project_name,
        dataset_name=source.dataset_name,
        schema=schema,
        row_count=combined.num_rows,
        parents=(source.url,),
        producer={"op": RELEASE_OP, "args": {"release": release_id, "count": len(records),
                                             "augmentation": recipe, **counts}},
        description=f"{release_name}: {len(records)} images of {source.name} and {len(new_rows)} augmented copies",
        arrow=combined,
    )
    target.mkdir()
    pq.write_table(combined, (target / ROW_CACHE_FILENAME).path, filesystem=target.fs)
    write_object_payload(target, table.to_dict())
    return table, counts


def _remove_tree(folder: Url) -> None:
    if folder.scheme == "file":
        import shutil

        shutil.rmtree(folder.path, ignore_errors=True)


def _record(source: Table, row: int) -> tuple[dict[str, Any], dict[str, Any] | None, str]:
    from granum.core.curation import image_column

    column = box_column(source)
    image_col = image_column(source)
    record = source.to_arrow().slice(row, 1).to_pylist()[0]
    return record, (record.get(column) if column else None), record[image_col]


def _render(image: Any, geometry: dict[str, Any] | None, d: Draw | None, size: int) -> dict[str, Any]:
    """One small JPEG (as a data URL) of ``image`` under ``d``, with its boxes."""
    import base64

    from PIL import Image

    width, height = image.size
    scale = min(1.0, size / max(width, height))
    small = image.resize((max(1, round(width * scale)), max(1, round(height * scale))), Image.BILINEAR)
    instances = (geometry or {}).get("instances") or []
    if d is not None:
        small = apply_image(small, d, scale=scale)
        instances = apply_instances(instances, d)
        width, height = d.size
    buffer = io.BytesIO()
    small.save(buffer, "JPEG", quality=85)
    return {
        "image": "data:image/jpeg;base64," + base64.b64encode(buffer.getvalue()).decode(),
        "width": width,
        "height": height,
        "boxes": [{"box": i["vertices"], "label": i.get("label"), "crowd": bool(i.get("iscrowd"))} for i in instances],
    }


_sample_rows: dict[str, int] = {}


def sample_row(source: Table, sample: int = 60, looked_at: int = 10) -> int:
    """A typical, well-exposed, colourful image of ``source`` to show augmentations on.

    Among a spread of rows, those with a middling number of boxes are candidates; of a few
    of them, the most colourful of mid brightness wins, as colour effects read poorly on a
    night scene or a washed-out sky. Versions never change, so the choice is remembered.
    """
    key = str(source.url)
    if key in _sample_rows:
        return _sample_rows[key]
    from PIL import Image, ImageStat

    column = box_column(source)
    rows = list(range(0, len(source), max(1, len(source) // sample)))[:sample]
    if column is None or not rows:
        return 0
    import pyarrow.compute as pc

    arrow = source.to_arrow().take(pa.array(rows, type=pa.int64()))
    counts = pc.list_value_length(pc.struct_field(arrow.column(column), "instances")).to_pylist()
    ranked = sorted((c or 0, r) for c, r in zip(counts, rows) if c)
    if not ranked:
        return rows[0]
    middle = ranked[len(ranked) // 4: max(len(ranked) // 4 + 1, 3 * len(ranked) // 4)]
    step = max(1, len(middle) // looked_at)
    best, best_score = middle[len(middle) // 2][1], -1e9
    for _count, row in middle[::step][:looked_at]:
        _record_, _geometry, image_url = _record(source, row)
        try:
            with Image.open(io.BytesIO(Url(image_url).read_bytes())) as image:
                image.draft("RGB", (160, 160))
                hsv = image.convert("RGB").resize((64, 64)).convert("HSV")
                saturation, value = ImageStat.Stat(hsv).mean[1:3]
        except Exception:  # noqa: BLE001 - an unreadable image is just not chosen
            continue
        score = min(saturation, 60) - 1.2 * abs(value - 140)
        if score > best_score:
            best, best_score = row, score
    _sample_rows[key] = best
    return best


def examples(source: Table, items: dict[str, tuple[dict[str, Any], str]], *, row: int | None = None, size: int = 320) -> dict[str, Any]:
    """One image of ``source``, as it is and under each item's recipe at a fixed end.

    ``items`` maps a key to ``(recipe, "min" | "max")``. Returns the row used (pass it back
    to keep showing the same image), the original and one rendering per key.
    """
    row = sample_row(source) if row is None or not 0 <= row < len(source) else row
    record, geometry, image_url = _record(source, row)
    image = load_image(image_url, int((geometry or {}).get("width") or 0), int((geometry or {}).get("height") or 0))
    rendered = {key: _render(image, geometry, draw(recipe, *image.size, np.random.default_rng(7), fixed=at), size)
                for key, (recipe, at) in items.items()}
    return {"row": row, "source": image_url, "original": _render(image, geometry, None, size), "items": rendered}


def average_image_bytes(source: Table, sample: int = 40) -> int:
    """Rough size of one image file of ``source``, from a sample, for disk estimates."""
    from granum.core.curation import image_column

    images = source.to_arrow().column(image_column(source)).to_pylist()
    if not images:
        return 0
    step = max(1, len(images) // sample)
    sizes = []
    for image in images[::step][:sample]:
        url = Url(image)
        if url.scheme == "file":
            try:
                sizes.append(os.path.getsize(url.path))
            except OSError:
                continue
    return int(sum(sizes) / len(sizes)) if sizes else 0
