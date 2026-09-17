"""Where Granum keeps its own files on each operating system.

Project data lives under the project root and never here. These folders hold the user
config, installed add-ons, the window's browser storage, logs and training records.

- Linux and other Unix: the XDG folders (``~/.config``, ``~/.local/share``, ``~/.local/state``).
- Windows: ``%APPDATA%\\Granum`` for config, ``%LOCALAPPDATA%\\Granum`` for data and state.

An ``XDG_*`` variable that is set wins on every system, so tests and portable runs can
point everything at a sandbox.
"""

from __future__ import annotations

import os
from pathlib import Path

IS_WINDOWS = os.name == "nt"


def _home(*parts: str) -> Path:
    return Path(os.path.expanduser("~"), *parts)


def _windows(variable: str, fallback: tuple[str, ...]) -> Path:
    return Path(os.environ.get(variable) or _home(*fallback)) / "Granum"


def config_dir() -> Path:
    if IS_WINDOWS and not os.environ.get("XDG_CONFIG_HOME"):
        return _windows("APPDATA", ("AppData", "Roaming"))
    return Path(os.environ.get("XDG_CONFIG_HOME") or _home(".config")) / "granum"


def data_dir() -> Path:
    if IS_WINDOWS and not os.environ.get("XDG_DATA_HOME"):
        return _windows("LOCALAPPDATA", ("AppData", "Local"))
    return Path(os.environ.get("XDG_DATA_HOME") or _home(".local", "share")) / "granum"


def state_dir() -> Path:
    if IS_WINDOWS and not os.environ.get("XDG_STATE_HOME"):
        return _windows("LOCALAPPDATA", ("AppData", "Local")) / "state"
    return Path(os.environ.get("XDG_STATE_HOME") or _home(".local", "state")) / "granum"
