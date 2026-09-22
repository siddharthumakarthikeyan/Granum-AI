"""Tags on images, and named views of a dataset: two small stores with one shape.

Neither is a fact about the data. A **tag** is a word a person put on an image because it
mattered to them -- ``night``, ``recheck``, ``from-the-carpark-camera`` -- and the point of
it is that nobody has to ask permission to invent one. A **view** is a set of filters worth
returning to, named, so "the unverified night shots in valid" is a click rather than four.

Both are kept per dataset beside the review log and for the same reasons: they must outlive
the browser tab, survive new versions of a set, and be readable by a person with a text
editor. Tags are an append-only log keyed by image, so the history of who tagged what stays;
views are a small list, rewritten when one is added or removed, because a view is a current
state rather than a history.
"""

from __future__ import annotations

import getpass
import json
import re
import threading
import uuid
from collections.abc import Iterable
from datetime import datetime, timezone
from typing import Any

from granum.core.config import Config, get_config
from granum.core.layout import ProjectLayout, sanitize
from granum.core.url import Url, sample_key
from granum.errors import GranumError

#: What a tag may be: a word a person can type and read back, not a sentence.
TAG = re.compile(r"[A-Za-z0-9][A-Za-z0-9 ._-]{0,39}")
MAX_TAGS_PER_IMAGE = 40
MAX_VIEWS = 200

_locks: dict[str, threading.Lock] = {}
_locks_guard = threading.Lock()


class TagError(GranumError):
    """A tag or a view could not be recorded."""


def _lock_for(key: str) -> threading.Lock:
    with _locks_guard:
        return _locks.setdefault(key, threading.Lock())


def _who() -> str:
    try:
        return getpass.getuser()
    except Exception:  # noqa: BLE001 - no user name available in some containers
        return ""


def clean_tag(tag: str) -> str:
    """A tag as it will be stored, or a refusal. Case and spacing are the user's."""
    text = " ".join(str(tag or "").split())
    if not text or not TAG.fullmatch(text):
        raise TagError(f"{tag!r} is not a tag: use letters, numbers, spaces, dots, dashes or underscores")
    return text


class TagStore:
    """Tags on the images of one dataset, as an append-only log."""

    def __init__(self, project_name: str, dataset_name: str, *, config: Config | None = None) -> None:
        config = config or get_config()
        self.project_name = project_name
        self.dataset_name = dataset_name
        self.url: Url = (ProjectLayout(config.project_root).project(project_name)
                         / "tags" / f"{sanitize(dataset_name)}.jsonl")

    def record(self, samples: Iterable[str], *, add: Iterable[str] = (), remove: Iterable[str] = (),
               author: str | None = None) -> dict[str, Any]:
        """Put tags on images, take tags off them, or both. Returns what was written."""
        keys = list(dict.fromkeys(sample_key(s) for s in samples if s))
        added = [clean_tag(t) for t in add]
        removed = [clean_tag(t) for t in remove]
        if not keys or not (added or removed):
            return {"images": 0, "added": [], "removed": []}
        now = datetime.now(timezone.utc).isoformat(timespec="seconds")
        person = _who() if author is None else author
        lines = "".join(
            json.dumps({"sample": key, "add": added, "remove": removed, "author": person, "time": now},
                       separators=(",", ":")) + "\n"
            for key in keys
        )
        with _lock_for(str(self.url)):
            self.url.parent.mkdir()
            with self.url.fs.open(self.url.path, "ab") as handle:
                handle.write(lines.encode("utf-8"))
        return {"images": len(keys), "added": added, "removed": removed}

    def events(self) -> list[dict[str, Any]]:
        if not self.url.exists():
            return []
        out = []
        with _lock_for(str(self.url)):
            text = self.url.read_text()
        for line in text.splitlines():
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue  # a torn final line from an interrupted write
            if isinstance(event, dict) and event.get("sample"):
                out.append(event)
        return out

    def current(self) -> dict[str, list[str]]:
        """Image -> its tags now, in the order they were first put on it."""
        held: dict[str, list[str]] = {}
        for event in self.events():
            tags = held.setdefault(event["sample"], [])
            for tag in event.get("add") or []:
                if tag not in tags and len(tags) < MAX_TAGS_PER_IMAGE:
                    tags.append(tag)
            for tag in event.get("remove") or []:
                if tag in tags:
                    tags.remove(tag)
        return {key: tags for key, tags in held.items() if tags}

    def counts(self) -> dict[str, int]:
        """How many images carry each tag, most used first."""
        counts: dict[str, int] = {}
        for tags in self.current().values():
            for tag in tags:
                counts[tag] = counts.get(tag, 0) + 1
        return dict(sorted(counts.items(), key=lambda item: (-item[1], item[0].lower())))


class ViewStore:
    """Named filter sets for one dataset: what a reader keeps coming back to."""

    def __init__(self, project_name: str, dataset_name: str, *, config: Config | None = None) -> None:
        config = config or get_config()
        self.project_name = project_name
        self.dataset_name = dataset_name
        self.url: Url = (ProjectLayout(config.project_root).project(project_name)
                         / "views" / f"{sanitize(dataset_name)}.json")

    def all(self) -> list[dict[str, Any]]:
        """Every saved view, newest first. A damaged file reads as no views, not a crash."""
        if not self.url.exists():
            return []
        try:
            payload = json.loads(self.url.read_text())
        except (ValueError, OSError):
            return []
        views = payload.get("views") if isinstance(payload, dict) else payload
        return [v for v in (views or []) if isinstance(v, dict) and v.get("id") and v.get("name")]

    def save(self, name: str, state: dict[str, Any], *, author: str | None = None) -> dict[str, Any]:
        """Add a view, or replace the one of that name. Returns the view as stored."""
        label = " ".join(str(name or "").split())
        if not label or len(label) > 60:
            raise TagError("a view needs a name of up to 60 characters")
        if not isinstance(state, dict) or len(json.dumps(state)) > 4000:
            raise TagError("a view's filters are a small object")
        view = {
            "id": uuid.uuid4().hex[:12],
            "name": label,
            "state": state,
            "author": _who() if author is None else author,
            "time": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        }
        with _lock_for(str(self.url)):
            views = [v for v in self.all() if v["name"].lower() != label.lower()]
            if len(views) >= MAX_VIEWS:
                raise TagError(f"a dataset keeps up to {MAX_VIEWS} views; delete one first")
            views.insert(0, view)
            self.url.parent.mkdir()
            self.url.write_text(json.dumps({"views": views}, indent=1))
        return view

    def delete(self, view_id: str) -> bool:
        with _lock_for(str(self.url)):
            views = self.all()
            kept = [v for v in views if v["id"] != view_id]
            if len(kept) == len(views):
                return False
            self.url.parent.mkdir()
            self.url.write_text(json.dumps({"views": kept}, indent=1))
        return True
