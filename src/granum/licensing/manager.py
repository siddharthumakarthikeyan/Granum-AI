"""What the licence on this computer allows, kept honest against clocks and copies.

The key (:mod:`granum.licensing.token`) says what was bought. This module decides
whether it holds *now*:

- **Machine.** A key names one machine; on any other it is refused.
- **Plan end.** Past ``expires`` the app is read-only: projects open and export, nothing
  changes.
- **Offline lease (online keys).** A key must be renewed from the licence server every
  :data:`LEASE_DAYS` days. The allowance runs out on whichever comes first: the
  calendar passing ``lease_until``, or :data:`LEASE_DAYS` of the app actually running
  since the last renewal. Running time is counted with a monotonic clock, so moving
  the calendar back does not give time back.
- **Clock rollback.** The latest time Granum has seen (from its own heartbeat, the key's
  issue time, and the newest object in the projects) is remembered in two places. A
  system clock more than :data:`CLOCK_TOLERANCE` behind it means the clock was turned
  back: read-only until the clock is right or the licence renews online.

The state files carry an HMAC tied to this machine: editing or copying them makes them
count as missing, and a missing state counts the offline allowance as spent. None of
this stops someone rewriting the app itself; it stops the easy ways around a licence.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import threading
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from granum.core.appdirs import data_dir, state_dir
from granum.licensing.keys import PUBLIC_KEYS
from granum.licensing.machine import machine_id
from granum.licensing.token import LicenceError, decode, format_time, parse_time

LEASE_DAYS = 7
CLOCK_TOLERANCE = 2 * 3600
HEARTBEAT_SECONDS = 60
#: How often a running app renews an online key, when it can reach the server.
RENEW_SECONDS = 6 * 3600
#: Server answers that end this computer's licence: the key is removed.
ENDING_CODES = ("revoked", "deactivated", "unknown")
_STATE_SALT = b"granum-licence-state-v1"


class Licensing:
    """The licence of this computer. One per service; :func:`get_licensing` for the SDK."""

    def __init__(
        self,
        *,
        folder: Path | None = None,
        mark_folder: Path | None = None,
        public_keys: dict[str, str] | None = None,
        machine: str | None = None,
        clock: Callable[[], float] = time.time,
        monotonic: Callable[[], float] = time.monotonic,
        latest_seen: Callable[[], float | None] | None = None,
        server: Any = None,
        unrestricted: bool = False,
    ) -> None:
        self.folder = folder or data_dir() / "licence"
        self.mark_folder = mark_folder or state_dir()
        self.public_keys = public_keys if public_keys is not None else PUBLIC_KEYS
        self.machine = machine or machine_id()
        self.clock = clock
        self.monotonic = monotonic
        self.latest_seen = latest_seen
        self.unrestricted = unrestricted
        #: The licence server (granum.licensing.client.LicenceServer), when one is configured.
        self.server = server
        self._last_renewal: float | None = None
        self.server_message: str | None = None
        self._lock = threading.RLock()
        self._last_beat: float | None = None
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._cached: dict[str, Any] | None = None

    @classmethod
    def open(cls) -> Licensing:
        """No limits: for tests and for code that must never be refused."""
        return cls(unrestricted=True, machine="GM-UNRESTRICTED")

    # -- files ------------------------------------------------------------------------

    @property
    def key_path(self) -> Path:
        return self.folder / "licence.key"

    @property
    def state_path(self) -> Path:
        return self.folder / "state.json"

    @property
    def mark_path(self) -> Path:
        return self.mark_folder / "licence-mark.json"

    def _mac(self, body: dict[str, Any]) -> str:
        key = hashlib.sha256(_STATE_SALT + self.machine.encode()).digest()
        return hmac.new(key, json.dumps(body, sort_keys=True, separators=(",", ":")).encode(), hashlib.sha256).hexdigest()

    def _read_signed(self, path: Path) -> dict[str, Any] | None:
        try:
            record = json.loads(path.read_text())
            body, mac = record["body"], record["mac"]
        except (OSError, ValueError, KeyError, TypeError):
            return None
        return body if isinstance(body, dict) and hmac.compare_digest(str(mac), self._mac(body)) else None

    def _write_signed(self, path: Path, body: dict[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_name(path.name + ".tmp")
        temporary.write_text(json.dumps({"body": body, "mac": self._mac(body)}))
        os.replace(temporary, path)

    def _token(self) -> str | None:
        try:
            return self.key_path.read_text().strip() or None
        except OSError:
            return None

    def _high_water(self, state: dict[str, Any] | None, payload: dict[str, Any] | None) -> float:
        marks = [0.0]
        if state:
            marks.append(float(state.get("high_water") or 0))
        mark = self._read_signed(self.mark_path)
        if mark:
            marks.append(float(mark.get("high_water") or 0))
        if payload:
            marks.append(parse_time(payload.get("issued")) or 0)
        if self.latest_seen:
            try:
                marks.append(float(self.latest_seen() or 0))
            except Exception:  # noqa: BLE001 - a project that cannot be read adds nothing
                pass
        return max(marks)

    # -- status -----------------------------------------------------------------------

    def status(self, *, fresh: bool = False) -> dict[str, Any]:
        """What the licence allows now: ``mode`` is ``full`` or ``read_only``, with why."""
        with self._lock:
            if self._cached is None or fresh:
                self._cached = self._evaluate()
            return {**self._cached, "server": self.server is not None, "server_message": self.server_message}

    def _evaluate(self) -> dict[str, Any]:
        base: dict[str, Any] = {"machine": self.machine}
        if self.unrestricted:
            return {**base, "mode": "full", "state": "unrestricted", "reason": None, "max_projects": None}
        token = self._token()
        if token is None:
            how = "Sign in to start a free trial or activate your plan." if self.server is not None else "Enter a licence key to create and edit."
            return {**base, "mode": "read_only", "state": "missing", "reason": f"No licence on this computer. {how}"}
        try:
            payload = decode(token, self.public_keys)
        except LicenceError as exc:
            return {**base, "mode": "read_only", "state": "invalid", "reason": f"The licence key cannot be used: {exc}."}
        info = {
            **base,
            "lid": payload["lid"], "email": payload["email"], "customer": payload.get("customer"),
            "plan": payload.get("plan"), "kind": payload["kind"], "machines": payload.get("machines", 1),
            "issued": payload["issued"], "expires": payload.get("expires"), "lease_until": payload.get("lease_until"),
            "max_projects": payload.get("max_projects"),
        }
        if payload["machine"] != self.machine:
            return {**info, "mode": "read_only", "state": "wrong_machine",
                    "reason": "This licence key belongs to another computer. Activate the licence on this one."}

        state = self._read_signed(self.state_path)
        now = self.clock()
        high_water = self._high_water(state, payload)
        if now + CLOCK_TOLERANCE < high_water:
            return {**info, "mode": "read_only", "state": "clock",
                    "reason": f"The computer's clock is behind the last time Granum ran ({format_time(high_water)}). Set the correct date and time."}
        trusted = max(now, high_water)
        expires = parse_time(payload.get("expires"))
        if expires is not None and trusted >= expires:
            return {**info, "mode": "read_only", "state": "expired", "reason": "The licence has ended. Renew the plan to create and edit again."}
        out = {**info, "mode": "full", "state": "active", "reason": None,
               "days_left": None if expires is None else round((expires - trusted) / 86400, 1)}
        if payload["kind"] == "online":
            issued = parse_time(payload["issued"]) or trusted
            lease_seconds = (parse_time(payload["lease_until"]) or issued) - issued
            used = self._usage(state, payload)
            left = min((parse_time(payload["lease_until"]) or 0) - trusted, lease_seconds - used)
            out["offline_days_left"] = round(max(0.0, left) / 86400, 1)
            if left <= 0:
                return {**out, "mode": "read_only", "state": "lease_expired",
                        "reason": f"Granum has run {LEASE_DAYS} days without renewing its licence. Connect to the internet to renew."}
        return out

    def _usage(self, state: dict[str, Any] | None, payload: dict[str, Any]) -> float:
        """Seconds the app has run on this key since it was issued; all of it when unknown."""
        if state and state.get("issued") == payload["issued"] and state.get("lid") == payload["lid"]:
            return float(state.get("usage") or 0)
        issued = parse_time(payload["issued"]) or 0
        lease_until = parse_time(payload.get("lease_until")) or issued
        return lease_until - issued

    # -- changes ------------------------------------------------------------------------

    def install(self, token: str) -> dict[str, Any]:
        """Check a key and make it this computer's licence. Refuses keys for other machines."""
        payload = decode(token, self.public_keys)
        if payload["machine"] != self.machine:
            raise LicenceError(f"this key is for another computer ({payload['machine']}); this one is {self.machine}")
        with self._lock:
            state = self._read_signed(self.state_path)
            now = self.clock()
            issued = parse_time(payload["issued"]) or now
            if state and state.get("issued") == payload["issued"] and state.get("lid") == payload["lid"]:
                usage = float(state.get("usage") or 0)  # the same key again: keep what it used
            else:
                # Time since the key was issued counts as used, so an old key is no fresher for being new here.
                usage = max(0.0, now - issued)
            high_water = self._high_water(state, payload)
            if now + CLOCK_TOLERANCE >= high_water:
                high_water = max(high_water, now)
            self.folder.mkdir(parents=True, exist_ok=True)
            self.key_path.write_text("".join(token.split()) + "\n")
            self._write_state(payload, usage, high_water)
            self._last_beat = self.monotonic()
            return self.status(fresh=True)

    def remove(self) -> dict[str, Any]:
        """Forget the licence key (the clock marks stay)."""
        with self._lock:
            try:
                self.key_path.unlink()
            except FileNotFoundError:
                pass
            return self.status(fresh=True)

    def _write_state(self, payload: dict[str, Any], usage: float, high_water: float) -> None:
        body = {"lid": payload["lid"], "issued": payload["issued"], "usage": round(usage, 1), "high_water": high_water}
        self._write_signed(self.state_path, body)
        self._write_signed(self.mark_path, {"high_water": high_water})

    def heartbeat(self) -> dict[str, Any]:
        """Count running time and move the clock mark forward; call about once a minute."""
        if self.unrestricted:
            return self.status()
        with self._lock:
            beat = self.monotonic()
            elapsed = 0.0 if self._last_beat is None else max(0.0, beat - self._last_beat)
            self._last_beat = beat
            token = self._token()
            try:
                payload = decode(token, self.public_keys) if token else None
            except LicenceError:
                payload = None
            state = self._read_signed(self.state_path)
            high_water = self._high_water(state, payload)
            now = self.clock()
            if now + CLOCK_TOLERANCE >= high_water:
                high_water = max(high_water, now)  # never learn a time from a clock turned back
            if payload and payload["machine"] == self.machine:
                self._write_state(payload, self._usage(state, payload) + elapsed, high_water)
            else:
                self._write_signed(self.mark_path, {"high_water": high_water})
            return self.status(fresh=True)

    # -- the licence server -------------------------------------------------------------

    def _require_server(self) -> Any:
        if self.server is None:
            raise LicenceError("no licence server is set up in this copy of Granum; enter a licence key instead")
        return self.server

    def send_code(self, email: str) -> dict[str, Any]:
        """Ask the server to email a sign-in code."""
        return self._require_server().send_code(email)

    def activate(self, email: str, code: str) -> dict[str, Any]:
        """Sign in: the server answers with this computer's key (its plan, or a free trial)."""
        key = self._require_server().activate(email, code, self.machine)
        self.server_message = None
        self._last_renewal = self.monotonic()
        return self.install(key)

    def renew(self) -> dict[str, Any]:
        """Swap an online key for a fresh one; a server that ends the licence removes the key."""
        from granum.licensing.client import Refused

        server = self._require_server()
        token = self._token()
        if token is None:
            raise LicenceError("no licence key to renew; sign in first")
        self._last_renewal = self.monotonic()
        try:
            fresh = server.refresh(token)
        except Refused as exc:
            self.server_message = str(exc)
            if exc.code in ENDING_CODES:
                self.remove()
            raise
        self.server_message = None
        return self.install(fresh)

    def sign_out(self) -> dict[str, Any]:
        """Free this computer on the server (so the plan can move) and forget the key."""
        token = self._token()
        if token is not None and self.server is not None:
            self.server.deactivate(token)
        return self.remove()

    def _renewal_due(self) -> bool:
        if self.server is None:
            return False
        status = self.status()
        if status.get("kind") != "online" or status["state"] in ("wrong_machine", "invalid", "missing"):
            return False
        return self._last_renewal is None or self.monotonic() - self._last_renewal >= RENEW_SECONDS

    def maybe_renew(self) -> None:
        """Renew when due; offline or refused, try again later."""
        if not self._renewal_due():
            return
        try:
            self.renew()
        except LicenceError:
            pass

    def start(self, interval: float = HEARTBEAT_SECONDS) -> None:
        """Beat (and renew when due) in the background until :meth:`stop`."""
        if self._thread is not None or self.unrestricted:
            return
        self.heartbeat()

        def run() -> None:
            self.maybe_renew()
            while not self._stop.wait(interval):
                try:
                    self.heartbeat()
                    self.maybe_renew()
                except Exception:  # noqa: BLE001 - a failed beat is retried next time
                    pass

        self._thread = threading.Thread(target=run, name="granum-licence", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    # -- checks -------------------------------------------------------------------------

    def require_write(self, action: str = "change data") -> None:
        status = self.status()
        if status["mode"] != "full":
            raise LicenceError(f"cannot {action}: Granum is read-only. {status['reason']}")

    def require_new_project(self, existing: int) -> None:
        """Refuse a new project past the plan's project limit (``existing`` counts the others)."""
        self.require_write("create a project")
        limit = self.status().get("max_projects")
        if limit is not None and existing >= int(limit):
            raise LicenceError(f"the plan allows {limit} project{'s' if limit != 1 else ''} and all are in use. "
                               "Delete a project or move to a plan with more.")


_LICENSING: Licensing | None = None


def get_licensing() -> Licensing:
    global _LICENSING
    if _LICENSING is None:
        _LICENSING = Licensing()
    return _LICENSING


def set_licensing(licensing: Licensing | None) -> None:
    global _LICENSING
    _LICENSING = licensing
