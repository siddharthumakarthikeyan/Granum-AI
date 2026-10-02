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
import hashlib
import json
import os
import uuid
from collections import OrderedDict
from collections.abc import Iterable
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from granum.core.config import Config, get_config
from granum.core.layout import ProjectLayout, sanitize
from granum.core.storage import fsync_directory, locked, workspace_lock
from granum.core.url import Url, sample_key
from granum.errors import GranumError

STATUSES = ("unreviewed", "reviewed", "rework")
MAX_COMMENT = 4000
MAX_AUTHOR = 80
_validated_logs: OrderedDict[str, tuple[int, ...]] = OrderedDict()

class QaError(GranumError):
    """A review status, comment or shipment could not be recorded."""


def new_release_id() -> str:
    return uuid.uuid4().hex[:12]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def review_fingerprints(table: Any, samples: Iterable[str] | None = None) -> dict[str, str]:
    """Bind review to the actual row and schema, not its position or mutable status."""
    from granum.core.curation import image_column
    from granum.core.integrity import file_digest

    column = image_column(table)
    schema = table.schema.to_dict()
    found = {}
    arrow = table.to_arrow()
    if samples is not None:
        wanted = {sample_key(s) for s in samples}
        indices = [i for i, image in enumerate(arrow.column(column).to_pylist()) if image and sample_key(image) in wanted]
        if not indices:
            return {}
        arrow = arrow.take(indices)
    for row in arrow.to_pylist():
        image = row.pop(column, None)
        if not image:
            continue
        try:
            media = file_digest(image)
        except (OSError, ValueError):
            media = None  # Legacy review remains possible, but approval rejects missing bytes.
        found[sample_key(image)] = hashlib.sha256(json.dumps(
            {"row": row, "schema": schema, "media": media}, sort_keys=True, default=str,
        ).encode()).hexdigest()
    return found


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
    with workspace_lock(), locked(url):
        url.parent.mkdir()
        if url.scheme == "file":
            def signature() -> tuple[int, ...]:
                stat = os.stat(url.path)
                return stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns

            # A torn tail must not swallow the next event. Interior corruption is an error.
            exists = url.exists()
            if exists and _validated_logs.get(url.path) != signature():
                _read(url)
                with open(url.path, "r+b") as handle:
                    handle.seek(0, os.SEEK_END)
                    end = handle.tell()
                    if end:
                        handle.seek(end - 1)
                        if handle.read(1) != b"\n":
                            handle.seek(0)
                            data = handle.read()
                            boundary = data.rfind(b"\n") + 1
                            try:
                                json.loads(data[boundary:])
                            except (json.JSONDecodeError, UnicodeDecodeError):
                                handle.truncate(boundary)
                            else:
                                handle.seek(0, os.SEEK_END)
                                handle.write(b"\n")
            with open(url.path, "ab") as handle:
                handle.write(text.encode("utf-8"))
                handle.flush()
                os.fsync(handle.fileno())
            if not exists:
                fsync_directory(Path(url.path).parent)
            _validated_logs.pop(url.path, None)
            _validated_logs[url.path] = signature()
            while len(_validated_logs) > 1024:
                _validated_logs.popitem(last=False)
            return
        with url.fs.open(url.path, "ab") as handle:
            handle.write(text.encode("utf-8"))


def _read(url: Url) -> list[dict[str, Any]]:
    if not url.exists():
        return []
    with locked(url):
        text = url.read_bytes()
    out = []
    lines = text.splitlines()
    for number, line in enumerate(lines):
        try:
            event = json.loads(line)
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            if number == len(lines) - 1 and not text.endswith(b"\n"):
                continue  # only an incomplete final record can be ignored
            raise QaError(f"corrupt log {url}, record {number + 1}; restore from backup before writing") from exc
        if not isinstance(event, dict):
            raise QaError(f"corrupt log {url}, record {number + 1}; expected a JSON object")
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
        fingerprints: dict[str, str] | None = None,
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
            {"sample": k, "status": status, "comment": comment, "author": who, "time": now, "table": table_url,
             "fingerprint": (fingerprints or {}).get(k)}
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
                             note=event.get("comment") or "", fingerprint=event.get("fingerprint"))
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

    @workspace_lock()
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
            "approval": "exploratory",
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
        approvals = {r["approved"]: r for r in records if r.get("approved")}
        return [
            {**s, "approval": "approved" if s["id"] in approvals else "exploratory",
             **({"approval_record": approvals[s["id"]]} if s["id"] in approvals else {})}
            for s in reversed(found)
        ]

    @workspace_lock()
    def approve(self, release_id: str, *, author: str | None = None) -> dict[str, Any]:
        """Approve exact contents, independently of the release's subset selection mode.

        Historical, unpinned reviews never silently become approvals. A schema or label
        change requires another review, even if the image reference did not change.
        """
        from granum.core.integrity import media_manifest
        from granum.core.objects.table import Table

        release = next((r for r in self.shipments() if r["id"] == release_id), None)
        if release is None:
            raise QaError("dataset version not found")
        if release["approval"] == "approved":
            return release
        current = self.current()
        checked: dict[str, dict[str, str]] = {}
        for name, version in release["sets"].items():
            table = Table.from_url(version["url"])
            media_manifest([table])  # Missing media cannot be approved, even with a legacy review.
            fingerprints = review_fingerprints(table)
            waiting = [image for image, fingerprint in fingerprints.items()
                       if current.get(image, {}).get("status") != "reviewed"
                       or current[image].get("fingerprint") != fingerprint]
            if waiting or not fingerprints or len(fingerprints) != len(table):
                raise QaError(f"{name}: every image needs a review of these exact annotations; "
                              f"{len(waiting)} missing or stale reviews (duplicate/missing image references are not approvable)")
            checked[name] = fingerprints
        record = {"approved": release_id, "author": _author(author), "time": _now(),
                  "policy": "reviewed-contents-v1", "fingerprints": checked}
        _append(self.ships_url, [record])
        return {**release, "approval": "approved", "approval_record": record}

    def require_approved(self, release_id: str, urls: Iterable[str]) -> dict[str, Any]:
        """Fail closed if a requested release is absent, unapproved or changed on disk."""
        from granum.core.objects.table import Table

        release = next((r for r in self.shipments() if r["id"] == release_id), None)
        if release is None or release["approval"] != "approved":
            raise QaError("this dataset version is exploratory; approve its exact contents first")
        if not set(urls).issubset({v["url"] for v in release["sets"].values()}):
            raise QaError("all training inputs must belong to the selected approved release")
        record = release["approval_record"]
        for name, version in release["sets"].items():
            if review_fingerprints(Table.from_url(version["url"])) != record["fingerprints"].get(name):
                raise QaError(f"{name}: approved contents changed on disk; restore the approved revision")
        return release

    @workspace_lock()
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
