"""Shared geometry and mask conversion, in image pixel coordinates."""

from __future__ import annotations

import json
from typing import Any

import numpy as np

from granum.errors import TableError


def json_value(value: Any, default: Any = None) -> Any:
    if value is None or value == "":
        return default
    return json.loads(value) if isinstance(value, str) else value


def extra_of(instance: dict[str, Any]) -> dict[str, Any]:
    value = json_value(instance.get("coco_extra"), {})
    if not isinstance(value, dict):
        raise TableError("annotation extras must be an object")
    return value


def polygon_area(points: Any) -> float:
    xy = np.asarray(points, dtype=float).reshape(-1, 2)
    if len(xy) < 3 or not np.isfinite(xy).all():
        return 0.0
    return float(abs(np.dot(xy[:, 0], np.roll(xy[:, 1], -1)) - np.dot(xy[:, 1], np.roll(xy[:, 0], -1))) / 2)


def polygon_bounds(points: Any) -> list[float]:
    xy = np.asarray(points, dtype=float).reshape(-1, 2)
    if len(xy) < 3 or not np.isfinite(xy).all():
        raise TableError("a polygon needs at least three finite points")
    low, high = xy.min(axis=0), xy.max(axis=0)
    return [float(low[0]), float(low[1]), float(high[0]), float(high[1])]


def oriented_corners(cx: float, cy: float, width: float, height: float, angle: float) -> list[float]:
    """Centre, width, height, angle in radians to four ordered corners."""
    if not np.isfinite([cx, cy, width, height, angle]).all() or min(width, height) <= 0:
        raise TableError("an oriented box needs finite values and positive dimensions")
    local = np.array([[-width, -height], [width, -height], [width, height], [-width, height]]) / 2
    c, s = np.cos(angle), np.sin(angle)
    return (local @ np.array([[c, s], [-s, c]]) + [cx, cy]).reshape(-1).tolist()


def minimum_rectangle(points: Any, *, bounds: tuple[float, float] | None = None) -> list[float]:
    """Smallest edge-aligned enclosing rectangle around an ordered convex polygon.

    When bounds are given, discard candidates extending outside the image. Include
    the axis-aligned rectangle as a fallback, preserving the complete visible polygon
    instead of independently clamping corners and creating a non-rectangular box.
    """
    xy = np.asarray(points, dtype=float).reshape(-1, 2)
    if len(xy) < 3 or polygon_area(xy) <= 0:
        raise TableError("an oriented rectangle needs a nondegenerate polygon")
    best_area, best = float("inf"), None
    edges = np.roll(xy, -1, axis=0) - xy
    if bounds is not None:
        if min(bounds) <= 0 or (xy < -1e-7).any() or (xy > np.asarray(bounds) + 1e-7).any():
            raise TableError("clip the polygon to positive image bounds before fitting a rectangle")
        edges = np.vstack([edges, [1, 0]])
    for edge in edges:
        angle = float(np.arctan2(edge[1], edge[0]))
        c, s = np.cos(angle), np.sin(angle)
        rotation = np.array([[c, -s], [s, c]])
        local = xy @ rotation
        low, high = local.min(axis=0), local.max(axis=0)
        area = float(np.prod(high - low))
        if area < best_area:
            centre = (low + high) / 2 @ rotation.T
            candidate = oriented_corners(float(centre[0]), float(centre[1]), float(high[0] - low[0]), float(high[1] - low[1]), angle)
            if bounds is not None:
                corners = np.asarray(candidate).reshape(-1, 2)
                if (corners < -1e-7).any() or (corners > np.asarray(bounds) + 1e-7).any():
                    continue
                candidate = np.clip(corners, [0, 0], bounds).reshape(-1).tolist()
            best = candidate
            best_area = area
    assert best is not None
    return best


def mask_array(segmentation: Any, width: int, height: int) -> np.ndarray:
    """Decode COCO polygon or RLE using COCO's own rasterization rules."""
    if min(width, height) <= 0 or width * height > 100_000_000:
        raise TableError("mask dimensions must be positive and at most 100 million pixels")
    value = json_value(segmentation, [])
    if isinstance(value, dict) and value.get("size") == [height, width]:
        counts = value.get("counts")
        if isinstance(counts, (str, bytes)):
            counts = compressed_counts(counts)
        if not isinstance(counts, list) or any(not isinstance(n, int) or n < 0 for n in counts) or sum(counts) != width * height:
            raise TableError("invalid RLE mask counts")
        pixels = np.zeros(width * height, dtype=np.uint8)
        at = 0
        for i, length in enumerate(counts):
            if i % 2:
                pixels[at:at + length] = 1
            at += length
        return pixels.reshape(height, width, order="F")
    if isinstance(value, list):
        if not value:
            return np.zeros((height, width), dtype=np.uint8)
        try:
            from pycocotools import mask as masks
        except ImportError as exc:
            raise TableError("polygon rasterization needs granum[vision] (pycocotools)") from exc
        for polygon in value:
            if not isinstance(polygon, list) or len(polygon) < 6 or len(polygon) % 2 or not np.isfinite(polygon).all():
                raise TableError("invalid COCO polygon")
        rle = masks.merge(masks.frPyObjects(value, height, width))
    else:
        raise TableError("segmentation must be COCO polygons or RLE with matching image dimensions")
    try:
        return masks.decode(rle).astype(np.uint8)
    except (ValueError, TypeError) as exc:
        raise TableError("invalid COCO segmentation") from exc


def compressed_counts(value: str | bytes) -> list[int]:
    """Decode COCO's differential signed five-bit integers before allocating a mask."""
    text = value.decode("ascii") if isinstance(value, bytes) else value
    counts: list[int] = []
    at = 0
    while at < len(text):
        number = bits = 0
        while True:
            if at >= len(text) or bits > 35:
                raise TableError("invalid compressed mask counts")
            part = ord(text[at]) - 48
            at += 1
            if not 0 <= part <= 63:
                raise TableError("invalid compressed mask counts")
            number += (part & 31) << bits
            bits += 5
            if not part & 32:
                if part & 16:
                    number -= 1 << bits
                break
        if len(counts) > 2:
            number += counts[-2]
        counts.append(number)
    return counts


def encode_mask(mask: Any) -> dict[str, Any]:
    """Portable, uncompressed COCO RLE; holes and disconnected regions are lossless."""
    array = np.asarray(mask)
    if array.ndim != 2:
        raise TableError("a mask must be a two-dimensional array")
    flat = (array != 0).ravel(order="F")
    boundaries = np.flatnonzero(np.diff(np.r_[False, flat, False]))
    counts = np.diff(np.r_[0, boundaries, len(flat)]).astype(int).tolist()
    # End in either foreground or background; a trailing zero is harmless but redundant.
    if len(counts) > 1 and counts[-1] == 0:
        counts.pop()
    return {"size": list(array.shape), "counts": counts}


def yolo_polygon(segmentation: Any, width: int, height: int) -> list[float]:
    """Join disjoint outlines with zero-area bridges for YOLO's single-outline format.

    Bitmap contours are pixel-quantized. COCO RLE remains the lossless export format.
    """
    value = json_value(segmentation, [])
    if isinstance(value, dict):
        try:
            import cv2
        except ImportError as exc:
            raise TableError("bitmap-to-YOLO conversion needs granum[vision] (OpenCV)") from exc
        contours, _ = cv2.findContours(mask_array(value, width, height), cv2.RETR_TREE, cv2.CHAIN_APPROX_SIMPLE)
        polygons = [c.reshape(-1, 2).astype(float) for c in contours if len(c) >= 3]
    else:
        polygons = [np.asarray(p, dtype=float).reshape(-1, 2) for p in value if len(p) >= 6]
    if not polygons:
        raise TableError("annotation has no nonempty mask to export as YOLO segmentation")
    joined = polygons[0]
    for polygon in polygons[1:]:
        # Avoid allocating the quadratic distance matrix for very detailed contours.
        best = (float("inf"), 0, 0)
        for at, point in enumerate(polygon):
            distances = ((joined - point) ** 2).sum(axis=1)
            j = int(distances.argmin())
            best = min(best, (float(distances[j]), j, at))
        _, j, at = best
        loop = np.concatenate((polygon[at:], polygon[:at + 1]))
        joined = np.concatenate((joined[:j + 1], loop, joined[j:]))
    return joined.reshape(-1).tolist()
