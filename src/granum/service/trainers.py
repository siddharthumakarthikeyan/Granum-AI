"""Training processes that outlive the service that started them.

A training run takes minutes to hours; the service may be restarted meanwhile (an upgrade,
a crash, a settings change). So a trainer is not tied to the service:

- it runs in its own session, and the installed service stops only its own process on restart;
- its output goes to a log file, not a pipe that would break when the service exits;
- a small record per trainer (process id, project, run, log) sits in the state folder.

When the service starts it reads those records: a trainer that is still running gets a job
again that follows its log, so progress, the log and Cancel keep working; a trainer that
died while no service was watching has its run marked ``interrupted``. Dashboard runs left
``running`` with no trainer behind them at all (from before this existed) are marked the
same way.
"""

from __future__ import annotations

import json
import os
import re
import signal
import subprocess
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from granum.errors import GranumError

TRAINER_MODULE = "granum.training.train"
#: Frameworks the dashboard trains; runs with one of these were started by a trainer here.
DASHBOARD_FRAMEWORKS = {"yolo", "rtdetr", "rfdetr"}
_ANSI = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")


def state_dir() -> Path:
    base = os.environ.get("XDG_STATE_HOME") or os.path.join(os.path.expanduser("~"), ".local", "state")
    return Path(base) / "granum" / "training"


@dataclass
class TrainerRecord:
    pid: int
    project: str
    run_name: str
    rounds: int
    log: str
    project_root: str
    started: float

    @property
    def path(self) -> Path:
        return state_dir() / f"{self.project_root_key}-{self.run_name}.json"

    @property
    def project_root_key(self) -> str:
        return re.sub(r"[^A-Za-z0-9]+", "_", self.project_root).strip("_")[-60:]

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(asdict(self)))

    def remove(self) -> None:
        self.path.unlink(missing_ok=True)

    @classmethod
    def load_all(cls, project_root: str) -> list[TrainerRecord]:
        found = []
        for path in sorted(state_dir().glob("*.json")) if state_dir().is_dir() else []:
            try:
                record = cls(**json.loads(path.read_text()))
            except (OSError, ValueError, TypeError):
                continue
            if record.project_root == project_root:
                found.append(record)
        return found


def is_trainer_alive(pid: int) -> bool:
    """The process exists and is still a Granum trainer (process ids get reused)."""
    try:
        cmdline = Path(f"/proc/{pid}/cmdline").read_bytes()
    except OSError:
        try:
            os.kill(pid, 0)
        except OSError:
            return False
        return True  # no /proc (not Linux): trust the id
    return TRAINER_MODULE.encode() in cmdline


def trainer_prefix(executable: list[str]) -> list[str]:
    return [*executable, "-u", "-m", TRAINER_MODULE]


def launch(command: list[str], *, cwd: Path | None, project_root: str, project: str, run_name: str, rounds: int) -> tuple[subprocess.Popen, TrainerRecord]:
    log = state_dir() / f"{re.sub(r'[^A-Za-z0-9]+', '_', project_root).strip('_')[-60:]}-{run_name}.log"
    log.parent.mkdir(parents=True, exist_ok=True)
    with log.open("ab") as handle:
        process = subprocess.Popen(
            command, stdout=handle, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL, cwd=cwd,
            env={**os.environ, "PYTHONUNBUFFERED": "1"}, start_new_session=True,
        )
    record = TrainerRecord(pid=process.pid, project=project, run_name=run_name, rounds=rounds, log=str(log),
                           project_root=project_root, started=time.time())
    record.save()
    return process, record


def terminate(pid: int, wait: float = 15.0) -> None:
    """Stop a trainer and everything it started (data loader workers)."""
    for sig in (signal.SIGTERM, signal.SIGKILL):
        try:
            os.killpg(pid, sig)
        except ProcessLookupError:
            return
        except PermissionError:
            try:
                os.kill(pid, sig)
            except OSError:
                return
        deadline = time.monotonic() + (wait if sig == signal.SIGTERM else 5)
        while time.monotonic() < deadline:
            if not is_trainer_alive(pid):
                return
            time.sleep(0.3)


def follow(job: Any, record: TrainerRecord, process: subprocess.Popen | None,
           finish: Callable[[TrainerRecord, bool, int | None], Any],
           fallback_step: Callable[[], tuple[int, int] | None] | None = None) -> Any:
    """Report a trainer's progress on ``job`` until it exits, then ``finish`` its run.

    ``process`` is the Popen when this service started the trainer (so its exit code is
    known); after a restart it is None and the outcome is read from the run itself.
    """
    job.progress("Starting", 0, record.rounds)
    position = 0
    pending = ""
    cancelled = False
    reported = {"step": False}

    def read_new() -> None:
        nonlocal position, pending
        try:
            with open(record.log, "rb") as handle:
                handle.seek(position)
                chunk = handle.read()
                position = handle.tell()
        except OSError:
            return
        text = pending + chunk.decode("utf-8", errors="replace").replace("\r", "\n")
        lines = text.split("\n")
        pending = lines.pop()
        for raw in lines:
            line = _ANSI.sub("", raw).strip()
            if not line:
                continue
            if line.startswith("GRANUM_PHASE "):
                job.phase = line[len("GRANUM_PHASE "):]
            elif line.startswith("GRANUM_PROGRESS "):
                try:
                    done, total = line.split()[1:3]
                    if int(done) != job.done:
                        job.step, job.round_started = 0, time.time()
                        if hasattr(job, "round_base"):
                            job.round_base = 0
                    job.done, job.total = int(done), int(total)
                except ValueError:
                    pass
            elif line.startswith("GRANUM_STEP "):
                try:
                    done, total = line.split()[1:3]
                    job.set_step(int(done), int(total))
                    reported["step"] = True
                except (ValueError, AttributeError):
                    pass
            elif not job.log or job.log[-1] != line:
                job.log.append(line[:400])

    def running() -> bool:
        return process.poll() is None if process is not None else is_trainer_alive(record.pid)

    while True:
        read_new()
        # Trainers started before step reporting existed: ask the framework's own logs.
        if fallback_step is not None and not reported["step"] and hasattr(job, "set_step"):
            try:
                found = fallback_step()
            except Exception:  # noqa: BLE001 - progress detail is best effort
                found = None
            if found:
                job.set_step(*found)
        if job.cancel.is_set() and not cancelled:
            cancelled = True
            job.phase = "Stopping"
            terminate(record.pid)
        if not running():
            read_new()
            break
        time.sleep(0.5)

    code = process.wait() if process is not None else None
    record.remove()
    return finish(record, cancelled, code)


def finish_run(run_url: Any, cancelled: bool, code: int | None) -> str:
    """Set the run's final status if the trainer did not. Returns that status."""
    from granum.core.objects.run import Run

    try:
        run = Run.from_url(run_url)
    except GranumError:
        return "missing"
    if run.status == "running":
        run.set_status("cancelled" if cancelled else "interrupted" if code is None else "failed" if code != 0 else "finished")
    return run.status
