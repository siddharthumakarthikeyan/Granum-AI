"""Renaming a project.

Granum records locations as absolute paths: a version names its parents, a run names the
table its metrics join to, review logs and shipments name the versions they refer to, and
the removed and isolated sets record the version each image came from. Renaming the
project folder alone would break all of those links, so a rename rewrites every one.

The rename is planned completely before anything changes: every file that mentions the
project is read and rewritten in memory. Only then is the folder moved and the rewritten
files written, each atomically. If a write fails, the files already written are restored
and the folder is moved back, so a project is never left half renamed.

Image files live outside projects and are never touched; training output is keyed by run
name, not by project, so it needs no change either.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path

import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.parquet as pq

from granum.core.layout import ProjectLayout, sanitize
from granum.core.url import Url
from granum.errors import GranumError

MAX_NAME = 80
_TEXT_SUFFIXES = {".json", ".jsonl", ".yaml", ".yml"}


class ProjectError(GranumError):
    """A project could not be renamed."""


def check_name(name: str) -> str:
    """A valid new project name, or a ProjectError saying what is wrong with it."""
    name = (name or "").strip()
    if not name:
        raise ProjectError("a project needs a name")
    if len(name) > MAX_NAME:
        raise ProjectError(f"project names are at most {MAX_NAME} characters")
    try:
        cleaned = sanitize(name)
    except ValueError as exc:
        raise ProjectError(str(exc)) from exc
    if cleaned != name:
        raise ProjectError("project names may use letters, numbers, spaces, dots, dashes and underscores, "
                           "and cannot start or end with a space, dot or dash")
    return name


@dataclass
class _Change:
    relative: Path
    kind: str  # "text" or "parquet"
    before: str | pa.Table
    after: str | pa.Table


def _rewrite_text(text: str, old_prefix: str, new_prefix: str, old: str, new: str) -> str:
    # A path is the prefix followed by "/" or the end of the string; "projects/aerial" must not
    # match inside "projects/aerial2".
    text = re.sub(re.escape(old_prefix) + r'(?=[/"\n]|$)', new_prefix.replace("\\", "\\\\"), text)
    text = re.sub(r'("project_name"\s*:\s*)"' + re.escape(old) + '"', lambda m: m.group(1) + '"' + new + '"', text)
    return text


def _rewrite_parquet(table: pa.Table, old_prefix: str, new_prefix: str) -> pa.Table | None:
    changed = False
    columns = []
    for column in table.columns:
        if pa.types.is_string(column.type) or pa.types.is_large_string(column.type):
            if pc.any(pc.starts_with(column, old_prefix + "/")).as_py():
                column = pc.replace_substring_regex(column, "^" + re.escape(old_prefix) + "/", new_prefix + "/")
                changed = True
        columns.append(column)
    if not changed:
        return None
    return pa.Table.from_arrays(columns, schema=table.schema)


def _write_atomic(path: Path, content: str | pa.Table) -> None:
    temporary = path.with_name(path.name + ".renaming")
    if isinstance(content, str):
        temporary.write_text(content)
    else:
        pq.write_table(content, temporary)
    os.replace(temporary, path)


def rename_project(project_root: Url | str, old: str, new: str) -> dict[str, object]:
    """Rename project ``old`` to ``new`` under a local project root."""
    new = check_name(new)
    root = Url(project_root)
    if root.scheme != "file":
        raise ProjectError("projects can only be renamed on a local disk")
    layout = ProjectLayout(root)
    source = Path(layout.project(old).path)
    target = Path(layout.project(new).path)
    if new == old:
        raise ProjectError("the new name is the same as the current one")
    if not source.is_dir():
        raise ProjectError(f"no project named {old!r}")
    if target.exists() or (target.parent.is_dir() and any(p.name.lower() == new.lower() for p in target.parent.iterdir())):
        raise ProjectError(f"a project named {new!r} already exists")

    old_prefix, new_prefix = str(source), str(target)
    changes: list[_Change] = []
    for path in sorted(source.rglob("*")):
        if not path.is_file() or path.name.endswith(".renaming"):
            continue
        relative = path.relative_to(source)
        if path.suffix in _TEXT_SUFFIXES:
            try:
                before = path.read_text()
            except UnicodeDecodeError:
                continue
            after = _rewrite_text(before, old_prefix, new_prefix, old, new)
            if after != before:
                changes.append(_Change(relative, "text", before, after))
        elif path.suffix == ".parquet":
            before_table = pq.read_table(path)
            after_table = _rewrite_parquet(before_table, old_prefix, new_prefix)
            if after_table is not None:
                changes.append(_Change(relative, "parquet", before_table, after_table))

    os.rename(source, target)
    written: list[_Change] = []
    try:
        for change in changes:
            _write_atomic(target / change.relative, change.after)
            written.append(change)
    except Exception as exc:
        for change in written:
            try:
                _write_atomic(target / change.relative, change.before)
            except OSError:
                pass
        os.rename(target, source)
        raise ProjectError(f"renaming failed and was undone: {exc}") from exc

    # The index markers above the project changed; touching them makes every scanner re-read.
    for marker in (target.parent / "index.granum.json", target.parent.parent / "index.granum.json"):
        if marker.exists():
            os.utime(marker)
    return {"old": old, "new": new, "files_updated": len(changes)}
