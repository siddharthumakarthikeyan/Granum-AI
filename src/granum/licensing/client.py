"""Talking to the licence server (``licence.server`` in the config).

Standard library only, so it works in every packaged build. A server that cannot be
reached is :class:`Unreachable`; one that answers no is :class:`Refused`, carrying the
server's own message and reason code.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Any

from granum import __version__
from granum.licensing.token import LicenceError


class Unreachable(LicenceError):
    """No answer from the licence server (offline, or the address is wrong)."""


class Refused(LicenceError):
    """The licence server answered no; ``code`` says why (e.g. ``trial_used``, ``revoked``)."""

    def __init__(self, message: str, *, status: int, code: str = "") -> None:
        super().__init__(message)
        self.status, self.code = status, code


class LicenceServer:
    def __init__(self, url: str, *, timeout: float = 15) -> None:
        self.url = url.rstrip("/")
        self.timeout = timeout

    def _post(self, path: str, body: dict[str, Any]) -> dict[str, Any]:
        request = urllib.request.Request(
            f"{self.url}{path}", data=json.dumps(body).encode(), method="POST",
            headers={"Content-Type": "application/json", "User-Agent": f"Granum/{__version__}"},
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                return json.loads(response.read() or b"{}")
        except urllib.error.HTTPError as exc:
            try:
                answer = json.loads(exc.read() or b"{}")
            except ValueError:
                answer = {}
            raise Refused(str(answer.get("detail") or f"the licence server said {exc.code}"),
                          status=exc.code, code=str(answer.get("code") or "")) from exc
        except (urllib.error.URLError, OSError, ValueError) as exc:
            raise Unreachable("cannot reach the licence server; check the internet connection") from exc

    def send_code(self, email: str) -> dict[str, Any]:
        return self._post("/v1/login/code", {"email": email})

    def activate(self, email: str, code: str, machine: str) -> str:
        return str(self._post("/v1/activate", {"email": email, "code": code, "machine": machine, "app_version": __version__})["key"])

    def refresh(self, key: str) -> str:
        return str(self._post("/v1/refresh", {"key": key, "app_version": __version__})["key"])

    def deactivate(self, key: str) -> None:
        self._post("/v1/deactivate", {"key": key})
