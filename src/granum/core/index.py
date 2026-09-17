"""Object discovery.

The indexer walks configured locations, finds Tables and Runs, and keeps a lineage graph
of how revisions relate. It is the least visible part of the system and the one most
likely to become unaffordable: a naive implementation lists every project directory on
every tick, which is merely slow on local disk and expensive on S3.

Two things keep it cheap. Each location carries an ``index.granum.json`` marker that
every writer touches; if the marker is unchanged since the last pass, the whole subtree
is skipped for the cost of a single metadata read. And a URL that fails is recorded in a
skip store with a retry cadence matched to *why* it failed, so one bad directory cannot
stall the rest of the index.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Any

from granum._logging import get_logger
from granum.core.config import Config, get_config
from granum.core.layout import INDEX_FILENAME, OBJECT_FILENAME
from granum.core.objects.base import read_object_payload
from granum.core.objects.run import Run
from granum.core.objects.table import Table
from granum.core.url import Url
from granum.errors import GranumError

logger = get_logger("index")

# How long to wait before retrying a URL that failed, by reason.
RETRY_SECONDS = {
    "transient": 5.0,      # network blips, listing races
    "permission": 3600.0,  # needs a human
    "malformed": 3600.0,   # needs a human
    "unknown_type": 86400.0,
}


class IndexError_(GranumError):
    """Indexing could not proceed."""


@dataclass(frozen=True)
class IndexEntry:
    """One discovered object."""

    url: Url
    type_name: str
    name: str
    project_name: str
    dataset_name: str
    created: str
    row_count: int = 0
    parents: tuple[Url, ...] = ()
    description: str = ""
    payload: dict[str, Any] = field(default_factory=dict, repr=False)

    def to_dict(self) -> dict[str, Any]:
        return {
            "url": str(self.url),
            "type": self.type_name,
            "name": self.name,
            "project_name": self.project_name,
            "dataset_name": self.dataset_name,
            "created": self.created,
            "row_count": self.row_count,
            "parents": [str(p) for p in self.parents],
            "description": self.description,
        }


@dataclass
class _Skip:
    reason: str
    retry_after: float
    failures: int = 1


@dataclass
class ScanStats:
    """What the last pass actually did. Useful for proving the skip logic works."""

    scans: int = 0
    locations_visited: int = 0
    locations_skipped: int = 0
    objects_found: int = 0
    failures: int = 0
    last_duration: float = 0.0


class Index:
    """An in-memory index over one or more scan roots."""

    def __init__(
        self,
        roots: Iterable[Url | str] | None = None,
        *,
        config: Config | None = None,
        backoff_multiplier: float = 1.0,
    ) -> None:
        config = config or get_config()
        resolved = [Url(r) for r in roots] if roots else [config.project_root]
        self.roots: list[Url] = resolved
        self.backoff_multiplier = backoff_multiplier

        self._entries: dict[str, IndexEntry] = {}
        self._markers: dict[str, str] = {}
        self._skips: dict[str, _Skip] = {}
        self._static: set[str] = set()
        self._lock = threading.RLock()
        self.stats = ScanStats()

        self._thread: threading.Thread | None = None
        self._stop = threading.Event()

    # -- scanning -----------------------------------------------------------

    def _marker_value(self, location: Url) -> str | None:
        marker = location / INDEX_FILENAME
        try:
            return marker.read_text() if marker.exists() else None
        except (OSError, ValueError):
            return None

    def _should_skip(self, url: Url) -> bool:
        skip = self._skips.get(str(url))
        return skip is not None and time.monotonic() < skip.retry_after

    def _record_failure(self, url: Url, reason: str) -> None:
        key = str(url)
        previous = self._skips.get(key)
        failures = (previous.failures + 1) if previous else 1
        base = RETRY_SECONDS.get(reason, RETRY_SECONDS["transient"])
        delay = base * self.backoff_multiplier
        if reason == "transient":
            delay *= min(2 ** (failures - 1), 64)
        self._skips[key] = _Skip(reason, time.monotonic() + delay, failures)
        self.stats.failures += 1
        logger.debug("index: skipping %s (%s, retry in %.0fs)", url, reason, delay)

    def clear_skip(self, url: Url | str) -> None:
        """Forget a recorded failure so the URL is retried immediately."""
        self._skips.pop(str(Url(url)), None)

    def _classify(self, exc: Exception) -> str:
        if isinstance(exc, PermissionError):
            return "permission"
        if isinstance(exc, (ValueError, KeyError, TypeError)):
            return "malformed"
        return "transient"

    def _load_entry(self, url: Url) -> IndexEntry | None:
        payload = read_object_payload(url)
        type_name = payload.get("type", "")
        if type_name not in {"table", "metrics_table", "run"}:
            self._record_failure(url, "unknown_type")
            return None
        return IndexEntry(
            url=url,
            type_name=type_name,
            name=payload.get("name", url.name),
            project_name=payload.get("project_name", ""),
            dataset_name=payload.get("dataset_name", ""),
            created=payload.get("created", ""),
            row_count=payload.get("row_count", 0),
            parents=tuple(Url(p) for p in payload.get("parents", [])),
            description=payload.get("description", ""),
            payload=payload,
        )

    def _walk(self, location: Url, found: dict[str, IndexEntry], depth: int = 0) -> None:
        """Recursively discover objects beneath ``location``."""
        if depth > 12 or self._should_skip(location):
            return

        # An object directory: record it, then keep going -- Runs contain metrics tables.
        if (location / OBJECT_FILENAME).exists():
            try:
                entry = self._load_entry(location)
                if entry is not None:
                    found[str(location)] = entry
                    self.clear_skip(location)
            except Exception as exc:  # noqa: BLE001 - one bad object must not stop the scan
                self._record_failure(location, self._classify(exc))

        try:
            children = [child for child in location.ls() if child.is_dir()]
        except Exception as exc:  # noqa: BLE001 - a failed listing skips the subtree only
            self._record_failure(location, self._classify(exc))
            return

        for child in children:
            self._walk(child, found, depth + 1)

    def refresh(self, *, force: bool = False) -> ScanStats:
        """Scan every root whose change marker moved. Returns the stats for this pass."""
        started = time.monotonic()
        with self._lock:
            self.stats.scans += 1
            found: dict[str, IndexEntry] = {}
            kept_roots: list[str] = []

            for root in self.roots:
                key = str(root)
                if key in self._static and key in self._markers and not force:
                    self.stats.locations_skipped += 1
                    kept_roots.append(key)
                    continue

                marker = self._marker_value(root)
                if not force and marker is not None and self._markers.get(key) == marker:
                    self.stats.locations_skipped += 1
                    kept_roots.append(key)
                    continue

                self.stats.locations_visited += 1
                self._walk(root, found)
                if marker is not None:
                    self._markers[key] = marker

            # Entries under a skipped root are retained; the rest are replaced.
            if kept_roots:
                for key, entry in self._entries.items():
                    if any(key.startswith(root) for root in kept_roots):
                        found.setdefault(key, entry)

            self._entries = found
            self.stats.objects_found = len(found)
            self.stats.last_duration = time.monotonic() - started
            return self.stats

    def mark_static(self, root: Url | str) -> None:
        """Declare a location immutable: scanned once, then never re-polled."""
        self._static.add(str(Url(root)))

    # -- queries ------------------------------------------------------------

    def entries(self) -> list[IndexEntry]:
        with self._lock:
            return list(self._entries.values())

    def get(self, url: Url | str) -> IndexEntry | None:
        with self._lock:
            return self._entries.get(str(Url(url)))

    def projects(self) -> list[dict[str, Any]]:
        counts: dict[str, dict[str, int]] = {}
        for entry in self.entries():
            if not entry.project_name:
                continue
            bucket = counts.setdefault(entry.project_name, {"tables": 0, "runs": 0})
            if entry.type_name == "table":
                bucket["tables"] += 1
            elif entry.type_name == "run":
                bucket["runs"] += 1
        return [
            {"name": name, "tables": c["tables"], "runs": c["runs"]}
            for name, c in sorted(counts.items())
        ]

    def tables(self, project_name: str | None = None) -> list[IndexEntry]:
        return sorted(
            (
                e
                for e in self.entries()
                if e.type_name == "table"
                and (project_name is None or e.project_name == project_name)
            ),
            key=lambda e: (e.dataset_name, e.created, e.name),
        )

    def runs(self, project_name: str | None = None) -> list[IndexEntry]:
        return sorted(
            (
                e
                for e in self.entries()
                if e.type_name == "run"
                and (project_name is None or e.project_name == project_name)
            ),
            key=lambda e: (e.created, e.name),
        )

    def lineage_edges(self, project_name: str | None = None) -> list[dict[str, str]]:
        """Parent-to-child edges, for drawing the revision graph."""
        edges: list[dict[str, str]] = []
        for entry in self.tables(project_name):
            for parent in entry.parents:
                edges.append({"from": str(parent), "to": str(entry.url)})
        return edges

    def children_of(self, url: Url | str) -> list[IndexEntry]:
        key = str(Url(url))
        return [e for e in self.entries() if key in {str(p) for p in e.parents}]

    def latest_revision(self, url: Url | str) -> IndexEntry | None:
        """The furthest descendant of a Table, resolved from the index rather than disk."""
        start = self.get(url)
        if start is None:
            return None
        best, best_depth = start, 0
        queue = [(start, 0)]
        seen = {str(start.url)}
        while queue:
            entry, depth = queue.pop()
            for child in self.children_of(entry.url):
                if str(child.url) in seen:
                    continue
                seen.add(str(child.url))
                if (depth + 1, child.created) > (best_depth, best.created):
                    best, best_depth = child, depth + 1
                queue.append((child, depth + 1))
        return best

    def resolve(self, url: Url | str) -> Table | Run:
        """Load the live object for an indexed URL."""
        entry = self.get(url)
        if entry is None:
            raise IndexError_(f"{url} is not in the index")
        if entry.type_name == "run":
            return Run.from_url(entry.url)
        from granum.core.objects.run import MetricsTable

        if entry.type_name == "metrics_table":
            return MetricsTable.from_url(entry.url)
        return Table.from_url(entry.url)

    # -- background ---------------------------------------------------------

    def start(self, interval: float | None = None) -> None:
        """Begin polling in the background. Idempotent."""
        if self._thread is not None and self._thread.is_alive():
            return
        seconds = float(interval if interval is not None else get_config().get(
            "indexing.scan-interval"))
        self._stop.clear()

        def loop() -> None:
            while not self._stop.is_set():
                try:
                    self.refresh()
                except Exception:  # noqa: BLE001 - the indexer must never die
                    logger.exception("index: scan failed")
                self._stop.wait(seconds)

        self._thread = threading.Thread(target=loop, name="granum-indexer", daemon=True)
        self._thread.start()

    def stop(self, timeout: float = 2.0) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=timeout)
            self._thread = None


_ACTIVE_INDEX: Index | None = None


def get_index(*, config: Config | None = None) -> Index:
    """The process-wide index, created and scanned on first use."""
    global _ACTIVE_INDEX
    if _ACTIVE_INDEX is None:
        _ACTIVE_INDEX = Index(config=config)
        _ACTIVE_INDEX.refresh()
    return _ACTIVE_INDEX


def set_index(index: Index | None) -> None:
    global _ACTIVE_INDEX
    if _ACTIVE_INDEX is not None and index is not _ACTIVE_INDEX:
        _ACTIVE_INDEX.stop()
    _ACTIVE_INDEX = index
