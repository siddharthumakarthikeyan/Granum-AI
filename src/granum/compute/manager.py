"""Local compute environments, pinned catalogues and checked immutable results.

Plugins are trusted Python code with the service user's permissions. A virtualenv
isolates dependencies; it is not a filesystem or network security sandbox.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urljoin, urlsplit
from urllib.request import urlopen

import pyarrow as pa
from filelock import FileLock, Timeout

from granum.core import appdirs
from granum.core.objects.table import Table
from granum.core.schemas import BoolSchema, Float32Schema, Int64Schema, StringSchema
from granum.processes import console_python, no_window

from .contracts import ANNOTATIONS, Catalogue, Manifest, PluginError
from .sdk_wheel import build_sdk_wheel

MAX_BYTES = 64 * 1024 * 1024
MAX_ROWS = 100_000


def digest(path: Path) -> str:
    result = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            result.update(chunk)
    return result.hexdigest()


def atomic_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent, delete=False) as stream:
        temporary = Path(stream.name)
        try:
            json.dump(value, stream, allow_nan=False)
        except Exception:
            temporary.unlink(missing_ok=True)
            raise
    try:
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def _read(source: str, maximum: int) -> bytes:
    parsed = urlsplit(source)
    if parsed.scheme == "https":
        with urlopen(source, timeout=30) as response:
            if urlsplit(response.geturl()).scheme != "https":
                raise PluginError("Catalogue downloads must stay on HTTPS")
            data = response.read(maximum + 1)
    elif parsed.scheme == "file":
        if parsed.netloc not in ("", "localhost"):
            raise PluginError("Use a local file URL")
        with Path(unquote(parsed.path)).open("rb") as stream:
            data = stream.read(maximum + 1)
    elif Path(source).is_absolute():
        with Path(source).open("rb") as stream:
            data = stream.read(maximum + 1)
    else:
        raise PluginError("Configure an absolute local catalogue path or HTTPS URL")
    if len(data) > maximum:
        raise PluginError("Catalogue or wheel exceeds its download budget")
    return data


def _python(environment: Path) -> Path:
    return environment / ("Scripts/python.exe" if os.name == "nt" else "bin/python")


def _process(command: list[str], *, cwd: Path, job: Any, timeout: float = 3600) -> None:
    """Drain output continuously; poll cancellation even when the child prints nothing."""
    environment = {key: value for key, value in os.environ.items() if key not in {"PYTHONPATH", "PYTHONHOME", "VIRTUAL_ENV"}}
    options = no_window() if os.name == "nt" else {"start_new_session": True}
    process = subprocess.Popen(command, cwd=cwd, env=environment, stdin=subprocess.DEVNULL,
                               stdout=subprocess.PIPE, stderr=subprocess.STDOUT, **options)

    def read() -> None:
        assert process.stdout is not None
        for raw in iter(lambda: process.stdout.readline(8192), b""):
            line = raw.decode("utf-8", errors="replace").strip()[:2000]
            if line.startswith("GRANUM_PROGRESS "):
                try:
                    progress = json.loads(line.removeprefix("GRANUM_PROGRESS "))
                    done, total = progress["done"], progress["total"]
                    if type(done) is int and type(total) is int and 0 <= done <= total:
                        job.progress(str(progress["phase"])[:200], done, total)
                        continue
                except (ValueError, KeyError, TypeError):
                    pass
            if line:
                job.log.append(line)

    reader = threading.Thread(target=read, daemon=True)
    reader.start()
    deadline = time.monotonic() + timeout
    try:
        while process.poll() is None:
            if job.cancel.wait(.1) or time.monotonic() > deadline:
                from granum.service.trainers import terminate

                terminate(process.pid, wait=1)
                process.wait(timeout=10)
                raise PluginError("Plugin job cancelled" if job.cancel.is_set() else "Plugin process exceeded its time limit")
        reader.join(timeout=2)
        if process.returncode:
            raise PluginError(f"Plugin process failed (exit {process.returncode}); see its log")
        if job.cancel.is_set():
            raise PluginError("Plugin job cancelled")
    finally:
        if process.stdout is not None:
            process.stdout.close()


class PluginManager:
    def __init__(self, workspace: str, *, root: Path | None = None, catalogues: list[str] | None = None):
        self.root = root or appdirs.data_dir() / "compute" / hashlib.sha256(workspace.encode()).hexdigest()
        self.catalogues = list(catalogues if catalogues is not None else filter(None, os.environ.get("GRANUM_COMPUTE_CATALOGS", "").split(",")))
        self.root.mkdir(parents=True, exist_ok=True)
        self._catalogue_lock = threading.Lock()
        self._catalogue_cache: tuple[float, dict[str, Any]] | None = None

    @contextmanager
    def locked(self, identifier: str):
        if not re.fullmatch(r"[a-z][a-z0-9-]{0,63}", identifier):
            raise PluginError("Invalid plugin ID")
        try:
            with FileLock(self.root / f"{identifier}.lock", timeout=0):
                yield
        except Timeout as exc:
            raise PluginError("This plugin has another operation running; finish or cancel it first") from exc

    def catalogue(self, *, refresh: bool = False) -> dict[str, Any]:
        with self._catalogue_lock:
            if not refresh and self._catalogue_cache and time.monotonic() - self._catalogue_cache[0] < 60:
                return self._catalogue_cache[1]
            records, errors, ambiguous = {}, [], set()
            sources = [("bundled", Catalogue(plugins=[ANNOTATIONS]))]
            for location in self.catalogues:
                try:
                    catalogue = Catalogue.model_validate_json(_read(location, 1024 * 1024))
                    for manifest in catalogue.plugins:
                        if manifest.id == ANNOTATIONS.id or not manifest.wheels:
                            raise PluginError("External plugins need pinned wheels and cannot replace bundled plugin IDs")
                        for wheel in manifest.wheels:
                            if urlsplit(location).scheme == "https":
                                wheel.url = urljoin(location, wheel.url)
                                if urlsplit(wheel.url).scheme != "https":
                                    raise PluginError("Remote catalogues must use HTTPS wheels")
                            elif not urlsplit(wheel.url).scheme and not Path(wheel.url).is_absolute():
                                parent = Path(unquote(urlsplit(location).path)) if location.startswith("file:") else Path(location)
                                wheel.url = str((parent.parent / wheel.url).resolve())
                    sources.append((location, catalogue))
                except (OSError, ValueError, PluginError) as exc:
                    errors.append({"source": location, "error": str(exc)})
            for location, catalogue in sources:
                for manifest in catalogue.plugins:
                    revision = hashlib.sha256(json.dumps(manifest.model_dump(), sort_keys=True).encode()).hexdigest()
                    if manifest.id in records:
                        ambiguous.add(manifest.id)
                        errors.append({"source": location, "error": f"Duplicate plugin ID: {manifest.id}; installation disabled"})
                    records[manifest.id] = {**manifest.model_dump(), "source": location, "revision": revision}
            for identifier in ambiguous:
                records.pop(identifier, None)
            result = {"plugins": list(records.values()), "errors": errors}
            self._catalogue_cache = (time.monotonic(), result)
            return result

    def available(self, identifier: str, revision: str) -> dict[str, Any]:
        found = next((record for record in self.catalogue()["plugins"] if record["id"] == identifier), None)
        if not found or found["revision"] != revision:
            raise PluginError("The catalogue changed or this plugin is unavailable; refresh before installing")
        return found

    def installed(self, identifier: str) -> dict[str, Any]:
        if not re.fullmatch(r"[a-z][a-z0-9-]{0,63}", identifier):
            raise PluginError("Invalid plugin ID")
        try:
            record = json.loads((self.root / "installed" / f"{identifier}.json").read_text())
            if record["manifest"]["id"] != identifier or not re.fullmatch(r"[a-f0-9]{32}", record["environment"]):
                raise ValueError("invalid environment record")
            Manifest.model_validate(record["manifest"])
            return record
        except (OSError, ValueError, KeyError, TypeError) as exc:
            raise PluginError("Plugin is not installed or its record is damaged") from exc

    def list_installed(self) -> list[dict[str, Any]]:
        records = []
        for path in sorted((self.root / "installed").glob("*.json")):
            try:
                record = self.installed(path.stem)
                record["health"] = "ready" if _python(self.root / "environments" / record["environment"]).exists() else "missing environment"
                records.append(record)
            except PluginError:
                records.append({"id": path.stem, "health": "damaged record"})
        return records

    def install(self, identifier: str, revision: str, job: Any) -> dict[str, Any]:
        import uuid

        with self.locked(identifier):
            selected = self.available(identifier, revision)
            manifest = Manifest.model_validate({key: selected[key] for key in Manifest.model_fields})
            old = None
            if (self.root / "installed" / f"{identifier}.json").exists():
                old = self.installed(identifier)
            environment = self.root / "environments" / uuid.uuid4().hex
            environment.parent.mkdir(parents=True, exist_ok=True)
            try:
                with tempfile.TemporaryDirectory(dir=self.root, prefix="install-") as temporary:
                    stage = Path(temporary)
                    sdk = build_sdk_wheel(stage)
                    wheels = [sdk]
                    for wheel in manifest.wheels:
                        job.progress("Downloading pinned wheels", len(wheels) - 1, len(manifest.wheels))
                        if job.cancel.is_set():
                            raise PluginError("Plugin job cancelled")
                        name = Path(unquote(urlsplit(wheel.url).path)).name
                        if not re.fullmatch(r"[A-Za-z0-9_.+!-]+\.whl", name) or name in {path.name for path in wheels}:
                            raise PluginError("Use distinct Python wheel filenames")
                        path = stage / name
                        path.write_bytes(_read(wheel.url, 512 * 1024 * 1024))
                        if digest(path) != wheel.sha256:
                            raise PluginError(f"Checksum mismatch for {name}")
                        wheels.append(path)
                    job.progress("Creating isolated environment", 0, 1)
                    _process([console_python(sys.executable), "-I", "-m", "venv", str(environment)], cwd=stage, job=job, timeout=300)
                    python = str(_python(environment))
                    job.progress("Installing pinned wheels", 0, 1)
                    _process([python, "-I", "-m", "pip", "--isolated", "install", "--no-input", "--disable-pip-version-check", "--no-index", "--no-deps", *map(str, wheels)], cwd=stage, job=job, timeout=900)
                    _process([python, "-I", "-m", "pip", "--isolated", "check"], cwd=stage, job=job, timeout=60)
                    _process([python, "-I", "-m", "granum_compute_sdk.worker", "--check", manifest.entrypoint], cwd=stage, job=job, timeout=60)
                    record = {"manifest": manifest.model_dump(), "revision": revision, "source": selected["source"],
                              "environment": environment.name, "installed_at": time.time(), "python": sys.version.split()[0],
                              "sdk_sha256": digest(sdk), "health": "ready"}
                    atomic_json(self.root / "installed" / f"{identifier}.json", record)
            except Exception:
                shutil.rmtree(environment, ignore_errors=True)
                raise
            if old:
                shutil.rmtree(self.root / "environments" / old["environment"], ignore_errors=True)
            return {"plugin": identifier, "version": manifest.version, "environment": environment.name}

    def uninstall(self, identifier: str, job: Any) -> dict[str, Any]:
        with self.locked(identifier):
            record = self.installed(identifier)
            if job.cancel.is_set():
                raise PluginError("Plugin job cancelled")
            (self.root / "installed" / f"{identifier}.json").unlink()
            shutil.rmtree(self.root / "environments" / record["environment"], ignore_errors=True)
            return {"plugin": identifier, "uninstalled": True}

    def check(self, identifier: str, job: Any) -> dict[str, Any]:
        with self.locked(identifier):
            record = self.installed(identifier)
            environment = self.root / "environments" / record["environment"]
            _process([str(_python(environment)), "-I", "-m", "pip", "--isolated", "check"], cwd=self.root, job=job, timeout=60)
            _process([str(_python(environment)), "-I", "-m", "granum_compute_sdk.worker", "--check", record["manifest"]["entrypoint"]], cwd=self.root, job=job, timeout=60)
            return {"plugin": identifier, "health": "ready"}

    def preflight(self, identifier: str, table: Table, inputs: dict[str, str], parameters: dict[str, Any], prefix: str) -> tuple[Manifest, dict[str, Any]]:
        manifest = Manifest.model_validate(self.installed(identifier)["manifest"])
        if table.type_name != "table" or not 0 < table.row_count <= MAX_ROWS:
            raise PluginError(f"Choose a dataset table with 1–{MAX_ROWS:,} rows")
        if set(inputs) != set(manifest.inputs) or any(name not in table.schema or table.schema[name].kind not in manifest.inputs[key] for key, name in inputs.items()):
            raise PluginError("Map every plugin input to a column of the supported kind")
        if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]{0,31}", prefix):
            raise PluginError("Use a simple output prefix of at most 32 characters")
        if any(f"{prefix}_{name}" in table.schema for name in manifest.outputs):
            raise PluginError("Output columns already exist; choose a different prefix")
        return manifest, manifest.values(parameters)

    def run(self, identifier: str, table: Table, inputs: dict[str, str], parameters: dict[str, Any], prefix: str, job: Any) -> dict[str, Any]:
        with self.locked(identifier):
            manifest, parameters = self.preflight(identifier, table, inputs, parameters, prefix)
            record = self.installed(identifier)
            selected = table.to_arrow().select(list(dict.fromkeys(inputs.values())))
            if selected.nbytes > MAX_BYTES:
                raise PluginError("Plugin input exceeds the 64 MiB budget; choose a smaller table")
            columns = selected.to_pydict()
            payload = {"entrypoint": manifest.entrypoint, "parameters": parameters,
                       "source": {"url": str(table.url), "project": table.project_name,
                                  "schema": {alias: table.schema[name].to_dict() for alias, name in inputs.items()}},
                       "samples": [{"id": i, "values": {alias: columns[name][i] for alias, name in inputs.items()}} for i in range(table.row_count)]}
            with tempfile.TemporaryDirectory(dir=self.root, prefix="run-") as temporary:
                stage = Path(temporary)
                request, output = stage / "input.json", stage / "output.json"
                atomic_json(request, payload)
                if request.stat().st_size > MAX_BYTES:
                    raise PluginError("Serialized plugin input exceeds the 64 MiB budget")
                job.progress("Computing", 0, table.row_count)
                _process([str(_python(self.root / "environments" / record["environment"])), "-I", "-m", "granum_compute_sdk.worker", str(request), str(output)], cwd=stage, job=job)
                if not output.exists() or output.stat().st_size > MAX_BYTES:
                    raise PluginError("Plugin output is missing or exceeds the 64 MiB budget")
                try:
                    result = json.loads(output.read_text())
                    values, summary = validate_result(manifest, table.row_count, result)
                except (ValueError, TypeError, KeyError) as exc:
                    raise PluginError(f"Invalid plugin result: {exc}") from exc
                provenance = {"plugin": identifier, "version": manifest.version, "revision": record["revision"],
                              "source": str(table.url), "catalogue": record["source"], "environment": record["environment"],
                              "python": record["python"], "sdk_sha256": record["sdk_sha256"],
                              "parameters": parameters, "inputs": inputs, "prefix": prefix,
                              "input_sha256": digest(request), "output_sha256": digest(output), "summary": summary}
                arrow, schema = table.to_arrow(), table.schema
                kinds = {"integer": Int64Schema, "number": Float32Schema, "boolean": BoolSchema, "string": StringSchema}
                for key, kind in manifest.outputs.items():
                    column_schema = kinds[kind](writable=False)
                    name = f"{prefix}_{key}"
                    arrow = arrow.append_column(name, pa.array(values[key], type=column_schema.arrow_type()))
                    schema = schema.with_column(name, column_schema)
                if job.cancel.is_set():
                    raise PluginError("Plugin job cancelled")
                derived = table._derive(arrow=arrow, schema=schema, op="compute_plugin", args=provenance)
                job.progress("Saved dataset version", table.row_count, table.row_count)
                return {"url": str(derived.url), "project": derived.project_name, "name": derived.name,
                        "columns": [f"{prefix}_{key}" for key in manifest.outputs], "summary": summary}


def validate_result(manifest: Manifest, count: int, result: Any) -> tuple[dict[str, list[Any]], dict[str, Any]]:
    if not isinstance(result, dict) or set(result) != {"sample_ids", "columns", "summary"}:
        raise PluginError("Plugin result must contain sample_ids, columns and summary")
    ids = result["sample_ids"]
    if not isinstance(ids, list) or len(ids) != count or any(type(i) is not int for i in ids) or set(ids) != set(range(count)):
        raise PluginError("Plugin must return each source sample ID exactly once")
    columns, summary = result["columns"], result["summary"]
    if not isinstance(columns, dict) or set(columns) != set(manifest.outputs):
        raise PluginError("Plugin output columns differ from its manifest")
    if not isinstance(summary, dict) or len(json.dumps(summary, allow_nan=False)) > 64 * 1024:
        raise PluginError("Plugin summary must be a JSON object under 64 KiB")
    order = sorted(range(count), key=ids.__getitem__)
    values = {}
    for key, kind in manifest.outputs.items():
        data = columns[key]
        if not isinstance(data, list) or len(data) != count:
            raise PluginError(f"Wrong output length for {key}")
        for value in data:
            valid = (type(value) is int and -(2**63) <= value < 2**63 if kind == "integer" else
                     type(value) in (int, float) and math.isfinite(value) and abs(value) <= 3.4028234663852886e38 if kind == "number" else
                     type(value) is bool if kind == "boolean" else isinstance(value, str) and len(value) <= 10000)
            if not valid:
                raise PluginError(f"Invalid {kind} value in output {key}")
        values[key] = [data[index] for index in order]
    return values, summary
