"""Tiered configuration with provenance.

Values resolve lowest-to-highest across: built-in default, system file, user file,
project file, environment variable, explicit override. Every option can report *where*
its current value came from, which is what makes the tool debuggable inside someone
else's infrastructure.
"""

from __future__ import annotations

import os
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import IntEnum
from typing import Any

import yaml

from granum.core.url import Url, register_url_alias
from granum.errors import ConfigError

CONFIG_FILENAME = "config.granum.yaml"
ALIASES_FILENAME = "default_aliases.granum.yaml"


class Tier(IntEnum):
    """Resolution order. Higher wins."""

    DEFAULT = 0
    SYSTEM = 1
    USER = 2
    PROJECT = 3
    ENV = 4
    OVERRIDE = 5


@dataclass(frozen=True)
class Option:
    """One declared configuration option."""

    name: str
    default: Any
    help: str
    env_var: str
    parse: Callable[[str], Any] = str


def _parse_bool(text: str) -> bool:
    return text.strip().lower() in {"1", "true", "yes", "on"}


def _parse_int(text: str) -> int:
    try:
        return int(text)
    except ValueError as exc:
        raise ConfigError(f"expected an integer, got {text!r}") from exc


def _parse_float(text: str) -> float:
    try:
        return float(text)
    except ValueError as exc:
        raise ConfigError(f"expected a number, got {text!r}") from exc


def _default_data_roots() -> str:
    """The home folder; on Windows also every local and removable drive, where datasets
    usually live (``D:\\datasets``) rather than under the user's profile."""
    home = os.path.expanduser("~")
    if os.name != "nt":
        return home
    import ctypes
    import string

    roots = [home]
    try:
        mask = ctypes.windll.kernel32.GetLogicalDrives()
        for index, letter in enumerate(string.ascii_uppercase):
            drive = f"{letter}:\\"
            # 2 removable, 3 fixed; skip network shares and optical drives, which can hang.
            if mask >> index & 1 and ctypes.windll.kernel32.GetDriveTypeW(drive) in (2, 3):
                roots.append(drive)
    except (AttributeError, OSError):
        pass
    return os.pathsep.join(roots)


def _default_project_root() -> str:
    return os.path.join(os.path.expanduser("~"), "granum")


OPTIONS: dict[str, Option] = {
    opt.name: opt
    for opt in [
        Option(
            "project-root-url",
            _default_project_root(),
            "Location for reading and writing Granum project data.",
            "GRANUM_PROJECT_ROOT_URL",
        ),
        Option("log-level", "WARNING", "Log level for the Granum logger.", "GRANUM_LOG_LEVEL"),
        Option(
            "service.data-roots",
            _default_data_roots(),
            "Folders the service may read datasets from when importing, separated by os.pathsep.",
            "GRANUM_SERVICE_DATA_ROOTS",
        ),
        Option(
            "service.allowed-origins",
            "",
            "Extra browser origins allowed to call the service, comma separated. Same-origin always works.",
            "GRANUM_SERVICE_ALLOWED_ORIGINS",
        ),
        Option(
            "service.port",
            8000,
            "Port the service and dashboard listen on; also used by `granum open` and `granum app`.",
            "GRANUM_SERVICE_PORT",
            _parse_int,
        ),
        Option("log-file", "", "Log file path for the Granum logger.", "GRANUM_LOG_FILE"),
        Option(
            "licence.server",
            "",
            "Address of the Granum licence server that starts trials, activates plans and renews keys.",
            "GRANUM_LICENCE_SERVER",
        ),
        Option(
            "display-progress",
            True,
            "Whether to display progress bars.",
            "GRANUM_DISPLAY_PROGRESS",
            _parse_bool,
        ),
        Option(
            "indexing.scan-interval",
            10,
            "Seconds between index scans of each location.",
            "GRANUM_INDEXING_SCAN_INTERVAL",
            _parse_int,
        ),
        Option(
            "table.row-cache",
            True,
            "Materialize a row cache alongside each Table.",
            "GRANUM_TABLE_ROW_CACHE",
            _parse_bool,
        ),
    ]
}


@dataclass(frozen=True)
class Resolved:
    """An option's current value and where it came from."""

    name: str
    value: Any
    tier: Tier
    source: str

    @property
    def is_default(self) -> bool:
        return self.tier is Tier.DEFAULT


def system_config_url() -> Url:
    if os.name == "nt":
        return Url(os.path.join(os.environ.get("PROGRAMDATA") or "C:\\ProgramData", "Granum", CONFIG_FILENAME))
    return Url(os.path.join("/etc", "granum", CONFIG_FILENAME))


def user_config_url() -> Url:
    from granum.core.appdirs import config_dir

    return Url(config_dir() / CONFIG_FILENAME)


def project_config_url() -> Url:
    return Url(os.path.join(os.getcwd(), CONFIG_FILENAME))


def _flatten(data: dict[str, Any], prefix: str = "") -> dict[str, Any]:
    """Turn nested YAML into dotted keys, leaving ``aliases`` intact."""
    out: dict[str, Any] = {}
    for key, value in data.items():
        dotted = f"{prefix}{key}"
        if isinstance(value, dict) and dotted != "aliases":
            out.update(_flatten(value, prefix=f"{dotted}."))
        else:
            out[dotted] = value
    return out


def _read_config_file(url: Url) -> dict[str, Any]:
    if not url.exists():
        return {}
    try:
        loaded = yaml.safe_load(url.read_text()) or {}
    except yaml.YAMLError as exc:
        raise ConfigError(f"{url} is not valid YAML: {exc}") from exc
    if not isinstance(loaded, dict):
        raise ConfigError(f"{url} must contain a mapping at the top level")
    return loaded


@dataclass
class Config:
    """Resolved configuration for this process."""

    _resolved: dict[str, Resolved] = field(default_factory=dict)
    _files: list[tuple[Tier, Url]] = field(default_factory=list)

    @classmethod
    def load(
        cls,
        *,
        overrides: dict[str, Any] | None = None,
        config_file: Url | str | None = None,
        use_config_files: bool = True,
        use_env: bool = True,
    ) -> Config:
        config = cls()
        for option in OPTIONS.values():
            config._resolved[option.name] = Resolved(
                option.name, option.default, Tier.DEFAULT, "built-in default"
            )

        if use_config_files:
            candidates: list[tuple[Tier, Url]] = (
                [(Tier.PROJECT, Url(config_file))]
                if config_file is not None
                else [
                    (Tier.SYSTEM, system_config_url()),
                    (Tier.USER, user_config_url()),
                    (Tier.PROJECT, project_config_url()),
                ]
            )
            for tier, url in candidates:
                data = _read_config_file(url)
                if not data:
                    continue
                config._files.append((tier, url))
                config._apply(_flatten(data), tier, str(url))

        if use_env:
            for option in OPTIONS.values():
                raw = os.environ.get(option.env_var)
                if raw is not None:
                    config._set(option.name, option.parse(raw), Tier.ENV, f"env:{option.env_var}")

        if overrides:
            config._apply(overrides, Tier.OVERRIDE, "explicit override")

        return config

    # -- internals ----------------------------------------------------------

    def _apply(self, data: dict[str, Any], tier: Tier, source: str) -> None:
        for key, value in data.items():
            if key == "aliases":
                if not isinstance(value, dict):
                    raise ConfigError(f"'aliases' in {source} must be a mapping")
                for token, path in value.items():
                    register_url_alias(str(token), str(path), force=True, origin=source)
                continue
            if key in OPTIONS:
                self._set(key, value, tier, source)

    def _set(self, name: str, value: Any, tier: Tier, source: str) -> None:
        current = self._resolved.get(name)
        if current is None or tier >= current.tier:
            self._resolved[name] = Resolved(name, value, tier, source)

    # -- public API ---------------------------------------------------------

    def get(self, name: str) -> Any:
        if name not in OPTIONS:
            raise ConfigError(f"unknown option {name!r}")
        return self._resolved[name].value

    def provenance(self, name: str) -> Resolved:
        if name not in OPTIONS:
            raise ConfigError(f"unknown option {name!r}")
        return self._resolved[name]

    def show(self) -> list[Resolved]:
        return [self._resolved[name] for name in sorted(OPTIONS)]

    def loaded_files(self) -> list[tuple[Tier, Url]]:
        return list(self._files)

    def validate(self) -> list[str]:
        """Return a list of problems. Empty means the configuration is usable."""
        problems: list[str] = []
        level = str(self.get("log-level")).upper()
        if level not in {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}:
            problems.append(f"log-level: {level!r} is not a valid level")
        if int(self.get("indexing.scan-interval")) <= 0:
            problems.append("indexing.scan-interval: must be greater than zero")
        try:
            Url(self.get("project-root-url"))
        except (ValueError, TypeError) as exc:
            problems.append(f"project-root-url: {exc}")
        return problems

    @property
    def project_root(self) -> Url:
        return Url(self.get("project-root-url"))

    def to_yaml(self, *, only_changed: bool = False) -> str:
        nested: dict[str, Any] = {}
        for item in self.show():
            if only_changed and item.is_default:
                continue
            node = nested
            parts = item.name.split(".")
            for part in parts[:-1]:
                node = node.setdefault(part, {})
            node[parts[-1]] = item.value
        return yaml.safe_dump(nested, sort_keys=True, default_flow_style=False)


_ACTIVE: Config | None = None


def get_config() -> Config:
    """The process-wide configuration, loaded on first use."""
    global _ACTIVE
    if _ACTIVE is None:
        _ACTIVE = Config.load()
    return _ACTIVE


def set_config(config: Config | None) -> None:
    """Replace the process-wide configuration. Passing ``None`` forces a reload."""
    global _ACTIVE
    _ACTIVE = config
