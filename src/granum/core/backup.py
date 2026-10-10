"""Portable, checksummed local project snapshots with non-overwriting restore.

Snapshots include referenced media and known model weights, not environments or shared
access credentials. Restoration validates the entire archive before publishing a project.
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import stat
import tempfile
import zipfile
from pathlib import Path, PurePosixPath
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq

from granum import __version__
from granum.core.integrity import file_digest, media_manifest
from granum.core.layout import OBJECT_FILENAME, ProjectLayout
from granum.core.objects.base import read_object_payload, touch_index_markers, utcnow
from granum.core.objects.table import Table
from granum.core.projects import check_name
from granum.core.storage import fsync_directory, locked, workspace_lock
from granum.core.url import Url, get_registered_url_aliases
from granum.errors import GranumError

MAX_FILES = 200_000
MAX_MANIFEST = 32 * 1024 * 1024
DEFAULT_MAX_BYTES = 100 * 1024**3


class BackupError(GranumError):
    pass


def _files(folder: Path) -> list[Path]:
    result = []
    for path in folder.rglob("*"):
        if any(p.startswith(".granum-") for p in path.relative_to(folder).parts) or path.name.endswith(".granum-lock"):
            continue
        if path.is_symlink():
            raise BackupError(f"project contains a symlink; materialize it before backup: {path}")
        if path.is_file() and path.name != "index.granum.json":
            result.append(path)
    return sorted(result)


def _stamp(path: Path) -> tuple[int, int, int]:
    s = path.stat()
    return s.st_size, s.st_mtime_ns, s.st_ino


@workspace_lock()
def backup_project(project: str, output: Path, *, root: Url) -> dict[str, Any]:
    if root.scheme != "file":
        raise BackupError("portable snapshots currently require a local project root")
    source = Path(ProjectLayout(root).project(project).path).resolve()
    output = output.resolve()
    if not source.is_dir():
        raise BackupError("project does not exist")
    if output.exists() or output.is_relative_to(source):
        raise BackupError("choose a new backup path outside the project; existing archives are never overwritten")
    files = _files(source)
    before = {p: _stamp(p) for p in files}
    tables = []
    artifacts = set()
    for path in files:
        if path.name != OBJECT_FILENAME:
            continue
        payload = read_object_payload(Url(path.parent))
        if payload.get("type") == "table":
            tables.append(Table.from_url(path.parent))
        for parent in [*payload.get("parents", []), *([payload["foreign_table_url"]] if payload.get("foreign_table_url") else [])]:
            ref = Url(parent)
            if ref.scheme != "file" or not Path(ref.path).resolve().is_relative_to(source):
                raise BackupError(f"project has an external table dependency ({parent}); snapshot it together with its source project before migration")
        weights = payload.get("parameters", {}).get("weights")
        if weights:
            artifacts.add(str(weights))
    media = media_manifest(tables)["files"]
    for artifact in artifacts:
        media.setdefault(artifact, file_digest(artifact))
    mappings: dict[str, str] = {}
    entries: dict[str, Path] = {"project/" + p.relative_to(source).as_posix(): p for p in files}
    for reference, digest in media.items():
        url = Url(reference)
        if url.scheme != "file":
            raise BackupError("materialize cloud media locally before making a portable snapshot")
        path = Path(url.path).resolve()
        if path.is_relative_to(source):
            archive_name = "project/" + path.relative_to(source).as_posix()
        else:
            archive_name = "media/" + digest["sha256"] + path.suffix.lower()
        entries[archive_name] = path
        mappings[reference] = archive_name
        mappings[str(url.resolved)] = archive_name
    if len(entries) > MAX_FILES:
        raise BackupError(f"snapshot exceeds {MAX_FILES:,} files; split the project")
    output.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=".granum-backup-", dir=output.parent)
    os.close(fd)
    manifest: dict[str, Any] = {"format_version": 1, "granum_version": __version__, "created": utcnow(),
                               "project": project, "source_project": source.as_posix(), "media": mappings,
                               "aliases": get_registered_url_aliases(), "files": {}}
    try:
        with zipfile.ZipFile(temporary, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=1, allowZip64=True) as archive:
            for name, path in entries.items():
                before_file = _stamp(path)
                digest = hashlib.sha256()
                size = 0
                with path.open("rb") as reader, archive.open(name, "w", force_zip64=True) as writer:
                    while chunk := reader.read(1024 * 1024):
                        writer.write(chunk)
                        digest.update(chunk)
                        size += len(chunk)
                if _stamp(path) != before_file:
                    raise BackupError(f"file changed during backup: {path}; stop writers and retry")
                manifest["files"][name] = {"sha256": digest.hexdigest(), "bytes": size}
            for reference, expected in media.items():
                if manifest["files"][mappings[reference]] != expected:
                    raise BackupError(f"media changed during backup: {reference}")
            if before != {p: _stamp(p) for p in _files(source)}:
                raise BackupError("project changed during backup; stop writers and retry")
            manifest_bytes = json.dumps(manifest, sort_keys=True).encode()
            if len(manifest_bytes) > MAX_MANIFEST:
                raise BackupError("snapshot manifest exceeds the supported size; split the project")
            archive.writestr("manifest.json", manifest_bytes)
        # Opened for writing: Windows refuses to flush a handle that is read-only.
        with open(temporary, "r+b") as handle:
            os.fsync(handle.fileno())
        # A hard-link publishes without replacing a concurrently created archive.
        os.link(temporary, output)
        fsync_directory(output.parent)
    finally:
        Path(temporary).unlink(missing_ok=True)
    return {"archive": str(output), "files": len(entries), "media": len(media), **file_digest(str(output))}


def _safe_name(name: str) -> bool:
    parts = PurePosixPath(name).parts
    return bool(parts and not name.startswith("/") and "\\" not in name and all(
        p not in {".", ".."} and ":" not in p and not p.endswith((" ", ".")) for p in parts
    ) and parts[0] in {"project", "media"})


def restore_project(archive_path: Path, *, root: Url, name: str | None = None, max_bytes: int = DEFAULT_MAX_BYTES) -> dict[str, Any]:
    if root.scheme != "file":
        raise BackupError("restore currently requires a local project root")
    with zipfile.ZipFile(archive_path) as archive:
        info = archive.getinfo("manifest.json")
        if info.file_size > MAX_MANIFEST:
            raise BackupError("backup manifest is too large")
        manifest = json.loads(archive.read(info))
        if manifest.get("format_version") != 1:
            raise BackupError("unsupported backup format; upgrade Granum first")
        files = manifest.get("files", {})
        names = archive.namelist()
        if len(names) != len(set(names)) or set(names) != {*files, "manifest.json"} or len(files) > MAX_FILES:
            raise BackupError("archive entries are duplicate, missing, or not declared in the manifest")
        if len({n.casefold() for n in files}) != len(files) or any(not _safe_name(n) for n in files):
            raise BackupError("unsafe or ambiguous archive path")
        if sum(archive.getinfo(n).file_size for n in files) > max_bytes:
            raise BackupError("archive exceeds the restore size limit")
        project = check_name(name or manifest["project"])
        target = Path(ProjectLayout(root).project(project).path)
        if target.exists():
            raise BackupError("restore never overwrites an existing project; choose a new name")
        target.parent.mkdir(parents=True, exist_ok=True)
        stage = Path(tempfile.mkdtemp(prefix=".granum-restore-", dir=target.parent))
        try:
            total = 0
            for member, expected in files.items():
                item = archive.getinfo(member)
                if item.is_dir() or stat.S_ISLNK(item.external_attr >> 16):
                    raise BackupError("archive must contain regular files only")
                destination = stage / member
                destination.parent.mkdir(parents=True, exist_ok=True)
                digest = hashlib.sha256()
                size = 0
                with archive.open(item) as reader, destination.open("xb") as writer:
                    while chunk := reader.read(1024 * 1024):
                        total += len(chunk)
                        size += len(chunk)
                        if total > max_bytes or size > expected["bytes"]:
                            raise BackupError("expanded archive exceeds its declared size")
                        writer.write(chunk)
                        digest.update(chunk)
                    writer.flush()
                    os.fsync(writer.fileno())
                if {"sha256": digest.hexdigest(), "bytes": size} != expected:
                    raise BackupError(f"checksum mismatch: {member}")

            source_prefix = manifest["source_project"]
            new_prefix = target.as_posix()
            media_map = {ref: new_prefix + "/" + ("restored-media/" + PurePosixPath(member).name if member.startswith("media/") else member[8:])
                         for ref, member in manifest["media"].items()}

            def rewrite(value: Any) -> Any:
                if isinstance(value, dict):
                    return {rewrite(k): project if k == "project_name" and v == manifest["project"] else rewrite(v) for k, v in value.items()}
                if isinstance(value, list):
                    return [rewrite(v) for v in value]
                if not isinstance(value, str):
                    return value
                expanded = value
                for alias, location in manifest.get("aliases", {}).items():
                    if expanded.startswith(alias):
                        expanded = location + expanded[len(alias):]
                if expanded in media_map:
                    return media_map[expanded]
                if expanded == source_prefix or expanded.startswith(source_prefix + "/"):
                    return new_prefix + expanded[len(source_prefix):]
                return value

            project_stage = stage / "project"
            if not project_stage.is_dir():
                raise BackupError("snapshot contains no project")
            if (stage / "media").exists():
                if (project_stage / "restored-media").exists():
                    raise BackupError("snapshot conflicts with the reserved restored-media directory")
                os.rename(stage / "media", project_stage / "restored-media")
            for path in _files(project_stage):
                if path.suffix == ".json":
                    data = json.loads(path.read_text())
                    if path.name == OBJECT_FILENAME and data.get("format_version", 1) != 1:
                        raise BackupError("snapshot contains a newer object format")
                    Url(path).write_text(json.dumps(rewrite(data), indent=2))
                elif path.suffix == ".jsonl":
                    rows = [rewrite(json.loads(line)) for line in path.read_text().splitlines() if line]
                    Url(path).write_text("".join(json.dumps(row) + "\n" for row in rows))
                elif path.suffix == ".parquet":
                    table = pq.read_table(path)
                    rows = [rewrite(row) for row in table.to_pylist()]
                    pq.write_table(pa.Table.from_pylist(rows, schema=table.schema), path)
                    with path.open("r+b") as handle:
                        os.fsync(handle.fileno())
            # Persist every extracted directory entry, including binary-only media folders,
            # before making the restored project visible through one final rename.
            directories = [p for p in project_stage.rglob("*") if p.is_dir()]
            for directory in sorted(directories, key=lambda p: len(p.parts), reverse=True):
                fsync_directory(directory)
            fsync_directory(project_stage)
            with locked(root / ".granum-workspace"):
                if target.exists():
                    raise BackupError("target project was created during restore; nothing was overwritten")
                os.rename(project_stage, target)
                fsync_directory(target.parent)
                touch_index_markers(Url(target), stop_at=root)
        finally:
            shutil.rmtree(stage, ignore_errors=True)
    return {"project": project, "url": str(Url(target)), "files": len(files), "verified": True}