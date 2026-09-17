"""Shared pieces of the format importers and exporters."""

from __future__ import annotations

import os
import shutil
from pathlib import Path
from typing import Any

from granum.core.objects.table import WEIGHT_COLUMN, Table
from granum.core.schemas import ImageSchema
from granum.core.schemas.geometry import BoundingBoxes2DSchema
from granum.core.url import Url
from granum.errors import TableError

IMAGE_STRATEGIES = ("copy", "symlink", "hardlink")


def geometry_column(table: Table, column: str | None) -> str:
    """The boxes column to export: the one named, or the only one there is."""
    candidates = [n for n in table.columns if isinstance(table.schema[n], BoundingBoxes2DSchema)]
    if column is not None:
        if column not in candidates:
            raise TableError(f"{column!r} is not a bounding-box column; box columns: {candidates}")
        return column
    if len(candidates) != 1:
        raise TableError(f"pass column=...: this table has {len(candidates)} box columns {candidates}")
    return candidates[0]


def image_column(table: Table) -> str:
    candidates = [n for n in table.columns if isinstance(table.schema[n], ImageSchema)]
    if not candidates:
        raise TableError("this table has no image column to export")
    return candidates[0]


def kept_rows(table: Table, weight_threshold: float | None) -> list[int]:
    """Rows to export. With a threshold, rows at or below it are left out -- weight 0
    is how a dashboard marks an image unusable, and exports should honour that."""
    if weight_threshold is None or WEIGHT_COLUMN not in table.schema:
        return list(range(len(table)))
    weights = table.to_arrow().column(WEIGHT_COLUMN).to_pylist()
    return [i for i, w in enumerate(weights) if w is not None and w > weight_threshold]


def place_image(source: str, target: Path, strategy: str) -> None:
    """Put an image where an export expects it."""
    if strategy not in IMAGE_STRATEGIES:
        raise TableError(f"image_strategy must be one of {IMAGE_STRATEGIES}, got {strategy!r}")
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists() or target.is_symlink():
        target.unlink()
    resolved = Url(source).resolved
    if strategy == "copy":
        shutil.copyfile(resolved, target)
    elif strategy == "symlink":
        try:
            os.symlink(os.path.abspath(resolved), target)
        except OSError:
            # Windows allows symlinks only with Developer Mode or admin rights.
            _link_or_copy(resolved, target)
    else:
        _link_or_copy(resolved, target)


def _link_or_copy(resolved: str, target: Path) -> None:
    try:
        os.link(resolved, target)
    except OSError:
        # Hard links need the same drive (and a filesystem that has them).
        shutil.copyfile(resolved, target)


def root_producer(table: Table, op: str) -> dict[str, Any]:
    """Args recorded by the importer that created this Table's lineage root."""
    for ancestor in table.lineage():
        if ancestor.producer.get("op") == op:
            return dict(ancestor.producer.get("args") or {})
    return {}


def clean_number(value: float) -> float | int:
    """Undo float noise from coordinate conversion: 473.07000000000005 -> 473.07."""
    rounded = round(float(value), 6)
    return int(rounded) if rounded.is_integer() and abs(rounded) < 2**53 else rounded
