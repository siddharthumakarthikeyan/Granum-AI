"""Standard-library build provenance; also usable inside an isolated wheel build."""
from __future__ import annotations

import ast
import hashlib
import json
import os
import subprocess
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

WEB_INPUTS = ("src", "public", "scripts", "package.json", "package-lock.json", "tsconfig.json", "vite.config.ts")


def digest(entries: list[tuple[str, bytes]]) -> str:
    result = hashlib.sha256()
    for name, data in sorted(entries):
        result.update(name.encode("utf-8") + b"\0" + data + b"\0")
    return result.hexdigest()


def tree_hash(root: Path, paths: tuple[str, ...] = (".",), *, exclude: tuple[str, ...] = ()) -> str:
    entries = []
    for name in paths:
        start = root / name
        candidates = start.rglob("*") if start.is_dir() else [start]
        for path in candidates:
            if not path.is_file() or "__pycache__" in path.parts:
                continue
            relative = path.relative_to(root).as_posix()
            if any(relative == prefix or relative.startswith(prefix + "/") for prefix in exclude):
                continue
            entries.append((relative, path.read_bytes()))
    return digest(entries)


def dashboard_stamp(root: Path) -> dict[str, Any] | None:
    static = root / "src/granum/service/static"
    try:
        stamp = json.loads((static / "build-stamp.json").read_text())
        if (stamp["version"] != 1 or not (static / "index.html").is_file()
                or stamp["source_sha256"] != tree_hash(root / "web", WEB_INPUTS)
                or stamp["bundle_sha256"] != tree_hash(static, exclude=("build-stamp.json",))):
            return None
        return stamp
    except (OSError, ValueError, KeyError, TypeError):
        return None


def git_state(root: Path) -> tuple[str | None, bool | None]:
    def git(*args: str) -> str:
        return subprocess.check_output(["git", "-C", str(root), *args], stderr=subprocess.DEVNULL, text=True).strip()

    try:
        return git("rev-parse", "HEAD"), bool(git("status", "--porcelain", "--untracked-files=normal"))
    except (OSError, subprocess.CalledProcessError):
        return None, None


def create_manifest(root: Path, version: str) -> dict[str, Any]:
    stamp = dashboard_stamp(root)
    revision, dirty = git_state(root)
    package = root / "src/granum"
    enforced = None
    for statement in ast.parse((package / "licensing/manager.py").read_text()).body:
        if isinstance(statement, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "ENFORCED" for t in statement.targets):
            enforced = ast.literal_eval(statement.value)
    if not isinstance(enforced, bool):
        raise ValueError("Cannot establish the build's licensing policy")
    if os.environ.get("GRANUM_RELEASE_BUILD") == "1":
        if not revision or dirty is not False or stamp is None:
            raise ValueError("Release builds require a clean Git tree and a matching, complete dashboard build")
        expected = os.environ.get("GITHUB_SHA")
        if expected and expected != revision:
            raise ValueError("The build revision differs from the CI revision")
        tag = os.environ.get("GITHUB_REF", "")
        if tag.startswith("refs/tags/v") and tag.removeprefix("refs/tags/v") != version:
            raise ValueError("The release tag and package version differ")
    timestamp = datetime.fromtimestamp(int(os.environ["SOURCE_DATE_EPOCH"]), timezone.utc) if "SOURCE_DATE_EPOCH" in os.environ else datetime.now(timezone.utc)
    return {
        "format_version": 1, "version": version, "built_at": timestamp.isoformat(),
        "source_revision": revision, "source_dirty": dirty,
        "channel": "licensed-alpha" if enforced else "unrestricted-alpha",
        "licensing_enforced": enforced, "dashboard": stamp,
        "package_sha256": tree_hash(package, exclude=("_build.json", "service/static")),
        "build_inputs_sha256": tree_hash(root, ("pyproject.toml", "hatch_build.py", "build_provenance.py", "packaging")),
    }


def verify_wheel(path: Path, *, version: str | None = None, revision: str | None = None) -> dict[str, Any]:
    with zipfile.ZipFile(path) as archive:
        names = archive.namelist()
        if len(names) != len(set(names)):
            raise ValueError("Duplicate entries in wheel")
        try:
            manifest = json.loads(archive.read("granum/_build.json"))
        except (KeyError, ValueError) as exc:
            raise ValueError("Wheel has no valid build provenance; rebuild it rather than reusing an old wheel") from exc
        if manifest.get("format_version") != 1 or (version and manifest.get("version") != version):
            raise ValueError("Wheel provenance or package version is incompatible")
        if revision and (manifest.get("source_revision") != revision or manifest.get("source_dirty") is not False):
            raise ValueError("Wheel does not match the clean release source revision")
        stamp = manifest.get("dashboard")
        if not stamp or "granum/service/static/index.html" not in names:
            raise ValueError("Desktop wheel requires a complete dashboard")
        backend, dashboard = [], []
        for name in names:
            if name.endswith("/") or not name.startswith("granum/") or "/__pycache__/" in name:
                continue
            relative = name.removeprefix("granum/")
            if relative.startswith("service/static/"):
                relative = relative.removeprefix("service/static/")
                if relative != "build-stamp.json":
                    dashboard.append((relative, archive.read(name)))
            elif relative != "_build.json":
                backend.append((relative, archive.read(name)))
        if digest(backend) != manifest["package_sha256"] or digest(dashboard) != stamp["bundle_sha256"]:
            raise ValueError("Wheel contents do not match the embedded build hashes")
        if json.loads(archive.read("granum/service/static/build-stamp.json")) != stamp:
            raise ValueError("Dashboard stamp does not match package provenance")
        return manifest