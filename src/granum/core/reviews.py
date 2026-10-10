"""Review decisions: what a person concluded about a sample, and why.

A model's opinion of a sample is a metric; a reviewer's conclusion is a decision, and it
needs to outlive the browser tab, survive new revisions, and stay auditable. Decisions
are kept per dataset as an append-only log -- nothing is overwritten, so the history of
who decided what, on which revision, is always there. The current status of a sample is
its latest event.

Samples are identified by their image reference rather than by row position: rows move
when a revision deletes some, the image a decision was about does not.

Statuses:

``correct``     the label was checked and is right, including valid hard examples
``corrected``   the label was wrong and has been (or will be) fixed
``ambiguous``   reviewers cannot tell what the right label is
``deferred``    needs another look later
``excluded``    should not be used, e.g. unusable image
``unreviewed``  clears an earlier decision (recorded, not erased)
"""

from __future__ import annotations

import getpass
from collections import Counter
from collections.abc import Iterable
from datetime import datetime, timezone
from typing import Any

from granum.core.config import Config, get_config
from granum.core.layout import ProjectLayout, sanitize
from granum.core.qa import _append, _read
from granum.core.url import Url, sample_key
from granum.errors import GranumError

STATUSES = ("correct", "corrected", "ambiguous", "deferred", "excluded", "unreviewed")
MAX_REASON = 2000

class ReviewError(GranumError):
    """A review decision could not be recorded."""


def _reviewer() -> str:
    try:
        return getpass.getuser()
    except Exception:  # noqa: BLE001 - no user name available in some containers
        return ""


class ReviewLog:
    """The review decisions for one dataset of one project."""

    def __init__(self, project_name: str, dataset_name: str, *, config: Config | None = None) -> None:
        config = config or get_config()
        self.project_name = project_name
        self.dataset_name = dataset_name
        self.url: Url = ProjectLayout(config.project_root).project(project_name) / "reviews" / f"{sanitize(dataset_name)}.jsonl"

    def record(
        self,
        samples: Iterable[str],
        status: str,
        *,
        reason: str = "",
        table_url: str | None = None,
        reviewer: str | None = None,
    ) -> int:
        """Append one decision per sample. Returns how many were recorded."""
        if status not in STATUSES:
            raise ReviewError(f"status must be one of {list(STATUSES)}, got {status!r}")
        reason = (reason or "").strip()
        if len(reason) > MAX_REASON:
            raise ReviewError(f"reason is longer than {MAX_REASON} characters")
        keys = list(dict.fromkeys(sample_key(s) for s in samples if s is not None and str(s)))
        if not keys:
            return 0
        now = datetime.now(timezone.utc).isoformat(timespec="seconds")
        who = _reviewer() if reviewer is None else reviewer
        _append(self.url, [
            {
                "sample": key, "status": status, "reason": reason, "table": table_url,
                "reviewer": who, "time": now,
            }
            for key in keys
        ])
        return len(keys)

    def events(self) -> list[dict[str, Any]]:
        """Every decision, oldest first. Only an incomplete final record is ignored."""
        return [e for e in _read(self.url) if e.get("status") in STATUSES and e.get("sample")]

    def current(self) -> dict[str, dict[str, Any]]:
        """The latest decision per sample, leaving out samples cleared back to unreviewed."""
        latest: dict[str, dict[str, Any]] = {}
        for event in self.events():
            latest[event["sample"]] = event
        return {k: v for k, v in latest.items() if v["status"] != "unreviewed"}

    def history(self, sample: str) -> list[dict[str, Any]]:
        return [e for e in self.events() if e["sample"] == sample]

    def counts(self) -> dict[str, int]:
        return dict(Counter(e["status"] for e in self.current().values()))
