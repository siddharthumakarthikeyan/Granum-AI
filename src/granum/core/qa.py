"""Annotation review and shipping: the gate between labelling and training.

Every image of a new dataset starts ``unreviewed``. A reviewer marks it ``reviewed`` when
the labels are right, or sends it back for ``rework`` with a comment saying what to fix;
the annotator fixes it and returns it to ``unreviewed`` for another look. Anyone can add
comments to an image's thread at any time.

A dataset version (:meth:`QaLog.release`, "Create dataset" in the dashboard) records a name,
a description and the exact version of each set it covers, optionally left with only its
verified images; only set versions in a dataset version are offered for training. Older
shipments (:meth:`QaLog.ship`, which required every image reviewed) live in the same log and
read as numbered dataset versions.

Both logs are append-only JSON lines beside the dataset's other review decisions, so who
reviewed, commented and shipped what, and when, is never lost. Images are identified by
their image reference, which survives new versions; row positions do not.
"""

from __future__ import annotations

import getpass
import json
import threading
import uuid
from collections.abc import Iterable
from datetime import datetime, timezone
from typing import Any

from granum.core.config import Config, get_config
from granum.core.layout import ProjectLayout, sanitize
from granum.core.url import Url, sample_key
from granum.errors import GranumError

STATUSES = ("unreviewed", "reviewed", "rework")
MAX_COMMENT = 4000
MAX_AUTHOR = 80

_locks: dict[str, threading.Lock] = {}
_locks_guard = threading.Lock()


class QaError(GranumError):
    """A review status, comment or shipment could not be recorded."""


def new_release_id() -> str:
    return uuid.uuid4().hex[:12]


def _lock_for(key: str) -> threading.Lock:
    with _locks_guard:
        return _locks.setdefault(key, threading.Lock())


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _author(author: str | None) -> str:
    author = (author or "").strip()
    if not author:
        try:
            author = getpass.getuser()
        except Exception:  # noqa: BLE001 - no user name available in some containers
            author = ""
    if len(author) > MAX_AUTHOR:
        raise QaError(f"names are at most {MAX_AUTHOR} characters")
    return author


def _append(url: Url, events: list[dict[str, Any]]) -> None:
    text = "".join(json.dumps(e, separators=(",", ":")) + "\n" for e in events)
    with _lock_for(str(url)):
        url.parent.mkdir()
        with url.fs.open(url.path, "ab") as handle:
            handle.write(text.encode("utf-8"))


def _read(url: Url) -> list[dict[str, Any]]:
    if not url.exists():
        return []
    with _lock_for(str(url)):
        text = url.read_text()
    out = []
    for line in text.splitlines():
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue  # a torn final line from an interrupted write
        if isinstance(event, dict):
            out.append(event)
    return out


class QaLog:
    """Review statuses, comments and shipments for one dataset of one project."""

    def __init__(self, project_name: str, dataset_name: str, *, config: Config | None = None) -> None:
        config = config or get_config()
        self.project_name = project_name
        self.dataset_name = dataset_name
        folder = ProjectLayout(config.project_root).project(project_name) / "reviews"
        self.url: Url = folder / f"{sanitize(dataset_name)}.qa.jsonl"
        self.ships_url: Url = folder / f"{sanitize(dataset_name)}.ships.jsonl"

    # -- statuses and comments ----------------------------------------------

    def set_status(
        self,
        samples: Iterable[str],
        status: str,
        *,
        comment: str = "",
        author: str | None = None,
        table_url: str | None = None,
    ) -> int:
        """Record a status for each image. Rework needs a comment saying what to fix."""
        if status not in STATUSES:
            raise QaError(f"status must be one of {list(STATUSES)}, got {status!r}")
        comment = self._comment(comment)
        if status == "rework" and not comment:
            raise QaError("say what needs rework")
        keys = list(dict.fromkeys(sample_key(s) for s in samples if s is not None and str(s)))
        if not keys:
            return 0
        who, now = _author(author), _now()
        _append(self.url, [
            {"sample": k, "status": status, "comment": comment, "author": who, "time": now, "table": table_url}
            for k in keys
        ])
        return len(keys)

    def add_comment(self, sample: str, comment: str, *, author: str | None = None, table_url: str | None = None) -> dict[str, Any]:
        comment = self._comment(comment)
        if not comment:
            raise QaError("a comment cannot be empty")
        if not sample:
            raise QaError("choose an image to comment on")
        event = {"sample": sample_key(sample), "status": None, "comment": comment, "author": _author(author), "time": _now(), "table": table_url}
        _append(self.url, [event])
        return event

    def add_comment_many(self, samples: Iterable[str], comment: str, *, author: str | None = None, table_url: str | None = None) -> int:
        """The same note on several images, e.g. why they were isolated."""
        comment = self._comment(comment)
        keys = list(dict.fromkeys(sample_key(s) for s in samples if s))
        if not comment or not keys:
            return 0
        who, now = _author(author), _now()
        _append(self.url, [{"sample": k, "status": None, "comment": comment, "author": who, "time": now, "table": table_url} for k in keys])
        return len(keys)

    @staticmethod
    def _comment(comment: str) -> str:
        comment = (comment or "").strip()
        if len(comment) > MAX_COMMENT:
            raise QaError(f"comments are at most {MAX_COMMENT} characters")
        return comment

    def events(self) -> list[dict[str, Any]]:
        return [
            e for e in _read(self.url)
            if e.get("sample") and (e.get("status") in STATUSES or (e.get("status") is None and e.get("comment")))
        ]

    def current(self) -> dict[str, dict[str, Any]]:
        """Per image: its latest status (absent means unreviewed) and how many comments it has."""
        out: dict[str, dict[str, Any]] = {}
        for event in self.events():
            entry = out.setdefault(event["sample"], {"status": "unreviewed", "comments": 0})
            if event.get("comment"):
                entry["comments"] += 1
            if event.get("status"):
                entry.update(status=event["status"], author=event.get("author"), time=event.get("time"),
                             note=event.get("comment") or "")
        return out

    def thread(self, sample: str) -> list[dict[str, Any]]:
        """Every status change and comment on one image, oldest first."""
        return [e for e in self.events() if e["sample"] == sample]

    # -- shipping -------------------------------------------------------------

    def ship(
        self,
        versions: dict[str, dict[str, Any]],
        statuses: dict[str, str],
        *,
        author: str | None = None,
        note: str = "",
    ) -> dict[str, Any]:
        """Ship the given set versions, if every one of their images is reviewed.

        ``versions`` maps set name to ``{"url", "name", "images": [image refs]}``;
        ``statuses`` is image -> current status.
        """
        if not versions:
            raise QaError("this dataset has no sets to ship")
        waiting = {
            name: sum(1 for image in v["images"] if statuses.get(image, "unreviewed") != "reviewed")
            for name, v in versions.items()
        }
        if any(waiting.values()):
            detail = ", ".join(f"{n} in {name}" for name, n in waiting.items() if n)
            raise QaError(f"every image must be reviewed before shipping; not yet reviewed: {detail}")
        shipment = {
            "id": uuid.uuid4().hex[:12],
            "time": _now(),
            "author": _author(author),
            "note": self._comment(note),
            "sets": {name: {"url": v["url"], "name": v["name"], "images": len(v["images"])} for name, v in versions.items()},
        }
        _append(self.ships_url, [shipment])
        return shipment

    def release(
        self,
        name: str,
        versions: dict[str, dict[str, Any]],
        *,
        description: str = "",
        mode: str = "all",
        author: str | None = None,
        release_id: str | None = None,
        augmentation: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Record a dataset version: a named, frozen choice of one version of each set.

        Unlike :meth:`ship` it does not require every image to be reviewed; the caller decides
        whether unverified images are included (``mode="all"``) or were left out of the set
        versions it passes (``mode="verified"``). ``versions`` maps set name to ``{"url",
        "name", "images", "verified"}`` with counts.
        """
        name = self.release_name(name)
        if mode not in ("all", "verified"):
            raise QaError("mode must be 'all' or 'verified'")
        if not versions or not any(v["images"] for v in versions.values()):
            raise QaError("a dataset version needs at least one image")
        release = {
            "id": release_id or new_release_id(),
            "time": _now(),
            "author": _author(author),
            "name": name,
            "note": self._comment(description),
            "mode": mode,
            # Counted over every version ever made, so a deleted number is never reused.
            "version": sum(1 for r in _read(self.ships_url) if isinstance(r.get("sets"), dict) and r.get("id")) + 1,
            "sets": {
                set_name: {
                    "url": v["url"], "name": v["name"], "images": int(v["images"]), "verified": int(v["verified"]),
                    **{k: int(v[k]) for k in ("originals", "augmented", "dropped_boxes", "dropped_masks") if k in v},
                }
                for set_name, v in versions.items()
            },
            **({"augmentation": augmentation} if augmentation else {}),
        }
        _append(self.ships_url, [release])
        return release

    def release_name(self, name: str) -> str:
        """``name`` tidied, or an error if it is empty, too long or already taken."""
        name = " ".join((name or "").split())
        if not name:
            raise QaError("give the dataset version a name")
        if len(name) > 80:
            raise QaError("names are at most 80 characters")
        if any(str(s.get("name", "")).casefold() == name.casefold() for s in self.shipments()):
            raise QaError(f"there is already a dataset version named {name!r}")
        return name

    def shipments(self) -> list[dict[str, Any]]:
        """Every shipment that was not deleted, newest first."""
        records = _read(self.ships_url)
        deleted = {r["deleted"] for r in records if r.get("deleted")}
        found = [s for s in records if isinstance(s.get("sets"), dict) and s.get("id") and s["id"] not in deleted]
        return list(reversed(found))

    def delete_release(self, release_id: str, *, author: str | None = None) -> dict[str, Any]:
        """Take a dataset version out of the list; the log keeps it, marked deleted.

        Its files (see the service) are the caller's to remove. Returns the version.
        """
        found = next((s for s in self.shipments() if s["id"] == release_id), None)
        if found is None:
            raise QaError(f"no dataset version {release_id!r} in {self.dataset_name}")
        _append(self.ships_url, [{"deleted": release_id, "time": _now(), "author": _author(author)}])
        return found

    def shipped_urls(self) -> set[str]:
        return {str(v.get("url")) for s in self.shipments() for v in s["sets"].values()}
