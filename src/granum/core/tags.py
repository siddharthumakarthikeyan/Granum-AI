"""Tags on images, and named views of a dataset: two small stores with one shape.

Neither is a fact about the data. A **tag** is a word a person put on an image because it
mattered to them -- ``night``, ``recheck``, ``from-the-carpark-camera`` -- and the point of
it is that nobody has to ask permission to invent one. A **view** is a set of filters worth
returning to, named, so "the unverified night shots in valid" is a click rather than four.

A tag can go on one *object* as well as on the picture holding it -- ``occluded`` on the one
box that is, ``check-this`` on the box in the corner -- and that is the same log with an
``object`` on the event. Boxes are addressed by their annotation id where an import gave them
one and by their position where it did not, which is what an image's own boxes can be
addressed by without rewriting the set.

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
#: Objects of one image that may be tagged in one call.
MAX_OBJECTS_PER_CALL = 500

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


def object_key(instance: Any, index: int) -> str:
    """How one box of an image is addressed by a tag.

    By its annotation id where the import gave it one, because that survives the boxes being
    reordered, and by its position where it did not. The two are kept apart by their prefix
    so that a set where some boxes are numbered and some are not cannot collide: box 3 of an
    unnumbered image is ``i3``, annotation 3 is ``a3``.
    """
    annotation = (instance or {}).get("annotation_id") if isinstance(instance, dict) else None
    return f"a{int(annotation)}" if annotation is not None else f"i{int(index)}"


class TagStore:
    """Tags on the images of one dataset, and on their objects, as an append-only log."""

    def __init__(self, project_name: str, dataset_name: str, *, config: Config | None = None) -> None:
        config = config or get_config()
        self.project_name = project_name
        self.dataset_name = dataset_name
        self.url: Url = (ProjectLayout(config.project_root).project(project_name)
                         / "tags" / f"{sanitize(dataset_name)}.jsonl")

    def record(self, samples: Iterable[str], *, add: Iterable[str] = (), remove: Iterable[str] = (),
               objects: Iterable[str] = (), author: str | None = None) -> dict[str, Any]:
        """Put tags on images or on their objects, take them off, or both.

        ``objects`` are the keys of :func:`object_key`. Given them, the tags go on those
        boxes of the one image named rather than on the image, because "this box is
        occluded" and "this picture is at night" are different claims and a reader filtering
        for one should not be handed the other.
        """
        keys = list(dict.fromkeys(sample_key(s) for s in samples if s))
        marks = list(dict.fromkeys(str(o) for o in objects if str(o)))
        added = [clean_tag(t) for t in add]
        removed = [clean_tag(t) for t in remove]
        if marks:
            if len(keys) != 1:
                raise TagError("tag the objects of one image at a time")
            if len(marks) > MAX_OBJECTS_PER_CALL:
                raise TagError(f"up to {MAX_OBJECTS_PER_CALL} objects at a time")
        if not keys or not (added or removed):
            return {"images": 0, "objects": 0, "added": [], "removed": []}
        now = datetime.now(timezone.utc).isoformat(timespec="seconds")
        person = _who() if author is None else author
        events = (
            [{"sample": keys[0], "object": mark, "add": added, "remove": removed, "author": person, "time": now}
             for mark in marks]
            if marks else
            [{"sample": key, "add": added, "remove": removed, "author": person, "time": now} for key in keys]
        )
        lines = "".join(json.dumps(event, separators=(",", ":")) + "\n" for event in events)
        with _lock_for(str(self.url)):
            self.url.parent.mkdir()
            with self.url.fs.open(self.url.path, "ab") as handle:
                handle.write(lines.encode("utf-8"))
        return {"images": 0 if marks else len(keys), "objects": len(marks),
                "added": added, "removed": removed}

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

    @staticmethod
    def _apply(held: list[str], event: dict[str, Any]) -> None:
        for tag in event.get("add") or []:
            if tag not in held and len(held) < MAX_TAGS_PER_IMAGE:
                held.append(tag)
        for tag in event.get("remove") or []:
            if tag in held:
                held.remove(tag)

    def current(self) -> dict[str, list[str]]:
        """Image -> its tags now, in the order they were first put on it."""
        held: dict[str, list[str]] = {}
        for event in self.events():
            if event.get("object"):
                continue
            self._apply(held.setdefault(event["sample"], []), event)
        return {key: tags for key, tags in held.items() if tags}

    def current_objects(self) -> dict[str, dict[str, list[str]]]:
        """Image -> object key -> that object's tags now."""
        held: dict[str, dict[str, list[str]]] = {}
        for event in self.events():
            mark = event.get("object")
            if not mark:
                continue
            self._apply(held.setdefault(event["sample"], {}).setdefault(str(mark), []), event)
        return {image: {mark: tags for mark, tags in marks.items() if tags}
                for image, marks in held.items()
                if any(marks.values())}

    @staticmethod
    def _tally(groups: Iterable[list[str]]) -> dict[str, int]:
        counts: dict[str, int] = {}
        for tags in groups:
            for tag in tags:
                counts[tag] = counts.get(tag, 0) + 1
        return dict(sorted(counts.items(), key=lambda item: (-item[1], item[0].lower())))

    def counts(self) -> dict[str, int]:
        """How many images carry each tag, most used first."""
        return self._tally(self.current().values())

    def object_counts(self) -> dict[str, int]:
        """How many objects carry each tag, most used first."""
        return self._tally(tags for marks in self.current_objects().values() for tags in marks.values())


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
