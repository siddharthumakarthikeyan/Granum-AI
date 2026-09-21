"""Where a dataset's image vectors are kept.

One file per dataset, beside its reviews: the vectors, the image each row belongs to, and the
set it was in when they were computed. Keyed by image reference rather than row position, so a
new version of a set does not invalidate them -- the same reason review decisions are keyed that
way (see :mod:`granum.core.reviews`).

Vectors go in an ``.npz``; everything else in a ``.json`` beside it, so the index is readable
without numpy and nothing is stored as a pickled object array.

Recomputing is cheap enough that this is a cache, not a record: deleting the files loses nothing
but the time to make them again. Images that have appeared since the last run are reported by
:meth:`EmbeddingStore.missing`, so the dashboard can offer to fill them in rather than redo the
whole set.
"""

from __future__ import annotations

import io
import json
from collections.abc import Sequence
from datetime import datetime, timezone
from typing import Any

import numpy as np

from granum.core.config import Config, get_config
from granum.core.layout import ProjectLayout, sanitize
from granum.core.url import Url
from granum.errors import GranumError
from granum.metrics.embeddings import EMBEDDINGS_VERSION, describe_embedder


class EmbeddingError(GranumError):
    """Vectors could not be read or written."""


class EmbeddingStore:
    """The vectors for one dataset of one project."""

    def __init__(self, project_name: str, dataset_name: str, *, config: Config | None = None) -> None:
        config = config or get_config()
        self.project_name = project_name
        self.dataset_name = dataset_name
        folder = ProjectLayout(config.project_root).project(project_name) / "embeddings"
        self.vectors_url: Url = folder / f"{sanitize(dataset_name)}.npz"
        self.index_url: Url = folder / f"{sanitize(dataset_name)}.json"

    # -- reading ------------------------------------------------------------

    def status(self) -> dict[str, Any] | None:
        """What was computed, when and with what, or None when there is nothing yet."""
        if not self.index_url.exists():
            return None
        try:
            payload = json.loads(self.index_url.read_text())
        except (ValueError, OSError) as exc:  # noqa: PERF203 - a damaged cache is not fatal
            raise EmbeddingError(f"the embedding index of {self.dataset_name!r} cannot be read: {exc}") from exc
        return {
            "version": payload.get("version"),
            "embedder": describe_embedder(payload.get("embedder", "descriptor")),
            "images": len(payload.get("images", [])),
            "unreadable": payload.get("unreadable", 0),
            "created": payload.get("created"),
            "sets": sorted(set(payload.get("sets", []))),
            "stale": payload.get("version") != EMBEDDINGS_VERSION,
        }

    def load(self) -> tuple[list[str], list[str], np.ndarray]:
        """The images, their sets, and their vectors, in one order."""
        if not self.index_url.exists() or not self.vectors_url.exists():
            raise EmbeddingError(f"{self.dataset_name!r} has no embeddings yet")
        payload = json.loads(self.index_url.read_text())
        with np.load(io.BytesIO(self.vectors_url.read_bytes()), allow_pickle=False) as data:
            vectors = data["vectors"]
        images = list(payload.get("images", []))
        if len(images) != len(vectors):
            raise EmbeddingError(
                f"the embeddings of {self.dataset_name!r} are damaged: {len(vectors)} vectors for "
                f"{len(images)} images. Compute them again."
            )
        return images, list(payload.get("sets", [])), vectors

    def missing(self, images: Sequence[str]) -> list[str]:
        """Which of ``images`` have no vector yet, in the order given."""
        try:
            known = set(self.load()[0])
        except EmbeddingError:
            return list(images)
        return [image for image in images if image not in known]

    # -- writing ------------------------------------------------------------

    def save(
        self,
        images: Sequence[str],
        sets: Sequence[str],
        vectors: np.ndarray,
        *,
        embedder: str,
        unreadable: int = 0,
    ) -> dict[str, Any]:
        """Replace what is stored."""
        if not (len(images) == len(sets) == len(vectors)):
            raise EmbeddingError("images, sets and vectors must be the same length")
        buffer = io.BytesIO()
        np.savez_compressed(buffer, vectors=np.asarray(vectors, dtype=np.float32))
        self.vectors_url.write_bytes(buffer.getvalue())
        self.index_url.write_text(json.dumps({
            "version": EMBEDDINGS_VERSION,
            "embedder": embedder,
            "created": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "unreadable": int(unreadable),
            "images": list(images),
            "sets": list(sets),
        }))
        return self.status() or {}

    def delete(self) -> None:
        for url in (self.vectors_url, self.index_url):
            if url.exists():
                url.rm()
