"""Explicit, single-workspace shared access. Not SSO or per-project multi-tenancy.

HTTP Basic is used only over TLS (including a trusted loopback TLS proxy). Browsers
authenticate images and API calls alike; no passwords or bearer tokens enter JS storage.
"""
from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import ipaddress
import json
import os
import re
import secrets
import threading
import time
from collections import OrderedDict, deque
from contextvars import ContextVar
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from fastapi import HTTPException, Request
from pydantic import BaseModel, model_validator

ROLES = ("viewer", "annotator", "reviewer", "admin")
READ_POSTS = {"/api/images/boxes", "/api/augment/examples"}
ANNOTATE = {"/api/table/commit", "/api/qa/comment", "/api/tags", "/api/views", "/api/qa/release"}
REVIEW = {"/api/qa/status", "/api/qa/ship", "/api/qa/approve", "/api/reviews", "/api/qa/isolate",
          "/api/qa/return", "/api/datasets/remove", "/api/datasets/restore", "/api/training",
          "/api/findings/screen", "/api/datasets/prelabel", "/api/embeddings", "/api/datasets/export"}


@dataclass(frozen=True)
class Principal:
    name: str
    role: str


principal: ContextVar[Principal | None] = ContextVar("granum_principal", default=None)


class AttributedRequest(BaseModel):
    """Never trust the browser's display-name field in authenticated shared mode."""

    @model_validator(mode="before")
    @classmethod
    def authenticated_author(cls, data: Any) -> Any:
        actor = principal.get()
        return {**data, "author": actor.name} if actor and isinstance(data, dict) else data


def is_loopback(host: str) -> bool:
    if host in {"localhost", "testclient"}:  # testclient is Starlette's in-process peer
        return True
    try:
        return ipaddress.ip_address(host.strip("[]")).is_loopback
    except ValueError:
        return False


def password_hash(password: str) -> str:
    if len(password) < 12 or len(password) > 1024:
        raise ValueError("use a password of 12–1024 characters")
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode(), salt=salt, n=16384, r=8, p=1, dklen=32)
    return f"scrypt${salt.hex()}${digest.hex()}"


def _verify(password: str, encoded: str) -> bool:
    _, salt, digest = encoded.split("$")
    actual = hashlib.scrypt(password.encode(), salt=bytes.fromhex(salt), n=16384, r=8, p=1, dklen=32)
    return hmac.compare_digest(actual, bytes.fromhex(digest))


class SharedAccess:
    def __init__(self, users: dict[str, dict[str, str]]) -> None:
        if not isinstance(users, dict) or any(not isinstance(u, dict) for u in users.values()):
            raise ValueError("the access registry must contain a users object")
        if not users or not any(u.get("role") == "admin" for u in users.values()):
            raise ValueError("shared access requires at least one administrator")
        for name, user in users.items():
            if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._@-]{0,79}", name) or user.get("role") not in ROLES:
                raise ValueError("invalid shared-access user or role")
            if not re.fullmatch(r"scrypt\$[a-f0-9]{32}\$[a-f0-9]{64}", user.get("password_hash", "")):
                raise ValueError("invalid password hash; use granum access add-user")
        self.users = {name: dict(user) for name, user in users.items()}
        # Authentication runs in worker threads. Serialize uncached password checks to bound
        # scrypt memory and make rate-limit/cache updates atomic; cached requests are cheap.
        self._lock = threading.RLock()
        self._dummy = password_hash(secrets.token_urlsafe(24))
        self._cache: OrderedDict[bytes, tuple[float, Principal]] = OrderedDict()
        self._secret = secrets.token_bytes(32)
        self._failures: OrderedDict[str, deque[float]] = OrderedDict()

    @classmethod
    def from_file(cls, path: Path) -> SharedAccess:
        if os.name != "nt" and path.stat().st_mode & 0o077:
            raise ValueError("the access file must be owner-only (chmod 600)")
        payload = json.loads(path.read_text())
        if payload.get("version") != 1:
            raise ValueError("unsupported access-file version")
        return cls(payload["users"])

    def authenticate(self, request: Request) -> Principal:
        if request.url.scheme != "https":
            raise HTTPException(403, "Shared access requires HTTPS. Use TLS or a trusted loopback TLS reverse proxy.")
        header = request.headers.get("authorization", "")
        if not header:
            # An initial browser challenge must not allocate scrypt memory or consume a login attempt.
            raise HTTPException(401, "Authentication required.", headers={"WWW-Authenticate": 'Basic realm="Granum workspace", charset="UTF-8"'})
        with self._lock:
            return self._authenticate(request, header)

    def _authenticate(self, request: Request, header: str) -> Principal:
        key = hmac.digest(self._secret, header.encode(), "sha256")
        now = time.monotonic()
        cached = self._cache.get(key)
        if cached and now - cached[0] < 60:
            return cached[1]
        peer = request.client.host if request.client else "unknown"
        attempts = self._failures.setdefault(peer, deque(maxlen=20))
        while attempts and now - attempts[0] > 60:
            attempts.popleft()
        if len(attempts) >= 20:
            raise HTTPException(429, "Too many failed sign-in attempts; retry in one minute.", headers={"Retry-After": "60"})
        if len(self._failures) > 2048:
            self._failures.popitem(last=False)
        name, password = "", ""
        try:
            scheme, value = header.split(" ", 1)
            if scheme.lower() == "basic" and len(value) <= 8192:
                name, password = base64.b64decode(value, validate=True).decode("utf-8").split(":", 1)
        except (ValueError, UnicodeDecodeError, binascii.Error):
            pass
        user = self.users.get(name)
        valid = _verify(password, user["password_hash"] if user else self._dummy)
        if not valid or not user:
            if header:
                attempts.append(now)
            raise HTTPException(401, "Authentication required.", headers={"WWW-Authenticate": 'Basic realm="Granum workspace", charset="UTF-8"'})
        actor = Principal(name, user["role"])
        self._cache[key] = (now, actor)
        if len(self._cache) > 256:
            self._cache.popitem(last=False)
        return actor

    @staticmethod
    def authorize(actor: Principal, method: str, path: str) -> None:
        if method in {"GET", "HEAD", "OPTIONS"} or (method == "POST" and path in READ_POSTS):
            return
        required = "annotator" if path in ANNOTATE else "reviewer" if path in REVIEW else "admin"
        if re.fullmatch(r"/api/jobs/[^/]+/cancel", path):
            required = "reviewer"
        if ROLES.index(actor.role) < ROLES.index(required):
            raise HTTPException(403, f"This action requires the {required} role; signed in as {actor.name} ({actor.role}).")