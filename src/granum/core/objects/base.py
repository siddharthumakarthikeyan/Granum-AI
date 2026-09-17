"""Serialization shared by every Granum object.

An object is a *directory* containing ``object.granum.json``. The object's URL is the
directory, never the file -- the same convention a web server uses for ``index.html``.

Writers also touch ``index.granum.json`` change markers up the tree. The Stage 3 indexer
compares those markers before scanning, so an unchanged project costs one metadata
lookup per interval rather than a full recursive listing. That difference is what makes
polling cloud storage affordable.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, ClassVar

from granum.core.layout import INDEX_FILENAME, OBJECT_FILENAME
from granum.core.url import Url
from granum.errors import ImmutableError, ObjectNotFoundError

SCHEMA_VERSION = 1


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds")


def touch_index_markers(url: Url, *, stop_at: Url | None = None, max_depth: int = 16) -> None:
    """Write change-signal markers at ``url`` and every ancestor up to the scan root.

    The marker must reach the root the indexer actually watches, or the indexer skips
    the tree and never notices the write. Stopping short is not a small bug: a running
    service would serve a stale index indefinitely.
    """
    if stop_at is None:
        try:
            from granum.core.config import get_config

            stop_at = get_config().project_root
        except Exception:  # noqa: BLE001 - markers are best-effort, never fatal
            stop_at = None

    payload = json.dumps({"modified": utcnow(), "version": SCHEMA_VERSION})
    root_text = str(Url(stop_at)) if stop_at is not None else None

    seen: set[str] = set()
    current = Url(url)
    for _ in range(max_depth):
        key = str(current)
        if key in seen:
            break
        seen.add(key)
        try:
            (current / INDEX_FILENAME).write_text(payload)
        except (OSError, ValueError):
            break
        if root_text is not None and key == root_text:
            break
        parent = current.parent
        if str(parent) == key:
            break
        current = parent


def read_object_payload(url: Url) -> dict[str, Any]:
    """Load the serialized body of the object stored at ``url``."""
    target = Url(url) / OBJECT_FILENAME
    if not target.exists():
        raise ObjectNotFoundError(f"no Granum object at {url} (expected {OBJECT_FILENAME})")
    return json.loads(target.read_text())


def write_object_payload(url: Url, payload: dict[str, Any]) -> Url:
    """Write an object body, then touch the index markers above it."""
    url = Url(url)
    url.mkdir()
    (url / OBJECT_FILENAME).write_text(json.dumps(payload, indent=2, sort_keys=False))
    touch_index_markers(url.parent)
    return url


class Immutable:
    """Mixin that turns attribute assignment into a useful error.

    Immutability is not a style preference here. The entire revision and lineage story
    assumes a Table never changes after it is written, and a single convenience method
    that writes in place would make every recorded lineage a lie.
    """

    _initialized: bool = False

    def __setattr__(self, name: str, value: Any) -> None:
        if getattr(self, "_initialized", False):
            raise ImmutableError(type(self).__name__)
        object.__setattr__(self, name, value)

    def __delattr__(self, name: str) -> None:
        raise ImmutableError(type(self).__name__)

    def _seal(self) -> None:
        object.__setattr__(self, "_initialized", True)


_OBJECT_TYPES: dict[str, type[GranumObject]] = {}


def register_object_type(cls: type[GranumObject]) -> type[GranumObject]:
    """Register a class so ``load_object`` can reconstruct it from disk."""
    _OBJECT_TYPES[cls.type_name] = cls
    return cls


def load_object(url: Url) -> GranumObject:
    """Open whatever Granum object lives at ``url``, dispatching on its recorded type."""
    url = Url(url)
    payload = read_object_payload(url)
    type_name = payload.get("type", "")
    cls = _OBJECT_TYPES.get(type_name)
    if cls is None:
        raise ObjectNotFoundError(
            f"{url} holds an object of unknown type {type_name!r}. "
            f"Known types: {sorted(_OBJECT_TYPES)}"
        )
    return cls.from_dict(payload, url)


class GranumObject(Immutable):
    """Base for Tables, Runs and metrics tables."""

    type_name: ClassVar[str] = "object"

    def to_dict(self) -> dict[str, Any]:
        raise NotImplementedError

    @classmethod
    def from_dict(cls, payload: dict[str, Any], url: Url) -> GranumObject:
        raise NotImplementedError
