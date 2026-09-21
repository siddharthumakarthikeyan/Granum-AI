"""A small generated example dataset: coloured shapes, with a few deliberate label problems.

It lets someone try the whole loop (import checks, browsing, review, editing, training)
without their own data. The images are drawn here, so there is nothing to license and
nothing to ship: the same seed always draws the same dataset.

The deliberate problems, so the checks and the review have something real to find:

* boxes missing from shapes that are drawn (``missing``)
* boxes carrying the wrong class (``wrong_class``)
* boxes far larger than their shape (``loose``)
* one box with no width (import preflight flags it)

Most are in the training set; a few missing and wrong-class boxes are in the validation and
test sets too, where a model's evidence is not weakened by having trained on the label.
* two training images copied byte for byte into the validation set (preflight flags them)

A project imported from it carries an ``example.json`` marker and does not count against a
plan's project limit; adding other data to it removes the marker.
"""

from __future__ import annotations

import json
import math
import random
import shutil
from pathlib import Path
from typing import Any

from granum.core.layout import ProjectLayout
from granum.core.url import Url

VERSION = 2
NAME = f"shapes-v{VERSION}"
CLASSES = ["circle", "square", "triangle"]
SPLITS = {"train": 84, "valid": 24, "test": 12}
SIZE = (320, 240)
MARKER = "example.json"
DESCRIPTION = "Generated example: coloured shapes, with deliberate label problems"

# Which images of each split get which problem (indices into the split).
PLANTED: dict[str, dict[str, tuple[int, ...]]] = {
    "train": {"missing": (3, 11, 19, 27, 35, 43, 51, 59), "wrong_class": (6, 14, 22, 30, 38, 46),
              "loose": (9, 25, 41, 57), "zero_width": (17,)},
    "valid": {"missing": (4, 9, 15), "wrong_class": (6, 12, 20)},
    "test": {"missing": (3,), "wrong_class": (7,)},
}
COPIED_TO_VALID = (5, 33)


def examples_dir(root: Url) -> Url:
    return Url(root) / ".examples"


def example_root(root: Url) -> Url:
    return examples_dir(root) / NAME


def is_example_project(layout: ProjectLayout, project_name: str) -> bool:
    return (layout.project(project_name) / MARKER).exists()


def mark_example_project(layout: ProjectLayout, project_name: str) -> None:
    (layout.project(project_name) / MARKER).write_text(json.dumps({"example": NAME, "version": VERSION}))


def unmark_example_project(layout: ProjectLayout, project_name: str) -> None:
    marker = layout.project(project_name) / MARKER
    if marker.exists():
        marker.rm()


def counted_projects(layout: ProjectLayout) -> list[str]:
    """Project folders that count against a plan's project limit."""
    if not layout.projects_dir.exists():
        return []
    return [u.name for u in layout.projects_dir.ls() if u.is_dir() and not (u / MARKER).exists()]


def sources(root: Url) -> list[dict[str, str]]:
    """The example's splits, as the import flow takes them; writes the files if needed."""
    folder = ensure_example(root)
    return [
        {"split": split, "annotations": str(folder / split / "_annotations.coco.json"), "images": str(folder / split)}
        for split in SPLITS
    ]


def ensure_example(root: Url) -> Url:
    """Draw the dataset once under ``<root>/.examples/``; later calls reuse it."""
    target = example_root(root)
    if (target / "done.json").exists():
        return target
    # Drawn beside the target and renamed into place, so a half-written example is never used.
    staging = Path((examples_dir(root) / f".{NAME}.partial").path)
    if staging.exists():
        shutil.rmtree(staging)
    _draw(staging)
    (staging / "done.json").write_text(json.dumps({"version": VERSION}))
    final = Path(target.path)
    if final.exists():
        shutil.rmtree(final)
    staging.rename(final)
    return target


# -- drawing ---------------------------------------------------------------------------

PALETTE = [(231, 76, 60), (46, 204, 113), (52, 152, 219), (241, 196, 15), (155, 89, 182), (230, 126, 34), (26, 188, 156)]


def _background(rng: random.Random) -> Any:
    import numpy as np

    w, h = SIZE
    base = np.array([rng.randint(40, 200) for _ in range(3)], dtype=np.float32)
    tint = np.array([rng.randint(-60, 60) for _ in range(3)], dtype=np.float32)
    ramp = np.linspace(0, 1, w, dtype=np.float32)[None, :, None] * 0.6 + np.linspace(0, 1, h, dtype=np.float32)[:, None, None] * 0.4
    noise = np.random.default_rng(rng.randint(0, 2**31)).normal(0, 9, (h, w, 3)).astype(np.float32)
    pixels = base[None, None, :] + ramp * tint[None, None, :] + noise
    return np.clip(pixels, 0, 255).astype(np.uint8)


def _shape(draw: Any, kind: str, box: tuple[float, float, float, float], colour: tuple[int, int, int], angle: float) -> None:
    x0, y0, x1, y1 = box
    if kind == "circle":
        draw.ellipse(box, fill=colour, outline=(20, 20, 20))
    elif kind == "square":
        draw.rectangle(box, fill=colour, outline=(20, 20, 20))
    else:
        cx, r = (x0 + x1) / 2, (x1 - x0) / 2
        points = [(cx + r * math.sin(angle + k * 2 * math.pi / 3), (y0 + y1) / 2 - r * math.cos(angle + k * 2 * math.pi / 3)) for k in range(3)]
        xs, ys = [p[0] for p in points], [p[1] for p in points]
        # Fit the triangle to the box it is labelled with.
        sx, sy = (x1 - x0) / (max(xs) - min(xs)), (y1 - y0) / (max(ys) - min(ys))
        draw.polygon([(x0 + (px - min(xs)) * sx, y0 + (py - min(ys)) * sy) for px, py in points], fill=colour, outline=(20, 20, 20))


def _place(rng: random.Random, placed: list[tuple[float, float, float, float]]) -> tuple[float, float, float, float] | None:
    w, h = SIZE
    for _ in range(40):
        size = rng.randint(22, 64)
        x0, y0 = rng.randint(4, w - size - 4), rng.randint(4, h - size - 4)
        box = (float(x0), float(y0), float(x0 + size), float(y0 + size))
        if all(box[2] < p[0] - 3 or box[0] > p[2] + 3 or box[3] < p[1] - 3 or box[1] > p[3] + 3 for p in placed):
            return box
    return None


def _draw(folder: Path) -> None:
    from PIL import Image, ImageDraw

    rng = random.Random(20260919)
    categories = [{"id": i + 1, "name": name, "supercategory": "shape"} for i, name in enumerate(CLASSES)]
    train_files: list[str] = []
    train_annotations: list[dict[str, Any]] = []
    for split, count in SPLITS.items():
        out = folder / split
        out.mkdir(parents=True)
        images, annotations = [], []
        for n in range(count):
            file_name = f"{split}_{n:03d}.jpg"
            if split == "valid" and n < len(COPIED_TO_VALID):
                # A byte-identical copy of a training image, as happens when splits are cut carelessly.
                source = train_files[COPIED_TO_VALID[n]]
                shutil.copyfile(folder / "train" / source, out / file_name)
                with Image.open(out / file_name) as copied:
                    size = copied.size
                images.append({"id": n, "file_name": file_name, "width": size[0], "height": size[1]})
                # Same image, same labels: only the split is wrong.
                for ann in [a for a in train_annotations if a["image_id"] == COPIED_TO_VALID[n]]:
                    annotations.append({**ann, "id": len(annotations), "image_id": n})
                continue
            canvas = Image.fromarray(_background(rng))
            draw = ImageDraw.Draw(canvas)
            placed: list[tuple[float, float, float, float]] = []
            objects = []
            for _ in range(rng.randint(1, 5)):
                box = _place(rng, placed)
                if box is None:
                    break
                placed.append(box)
                kind = rng.choice(CLASSES)
                _shape(draw, kind, box, rng.choice(PALETTE), rng.uniform(-0.4, 0.4))
                objects.append((kind, box))
            canvas.save(out / file_name, quality=90)
            images.append({"id": n, "file_name": file_name, "width": SIZE[0], "height": SIZE[1]})
            planted = PLANTED.get(split, {})
            for k, (kind, (x0, y0, x1, y1)) in enumerate(objects):
                label = CLASSES.index(kind)
                bbox = [x0, y0, x1 - x0, y1 - y0]
                if k == 0:
                    # A missing box only where another object keeps the image labelled.
                    if n in planted.get("missing", ()) and len(objects) > 1:
                        continue
                    if n in planted.get("wrong_class", ()):
                        label = (label + 1) % len(CLASSES)
                    if n in planted.get("loose", ()):
                        grow = 0.5 * (x1 - x0)
                        bbox = [max(0.0, x0 - grow / 2), max(0.0, y0 - grow / 2), min(SIZE[0] - x0, (x1 - x0) + grow), min(SIZE[1] - y0, (y1 - y0) + grow)]
                    if n in planted.get("zero_width", ()):
                        bbox = [x0, y0, 0.0, y1 - y0]
                annotations.append({
                    "id": len(annotations), "image_id": n, "category_id": label + 1, "bbox": [round(v, 1) for v in bbox],
                    "area": round(bbox[2] * bbox[3], 1), "iscrowd": 0,
                })
        if split == "train":
            train_files = [i["file_name"] for i in images]
            train_annotations = annotations
        document = {
            "info": {"description": DESCRIPTION, "version": str(VERSION)},
            "images": images, "annotations": annotations, "categories": categories,
        }
        (out / "_annotations.coco.json").write_text(json.dumps(document))

