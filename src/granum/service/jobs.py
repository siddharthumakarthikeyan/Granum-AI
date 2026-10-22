"""Background jobs for work too slow for one request: preflight and import.

A job runs in a thread and reports phase, progress and a result the dashboard polls.
Jobs normally live in memory. Opt-in durable jobs retain their terminal result and logs;
an unfinished durable job is marked interrupted on restart, never silently replayed.
"""

from __future__ import annotations

import json
import re
import threading
import time
import traceback
from collections import deque
from collections.abc import Callable
from contextvars import copy_context
from dataclasses import dataclass, field
from pathlib import Path
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
    durable: bool = False

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
    def __init__(self, state_dir: Path | None = None) -> None:
        self._jobs: dict[str, Job] = {}
        self._lock = threading.Lock()
        self.state_dir = state_dir
        if state_dir is not None:
            for path in sorted(state_dir.glob("*.json"), key=lambda p: p.stat().st_mtime)[-MAX_JOBS:]:
                try:
                    data = json.loads(path.read_text())
                    if data.pop("version") != 1 or data["id"] != path.stem or not re.fullmatch(r"[a-f0-9]{12}", data["id"]):
                        continue
                    fields = {key: data[key] for key in ("id", "kind", "status", "phase", "done", "total", "started", "finished", "error", "result")}
                    job = Job(**fields, durable=True)
                    job.log.extend(data.get("log", [])[-80:])
                    if job.status == "running":
                        job.status, job.phase = "failed", "Interrupted"
                        job.error = "The service restarted before this job finished. Check its result or installation before retrying."
                        job.finished = time.time()
                        self._checkpoint(job)
                    self._jobs[job.id] = job
                except (OSError, ValueError, KeyError, TypeError):
                    logger.warning("Could not restore job record %s", path)

    def _checkpoint(self, job: Job) -> None:
        if not job.durable or self.state_dir is None:
            return
        from granum.compute.manager import atomic_json

        atomic_json(self.state_dir / f"{job.id}.json", {"version": 1, **job.to_dict(), "started": job.started, "finished": job.finished})

    def start(self, kind: str, work: Callable[[Job], Any], *, durable: bool = False) -> Job:
        job = Job(id=uuid4().hex[:12], kind=kind, durable=durable)
        self._checkpoint(job)
        with self._lock:
            finished = [j for j in self._jobs.values() if j.status != "running"]
            while len(self._jobs) >= MAX_JOBS and finished:
                old = finished.pop(0)
                self._jobs.pop(old.id, None)
                if old.durable and self.state_dir:
                    (self.state_dir / f"{old.id}.json").unlink(missing_ok=True)
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
                try:
                    self._checkpoint(job)
                except OSError:
                    logger.error("Could not persist job %s", job.id, exc_info=True)

        context = copy_context()
        threading.Thread(target=lambda: context.run(run), name=f"granum-job-{job.id}", daemon=True).start()
        return job

    def get(self, job_id: str) -> Job | None:
        return self._jobs.get(job_id)

    def all(self) -> list[Job]:
        return list(self._jobs.values())
