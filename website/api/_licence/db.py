"""Storage: Postgres in production (``DATABASE_URL``, e.g. Neon on Vercel), SQLite for tests.

Queries use ``:name`` parameters, which both drivers take. Rows come back as dicts.
"""

from __future__ import annotations

import re
import sqlite3
import ssl
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, unquote, urlsplit

SCHEMA = """
CREATE TABLE IF NOT EXISTS accounts (
    email       TEXT PRIMARY KEY,
    created     DOUBLE PRECISION NOT NULL,
    source      TEXT,
    name        TEXT,
    company     TEXT
);
CREATE TABLE IF NOT EXISTS codes (
    id          {id},
    email       TEXT NOT NULL,
    code_hash   TEXT NOT NULL,
    created     DOUBLE PRECISION NOT NULL,
    expires     DOUBLE PRECISION NOT NULL,
    attempts    INTEGER NOT NULL DEFAULT 0,
    used        INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS codes_email ON codes(email);
CREATE TABLE IF NOT EXISTS licences (
    lid          TEXT PRIMARY KEY,
    email        TEXT NOT NULL,
    customer     TEXT,
    plan         TEXT NOT NULL,
    kind         TEXT NOT NULL,
    created      DOUBLE PRECISION NOT NULL,
    expires      DOUBLE PRECISION,
    machines     INTEGER NOT NULL DEFAULT 1,
    max_projects INTEGER,
    revoked      INTEGER NOT NULL DEFAULT 0,
    note         TEXT
);
CREATE INDEX IF NOT EXISTS licences_email ON licences(email);
CREATE TABLE IF NOT EXISTS activations (
    lid          TEXT NOT NULL,
    machine      TEXT NOT NULL,
    created      DOUBLE PRECISION NOT NULL,
    last_seen    DOUBLE PRECISION NOT NULL,
    app_version  TEXT,
    deactivated  DOUBLE PRECISION,
    PRIMARY KEY (lid, machine)
);
CREATE TABLE IF NOT EXISTS trials (
    machine      TEXT PRIMARY KEY,
    email        TEXT NOT NULL,
    lid          TEXT NOT NULL,
    created      DOUBLE PRECISION NOT NULL
);
CREATE TABLE IF NOT EXISTS downloads (
    id           {id},
    email        TEXT NOT NULL,
    os           TEXT,
    created      DOUBLE PRECISION NOT NULL
);
CREATE TABLE IF NOT EXISTS quotes (
    id           {id},
    email        TEXT NOT NULL,
    name         TEXT,
    company      TEXT,
    plan         TEXT,
    computers    INTEGER,
    message      TEXT,
    created      DOUBLE PRECISION NOT NULL
);
"""

_PARAM = re.compile(r"(?<!:):([A-Za-z_][A-Za-z0-9_]*)")


class Database:
    """One connection per thread (a serverless instance handles one request at a time)."""

    def __init__(self, url: str) -> None:
        self.url = url
        self.postgres = url.startswith(("postgres://", "postgresql://"))
        self._local = threading.local()
        self._memory: sqlite3.Connection | None = None
        if not self.postgres and url not in (":memory:", "") and not url.startswith("sqlite:"):
            Path(url).parent.mkdir(parents=True, exist_ok=True)
        with self.transaction():
            for statement in SCHEMA.format(id="BIGSERIAL PRIMARY KEY" if self.postgres else "INTEGER PRIMARY KEY AUTOINCREMENT").split(";"):
                if statement.strip():
                    self.run(statement)

    # -- connections -----------------------------------------------------------------

    def _connect_postgres(self) -> Any:
        import pg8000.native

        parts = urlsplit(self.url)
        query = parse_qs(parts.query)
        context = None
        if query.get("sslmode", ["require"])[0] != "disable":
            context = ssl.create_default_context()
        return pg8000.native.Connection(
            user=unquote(parts.username or ""), password=unquote(parts.password or ""), host=parts.hostname or "localhost",
            port=parts.port or 5432, database=(parts.path or "/").lstrip("/") or "postgres", ssl_context=context, timeout=15,
        )

    def _connection(self) -> Any:
        if self.postgres:
            connection = getattr(self._local, "connection", None)
            if connection is None:
                connection = self._local.connection = self._connect_postgres()
            return connection
        if self.url in (":memory:", ""):
            if self._memory is None:
                self._memory = sqlite3.connect(":memory:", check_same_thread=False, isolation_level=None)
                self._memory.row_factory = sqlite3.Row
            return self._memory
        connection = getattr(self._local, "connection", None)
        if connection is None:
            connection = sqlite3.connect(self.url.removeprefix("sqlite:"), isolation_level=None, timeout=10)
            connection.row_factory = sqlite3.Row
            connection.execute("PRAGMA journal_mode=WAL")
            self._local.connection = connection
        return connection

    # -- queries ---------------------------------------------------------------------

    def rows(self, sql: str, **params: Any) -> list[dict[str, Any]]:
        if self.postgres:
            connection = self._connection()
            try:
                result = connection.run(sql, **params)
            except Exception as exc:  # a connection a warm instance kept can go stale
                if getattr(self._local, "depth", 0) or "network" not in str(exc).lower() and "closed" not in str(exc).lower():
                    raise
                self._local.connection = None
                connection = self._connection()
                result = connection.run(sql, **params)
            if not connection.columns:
                return []
            names = [c["name"] for c in connection.columns]
            return [dict(zip(names, row)) for row in (result or [])]
        cursor = self._connection().execute(sql, params)
        return [dict(row) for row in cursor.fetchall()] if cursor.description else []

    def row(self, sql: str, **params: Any) -> dict[str, Any] | None:
        found = self.rows(sql, **params)
        return found[0] if found else None

    def value(self, sql: str, **params: Any) -> Any:
        found = self.row(sql, **params)
        return None if found is None else next(iter(found.values()))

    def run(self, sql: str, **params: Any) -> None:
        self.rows(sql, **params)

    @contextmanager
    def transaction(self, lock: str | None = None) -> Iterator[None]:
        """All or nothing; with ``lock``, one transaction per lock name at a time."""
        depth = getattr(self._local, "depth", 0)
        if depth:
            self._local.depth = depth + 1
            try:
                yield
            finally:
                self._local.depth = depth
            return
        self.run("BEGIN" if self.postgres else "BEGIN IMMEDIATE")
        self._local.depth = 1
        try:
            if lock and self.postgres:
                self.run("SELECT pg_advisory_xact_lock(hashtext(:lock))", lock=lock)
            yield
            self.run("COMMIT")
        except BaseException:
            self.run("ROLLBACK")
            raise
        finally:
            self._local.depth = 0
