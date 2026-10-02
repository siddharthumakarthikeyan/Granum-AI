"""Content-based media integrity; paths and modification times are not identities."""
from __future__ import annotations

import hashlib
import re
from collections.abc import Iterable
from typing import Any

from granum.core.url import Url, sample_key
from granum.errors import GranumError


class IntegrityError(GranumError):
    pass


def file_digest(reference: str | Url) -> dict[str, Any]:
    url = Url(reference)
    digest = hashlib.sha256()
    size = 0
    before = url.fs.info(url.path)
    with url.fs.open(url.path, "rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
            size += len(chunk)
    after = url.fs.info(url.path)
    for key in ("size", "mtime", "etag", "ETag", "version_id"):
        if before.get(key) != after.get(key):
            raise IntegrityError(f"media changed while being read: {reference}")
    return {"sha256": digest.hexdigest(), "bytes": size}


def media_manifest(tables: Iterable[Any]) -> dict[str, Any]:
    from granum.core.curation import CurationError, image_column

    files: dict[str, Any] = {}
    for table in tables:
        try:
            column = image_column(table)
        except CurationError:
            continue
        for ref in table.to_arrow().column(column).to_pylist():
            if not ref or sample_key(ref) in files:
                continue
            try:
                files[sample_key(ref)] = file_digest(ref)
            except (OSError, ValueError) as exc:
                raise IntegrityError(f"media is missing or unreadable: {ref}") from exc
    return {"format_version": 1, "algorithm": "sha256", "files": files}


def verify_media(manifest: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(manifest, dict) or manifest.get("format_version") != 1 or manifest.get("algorithm") != "sha256":
        raise IntegrityError("unsupported media manifest version or hash algorithm")
    files = manifest.get("files")
    if not isinstance(files, dict):
        raise IntegrityError("invalid media manifest: files must be an object")
    for ref, expected in files.items():
        if (not isinstance(ref, str) or not ref or not isinstance(expected, dict)
                or set(expected) != {"sha256", "bytes"}
                or not isinstance(expected["sha256"], str)
                or not re.fullmatch(r"[a-f0-9]{64}", expected["sha256"])
                or type(expected["bytes"]) is not int or expected["bytes"] < 0):
            raise IntegrityError("invalid media manifest: each file requires a SHA-256 digest and non-negative byte size")
    changed, missing = [], []
    for ref, expected in files.items():
        try:
            actual = file_digest(ref)
        except (OSError, ValueError, IntegrityError):
            missing.append(ref)
            continue
        if actual != expected:
            changed.append(ref)
    return {"ok": not changed and not missing, "checked": len(files), "changed": changed, "missing": missing}