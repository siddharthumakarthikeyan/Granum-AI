"""Background jobs for work too slow for one request: preflight and import.

A job runs in a thread and reports phase, progress and a result the dashboard polls.
Jobs live in memory only -- restarting the service forgets them, which is stated to the
user rather than hidden: a finished import is on disk regardless, and its report is saved
with the project.
"""

from __future__ import annotations

import threading
import time
import traceback
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any
from uuid import uuid4

from granum._logging import get_logger
from granum.errors import GranumError

logger = get_logger("jobs")

MAX_JOBS = 32


@dataclass
class Job:
    id: str
    kind: str
    status: str = "running"  # running | done | failed | cancelled
    phase: str = "Starting"
    done: int = 0
    total: int = 0
    started: float = field(default_factory=time.time)
    finished: float | None = None
    error: str | None = None
    result: Any = None
    #: Server-side state that must not be serialized, e.g. a parsed preflight report.
    payload: Any = None
    cancel: threading.Event = field(default_factory=threading.Event)
    #: Recent output lines, for jobs that run a process.
    log: deque = field(default_factory=lambda: deque(maxlen=200))
    #: Progress within the current round of a training, and when that round started.
    step: int = 0
    steps: int = 0
    round_started: float | None = None
    #: The step when timing began: after a restart the service joins a round midway.
    round_base: int = 0

    def progress(self, phase: str, done: int, total: int) -> None:
        self.phase, self.done, self.total = phase, done, total

    def set_step(self, step: int, steps: int) -> None:
        if steps <= 0:
            return
        if step < self.step or self.round_started is None or steps != self.steps:
            self.round_started = time.time()
            self.round_base = step
        self.step, self.steps = step, steps

    def _round_eta(self) -> float | None:
        """Seconds left in the current round, from the pace so far."""
        if not self.steps or not self.step or self.round_started is None or self.step >= self.steps:
            return None
        elapsed = time.time() - self.round_started
        progressed = self.step - self.round_base
        if elapsed < 20 or progressed < 5:
            return None
        return round(elapsed / progressed * (self.steps - self.step))

    def to_dict(self) -> dict[str, Any]:
        result = self.result.to_dict() if hasattr(self.result, "to_dict") else self.result
        return {
            "id": self.id,
            "kind": self.kind,
            "status": self.status,
            "phase": self.phase,
            "done": self.done,
            "total": self.total,
            "elapsed": round((self.finished or time.time()) - self.started, 2),
            "error": self.error,
            "result": result if self.status == "done" else None,
            "log": list(self.log)[-80:],
            "step": self.step,
            "steps": self.steps,
            "round_eta": self._round_eta(),
        }


class JobRegistry:
    def __init__(self) -> None:
        self._jobs: dict[str, Job] = {}
        self._lock = threading.Lock()

    def start(self, kind: str, work: Callable[[Job], Any]) -> Job:
        job = Job(id=uuid4().hex[:12], kind=kind)
        with self._lock:
            finished = [j for j in self._jobs.values() if j.status != "running"]
            while len(self._jobs) >= MAX_JOBS and finished:
                self._jobs.pop(finished.pop(0).id, None)
            self._jobs[job.id] = job

        def run() -> None:
            try:
                job.result = work(job)
                job.status = "cancelled" if job.cancel.is_set() else "done"
            except GranumError as exc:
                job.status = "cancelled" if job.cancel.is_set() else "failed"
                job.error = str(exc)
            except Exception as exc:  # noqa: BLE001 - reported to the user, logged in full
                logger.error("job %s failed:\n%s", job.id, traceback.format_exc())
                job.status = "failed"
                job.error = f"{type(exc).__name__}: {exc}"
            finally:
                job.finished = time.time()

        threading.Thread(target=run, name=f"granum-job-{job.id}", daemon=True).start()
        return job

    def get(self, job_id: str) -> Job | None:
        return self._jobs.get(job_id)

    def all(self) -> list[Job]:
        return list(self._jobs.values())
