"""Downsampled image copies.

A table cell is drawn at a fraction of the size of the image behind it. Shipping the
full-resolution original to render a 64px cell is the difference between a dashboard
that scrolls and one that does not.

Thumbnails live under the dataset's own ``cache/thumbnails`` directory, so anyone who
can read the dataset gets them, and they are deleted with it.
"""

from __future__ import annotations

import hashlib
import io
import os
from collections.abc import Iterable, Sequence

from granum._logging import get_logger
from granum.core.layout import ProjectLayout
from granum.core.objects.table import Table
from granum.core.schemas import ImageSchema
from granum.core.url import Url
from granum.errors import GranumError

logger = get_logger("thumbnails")

DEFAULT_SIZES: tuple[int, ...] = (64, 128, 256)
THUMBNAIL_FORMAT = "JPEG"
THUMBNAIL_SUFFIX = ".jpg"


class ThumbnailError(GranumError):
    """A thumbnail could not be produced."""


def thumbnail_key(image_url: Url | str) -> str:
    """A stable filename for an image, independent of its path length or characters.

    On Windows ``C:\\a.png`` and ``C:/a.png`` are one file, so they share one key.
    """
    text = str(image_url)
    if os.name == "nt":
        text = text.replace("\\", "/")
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:32]


def thumbnail_url(cache_dir: Url, image_url: Url | str, size: int) -> Url:
    return Url(cache_dir) / str(size) / f"{thumbnail_key(image_url)}{THUMBNAIL_SUFFIX}"


def image_columns(table: Table) -> list[str]:
    return [name for name in table.columns if isinstance(table.schema[name], ImageSchema)]


def render_thumbnail(data: bytes, size: int) -> bytes:
    """Downscale image bytes, preserving aspect ratio."""
    try:
        from PIL import Image
    except ImportError as exc:  # pragma: no cover - depends on optional extra
        raise ThumbnailError("thumbnails need Pillow. Install granum[images].") from exc

    with Image.open(io.BytesIO(data)) as image:
        image = image.convert("RGB")
        image.thumbnail((size, size), Image.LANCZOS)
        buffer = io.BytesIO()
        image.save(buffer, THUMBNAIL_FORMAT, quality=85)
        return buffer.getvalue()


def create_for_table(
    table: Table,
    *,
    sizes: Sequence[int] = DEFAULT_SIZES,
    overwrite: bool = False,
    dry_run: bool = False,
    cache_dir: Url | None = None,
) -> dict[str, int]:
    """Publish thumbnails for every image column of ``table``.

    Every size the service may ask for is generated up front, because which one it asks
    for is its own decision.
    """
    from granum.core.config import get_config

    columns = image_columns(table)
    if not columns:
        return {"written": 0, "skipped": 0, "failed": 0, "images": 0}

    target_cache = cache_dir or ProjectLayout(get_config().project_root).thumbnails(
        table.project_name, table.dataset_name
    )

    written = skipped = failed = images = 0
    arrow = table.to_arrow()
    for column in columns:
        for value in arrow.column(column).to_pylist():
            if not value:
                continue
            images += 1
            source = Url(value)
            for size in sizes:
                destination = thumbnail_url(target_cache, value, size)
                if destination.exists() and not overwrite:
                    skipped += 1
                    continue
                if dry_run:
                    written += 1
                    continue
                try:
                    destination.write_bytes(render_thumbnail(source.read_bytes(), size))
                    written += 1
                except Exception as exc:  # noqa: BLE001 - one bad image is not fatal
                    logger.debug("thumbnail failed for %s: %s", source, exc)
                    failed += 1
    return {"written": written, "skipped": skipped, "failed": failed, "images": images}


def create_for_run(run, **kwargs) -> dict[str, int]:
    """Publish thumbnails for every input Table a Run references."""
    totals = {"written": 0, "skipped": 0, "failed": 0, "images": 0}
    seen: set[str] = set()
    for metrics in run.metrics_tables():
        if metrics.foreign_table_url is None or str(metrics.foreign_table_url) in seen:
            continue
        seen.add(str(metrics.foreign_table_url))
        result = create_for_table(metrics.input_table(), **kwargs)
        for key in totals:
            totals[key] += result[key]
    return totals


def resolve(cache_dirs: Iterable[Url], image_url: Url | str, size: int) -> Url | None:
    """Find a published thumbnail for an image, or None to fall back to the original."""
    for cache_dir in cache_dirs:
        candidate = thumbnail_url(cache_dir, image_url, size)
        if candidate.exists():
            return candidate
    return None


def nearest_size(size: int, available: Sequence[int] = DEFAULT_SIZES) -> int:
    """The smallest published size that still covers ``size``."""
    for candidate in sorted(available):
        if candidate >= size:
            return candidate
    return max(available)
