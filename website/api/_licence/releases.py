"""The desktop build the site offers, read from the approved GitHub release.

Every push to the app's main branch is built and kept as the "latest" pre-release. A build
becomes the site's download only when it is approved: the *Publish download* workflow
checks its files and publishes them as a full release carrying ``release.json``. GitHub
serves the newest full release's file at a fixed address, which is what is read here, so
approving a build is all it takes for the site to offer it.
"""

from __future__ import annotations

import json
import re
import time
import urllib.request
from collections.abc import Callable
from typing import Any

#: How long an answer is kept before GitHub is asked again, in seconds.
TTL = 300
_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,120}")
_REPOSITORY = re.compile(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+")


def _fetch(url: str) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": "granum-website", "Accept": "application/json"})
    with urllib.request.urlopen(request, timeout=6) as response:  # noqa: S310 - https, fixed host
        return response.read(1_000_000)


def site_of(release: Any, repository: str) -> dict[str, Any]:
    """``release.json`` as the site settings the publication gate checks; {} if it is malformed."""
    if not isinstance(release, dict) or not isinstance(release.get("files"), dict):
        return {}
    tag = release.get("tag")
    if not isinstance(tag, str) or not _NAME.fullmatch(tag):
        return {}
    base = f"https://github.com/{repository}/releases/download/{tag}/"
    out: dict[str, Any] = {
        "version": release.get("version") if isinstance(release.get("version"), str) else "",
        "downloads": {}, "checksums": {}, "manifests": {},
        # Being the newest full release is the approval; the gate still checks the rest.
        "release": {"qualified": True, "channel": release.get("channel"), "source_revision": release.get("source_revision") or ""},
    }
    for name in ("windows", "linux"):
        entry = release["files"].get(name)
        if not isinstance(entry, dict):
            continue
        file, manifest, checksum = entry.get("name"), entry.get("manifest"), entry.get("sha256")
        if not all(isinstance(v, str) for v in (file, manifest, checksum)) or not _NAME.fullmatch(file) or not _NAME.fullmatch(manifest):
            continue
        out["downloads"][name] = base + file
        out["manifests"][name] = base + manifest
        out["checksums"][name] = checksum
    return out


class ApprovedRelease:
    """Site settings that follow the approved release of ``repository`` ("owner/name")."""

    def __init__(self, repository: str, *, contact: str = "", fetch: Callable[[str], bytes] = _fetch,
                 clock: Callable[[], float] = time.monotonic, ttl: float = TTL) -> None:
        if not _REPOSITORY.fullmatch(repository):
            raise ValueError("the release repository must be 'owner/name'")
        self.repository = repository
        self.url = f"https://github.com/{repository}/releases/latest/download/release.json"
        self._contact, self._fetch, self._clock, self._ttl = contact, fetch, clock, ttl
        self._site: dict[str, Any] = {}
        self._read_at: float | None = None

    def __call__(self) -> dict[str, Any]:
        now = self._clock()
        if self._read_at is None or now - self._read_at >= self._ttl:
            self._read_at = now
            try:
                self._site = site_of(json.loads(self._fetch(self.url)), self.repository)
            except Exception:  # noqa: BLE001 - GitHub out of reach, or no build approved yet
                pass  # keep offering what was last known to be approved
        return {**self._site, "contact": self._contact}
