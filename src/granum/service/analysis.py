"""Analysis routes; object access always goes through the parent service's root checks."""
from __future__ import annotations

import hashlib
import json
import re
import shutil
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

from fastapi import HTTPException
from pydantic import BaseModel, Field

from granum.core import appdirs
from granum.reduction import Reducer, ReductionError, methods, reduce_run, reduce_table, values_from


class ProjectionRequest(BaseModel):
    url: str
    kind: Literal["table", "run"] = "table"
    column: str
    method: Literal["pca", "umap", "pacmap"] = "pca"
    dimensions: Literal[2, 3] = 2
    neighbours: int = Field(15, ge=2, le=200)
    seed: int = Field(0, ge=0, le=2**31 - 1)
    min_distance: float = Field(0.1, ge=0, le=1)
    prefix: str = Field("projection", pattern=r"^[A-Za-z][A-Za-z0-9_-]{0,63}$")
    reducer_id: str | None = Field(None, pattern=r"^[0-9a-f]{32}$")
    save_reducer_as: str | None = Field(None, min_length=1, max_length=80)


class ReducerStore:
    """Only models fitted by this service, scoped to its workspace and project.

    Clients address opaque IDs, never filesystem paths or uploaded Python state. The
    service's private state directory is trusted, just like its installed Python packages.
    """
    def __init__(self, workspace: str):
        self.root = appdirs.state_dir() / "reducers" / hashlib.sha256(workspace.encode()).hexdigest()

    def _project(self, project: str) -> Path:
        return self.root / hashlib.sha256(project.encode()).hexdigest()

    def _path(self, project: str, identifier: str) -> Path:
        if not re.fullmatch(r"[0-9a-f]{32}", identifier):
            raise ReductionError("invalid saved projection ID")
        return self._project(project) / identifier

    def list(self, project: str) -> list[dict[str, Any]]:
        result = []
        for path in self._project(project).glob("*/catalogue.json"):
            try:
                metadata = json.loads(path.read_text())
                if metadata["id"] == path.parent.name and metadata["project"] == project:
                    result.append(metadata)
            except (OSError, ValueError, KeyError, TypeError):
                continue
        return sorted(result, key=lambda record: record["created_at"], reverse=True)

    def load(self, project: str, identifier: str) -> Reducer:
        folder = self._path(project, identifier)
        try:
            metadata = json.loads((folder / "catalogue.json").read_text())
            if metadata["id"] != identifier or metadata["project"] != project:
                raise ReductionError("saved projection belongs to another project")
        except (OSError, ValueError, KeyError, TypeError) as exc:
            raise ReductionError("saved projection was not found in this project") from exc
        # These artifacts are fitted locally by save(); no API imports model files.
        return Reducer.load(folder, trusted=True)

    def save(self, project: str, reducer: Reducer, *, name: str, source_url: str, column: str) -> dict[str, Any]:
        identifier = uuid.uuid4().hex
        target = self._path(project, identifier)
        metadata = {"id": identifier, "project": project, "name": name.strip(),
                    "created_at": datetime.now(timezone.utc).isoformat(),
                    "source_url": source_url, "column": column,
                    "features": int(reducer.reference.shape[1]),
                    "reference_samples": len(reducer.reference), **reducer.manifest()}
        try:
            reducer.save(target)
            temporary = target / ".catalogue.tmp"
            temporary.write_text(json.dumps(metadata, indent=2))
            temporary.replace(target / "catalogue.json")
        except Exception:
            shutil.rmtree(target, ignore_errors=True)
            raise
        return metadata


def register_analysis(app: Any, *, table_at: Any, run_at: Any, jobs: Any, index: Any, config: Any) -> None:
    saved = ReducerStore(str(config.project_root))

    @app.get("/api/analysis/methods")
    def reduction_methods() -> list[dict[str, Any]]:
        return methods()

    @app.get("/api/analysis/reducers")
    def saved_reducers(url: str, kind: Literal["table", "run"] = "table") -> list[dict[str, Any]]:
        source = run_at(url) if kind == "run" else table_at(url)
        return saved.list(source.project_name)

    @app.post("/api/analysis/project")
    def project(request: ProjectionRequest) -> dict[str, Any]:
        source = run_at(request.url) if request.kind == "run" else table_at(request.url)
        tables = source.metrics_tables() if request.kind == "run" else [source]
        selected = [table for table in tables if request.column in table.schema]
        if not selected or any(table.schema[request.column].kind != "embedding" for table in selected):
            raise HTTPException(400, "Choose an embedding column")
        if sum(table.row_count for table in selected) > 250_000:
            raise HTTPException(413, "This projection exceeds the 250,000-row workspace budget; use the Python SDK")
        if request.save_reducer_as is not None and not request.save_reducer_as.strip():
            raise HTTPException(400, "Give the saved projection a name")
        if request.reducer_id and request.save_reducer_as:
            raise HTTPException(400, "A reused projection is already saved")
        if not request.reducer_id and not next(m["installed"] for m in methods() if m["id"] == request.method):
            raise HTTPException(400, f"Install granum[reduction] to use {request.method}")

        def work(job: Any) -> dict[str, Any]:
            reducer = saved.load(source.project_name, request.reducer_id) if request.reducer_id else Reducer(
                request.method, dimensions=request.dimensions, neighbours=request.neighbours,
                seed=request.seed, min_distance=request.min_distance,
            )
            if request.kind == "run":
                result = reduce_run(source, request.column, reducer=reducer, prefix=request.prefix, config=config,
                                    cancelled=job.cancel.is_set, progress=job.progress)
            else:
                job.progress("Reusing saved projection" if request.reducer_id else "Fitting projection", 0, 1)
                if reducer.reference is None:
                    reducer.fit_transform(values_from(source, request.column))
                if job.cancel.is_set():
                    raise ReductionError("projection cancelled")
                result = reduce_table(source, request.column, reducer=reducer, prefix=request.prefix)
                job.progress("Projection saved", 1, 1)
            record = None
            if request.save_reducer_as:
                record = saved.save(source.project_name, reducer, name=request.save_reducer_as,
                                    source_url=request.url, column=request.column)
            index.refresh(force=True)
            return {"url": str(result.url), "name": result.name, "kind": request.kind, "project": result.project_name,
                    "axes": [f"{request.prefix}_{axis}" for axis in "xyz"[:reducer.dimensions]],
                    "projection": reducer.manifest(), "reducer_id": record["id"] if record else request.reducer_id}

        return jobs.start("projection", work).to_dict()
