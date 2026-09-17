"""The ``Url`` value type and the alias registry.

Every location Granum touches is a ``Url``. Nothing in the codebase outside this module
may use ``os.path`` or bare ``open()`` -- that rule is what keeps cloud storage from
becoming a rewrite later (Stage 12 of the build plan).

Aliases let a Table written on one machine resolve on another. A Url stores the aliased
form (``<PROJECT_DATA>/1.jpg``) and expands it only at the moment of I/O, so the same
Table works against local disk for one user and S3 for another.
"""

from __future__ import annotations

import os
import re
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Any

import fsspec

from granum.errors import AliasConflictError

_ALIAS_RE = re.compile(r"<([A-Z0-9_]+)>")
_WINDOWS = os.name == "nt"
_DRIVE_ROOT = re.compile(r"^[A-Za-z]:/?$")


def _local_path(text: str) -> str:
    """An absolute local path in Granum's one spelling: forward slashes on every system.

    Windows accepts ``C:/Users/me`` everywhere it accepts ``C:\\Users\\me``, and a single
    separator keeps equality, prefix checks, joins and the dashboard's path handling
    identical to Linux.
    """
    text = os.path.abspath(os.path.expanduser(text))
    return text.replace("\\", "/") if _WINDOWS else text


def _strip_trailing(text: str) -> str:
    """Drop trailing slashes, except the one a root needs (``/``, ``C:/``)."""
    stripped = text.rstrip("/")
    if _WINDOWS and _DRIVE_ROOT.match(stripped):
        return stripped[:2] + "/"
    return stripped or "/"


def sample_key(value: object) -> str:
    """An image reference in the spelling tables store it in, for looking it up.

    Tables store local paths in Url spelling; on Windows a caller may still pass
    ``C:\\data\\a.png`` for the stored ``C:/data/a.png``. Everything else is unchanged.
    """
    text = str(value)
    if _WINDOWS and re.match(r"^[A-Za-z]:[\\/]", text):
        return text.replace("\\", "/")
    return text


def real_local_path(text: str) -> str:
    """``os.path.realpath`` in the same spelling, compared case-insensitively on Windows."""
    real = os.path.realpath(text)
    return real.replace("\\", "/").casefold() if _WINDOWS else real
_ALIAS_ENV_PREFIX = "GRANUM_ALIAS_"

# token -> (path, origin)
_ALIASES: dict[str, tuple[str, str]] = {}
_ENV_ALIASES_LOADED = False


def _load_env_aliases() -> None:
    global _ENV_ALIASES_LOADED
    if _ENV_ALIASES_LOADED:
        return
    _ENV_ALIASES_LOADED = True
    for key, value in os.environ.items():
        if key.startswith(_ALIAS_ENV_PREFIX):
            token = key[len(_ALIAS_ENV_PREFIX) :]
            if token:
                _ALIASES.setdefault(token, (value, f"env:{key}"))


def register_url_alias(token: str, path: str, *, force: bool = False, origin: str = "code") -> None:
    """Point ``token`` at ``path`` for this process.

    Re-pointing an existing token at a different path raises ``AliasConflictError``
    unless ``force=True``. Silent re-pointing is how two users end up looking at
    different data while believing they see the same thing.
    """
    _load_env_aliases()
    token = token.upper()
    existing = _ALIASES.get(token)
    if existing is not None and existing[0] != path and not force:
        raise AliasConflictError(
            f"Alias <{token}> is already registered to {existing[0]!r} (from {existing[1]}). "
            f"Pass force=True to re-point it to {path!r}."
        )
    _ALIASES[token] = (path, origin)


def unregister_url_alias(token: str) -> None:
    """Remove a programmatically registered alias.

    Aliases that came from configuration files or the environment must be removed at
    their source; this only drops in-process registrations.
    """
    _load_env_aliases()
    token = token.upper()
    entry = _ALIASES.get(token)
    if entry is not None and entry[1] == "code":
        del _ALIASES[token]


def get_registered_url_aliases() -> dict[str, str]:
    """Every active alias token mapped to its path."""
    _load_env_aliases()
    return {token: path for token, (path, _) in _ALIASES.items()}


def get_url_alias_origins() -> dict[str, str]:
    """Every active alias token mapped to where it was defined."""
    _load_env_aliases()
    return {token: origin for token, (_, origin) in _ALIASES.items()}


def _clear_url_aliases() -> None:
    """Test helper. Not part of the public API."""
    global _ENV_ALIASES_LOADED
    _ALIASES.clear()
    _ENV_ALIASES_LOADED = False


def expand_aliases(value: str) -> str:
    """Replace every ``<TOKEN>`` in ``value`` with its registered path."""
    _load_env_aliases()

    def _sub(match: re.Match[str]) -> str:
        token = match.group(1)
        entry = _ALIASES.get(token)
        return entry[0] if entry is not None else match.group(0)

    return _ALIAS_RE.sub(_sub, value)


def contract_aliases(value: str) -> str:
    """Replace known path prefixes in ``value`` with their alias token.

    The longest matching prefix wins, so a nested alias does not get shadowed by a
    broader one.
    """
    _load_env_aliases()
    best_token: str | None = None
    best_path = ""
    for token, (path, _) in _ALIASES.items():
        normalized = (path.replace("\\", "/") if _WINDOWS else path).rstrip("/")
        if normalized and value.startswith(normalized) and len(normalized) > len(best_path):
            best_token, best_path = token, normalized
    if best_token is None:
        return value
    return f"<{best_token}>{value[len(best_path):]}"


@dataclass(frozen=True)
class Url:
    """An immutable, scheme-agnostic location.

    ``Url`` stores the *aliased* string. ``resolved`` gives the expanded form used for
    I/O. Joining with ``/`` mirrors ``pathlib``.
    """

    raw: str

    def __init__(self, value: str | os.PathLike[str] | Url) -> None:
        if isinstance(value, Url):
            text = value.raw
        else:
            text = os.fspath(value)
        text = str(text).strip()
        if not text:
            raise ValueError("Url cannot be empty")
        if "://" not in text and not text.startswith("<"):
            # A bare filesystem path. Make it absolute so equality and joins behave.
            text = _local_path(text)
        elif _WINDOWS and text.startswith("<"):
            text = text.replace("\\", "/")
        object.__setattr__(self, "raw", _strip_trailing(text))

    # -- string forms -------------------------------------------------------

    def __str__(self) -> str:
        return self.raw

    def __repr__(self) -> str:
        return f"Url({self.raw!r})"

    def __fspath__(self) -> str:
        return self.resolved

    @property
    def resolved(self) -> str:
        """The alias-expanded string, suitable for handing to fsspec."""
        return expand_aliases(self.raw)

    def aliased(self) -> Url:
        """This Url with any known path prefix contracted back to an alias token."""
        return Url(contract_aliases(self.raw))

    # -- path algebra -------------------------------------------------------

    def __truediv__(self, other: str) -> Url:
        return self.join(other)

    def join(self, *parts: str) -> Url:
        """Append path segments."""
        text = self.raw
        for part in parts:
            part = str(part)
            if _WINDOWS:
                part = part.replace("\\", "/")
            part = part.strip("/")
            if part:
                text = f"{text.rstrip('/')}/{part}"
        return Url(text)

    @property
    def scheme(self) -> str:
        """``file``, ``s3``, ``gs``, ``memory``, and so on."""
        head = self.resolved.split("://", 1)
        return head[0] if len(head) == 2 else "file"

    @property
    def name(self) -> str:
        """The final path segment."""
        return self.raw.rstrip("/").rsplit("/", 1)[-1]

    @property
    def stem(self) -> str:
        """The final segment without its extension."""
        return PurePosixPath(self.name).stem

    @property
    def suffix(self) -> str:
        """The final segment's extension, including the dot."""
        return PurePosixPath(self.name).suffix

    @property
    def parent(self) -> Url:
        """The containing directory."""
        text = self.raw.rstrip("/")
        if "://" in text:
            scheme, rest = text.split("://", 1)
            if "/" not in rest:
                return self
            return Url(f"{scheme}://{rest.rsplit('/', 1)[0]}")
        if _WINDOWS and _DRIVE_ROOT.match(text + "/"):
            return self  # C:/ is its own parent, as / is
        if "/" not in text.lstrip("/") or text == "/":
            return Url("/")
        head = text.rsplit("/", 1)[0] or "/"
        return Url(head + "/" if _WINDOWS and _DRIVE_ROOT.match(head) else head)

    # -- filesystem ---------------------------------------------------------

    @property
    def fs(self) -> Any:
        """The fsspec filesystem backing this Url."""
        fs, _ = fsspec.core.url_to_fs(self.resolved)
        return fs

    @property
    def path(self) -> str:
        """The path component as the backing filesystem expects it."""
        _, path = fsspec.core.url_to_fs(self.resolved)
        return path

    def exists(self) -> bool:
        return bool(self.fs.exists(self.path))

    def is_dir(self) -> bool:
        try:
            return bool(self.fs.isdir(self.path))
        except (OSError, ValueError):
            return False

    def mkdir(self, *, exist_ok: bool = True) -> Url:
        fs = self.fs
        try:
            fs.makedirs(self.path, exist_ok=exist_ok)
        except FileExistsError:
            if not exist_ok:
                raise
        return self

    def read_bytes(self) -> bytes:
        with self.fs.open(self.path, "rb") as handle:
            return handle.read()

    def write_bytes(self, data: bytes) -> Url:
        self.parent.mkdir()
        with self.fs.open(self.path, "wb") as handle:
            handle.write(data)
        return self

    def read_text(self, encoding: str = "utf-8") -> str:
        return self.read_bytes().decode(encoding)

    def write_text(self, text: str, encoding: str = "utf-8") -> Url:
        return self.write_bytes(text.encode(encoding))

    def ls(self) -> list[Url]:
        """Immediate children, as Urls. Empty when this is not a directory."""
        if not self.is_dir():
            return []
        scheme = "" if "://" not in self.resolved else f"{self.scheme}://"
        out: list[Url] = []
        for entry in self.fs.ls(self.path, detail=False):
            out.append(Url(f"{scheme}{entry}" if scheme else entry))
        return sorted(out, key=str)

    def iterdir(self) -> Iterator[Url]:
        yield from self.ls()

    def rm(self, *, recursive: bool = False) -> None:
        self.fs.rm(self.path, recursive=recursive)
