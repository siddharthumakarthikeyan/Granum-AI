"""The Object Service: a REST API over indexed Granum objects.

This is the bridge the dashboard reads through. It runs on the user's own machine and
reads their data locally -- nothing here uploads anything, which is the whole reason the
architecture is split this way.

Two rules worth stating plainly.

Every URL arriving from a client is checked before it is opened: object URLs must sit
under a scan root, media must be referenced by an indexed Table (or by a preflight the
user is running), and import sources must sit under a configured data root. Without
that, ``/api/media?url=/etc/passwd`` turns a local dashboard into a file-exfiltration
endpoint.

A service on 127.0.0.1 is still reachable from any web page the user has open. So
requests must name an allowed host (defeating DNS rebinding), cross-origin requests from
origins not explicitly allowed are refused, and writes must be JSON, which a page cannot
send cross-origin without a preflight this service never approves.
"""

from __future__ import annotations

import io
import json
import mimetypes
import os
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import pyarrow as pa
from fastapi import Body, FastAPI, HTTPException, Query, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, Field

from granum import __version__
from granum.core.config import Config, get_config
from granum.core.index import Index, get_index
from granum.core.layout import ProjectLayout
from granum.core.objects.run import MetricsTable, Run
from granum.core.objects.table import ROW_PRESERVING_OPS, Table
from granum.core.schemas import CategoricalLabelSchema, Geometry2DSchema, ImageSchema, Schema
from granum.core.url import Url
from granum.errors import GranumError
from granum.service import thumbnails as thumbs
from granum.service.cache import ByteCache
from granum.service.jobs import JobRegistry

MAX_PAGE = 10_000
#: Sizes rendered on request when no thumbnail was published; a fixed set bounds the cache.
RENDER_SIZES = (64, 128, 256, 512, 1024, 2048)
JOINED_CACHE_RUNS = 4
COLLECTED_SUFFIX = "@collected"
LOOPBACK_HOSTS = ("127.0.0.1", "localhost", "::1", "[::1]")
ANNOTATION_HINTS = ("_annotations.coco.json", "instances_", "annotations")


def _error(status: int, message: str) -> HTTPException:
    return HTTPException(status_code=status, detail=message)


def _column_info(name: str, schema: Schema, source: str = "table") -> dict[str, Any]:
    """How the dashboard sees a column: its type, whether it can be edited, its classes."""
    info: dict[str, Any] = {
        "name": name,
        "kind": schema.kind,
        "writable": bool(schema.writable) and source != "metrics",
        "default_visible": schema.default_visible,
        "number_role": schema.number_role,
        "source": source,
    }
    if isinstance(schema, (CategoricalLabelSchema, Geometry2DSchema)):
        info["value_map"] = {str(k): v.to_dict() for k, v in sorted(schema.value_map.items())}
    if isinstance(schema, Geometry2DSchema):
        info["instance_properties"] = dict(schema.instance_properties)
    return info


class CommitRequest(BaseModel):
    """A dashboard editing session, sent sparsely: only the cells that changed."""

    url: str
    values: dict[str, dict[str, Any]] = Field(default_factory=dict)
    new_columns: dict[str, tuple[str, Any]] = Field(default_factory=dict)
    value_maps: dict[str, dict[str, Any]] = Field(default_factory=dict)
    name: str | None = None
    description: str = ""


class SourceRequest(BaseModel):
    split: str
    annotations: str
    images: str | None = None


class PreflightRequest(BaseModel):
    sources: list[SourceRequest]
    media: str = "full"


class ReviewRequest(BaseModel):
    project: str
    dataset: str
    samples: list[str] = Field(max_length=200_000)
    status: str
    reason: str = ""
    table: str | None = None


class QaStatusRequest(BaseModel):
    project: str
    dataset: str
    samples: list[str] = Field(min_length=1, max_length=200_000)
    status: str
    comment: str = ""
    author: str = ""
    table: str | None = None


class QaCommentRequest(BaseModel):
    project: str
    dataset: str
    sample: str
    comment: str
    author: str = ""
    table: str | None = None


class QaMoveRequest(BaseModel):
    """Isolate or delete images of one set version, or return isolated images."""

    project: str
    dataset: str
    samples: list[str] = Field(min_length=1, max_length=200_000)
    table: str | None = None
    reason: str = Field("", max_length=2000)
    author: str = ""


class ShipRequest(BaseModel):
    project: str
    dataset: str
    author: str = ""
    note: str = ""


class TrainingRequest(BaseModel):
    project: str
    train_table: str
    valid_table: str
    rounds: int = Field(12, ge=1, le=300)
    family: str = "yolo"
    version: str = "yolo26n.pt"
    image_size: int = 640
    track_learning: bool = True
    compare_with: str | None = None
    run_name: str | None = None


class RemoveImagesRequest(BaseModel):
    project: str
    table: str
    samples: list[str] = Field(min_length=1, max_length=200_000)
    reason: str = Field("", max_length=2000)
    reasons: dict[str, str] = Field(default_factory=dict)


class RestoreImagesRequest(BaseModel):
    project: str
    dataset: str
    samples: list[str] = Field(min_length=1, max_length=200_000)


class ImportRequest(BaseModel):
    preflight_job: str
    project_name: str
    resolutions: dict[str, str] = Field(default_factory=dict)
    dataset_name: str | None = None
    description: str = ""


def _split_list(value: Any, separators: str) -> list[str]:
    if isinstance(value, (list, tuple)):
        return [str(v) for v in value if str(v).strip()]
    text = str(value or "")
    for separator in separators[1:]:
        text = text.replace(separator, separators[0])
    return [part.strip() for part in text.split(separators[0]) if part.strip()]


def _dashboard_dir() -> Path | None:
    """Built dashboard assets: packaged beside the service, or a repository build."""
    here = Path(__file__).resolve()
    for candidate in (here.parent / "static", here.parents[3] / "web" / "dist"):
        if (candidate / "index.html").is_file():
            return candidate
    return None


def create_app(
    *,
    index: Index | None = None,
    config: Config | None = None,
    cache: ByteCache | None = None,
    include_docs: bool = True,
    allowed_hosts: list[str] | None = None,
    allowed_origins: list[str] | None = None,
    data_roots: list[str] | None = None,
    serve_dashboard: bool = True,
) -> FastAPI:
    """Build the service. Injectable pieces keep it testable without a live server.

    ``allowed_hosts`` are the Host header values accepted (loopback names by default);
    ``allowed_origins`` are extra browser origins allowed cross-origin (none by default);
    ``data_roots`` bound where imports may read from (config ``service.data-roots``).
    """
    config = config or get_config()
    index = index or get_index(config=config)
    cache = cache or ByteCache()
    jobs = JobRegistry()
    #: Images listed by each finished preflight, so its examples can be previewed.
    preflight_media: dict[str, frozenset[str]] = {}
    hosts = {h.lower() for h in (allowed_hosts or []) } | set(LOOPBACK_HOSTS)
    origins = set(allowed_origins if allowed_origins is not None else _split_list(config.get("service.allowed-origins"), ","))
    import_roots = [
        Url(os.path.expanduser(r))
        for r in (data_roots if data_roots is not None else _split_list(config.get("service.data-roots"), os.pathsep + ","))
    ]

    app = FastAPI(
        title="Granum Object Service",
        version=__version__,
        docs_url="/docs" if include_docs else None,
        redoc_url=None,
        summary="Serves Granum Tables, Runs and media to the dashboard.",
    )
    if origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=sorted(origins),
            allow_methods=["GET", "POST"],
            allow_headers=["Content-Type"],
        )
    app.state.index = index
    app.state.config = config
    app.state.cache = cache
    app.state.jobs = jobs

    # -- local access ---------------------------------------------------------

    @app.middleware("http")
    async def local_access(request: Request, call_next: Any) -> Response:
        host = (request.headers.get("host") or "").lower()
        hostname = host.rsplit(":", 1)[0] if not host.endswith("]") else host
        if hostname not in hosts:
            return JSONResponse({"detail": f"host {host!r} is not allowed; start the service with --allow-host to add it"}, 403)
        origin = request.headers.get("origin")
        if origin and origin != "null":
            same = urlsplit(origin).netloc.lower() == host
            if not same and origin not in origins:
                return JSONResponse({"detail": f"requests from {origin} are not allowed"}, 403)
        elif origin == "null":
            return JSONResponse({"detail": "requests from opaque origins are not allowed"}, 403)
        if request.headers.get("sec-fetch-site") == "cross-site" and origin not in origins:
            return JSONResponse({"detail": "cross-site requests are not allowed"}, 403)
        if request.method not in ("GET", "HEAD", "OPTIONS"):
            content_type = request.headers.get("content-type", "").split(";")[0].strip().lower()
            if content_type and content_type != "application/json":
                return JSONResponse({"detail": "write requests must be application/json"}, 415)
        return await call_next(request)

    # -- guards -------------------------------------------------------------

    def _roots() -> list[Url]:
        return list(index.roots)

    def _within(url: Url, roots: list[Url]) -> bool:
        resolved = os.path.realpath(url.resolved) if url.scheme in ("", "file") else url.resolved
        for root in roots:
            root_text = os.path.realpath(root.resolved) if root.scheme in ("", "file") else root.resolved
            root_text = root_text.rstrip("/")
            if resolved == root_text or resolved.startswith(root_text + "/"):
                return True
        return False

    def _check_within_roots(url: Url) -> Url:
        """Refuse any URL outside the configured scan roots."""
        if not _within(url, _roots()):
            raise _error(403, f"{url} is outside the configured scan roots")
        return url

    def _check_import_path(text: str) -> Url:
        url = Url(os.path.expanduser(text))
        if not import_roots or not _within(url, import_roots):
            raise _error(403, f"{text} is outside the folders this service may import from ({', '.join(str(r) for r in import_roots) or 'none configured'})")
        return url

    def _table_at(url_text: str) -> Table:
        url = _check_within_roots(Url(url_text))
        entry = index.get(url)
        try:
            if entry is not None and entry.type_name == "metrics_table":
                return MetricsTable.from_url(url)
            return Table.from_url(url)
        except GranumError as exc:
            raise _error(404, str(exc)) from exc

    def _run_at(url_text: str) -> Run:
        url = _check_within_roots(Url(url_text))
        try:
            return Run.from_url(url)
        except GranumError as exc:
            raise _error(404, str(exc)) from exc

    def _input_revision(metrics: MetricsTable) -> tuple[Table, str | None]:
        """The revision a run view joins against, and why a newer one was passed over.

        Metrics address samples by row position, so a descendant is usable only if every
        revision between it and the collected Table kept rows in place. Equal length is
        not enough: a deletion followed by an addition has the same length and different
        samples at the same positions.
        """
        original = metrics.input_table()
        best, best_key = original, (0, original.created)
        skipped: str | None = None
        queue = [(original, 0)]
        seen = {str(original.url)}
        while queue:
            table, depth = queue.pop()
            for child_entry in index.children_of(table.url):
                if str(child_entry.url) in seen or child_entry.type_name != "table":
                    continue
                seen.add(str(child_entry.url))
                try:
                    child = Table.from_url(child_entry.url)
                except GranumError:
                    continue
                op = child.producer.get("op")
                if op not in ROW_PRESERVING_OPS or len(child) != len(original) or len(child.parents) != 1:
                    skipped = f"{child.name} ({op}) changes which rows exist, so its values cannot be shown beside these metrics"
                    continue
                key = (depth + 1, child.created)
                if key > best_key:
                    best, best_key = child, key
                queue.append((child, depth + 1))
        return best, (skipped if str(best.url) == str(original.url) else None)

    # A run's join touches every metrics row and every sample behind it -- ~1s for 80k
    # rows. The dashboard pages through it, so rebuilding per page made opening a real
    # run quadratic. Metrics tables are write-once, so the set of them plus the input
    # revisions joined is the key: a new epoch or a new commit invalidates the entry.
    joined_cache: dict[str, tuple[tuple[str, ...], dict[str, Any]]] = {}

    def _changed_columns(original: Table, current: Table) -> list[str]:
        """Columns whose values differ between the collected and the displayed revision."""
        out = []
        for name in current.columns:
            if name not in original.columns:
                continue
            schema = current.schema[name]
            if isinstance(schema, (ImageSchema, Geometry2DSchema)):
                continue
            if not original.to_arrow().column(name).equals(current.to_arrow().column(name)):
                out.append(name)
        return out

    def _joined(run: Run) -> dict[str, Any]:
        key = str(run.url)
        # Per-epoch score summaries (no boxes) feed the learning view, not the row view.
        metrics = [t for t in run.metrics_tables()
                   if t.foreign_table_url is not None and not t.constants.get("summary_only")]
        resolved = {str(t.url): _input_revision(t) for t in metrics}
        inputs = {k: v[0] for k, v in resolved.items()}
        version = tuple(sorted(str(t.url) for t in metrics)) + tuple(
            sorted(str(t.url) for t in inputs.values())
        )
        hit = joined_cache.get(key)
        if hit is not None and hit[0] == version:
            return hit[1]

        # Runs that track learning store boxes every epoch. Sending every epoch's boxes (and
        # the joined labels, repeated per epoch) to the row view would be hundreds of MB, so
        # only each input's last epoch keeps geometry; earlier epochs keep their scores.
        # One image's boxes at any epoch come from /api/run/image-rounds instead.
        def epoch_of(table: MetricsTable) -> int | None:
            if "epoch" not in table.columns or len(table) == 0:
                return None
            value = table.to_arrow().column("epoch")[0].as_py()
            return int(value) if isinstance(value, (int, float)) else None

        last_epoch: dict[str, int] = {}
        for table in metrics:
            epoch = epoch_of(table)
            if epoch is not None:
                foreign = str(table.foreign_table_url)
                last_epoch[foreign] = max(epoch, last_epoch.get(foreign, epoch))

        sources: list[str] = []
        rows: list[dict[str, Any]] = []
        collected_columns: dict[str, dict[str, Any]] = {}
        described = []
        # Last epochs first, so the view opens on rows that carry the model's boxes.
        def is_last(table: MetricsTable) -> bool:
            epoch = epoch_of(table)
            return epoch is None or epoch >= last_epoch.get(str(table.foreign_table_url), epoch)

        for table in sorted(metrics, key=lambda t: not is_last(t)):
            epoch = epoch_of(table)
            slim = epoch is not None and epoch < last_epoch.get(str(table.foreign_table_url), epoch)
            source = inputs[str(table.url)]
            if str(source.url) not in sources:
                sources.append(str(source.url))
            position = sources.index(str(source.url))
            changed: list[str] = []
            original_data: dict[str, list[Any]] = {}
            if str(source.url) != str(table.foreign_table_url):
                original = table.input_table()
                changed = _changed_columns(original, source)
                original_data = {name: original.to_arrow().column(name).to_pylist() for name in changed}
                for name in changed:
                    info = _column_info(name, original.schema[name], "metrics")
                    info["name"] = f"{name}{COLLECTED_SUFFIX}"
                    info["collected_of"] = name
                    collected_columns[info["name"]] = info
            heavy = [n for n in (*table.columns, *source.columns)
                     if n == "gt_match" or isinstance((table.schema[n] if n in table.columns else source.schema[n]), Geometry2DSchema)] if slim else []
            for row in table.join_input(input_table=source):
                for name in heavy:
                    row[name] = None
                row["_src"] = position
                for name in changed:
                    row[f"{name}{COLLECTED_SUFFIX}"] = original_data[name][row["example_id"]]
                rows.append(row)
            described.append({
                "metrics_table": table.name,
                "collected_on": str(table.foreign_table_url),
                "joined": str(source.url),
                "changed_columns": changed,
                "newer_revision_skipped": resolved[str(table.url)][1],
            })
        result = {
            "rows": rows,
            "sources": sources,
            "inputs": described,
            "collected_columns": list(collected_columns.values()),
        }
        joined_cache.pop(key, None)
        while len(joined_cache) >= JOINED_CACHE_RUNS:
            joined_cache.pop(next(iter(joined_cache)))
        joined_cache[key] = (version, result)
        return result

    # -- meta ---------------------------------------------------------------

    @app.get("/api/health")
    def health() -> dict[str, Any]:
        return {
            "status": "ok",
            "version": __version__,
            "roots": [str(r) for r in _roots()],
            "data_roots": [str(r) for r in import_roots],
            "objects": len(index.entries()),
            "scans": index.stats.scans,
            "dashboard_bundled": _dashboard_dir() is not None,
        }

    @app.get("/api/stats")
    def stats() -> dict[str, Any]:
        return {
            "index": {
                "scans": index.stats.scans,
                "locations_visited": index.stats.locations_visited,
                "locations_skipped": index.stats.locations_skipped,
                "objects_found": index.stats.objects_found,
                "failures": index.stats.failures,
                "last_duration_seconds": round(index.stats.last_duration, 4),
            },
            "cache": cache.stats(),
        }

    @app.post("/api/reindex")
    def reindex(force: bool = Query(True)) -> dict[str, Any]:
        index.refresh(force=force)
        return {"objects": len(index.entries()), "scans": index.stats.scans}

    # -- navigation ---------------------------------------------------------

    @app.get("/api/projects")
    def projects() -> dict[str, Any]:
        return {"projects": index.projects()}

    box_counts: dict[str, dict[str, int]] = {}

    def _box_counts(table: Table, column: str | None) -> dict[str, int]:
        """Boxes and classes in a version; versions never change, so this is computed once."""
        key = str(table.url)
        if key not in box_counts:
            counts = {"box_count": 0, "class_count": 0}
            if column is not None:
                import pyarrow.compute as pc

                instances = pc.struct_field(table.to_arrow().column(column), "instances")
                counts["box_count"] = int(pc.sum(pc.list_value_length(instances)).as_py() or 0)
                counts["class_count"] = len(table.schema[column].value_map or {})
            box_counts[key] = counts
        return box_counts[key]

    @app.get("/api/projects/{project_name}/tables")
    def project_tables(project_name: str) -> dict[str, Any]:
        out = []
        for entry in index.tables(project_name):
            payload = entry.to_dict()
            try:
                table = Table.from_url(entry.url)
                preflight = table.producer.get("args", {}).get("preflight")
                payload["op"] = table.producer.get("op")
                payload["split"] = table.base_name
                if preflight:
                    payload["preflight"] = {
                        k: preflight.get(k) for k in ("import_id", "verdict", "created", "resolutions")
                    }
                    payload["preflight"]["warnings"] = sum(1 for f in preflight.get("findings", []) if f["severity"] == "warn")
                payload["box_column"] = next(
                    (n for n in table.columns if isinstance(table.schema[n], Geometry2DSchema)), None
                )
                payload.update(_box_counts(table, payload["box_column"]))
            except GranumError:
                pass
            out.append(payload)
        return {"tables": out}

    @app.get("/api/projects/{project_name}/runs")
    def project_runs(project_name: str) -> dict[str, Any]:
        """Runs with their hyperparameters and last logged scalars, so they compare in a list."""
        out = []
        for entry in index.runs(project_name):
            payload = entry.to_dict()
            try:
                run = Run.from_url(entry.url)
                aggregates = run.aggregate_metrics()
                payload["parameters"] = run.parameters
                payload["status"] = run.status
                payload["last_metrics"] = {
                    k: v for k, v in (aggregates[-1] if aggregates else {}).items() if not k.startswith("_")
                }
                payload["epochs"] = len(aggregates)
                payload["history"] = [
                    {k: v for k, v in row.items() if not k.startswith("_") and isinstance(v, (int, float))}
                    for row in aggregates
                ]
                payload["inputs"] = sorted({str(t.foreign_table_url) for t in run.metrics_tables() if t.foreign_table_url})
            except GranumError:
                payload["parameters"], payload["last_metrics"] = {}, {}
            out.append(payload)
        return {"runs": out}

    @app.get("/api/projects/{project_name}/lineage")
    def project_lineage(project_name: str) -> dict[str, Any]:
        return {
            "nodes": [e.to_dict() for e in index.tables(project_name)],
            "edges": index.lineage_edges(project_name),
        }

    @app.get("/api/projects/{project_name}/imports")
    def project_imports(project_name: str) -> dict[str, Any]:
        """Saved import reports, newest first."""
        folder = ProjectLayout(config.project_root).project(project_name) / "imports"
        out = []
        if folder.exists():
            for url in sorted(folder.ls(), key=lambda u: u.name, reverse=True):
                if url.suffix != ".json":
                    continue
                try:
                    saved = json.loads(url.read_text())
                except (OSError, json.JSONDecodeError):
                    continue
                out.append({
                    "id": saved["import"]["id"],
                    "created": saved["report"]["created"],
                    "verdict": saved["report"]["verdict"],
                    "sources": saved["report"]["sources"],
                    "tables": saved["import"]["tables"],
                    "findings": [
                        {k: f[k] for k in ("code", "severity", "title", "count", "unit")}
                        for f in saved["report"]["findings"]
                    ],
                    "resolutions": saved["import"]["resolutions"],
                    "effects": saved["import"]["effects"],
                })
        return {"imports": out}

    @app.get("/api/projects/{project_name}/imports/{import_id}")
    def project_import(project_name: str, import_id: str) -> dict[str, Any]:
        if "/" in import_id or ".." in import_id:
            raise _error(400, "invalid import id")
        url = ProjectLayout(config.project_root).project(project_name) / "imports" / f"{import_id}.json"
        if not url.exists():
            raise _error(404, f"no import {import_id} in {project_name}")
        return json.loads(url.read_text())

    # -- tables -------------------------------------------------------------

    @app.get("/api/table")
    def table_metadata(url: str = Query(...)) -> dict[str, Any]:
        table = _table_at(url)
        payload = table.to_dict()
        payload["url"] = str(table.url)
        source = "metrics" if isinstance(table, MetricsTable) else "table"
        payload["columns"] = [_column_info(name, table.schema[name], source) for name in table.columns]
        latest = index.latest_revision(table.url)
        payload["latest_revision"] = str(latest.url) if latest else str(table.url)
        return payload

    @app.get("/api/table/rows")
    def table_rows(
        url: str = Query(...),
        offset: int = Query(0, ge=0),
        limit: int = Query(100, ge=1, le=MAX_PAGE),
    ) -> dict[str, Any]:
        table = _table_at(url)
        stop = min(offset + limit, len(table))
        rows = [table[i] for i in range(offset, stop)]
        for index_, row in zip(range(offset, stop), rows):
            row["_row"] = index_
        return {
            "url": str(table.url),
            "offset": offset,
            "limit": limit,
            "total": len(table),
            "rows": rows,
        }

    @app.get("/api/table/sample")
    def table_sample(url: str = Query(...), n: int = Query(12, ge=1, le=60)) -> dict[str, Any]:
        """Image references spread evenly through a version, for thumbnail strips."""
        from granum.core.curation import CurationError, image_column

        table = _table_at(url)
        try:
            column = image_column(table)
        except CurationError:
            return {"images": []}
        total = len(table)
        if total == 0:
            return {"images": []}
        step = max(1, total // n)
        rows = list(range(0, total, step))[:n]
        values = table.to_arrow().column(column).take(pa.array(rows, type=pa.int64())).to_pylist()
        return {"images": [{"row": r, "image": v} for r, v in zip(rows, values)]}

    @app.get("/api/table/arrow")
    def table_arrow(
        url: str = Query(...),
        offset: int = Query(0, ge=0),
        limit: int = Query(MAX_PAGE, ge=1, le=100_000),
    ) -> Response:
        """Columnar rows for the dashboard grid -- no JSON parse on the client."""
        table = _table_at(url)
        sliced = table.to_arrow().slice(offset, limit)
        sink = io.BytesIO()
        with pa.ipc.new_stream(sink, sliced.schema) as writer:
            writer.write_table(sliced)
        return Response(
            content=sink.getvalue(),
            media_type="application/vnd.apache.arrow.stream",
        )

    @app.post("/api/table/commit")
    def commit(request: CommitRequest = Body(...)) -> dict[str, Any]:
        """Write a dashboard editing session as one new revision of a Table."""
        target = _check_within_roots(Url(request.url))
        entry = index.get(target)
        if entry is not None and entry.type_name == "metrics_table":
            raise _error(400, "metrics tables are read-only; edit the input Table instead")
        try:
            table = Table.from_url(target)
        except GranumError as exc:
            raise _error(404, str(exc)) from exc
        try:
            values = {
                column: {int(row): value for row, value in cells.items()}
                for column, cells in request.values.items()
            }
        except ValueError as exc:
            raise _error(400, f"row keys must be integers: {exc}") from exc
        try:
            revision = table.apply_edits(
                values=values,
                new_columns={name: (kind, default) for name, (kind, default) in request.new_columns.items()},
                value_maps=request.value_maps,
                table_name=request.name or None,
                description=request.description,
            )
        except (GranumError, ValueError) as exc:
            raise _error(400, str(exc)) from exc
        index.refresh(force=True)
        return {
            "url": str(revision.url),
            "name": revision.name,
            "parents": [str(p) for p in revision.parents],
            "row_count": len(revision),
            "summary": revision.producer.get("args", {}),
        }

    # -- runs ---------------------------------------------------------------

    @app.get("/api/run")
    def run_metadata(url: str = Query(...)) -> dict[str, Any]:
        run = _run_at(url)
        payload = run.to_dict()
        payload["url"] = str(run.url)
        payload["metrics_tables"] = [
            {
                "url": str(t.url),
                "name": t.name,
                "rows": len(t),
                "columns": t.columns,
                "foreign_table_url": str(t.foreign_table_url) if t.foreign_table_url else None,
                "constants": t.constants,
            }
            for t in run.metrics_tables()
        ]
        payload["aggregate_metrics"] = run.aggregate_metrics()
        joined = _joined(run)
        payload["columns"] = _run_columns(run) + joined["collected_columns"]
        payload["inputs"] = joined["inputs"]
        payload["sources"] = joined["sources"]
        return payload

    def _run_columns(run: Run) -> list[dict[str, Any]]:
        """Columns of the joined view: the input Table's (editable where the schema
        allows), then metrics and constants (always read-only)."""
        out: dict[str, dict[str, Any]] = {}
        for table in run.metrics_tables():
            if table.foreign_table_url is None or table.constants.get("summary_only"):
                continue
            source, _ = _input_revision(table)
            for name in source.columns:
                out.setdefault(name, _column_info(name, source.schema[name], "table"))
            for name in table.columns:
                out.setdefault(name, _column_info(name, table.schema[name], "metrics"))
            for name, value in table.constants.items():
                if name not in out:
                    kind = "string" if isinstance(value, str) else "int64"
                    out[name] = {
                        "name": name, "kind": kind, "writable": False, "default_visible": True,
                        "number_role": None, "source": "metrics",
                    }
        return list(out.values())

    @app.get("/api/run/learning")
    def run_learning(url: str = Query(...), good: float = Query(0.5, ge=0.05, le=0.95)) -> dict[str, Any]:
        """How each image was learned across the run's recorded epochs, per split."""
        from granum.metrics.dynamics import image_learning

        run = _run_at(url)
        by_split: dict[str, list[MetricsTable]] = {}
        for table in run.metrics_tables():
            if table.foreign_table_url is None or "f1" not in table.columns or "epoch" not in table.columns:
                continue
            by_split.setdefault(str(table.constants.get("split") or "all"), []).append(table)

        splits = []
        for split, tables in by_split.items():
            records: list[dict[str, Any]] = []
            source_url = str(tables[0].foreign_table_url)
            for table in tables:
                data = table.to_arrow().select([c for c in ("example_id", "epoch", "tp", "fp", "fn", "f1") if c in table.columns]).to_pylist()
                for record in data:
                    record["_src"] = str(table.foreign_table_url)
                records.extend(data)
            stats = image_learning(records, good=good)
            epochs = sorted({e for s_ in stats.values() for e in s_["epochs"]})
            try:
                source = Table.from_url(source_url)
                arrow = source.to_arrow()
                images = arrow.column("image").to_pylist() if "image" in source.columns else []
                box_column = next((n for n in source.columns if isinstance(source.schema[n], Geometry2DSchema)), None)
                boxes = arrow.column(box_column).to_pylist() if box_column else []
            except GranumError:
                images, boxes, source = [], [], None
            counts: dict[str, int] = {}
            rows = []
            for (src, example), item in sorted(stats.items(), key=lambda kv: kv[0][1]):
                if src != source_url:
                    continue  # a split re-collected on another revision is not mixed in
                counts[item["category"]] = counts.get(item["category"], 0) + 1
                index_of = {e: i for i, e in enumerate(item["epochs"])}
                value = boxes[example] if example < len(boxes) else None
                rows.append({
                    "example_id": example,
                    "image": images[example] if example < len(images) else None,
                    "objects": sum(1 for i in (value or {}).get("instances", []) if not i.get("iscrowd")),
                    "width": (value or {}).get("width"),
                    "height": (value or {}).get("height"),
                    "category": item["category"],
                    "first_good_epoch": item["first_good_epoch"],
                    "learned_epoch": item["learned_epoch"],
                    "forgetting_events": item["forgetting_events"],
                    "final_score": round(item["final_score"], 4),
                    "mean_score": round(item["mean_score"], 4),
                    "best_score": round(item["best_score"], 4),
                    "scores": [round(item["scores"][index_of[e]], 4) if e in index_of else None for e in epochs],
                })
            sample = next(iter(stats.values()), {})
            splits.append({
                "split": split,
                "table": source_url,
                "table_name": source.name if source is not None else None,
                "dataset": source.dataset_name if source is not None else None,
                "epochs": epochs,
                "counts": counts,
                "early_before": sample.get("early_before"),
                "late_after": sample.get("late_after"),
                "images": rows,
            })
        order = {"train": 0, "valid": 1, "val": 1, "test": 2}
        splits.sort(key=lambda s_: order.get(s_["split"], 9))
        return {
            "url": str(run.url),
            "name": run.name,
            "good": good,
            "tracks_learning": bool(run.parameters.get("tracks_learning")),
            "splits": splits,
        }

    @app.get("/api/run/image-rounds")
    def run_image_rounds(
        url: str = Query(...),
        table: str = Query(...),
        example: int = Query(..., ge=0),
        good: float = Query(0.5, ge=0.05, le=0.95),
    ) -> dict[str, Any]:
        """One image through training: its labels, and the model's boxes and score each round."""
        run = _run_at(url)
        source = _table_at(table)
        if example >= len(source):
            raise _error(404, f"{source.name} has no image {example}")
        box_column = next((n for n in source.columns if isinstance(source.schema[n], Geometry2DSchema)), None)
        if box_column is None:
            raise _error(400, f"{source.name} has no boxes")
        row = source.to_arrow().slice(example, 1).to_pylist()[0]
        value_map = source.schema[box_column].value_map or {}

        by_epoch: dict[int, dict[str, Any]] = {}
        for metrics in run.metrics_tables():
            if str(metrics.foreign_table_url) != str(source.url) or "epoch" not in metrics.columns or "f1" not in metrics.columns:
                continue
            arrow = metrics.to_arrow()
            ids = arrow.column("example_id").to_pylist()
            try:
                at = ids.index(example)
            except ValueError:
                continue
            record = arrow.slice(at, 1).to_pylist()[0]
            epoch = int(record["epoch"])
            has_boxes = "bbs_predicted" in record and record["bbs_predicted"] is not None
            if epoch in by_epoch and by_epoch[epoch]["boxes"] is not None and not has_boxes:
                continue  # a round recorded twice: keep the copy with boxes
            by_epoch[epoch] = {
                "epoch": epoch,
                **{k: record.get(k) for k in ("tp", "fp", "fn", "precision", "recall", "f1")},
                "boxes": (record["bbs_predicted"] or {}).get("instances", []) if has_boxes else None,
                "gt_match": record.get("gt_match") if has_boxes else None,
            }
        rounds = [by_epoch[e] for e in sorted(by_epoch)]

        def holds_from(test: Any) -> int | None:
            start = None
            for item in rounds:
                if test(item):
                    start = item["epoch"] if start is None else start
                else:
                    start = None
            return start

        truth = row.get(box_column) or {}
        labelled = sum(1 for i in truth.get("instances", []) if not i.get("iscrowd"))
        return {
            "image": row.get("image"),
            "table": str(source.url),
            "table_name": source.name,
            "set": source.base_name,
            "dataset": source.dataset_name,
            "example": example,
            "width": truth.get("width"),
            "height": truth.get("height"),
            "labels": {str(k): (v.display_name or v.internal_name) for k, v in value_map.items()},
            "truth": truth.get("instances", []),
            "rounds": rounds,
            "good": good,
            "learned_from": holds_from(lambda r: (r["f1"] or 0) >= good),
            # Perfect: every labelled object found and nothing extra guessed.
            "perfect_from": holds_from(lambda r: r["fp"] == 0 and r["fn"] == 0 and (r["tp"] or 0) == labelled),
        }

    @app.get("/api/run/joined")
    def run_joined(
        url: str = Query(...),
        offset: int = Query(0, ge=0),
        limit: int = Query(100, ge=1, le=MAX_PAGE),
    ) -> dict[str, Any]:
        """Metrics rows joined to the samples that produced them."""
        run = _run_at(url)
        joined = _joined(run)
        rows = joined["rows"]
        return {
            "url": str(run.url),
            "sources": joined["sources"],
            "total": len(rows),
            "offset": offset,
            "limit": limit,
            "rows": rows[offset : offset + limit],
        }

    # -- review decisions ---------------------------------------------------

    def _review_log(project: str, dataset: str) -> Any:
        from granum.core.reviews import ReviewLog

        if not any(t.dataset_name == dataset for t in index.tables(project)):
            raise _error(404, f"no dataset {dataset!r} in project {project!r}")
        return ReviewLog(project, dataset, config=config)

    @app.get("/api/reviews")
    def reviews(project: str = Query(...), dataset: str = Query(...)) -> dict[str, Any]:
        log = _review_log(project, dataset)
        current = log.current()
        return {
            "statuses": {
                sample: {k: event.get(k) for k in ("status", "reason", "time", "table", "reviewer")}
                for sample, event in current.items()
            },
            "counts": log.counts(),
        }

    @app.post("/api/reviews")
    def record_review(request: ReviewRequest = Body(...)) -> dict[str, Any]:
        from granum.core.reviews import ReviewError

        log = _review_log(request.project, request.dataset)
        if request.table is not None:
            _check_within_roots(Url(request.table))
        try:
            recorded = log.record(request.samples, request.status, reason=request.reason, table_url=request.table)
        except ReviewError as exc:
            raise _error(400, str(exc)) from exc
        return {"recorded": recorded, "counts": log.counts()}

    @app.get("/api/reviews/history")
    def review_history(project: str = Query(...), dataset: str = Query(...), sample: str = Query(...)) -> dict[str, Any]:
        return {"events": _review_log(project, dataset).history(sample)}

    # -- annotation review and shipping --------------------------------------

    def _qa_log(project: str, dataset: str) -> Any:
        from granum.core.qa import QaLog

        if not any(t.dataset_name == dataset for t in index.tables(project)):
            raise _error(404, f"no dataset {dataset!r} in project {project!r}")
        return QaLog(project, dataset, config=config)

    def _review_sets(project: str, dataset: str) -> dict[str, Table]:
        """The sets a shipment covers: the newest version of each, without the removed set."""
        from granum.core.curation import HOLDING_SETS

        return {name: t for name, t in _newest_sets(project, dataset).items() if name not in HOLDING_SETS}

    def _set_images(table: Table) -> list[dict[str, Any]]:
        from granum.core.curation import CurationError, image_column

        try:
            column = image_column(table)
        except CurationError:
            return []
        arrow = table.to_arrow()
        box_column = next((n for n in table.columns if isinstance(table.schema[n], Geometry2DSchema)), None)
        boxes = arrow.column(box_column).to_pylist() if box_column else [None] * len(arrow)
        return [
            {"row": i, "image": image,
             "objects": sum(1 for x in (value or {}).get("instances", []) if not x.get("iscrowd"))}
            for i, (image, value) in enumerate(zip(arrow.column(column).to_pylist(), boxes))
            if image
        ]

    def _shipped_urls(project: str) -> set[str]:
        from granum.core.qa import QaLog

        names = {t.dataset_name for t in index.tables(project)}
        return set().union(*(QaLog(project, name, config=config).shipped_urls() for name in names)) if names else set()

    @app.get("/api/qa")
    def qa_overview(project: str = Query(...), dataset: str = Query(...)) -> dict[str, Any]:
        """Every image of the dataset's newest sets, with its review status, and the shipments."""
        log = _qa_log(project, dataset)
        current = log.current()
        from granum.core.curation import ISOLATED_SET, image_column

        sets = []
        isolated = None
        newest_all = _newest_sets(project, dataset)
        if ISOLATED_SET in newest_all and len(newest_all[ISOLATED_SET]):
            holding = newest_all[ISOLATED_SET]
            arrow = holding.to_arrow()
            origins = dict(zip(arrow.column(image_column(holding)).to_pylist(),
                               zip(arrow.column("removed_from").to_pylist(), arrow.column("removed_reason").to_pylist())))
            images = [{**i, "from": origins.get(i["image"], (None, None))[0], "reason": origins.get(i["image"], (None, None))[1] or ""}
                      for i in _set_images(holding)]
            counts = {status: 0 for status in ("unreviewed", "reviewed", "rework")}
            for item in images:
                counts[current.get(item["image"], {}).get("status", "unreviewed")] += 1
            isolated = {**_version_payload(holding), "images": images, "counts": counts}
        for table in _review_sets(project, dataset).values():
            images = _set_images(table)
            counts = {status: 0 for status in ("unreviewed", "reviewed", "rework")}
            for item in images:
                counts[current.get(item["image"], {}).get("status", "unreviewed")] += 1
            sets.append({**_version_payload(table), "images": images, "counts": counts})
        order = ["train", "valid", "val", "validation", "test"]
        sets.sort(key=lambda s: (order.index(s["set"]) if s["set"] in order else len(order), s["set"]))
        shipments = log.shipments()
        newest = {s["set"]: s["url"] for s in sets}
        latest = shipments[0] if shipments else None
        return {
            "sets": sets,
            "isolated": isolated,
            "statuses": current,
            "shipments": shipments,
            "ready": bool(sets) and all(s["counts"]["reviewed"] == len(s["images"]) for s in sets),
            # Shipped, and nothing has changed since: the newest versions are what shipped.
            "up_to_date": latest is not None and {k: v["url"] for k, v in latest["sets"].items()} == newest,
        }

    @app.post("/api/qa/status")
    def qa_status(request: QaStatusRequest = Body(...)) -> dict[str, Any]:
        from granum.core.qa import QaError

        log = _qa_log(request.project, request.dataset)
        if request.table is not None:
            _check_within_roots(Url(request.table))
        try:
            recorded = log.set_status(request.samples, request.status, comment=request.comment,
                                      author=request.author, table_url=request.table)
        except QaError as exc:
            raise _error(400, str(exc)) from exc
        current = log.current()
        return {"recorded": recorded, "statuses": {s: current.get(s, {"status": "unreviewed", "comments": 0}) for s in request.samples}}

    @app.post("/api/qa/comment")
    def qa_comment(request: QaCommentRequest = Body(...)) -> dict[str, Any]:
        from granum.core.qa import QaError

        log = _qa_log(request.project, request.dataset)
        if request.table is not None:
            _check_within_roots(Url(request.table))
        try:
            event = log.add_comment(request.sample, request.comment, author=request.author, table_url=request.table)
        except QaError as exc:
            raise _error(400, str(exc)) from exc
        return {"event": event, "thread": log.thread(request.sample)}

    @app.get("/api/qa/image")
    def qa_image(project: str = Query(...), dataset: str = Query(...), table: str = Query(...), image: str = Query(...)) -> dict[str, Any]:
        """One image for review: its labelled boxes, class names and comment thread."""
        from granum.core.curation import CurationError, image_column

        log = _qa_log(project, dataset)
        source = _table_at(table)
        if isinstance(source, MetricsTable) or source.project_name != project or source.dataset_name != dataset:
            raise _error(400, "choose a version of this dataset")
        try:
            column = image_column(source)
        except CurationError as exc:
            raise _error(400, str(exc)) from exc
        arrow = source.to_arrow()
        try:
            row = arrow.column(column).to_pylist().index(image)
        except ValueError:
            raise _error(404, f"{source.name} has no image {image}") from None
        record = arrow.slice(row, 1).to_pylist()[0]
        box_column = next((n for n in source.columns if isinstance(source.schema[n], Geometry2DSchema)), None)
        value = (record.get(box_column) or {}) if box_column else {}
        value_map = (source.schema[box_column].value_map or {}) if box_column else {}
        return {
            "image": image,
            "row": row,
            "table": str(source.url),
            "box_column": box_column,
            "editable": bool(box_column and source.schema[box_column].writable),
            "width": value.get("width"),
            "height": value.get("height"),
            "labels": {str(k): (v.display_name or v.internal_name) for k, v in value_map.items()},
            "boxes": value.get("instances", []),
            "thread": log.thread(image),
        }

    def _qa_move(request: QaMoveRequest, holding: str) -> dict[str, Any]:
        from granum.core.curation import CurationError, remove_images
        from granum.core.qa import QaError

        log = _qa_log(request.project, request.dataset)
        if request.table is None:
            raise _error(400, "choose the set version to take images out of")
        source = _table_at(request.table)
        if isinstance(source, MetricsTable) or source.project_name != request.project or source.dataset_name != request.dataset:
            raise _error(400, "choose a version of this dataset")
        newest = _newest_sets(request.project, request.dataset)
        latest = newest.get(source.base_name)
        if latest is not None and str(latest.url) != str(source.url):
            raise _error(409, f"{source.name} is not the newest version of {source.base_name}; reload and try again")
        try:
            done = remove_images(source, request.samples, removed_set=newest.get(holding), reason=request.reason,
                                 config=config, holding=holding)
            verb = "Deleted" if holding == "removed" else "Isolated"
            log.add_comment_many(request.samples, f"{verb} from {source.base_name}" + (f": {request.reason}" if request.reason else ""),
                                 author=request.author, table_url=str(done["version"].url))
        except (CurationError, QaError) as exc:
            raise _error(400, str(exc)) from exc
        index.refresh(force=True)
        return {"count": done["count"], "version": _version_payload(done["version"]), "holding": _version_payload(done["removed"])}

    @app.post("/api/qa/isolate")
    def qa_isolate(request: QaMoveRequest = Body(...)) -> dict[str, Any]:
        """Set images aside so the rest of the dataset can ship; they return later."""
        return _qa_move(request, "isolated")

    @app.post("/api/qa/delete")
    def qa_delete(request: QaMoveRequest = Body(...)) -> dict[str, Any]:
        """Take images out of the dataset, into its removed set (recoverable from there)."""
        return _qa_move(request, "removed")

    @app.post("/api/qa/return")
    def qa_return(request: QaMoveRequest = Body(...)) -> dict[str, Any]:
        """Put isolated images back into the newest version of the set each came from."""
        from granum.core.curation import ISOLATED_SET, CurationError, restore_images
        from granum.core.qa import QaError

        log = _qa_log(request.project, request.dataset)
        newest = _newest_sets(request.project, request.dataset)
        isolated = newest.pop(ISOLATED_SET, None)
        if isolated is None:
            raise _error(404, "nothing is isolated in this dataset")
        try:
            done = restore_images(isolated, request.samples, newest_of=newest, config=config)
            log.add_comment_many(request.samples, "Returned from isolation", author=request.author, table_url=str(isolated.url))
        except (CurationError, QaError) as exc:
            raise _error(400, str(exc)) from exc
        index.refresh(force=True)
        return {"count": done["count"], "versions": [_version_payload(v) for v in done["versions"]]}

    @app.post("/api/qa/ship")
    def qa_ship(request: ShipRequest = Body(...)) -> dict[str, Any]:
        from granum.core.qa import QaError

        log = _qa_log(request.project, request.dataset)
        statuses = {k: v["status"] for k, v in log.current().items()}
        versions = {
            name: {"url": str(table.url), "name": table.name, "images": [i["image"] for i in _set_images(table)]}
            for name, table in _review_sets(request.project, request.dataset).items()
        }
        try:
            shipment = log.ship(versions, statuses, author=request.author, note=request.note)
        except QaError as exc:
            raise _error(409, str(exc)) from exc
        return {"shipment": shipment}

    # -- removing images from sets ------------------------------------------

    def _newest_sets(project: str, dataset: str) -> dict[str, Table]:
        """The newest version of every set (train, valid, removed, ...) in a dataset."""
        tables = []
        for entry in index.tables(project):
            if entry.dataset_name != dataset:
                continue
            try:
                tables.append(Table.from_url(entry.url))
            except GranumError:
                continue
        if not tables:
            raise _error(404, f"no dataset {dataset!r} in project {project!r}")
        parents = {str(p) for t in tables for p in t.parents}
        newest: dict[str, Table] = {}
        for table in tables:
            if str(table.url) in parents:
                continue
            current = newest.get(table.base_name)
            if current is None or table.created > current.created:
                newest[table.base_name] = table
        return newest

    def _version_payload(table: Table) -> dict[str, Any]:
        return {"url": str(table.url), "name": table.name, "set": table.base_name, "row_count": len(table)}

    @app.post("/api/datasets/remove")
    def remove_from_set(request: RemoveImagesRequest = Body(...)) -> dict[str, Any]:
        """Take images out of the newest version of a set, into the dataset's removed set."""
        from granum.core.curation import REMOVED_SET, CurationError, remove_images

        source = _table_at(request.table)
        if isinstance(source, MetricsTable) or source.project_name != request.project:
            raise _error(400, "choose a version of a dataset in this project")
        newest = _newest_sets(request.project, source.dataset_name)
        latest = newest.get(source.base_name)
        if latest is not None and str(latest.url) != str(source.url):
            raise _error(409, f"{source.name} is not the newest version of {source.base_name}; remove images from {latest.name} instead")
        try:
            done = remove_images(source, request.samples, removed_set=newest.get(REMOVED_SET), reason=request.reason,
                                 reasons={k: v[:2000] for k, v in request.reasons.items()}, config=config)
        except CurationError as exc:
            raise _error(400, str(exc)) from exc
        index.refresh(force=True)
        return {
            "count": done["count"], "missing": done["missing"],
            "version": _version_payload(done["version"]), "removed": _version_payload(done["removed"]),
        }

    @app.get("/api/datasets/removed")
    def removed_images(project: str = Query(...), dataset: str = Query(...)) -> dict[str, Any]:
        from granum.core.curation import REMOVED_SET, image_column

        removed = _newest_sets(project, dataset).get(REMOVED_SET)
        if removed is None:
            return {"table": None, "images": []}
        arrow = removed.to_arrow()
        column = image_column(removed)
        box_column = next((n for n in removed.columns if isinstance(removed.schema[n], Geometry2DSchema)), None)
        boxes = arrow.column(box_column).to_pylist() if box_column else [None] * len(arrow)
        images = []
        for i, (image, value) in enumerate(zip(arrow.column(column).to_pylist(), boxes)):
            images.append({
                "row": i, "image": image,
                "objects": sum(1 for x in (value or {}).get("instances", []) if not x.get("iscrowd")),
                **{k: arrow.column(k)[i].as_py() for k in ("removed_from", "removed_from_version", "removed_reason", "removed_at")},
            })
        images.sort(key=lambda r: r["removed_at"] or "", reverse=True)
        return {"table": _version_payload(removed), "images": images}

    @app.post("/api/datasets/restore")
    def restore_to_sets(request: RestoreImagesRequest = Body(...)) -> dict[str, Any]:
        """Put images from the removed set back where each came from."""
        from granum.core.curation import REMOVED_SET, CurationError, restore_images

        newest = _newest_sets(request.project, request.dataset)
        removed = newest.pop(REMOVED_SET, None)
        if removed is None:
            raise _error(404, "nothing has been removed from this dataset")
        try:
            done = restore_images(removed, request.samples, newest_of=newest, config=config)
        except CurationError as exc:
            raise _error(400, str(exc)) from exc
        index.refresh(force=True)
        return {
            "count": done["count"], "versions": [_version_payload(v) for v in done["versions"]],
            "removed": _version_payload(done["removed"]),
        }

    # -- training -------------------------------------------------------------

    training_check: dict[str, Any] = {}

    def _training_environment() -> dict[str, Any]:
        """Whether this machine can train, checked once in a child process (importing
        torch in the service itself would slow every start and hold GPU memory)."""
        if training_check:
            return training_check
        import subprocess
        import sys

        probe = (
            "import json, importlib.util as u\n"
            "out = {'ultralytics': bool(u.find_spec('ultralytics')), 'torch': bool(u.find_spec('torch')),"
            " 'rfdetr': bool(u.find_spec('rfdetr'))}\n"
            "if out['torch']:\n"
            "    import torch\n"
            "    out['gpu'] = torch.cuda.get_device_name(0) if torch.cuda.is_available() else None\n"
            "print(json.dumps(out))\n"
        )
        try:
            done = subprocess.run([sys.executable, "-c", probe], capture_output=True, text=True, timeout=120)
            found = json.loads(done.stdout.strip().splitlines()[-1])
        except Exception as exc:  # noqa: BLE001 - reported to the user
            found = {"ultralytics": False, "torch": False, "error": str(exc)}
        from granum.training.models import FAMILIES

        families = [
            {**f, "installed": bool(found.get(f["package"])) and bool(found.get("torch")),
             "install_hint": None if found.get(f["package"]) else f"pip install {f['package']}"}
            for f in FAMILIES
        ]
        available = found.get("torch") and any(f["installed"] for f in families)
        training_check.update({
            "available": bool(available),
            "gpu": found.get("gpu"),
            "families": families,
            "reason": None if available else "Training needs PyTorch and a detector package, for example: pip install ultralytics",
        })
        return training_check

    def _running_training() -> Any:
        return next((j for j in jobs.all() if j.kind == "training" and j.status == "running"), None)

    @app.get("/api/training/status")
    def training_status(project: str = Query(...)) -> dict[str, Any]:
        environment = _training_environment()
        running = _running_training()
        return {
            **environment,
            "running_job": running.to_dict() if running is not None and running.payload == project else None,
            "busy_elsewhere": running is not None and running.payload != project,
            "shipped": sorted(_shipped_urls(project)),
        }

    @app.post("/api/training")
    def start_training(request: TrainingRequest = Body(...)) -> dict[str, Any]:
        import re
        import subprocess
        import sys
        import threading
        import time as _time

        environment = _training_environment()
        if not environment["available"]:
            raise _error(400, environment["reason"])
        if _running_training() is not None:
            raise _error(409, "a model is already training on this computer; wait for it to finish or cancel it")
        chosen = next((f for f in environment["families"] if f["id"] == request.family), None)
        if chosen is None:
            raise _error(400, f"family must be one of {[f['id'] for f in environment['families']]}")
        if not chosen["installed"]:
            raise _error(400, f"{chosen['name']} is not installed on this computer: {chosen['install_hint']}")
        if request.version not in [v["id"] for v in chosen["versions"]]:
            raise _error(400, f"{chosen['name']} versions are {[v['id'] for v in chosen['versions']]}")
        if request.image_size not in (640, 960, 1280):
            raise _error(400, "image_size must be 640, 960 or 1280")
        tables = {str(e.url): e for e in index.tables(request.project)}
        for url in (request.train_table, request.valid_table):
            _check_within_roots(Url(url))
            if url not in tables:
                raise _error(404, f"{url} is not a dataset version in {request.project}")
        if request.train_table == request.valid_table:
            raise _error(400, "train and check on different datasets; using the same images for both hides mistakes")
        runs = {e.name for e in index.runs(request.project)}
        if request.compare_with and request.compare_with not in runs:
            raise _error(404, f"no run named {request.compare_with!r} in {request.project}")
        name = request.run_name or f"run-{_time.strftime('%m%d-%H%M%S')}"
        if not re.fullmatch(r"[A-Za-z0-9._-]{1,80}", name):
            raise _error(400, "run names may use letters, numbers, dots, dashes and underscores")
        shipped = _shipped_urls(request.project)
        for url in (request.train_table, request.valid_table):
            if url not in shipped:
                raise _error(409, f"{tables[url].name} has not been shipped; review every image and ship the dataset first")

        command = [
            sys.executable, "-u", "-m", "granum.training.train",
            "--project-root", str(config.project_root), "--project", request.project,
            "--train-table", request.train_table, "--valid-table", request.valid_table,
            "--run-name", name, "--epochs", str(request.rounds), "--imgsz", str(request.image_size),
            "--family", request.family, "--version", request.version,
            *(["--track-learning"] if request.track_learning else []),
            *(["--compare-with", request.compare_with] if request.compare_with else []),
        ]

        def work(job: Any) -> Any:
            job.progress("Starting", 0, request.rounds)
            process = subprocess.Popen(
                command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1,
                env={**os.environ, "PYTHONUNBUFFERED": "1"},
            )

            finished = threading.Event()

            def watch_cancel() -> None:
                while not finished.wait(0.5):
                    if job.cancel.is_set():
                        break
                else:
                    return
                if process.poll() is None:
                    process.terminate()
                    try:
                        process.wait(timeout=15)
                    except subprocess.TimeoutExpired:
                        process.kill()

            threading.Thread(target=watch_cancel, daemon=True).start()
            assert process.stdout is not None
            for raw in process.stdout:
                for line in raw.replace("\r", "\n").splitlines():
                    line = re.sub(r"\x1b\[[0-9;]*[A-Za-z]", "", line).strip()
                    if not line:
                        continue
                    if line.startswith("GRANUM_PHASE "):
                        job.phase = line[len("GRANUM_PHASE "):]
                    elif line.startswith("GRANUM_PROGRESS "):
                        done, total = line.split()[1:3]
                        job.done, job.total = int(done), int(total)
                    elif not job.log or job.log[-1] != line:
                        job.log.append(line[:400])
            code = process.wait()
            finished.set()
            # A stopped or crashed trainer never marks its run finished; say what happened.
            if job.cancel.is_set() or code != 0:
                try:
                    stopped = Run.from_url(ProjectLayout(config.project_root).run(request.project, name))
                    if stopped.status == "running":
                        stopped.set_status("cancelled" if job.cancel.is_set() else "failed")
                except GranumError:
                    pass
            index.refresh(force=True)
            if job.cancel.is_set():
                return {"run_name": name, "cancelled": True}
            if code != 0:
                raise GranumError(f"training stopped with an error (exit code {code}); see the technical log")
            return {"run_name": name, "exit_code": code}

        job = jobs.start("training", work)
        job.payload = request.project
        return job.to_dict()

    # -- import -------------------------------------------------------------

    @app.get("/api/import/browse")
    def import_browse(path: str | None = Query(None)) -> dict[str, Any]:
        """Folders and annotation files under the data roots, for picking a dataset."""
        if path is None:
            return {
                "path": None,
                "parent": None,
                "entries": [
                    {"name": str(r), "path": str(r), "type": "dir"} for r in import_roots if r.exists()
                ],
            }
        folder = _check_import_path(path)
        if not folder.is_dir():
            raise _error(404, f"{path} is not a folder")
        entries = []
        images = 0
        for child in sorted(folder.ls(), key=lambda u: u.name.lower()):
            if child.name.startswith("."):
                continue
            if child.is_dir():
                entries.append({"name": child.name, "path": str(child), "type": "dir"})
            elif child.suffix.lower() == ".json":
                entries.append({"name": child.name, "path": str(child), "type": "annotations"})
            elif child.suffix.lower() in {".jpg", ".jpeg", ".png", ".bmp", ".webp", ".tif", ".tiff"}:
                images += 1
        parent = folder.parent
        return {
            "path": str(folder),
            "parent": str(parent) if _within(parent, import_roots) and str(parent) != str(folder) else None,
            "entries": entries,
            "images": images,
            "detected": _detect_dataset(folder),
        }

    def _detect_dataset(folder: Url) -> list[dict[str, Any]]:
        """The splits of the dataset a folder belongs to.

        Opening one split folder (say ``train/``) finds only its own file, so the parent is
        checked too: when it holds more splits, those are the dataset.
        """
        found = _detect_sources(folder)
        parent = folder.parent
        if len(found) <= 1 and str(parent) != str(folder) and _within(parent, import_roots):
            siblings = _detect_sources(parent)
            files = {s["annotations"] for s in siblings}
            if len(siblings) > len(found) and all(s["annotations"] in files for s in found):
                return siblings
        return found

    def _detect_sources(folder: Url) -> list[dict[str, Any]]:
        """COCO annotation files in a folder or its immediate subfolders, one per split."""
        found: list[dict[str, Any]] = []
        candidates: list[Url] = []
        try:
            children = folder.ls()
        except OSError:
            return found
        for child in children:
            if child.is_dir():
                try:
                    candidates.extend(c for c in child.ls() if c.suffix.lower() == ".json")
                except OSError:
                    continue
            elif child.suffix.lower() == ".json":
                candidates.append(child)
        for candidate in sorted(candidates, key=str):
            name = candidate.name.lower()
            if not any(hint in name for hint in ANNOTATION_HINTS):
                continue
            split = candidate.parent.name if str(candidate.parent) != str(folder) else (
                name.replace("instances_", "").replace(".json", "") or "train"
            )
            found.append({"split": split, "annotations": str(candidate), "images": str(candidate.parent)})
        return found

    @app.post("/api/import/preflight")
    def import_preflight(request: PreflightRequest = Body(...)) -> dict[str, Any]:
        from granum.importing import MEDIA_MODES, Source, run_preflight

        if request.media not in MEDIA_MODES:
            raise _error(400, f"media must be one of {list(MEDIA_MODES)}")
        if not request.sources:
            raise _error(400, "add at least one annotation file")
        sources = []
        for item in request.sources:
            annotations = _check_import_path(item.annotations)
            images = _check_import_path(item.images) if item.images else None
            sources.append(Source(split=item.split.strip(), annotations=str(annotations), images=str(images) if images else None))
        if any(not s.split for s in sources) or len({s.split for s in sources}) != len(sources):
            raise _error(400, "every file needs a distinct split name")

        def work(job: Any) -> Any:
            report = run_preflight(sources, media=request.media, progress=job.progress, cancel=job.cancel)
            preflight_media[job.id] = frozenset(
                (data.source.image_folder / str(image["file_name"])).resolved
                for data in report.parsed.values()
                for image in data.images
            )
            job.payload = report
            return report

        return jobs.start("preflight", work).to_dict()

    @app.post("/api/import/commit")
    def import_commit(request: ImportRequest = Body(...)) -> dict[str, Any]:
        from granum.importing import PreflightError, import_coco, resolve_options

        preflight = jobs.get(request.preflight_job)
        if preflight is None or preflight.kind != "preflight":
            raise _error(404, "that preflight is no longer available; run preflight again")
        if preflight.status != "done" or preflight.payload is None:
            raise _error(409, f"preflight is {preflight.status}, not done")
        if not request.project_name.strip():
            raise _error(400, "name the project to import into")
        from granum.importing.apply import suggest_dataset_name

        dataset_name = (request.dataset_name or "").strip() or suggest_dataset_name(preflight.payload, request.project_name.strip())
        splits = {s.split for s in preflight.payload.sources}
        clash = sorted(t.name for t in index.tables(request.project_name.strip())
                       if t.dataset_name == dataset_name and t.name in splits)
        if clash:
            raise _error(409, f"dataset {dataset_name!r} in {request.project_name!r} already has {', '.join(clash)}; choose another dataset name")
        try:
            resolve_options(preflight.payload, request.resolutions)
        except PreflightError as exc:
            raise _error(400, str(exc)) from exc

        def work(job: Any) -> Any:
            result = import_coco(
                preflight.payload,
                project_name=request.project_name.strip(),
                resolutions=request.resolutions,
                dataset_name=dataset_name,
                description=request.description,
                progress=job.progress,
                config=config,
            )
            job.progress("Indexing", 0, 1)
            index.refresh(force=True)
            return result

        return jobs.start("import", work).to_dict()

    @app.get("/api/jobs/{job_id}")
    def job_status(job_id: str) -> dict[str, Any]:
        job = jobs.get(job_id)
        if job is None:
            raise _error(404, "no such job; the service may have restarted")
        return job.to_dict()

    @app.post("/api/jobs/{job_id}/cancel")
    def job_cancel(job_id: str) -> dict[str, Any]:
        job = jobs.get(job_id)
        if job is None:
            raise _error(404, "no such job")
        job.cancel.set()
        return job.to_dict()

    # -- media --------------------------------------------------------------

    @app.get("/api/media")
    def media(
        url: str = Query(...),
        size: int | None = Query(None, ge=1, le=4096),
        project: str | None = Query(None),
        dataset: str | None = Query(None),
    ) -> Response:
        """Serve an image, preferring a published thumbnail.

        Media URLs are *not* required to sit under a scan root -- images legitimately
        live outside the project tree. They must instead be referenced by an indexed
        Table or by a preflight report held by this service, which is checked below.
        Without a published thumbnail, a requested size is rendered and cached, so a
        grid of 2000-pixel photos does not ship megabytes per cell.
        """
        target = Url(url)
        cache_key = f"{target}|{size or 0}"
        cached = cache.get(cache_key)
        if cached is not None:
            return Response(content=cached, media_type="image/jpeg" if size else _media_type(target))

        if not _is_referenced(target):
            raise _error(403, f"{target} is not referenced by any indexed Table")

        served = target
        if size is not None and project and dataset:
            cache_dir = ProjectLayout(config.project_root).thumbnails(project, dataset)
            found = thumbs.resolve([cache_dir], target, thumbs.nearest_size(size))
            if found is not None:
                served = found

        try:
            data = served.read_bytes()
        except Exception as exc:  # noqa: BLE001
            raise _error(404, f"could not read {served}: {exc}") from exc

        media_type = _media_type(served)
        if size is not None and served is target and len(data) > 64_000:
            try:
                data = thumbs.render_thumbnail(data, thumbs.nearest_size(size, RENDER_SIZES))
                media_type = "image/jpeg"
            except Exception:  # noqa: BLE001 - fall back to the original bytes
                pass
        cache.put(cache_key, data)
        return Response(content=data, media_type=media_type)

    referenced: dict[str, Any] = {"key": None, "urls": frozenset()}

    def _referenced_urls() -> frozenset[str]:
        """Every image URL referenced by an indexed Table, rebuilt only when the index changes."""
        entries = [e for e in index.entries() if e.type_name in {"table", "metrics_table"}]
        key = tuple(sorted(str(e.url) for e in entries))
        if referenced["key"] == key:
            return referenced["urls"]
        urls: set[str] = set()
        for entry in entries:
            try:
                table = Table.from_url(entry.url)
            except GranumError:
                continue
            columns = thumbs.image_columns(table)
            if not columns:
                continue
            arrow = table.to_arrow()
            for column in columns:
                for value in arrow.column(column).to_pylist():
                    if value:
                        urls.add(Url(value).resolved)
        referenced.update(key=key, urls=frozenset(urls))
        return referenced["urls"]

    def _is_referenced(target: Url) -> bool:
        resolved = target.resolved
        if resolved in _referenced_urls():
            return True
        live = {job.id for job in jobs.all()}
        for job_id in [k for k in preflight_media if k not in live]:
            preflight_media.pop(job_id, None)
        return any(resolved in urls for urls in preflight_media.values())

    # -- dashboard ------------------------------------------------------------

    dashboard = _dashboard_dir() if serve_dashboard else None
    if dashboard is not None:
        root = dashboard.resolve()

        @app.get("/{path:path}", include_in_schema=False)
        def dashboard_files(path: str) -> Response:
            if path.startswith("api/"):
                raise _error(404, "no such endpoint")
            candidate = (root / path).resolve()
            if path and candidate.is_file() and root in candidate.parents:
                return FileResponse(candidate)
            return FileResponse(root / "index.html", headers={"Cache-Control": "no-cache"})

    return app


def _media_type(url: Url) -> str:
    guessed, _ = mimetypes.guess_type(url.resolved)
    return guessed or "application/octet-stream"
