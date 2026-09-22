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

import hashlib
import io
import json
import mimetypes
import os
import re
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
from granum.core.prelabel import MODEL as PRELABEL_MODEL
from granum.core.prelabel import SOURCE
from granum.core.schemas import CategoricalLabelSchema, Geometry2DSchema, ImageSchema, Schema
from granum.core.url import Url, real_local_path
from granum.errors import GranumError
from granum.importing.example import is_example_project
from granum.licensing import LEASE_DAYS, LicenceError, Licensing, get_licensing
from granum.metrics.findings import RULES as RULES_FOR_HEALTH
from granum.processes import console_python, no_window
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
IMAGE_SUFFIXES_FOR_IMPORT = {".jpg", ".jpeg", ".png", ".bmp", ".webp", ".tif", ".tiff"}


#: Requests that change nothing, allowed while the licence makes the app read-only. Every
#: other write is refused then, so a new endpoint is read-only safe unless listed here.
READ_ONLY_WRITES = frozenset({
    "/api/images/boxes", "/api/augment/examples", "/api/import/preflight", "/api/reindex",
    "/api/embeddings",
    "/api/service/quit", "/api/licence/install", "/api/licence/remove",
    "/api/licence/code", "/api/licence/activate", "/api/licence/renew", "/api/licence/sign-out",
})
_READ_ONLY_PATTERNS = (re.compile(r"^/api/jobs/[^/]+/cancel$"),)


def _allowed_read_only(method: str, path: str) -> bool:
    if method in ("GET", "HEAD", "OPTIONS"):
        return True
    return path in READ_ONLY_WRITES or any(p.match(path) for p in _READ_ONLY_PATTERNS)


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
    #: Geometry column -> {property: kind} to add to its instances (e.g. segmentation).
    instance_properties: dict[str, dict[str, str]] = Field(default_factory=dict)
    name: str | None = None
    description: str = ""


class SourceRequest(BaseModel):
    split: str
    annotations: str
    images: str | None = None
    #: The layout it is in. Anything but ``coco`` is converted to COCO before preflight,
    #: so every import is checked by the same rules whatever it arrived as.
    format: str = "coco"
    #: YOLO only: which split of its data.yaml this source is.
    yolo_split: str | None = None


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


class RenameProjectRequest(BaseModel):
    new_name: str = Field(max_length=200)


class DeleteProjectRequest(BaseModel):
    """The project name typed again, so a project is never deleted by a stray click or request."""

    confirm: str


class ShipRequest(BaseModel):
    project: str
    dataset: str
    author: str = ""
    note: str = ""
    #: Set name -> the version to ship. Omitted: the newest version of every set.
    sets: dict[str, str] | None = None


class ReleaseRequest(BaseModel):
    project: str
    dataset: str
    name: str
    description: str = ""
    #: "all": every image of every set; "verified": only images marked verified.
    mode: str = "all"
    author: str = ""
    #: Augmented copies of the train set (granum.core.augment recipe); None for none.
    augmentation: dict[str, Any] | None = None


class EmbeddingRequest(BaseModel):
    project: str
    dataset: str
    embedder: str | None = Field(default=None, description="force one; the best installed is used otherwise")


class LicenceKeyRequest(BaseModel):
    key: str = Field(min_length=10, max_length=20_000)


class LicenceEmailRequest(BaseModel):
    email: str = Field(min_length=3, max_length=254)


class LicenceActivateRequest(BaseModel):
    email: str = Field(min_length=3, max_length=254)
    code: str = Field(min_length=4, max_length=12)


class DeleteReleaseRequest(BaseModel):
    project: str
    dataset: str
    release_id: str
    author: str = ""


class AugmentExample(BaseModel):
    recipe: dict[str, Any]
    #: Which end of each range to show.
    at: str = "max"


class AugmentExamplesRequest(BaseModel):
    project: str
    dataset: str
    #: Key -> one recipe to show; up to one per augmentation and end.
    items: dict[str, AugmentExample] = Field(max_length=40)
    #: The train row to show, as returned by an earlier call; None picks a typical one.
    row: int | None = None
    size: int = Field(320, ge=64, le=720)


class PullRequest(BaseModel):
    #: Project -> the class keys to take from it (granum.importing.library.class_key);
    #: an empty list takes every image of that project.
    selection: dict[str, list[str]] = Field(min_length=1, max_length=200)
    #: Keep boxes of classes not chosen, on the images pulled for the chosen ones.
    keep_other_labels: bool = False


class TrainingRequest(BaseModel):
    project: str
    train_table: str
    valid_table: str
    # Held out: scored once with the finished model, never used to pick it.
    test_table: str | None = None
    rounds: int = Field(12, ge=1, le=300)
    family: str = "yolo"
    version: str = "yolo26n.pt"
    image_size: int = 640
    track_learning: bool = True
    compare_with: str | None = None
    run_name: str | None = None


class ScreeningRequest(BaseModel):
    """Run one model over a dataset version's sets, to find labels worth checking."""

    project: str
    #: set name -> the table version to read it from, as a dataset version ships them.
    sets: dict[str, str] = Field(min_length=1, max_length=8)
    #: Exactly one of these: a run in this project whose weights to use, or a model that
    #: has never seen this data.
    weights_run: str | None = None
    pretrained: str | None = None
    image_size: int = 640
    run_name: str | None = None


class ExportRequest(BaseModel):
    """Write a dataset version out in somebody else's format."""

    project: str
    dataset: str
    #: A dataset version's id, or the current sets when left out.
    release_id: str | None = None
    format: str = "coco"
    #: Where the images go: beside the labels, or referenced where they already are.
    images: str = "symlink"


class TagRequest(BaseModel):
    """Put words on images, or take them off."""

    project: str
    dataset: str
    samples: list[str] = Field(min_length=1, max_length=200_000)
    add: list[str] = Field(default_factory=list, max_length=20)
    remove: list[str] = Field(default_factory=list, max_length=20)
    author: str = ""


class ViewRequest(BaseModel):
    """A named set of filters worth coming back to."""

    project: str
    dataset: str
    name: str = Field(max_length=60)
    state: dict[str, Any] = Field(default_factory=dict)
    author: str = ""


class PrelabelRequest(BaseModel):
    """Draft a set's labels with a model: a new version of each set, boxes marked as drafts."""

    project: str
    dataset: str
    #: The newest version of each set to draft. Writing off an older one would fork it.
    tables: list[str] = Field(min_length=1, max_length=8)
    weights_run: str | None = None
    pretrained: str | None = None
    #: ``empty`` leaves every labelled image alone; ``replace`` redraws them.
    mode: str = "empty"
    confidence: float = Field(0.4, ge=0.05, le=0.95)
    image_size: int = 640


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


class ImageBoxItem(BaseModel):
    table: str
    row: int = Field(ge=0)


class ImageBoxesRequest(BaseModel):
    project: str
    dataset: str
    items: list[ImageBoxItem] = Field(min_length=1, max_length=2000)


class ImportRequest(BaseModel):
    preflight_job: str
    project_name: str
    resolutions: dict[str, str] = Field(default_factory=dict)
    dataset_name: str | None = None
    description: str = ""
    """How many images each split should end up with; images move to meet it."""
    split_plan: dict[str, int] | None = None
    #: What the labels are for (granum.importing.tasks.TASKS); default: what preflight detected.
    tasks: list[str] | None = None


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
    licensing: Licensing | None = None,
) -> FastAPI:
    """Build the service. Injectable pieces keep it testable without a live server.

    ``allowed_hosts`` are the Host header values accepted (loopback names by default);
    ``allowed_origins`` are extra browser origins allowed cross-origin (none by default);
    ``data_roots`` bound where imports may read from (config ``service.data-roots``).
    ``licensing`` decides whether writes are allowed (:mod:`granum.licensing`).
    """
    config = config or get_config()
    licensing = licensing or get_licensing()
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
        if not _allowed_read_only(request.method, request.url.path):
            status = licensing.status()
            if status["mode"] != "full":
                return JSONResponse({"detail": f"Granum is read-only. {status['reason']}", "licence": status}, 402)
        return await call_next(request)

    # -- licence --------------------------------------------------------------

    def _licence_status() -> dict[str, Any]:
        return {**licensing.status(), "projects_used": len(index.projects()), "lease_days": LEASE_DAYS}

    @app.get("/api/licence")
    def licence() -> dict[str, Any]:
        """What the licence of this computer allows, and this computer's id."""
        return _licence_status()

    @app.post("/api/licence/install")
    def licence_install(request: LicenceKeyRequest = Body(...)) -> dict[str, Any]:
        try:
            licensing.install(request.key)
        except LicenceError as exc:
            raise _error(400, str(exc)) from exc
        return _licence_status()

    @app.post("/api/licence/remove")
    def licence_remove() -> dict[str, Any]:
        licensing.remove()
        return _licence_status()

    def _server_call(call: Any) -> dict[str, Any]:
        from granum.licensing.client import Refused, Unreachable

        try:
            call()
        except Unreachable as exc:
            raise _error(503, str(exc)) from exc
        except Refused as exc:
            raise HTTPException(status_code=400, detail={"message": str(exc), "code": exc.code}) from exc
        except LicenceError as exc:
            raise _error(400, str(exc)) from exc
        return _licence_status()

    @app.post("/api/licence/code")
    def licence_code(request: LicenceEmailRequest = Body(...)) -> dict[str, Any]:
        """Email a sign-in code (through the licence server)."""
        from granum.licensing.client import Refused, Unreachable

        try:
            sent = licensing.send_code(request.email)
        except Unreachable as exc:
            raise _error(503, str(exc)) from exc
        except (Refused, LicenceError) as exc:
            raise _error(400, str(exc)) from exc
        return {"sent": True, "minutes": sent.get("minutes", 10), **({"dev_code": sent["dev_code"]} if "dev_code" in sent else {})}

    @app.post("/api/licence/activate")
    def licence_activate(request: LicenceActivateRequest = Body(...)) -> dict[str, Any]:
        """Sign in with email and code: this computer gets its plan, or a free trial."""
        return _server_call(lambda: licensing.activate(request.email, request.code))

    @app.post("/api/licence/renew")
    def licence_renew() -> dict[str, Any]:
        return _server_call(licensing.renew)

    @app.post("/api/licence/sign-out")
    def licence_sign_out() -> dict[str, Any]:
        """Free this computer on the server and remove the key here."""
        return _server_call(licensing.sign_out)

    # -- guards -------------------------------------------------------------

    def _roots() -> list[Url]:
        return list(index.roots)

    def _within(url: Url, roots: list[Url]) -> bool:
        resolved = real_local_path(url.resolved) if url.scheme in ("", "file") else url.resolved
        for root in roots:
            root_text = real_local_path(root.resolved) if root.scheme in ("", "file") else root.resolved
            root_text = root_text.rstrip("/")
            if resolved == root_text or resolved.startswith(root_text + "/"):
                return True
        return False

    def _check_within_roots(url: Url) -> Url:
        """Refuse any URL outside the configured scan roots."""
        if not _within(url, _roots()):
            raise _error(403, f"{url} is outside the configured scan roots")
        return url

    def _pulls_dir() -> Url:
        """Where COCO files pulled from existing projects are written, for preflight to read."""
        return config.project_root / ".pulls"

    def _check_import_path(text: str) -> Url:
        from granum.importing.example import examples_dir

        url = Url(os.path.expanduser(text))
        if _within(url, [_pulls_dir(), examples_dir(config.project_root)]):
            return url
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

    @app.post("/api/service/quit")
    def service_quit() -> dict[str, Any]:
        """Stop the service when nothing is running in it; the app's window calls this on close
        where no service manager would otherwise ever stop it (Windows)."""
        busy = [job.kind for job in jobs.all() if job.status == "running"]
        if busy:
            return {"stopping": False, "busy": busy}

        import signal
        import threading
        import time

        def stop() -> None:
            time.sleep(0.3)  # let this response reach the caller
            signal.raise_signal(signal.SIGINT)  # uvicorn's own graceful shutdown
            time.sleep(15)
            os._exit(0)

        threading.Thread(target=stop, daemon=True).start()
        return {"stopping": True, "busy": []}

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

    @app.get("/api/projects/summary")
    def projects_summary() -> dict[str, Any]:
        """Every project with what the projects page shows: types, size, review progress,
        dataset versions, runs, last activity and a few images to recognise it by."""
        from granum.core.qa import QaLog

        out = []
        for project in index.projects():
            name = project["name"]
            tasks = _dataset_tasks(name)
            datasets = sorted({t.dataset_name for t in index.tables(name) if t.dataset_name})
            images = verified = boxes = versions = 0
            classes: set[str] = set()
            sets: set[str] = set()
            covers: list[dict[str, str]] = []
            times = [t.created for t in index.tables(name)] + [r.created for r in index.runs(name)]
            for dataset in datasets:
                try:
                    newest = _review_sets(name, dataset)
                except HTTPException:
                    continue
                log = QaLog(name, dataset, config=config)
                statuses = log.current()
                shipments = log.shipments()
                versions += len(shipments)
                times += [s["time"] for s in shipments]
                times += [v["time"] for v in statuses.values() if v.get("time")]
                ordered = sorted(newest.values(), key=lambda t: (not t.base_name.startswith("train"), t.base_name))
                for table in ordered:
                    sets.add(table.base_name)
                    listed = _version_images(table)
                    images += len(listed)
                    verified += sum(1 for image in listed if statuses.get(image, {}).get("status") == "reviewed")
                    column = next((n for n in table.columns if isinstance(table.schema[n], Geometry2DSchema)), None)
                    if column:
                        classes.update(e.display_name or e.internal_name for e in (table.schema[column].value_map or {}).values())
                        boxes += _box_counts(table, column)["box_count"]
                    if len(covers) < 4 and listed:
                        # Spread over the set, not its first few frames of one sequence.
                        step = max(1, len(listed) // 4)
                        for image in listed[::step][: 4 - len(covers)]:
                            covers.append({"image": image, "dataset": dataset})
            runs = sorted(index.runs(name), key=lambda r: r.created, reverse=True)
            last_run = None
            if runs:
                payload = runs[0].payload
                last_run = {"name": runs[0].name, "created": runs[0].created, "status": payload.get("status")}
            out.append({
                "name": name,
                "tasks": sorted({t for ts in tasks.values() for t in ts}),
                "datasets": len(datasets),
                "sets": sorted(sets),
                "images": images,
                "verified": verified,
                "boxes": boxes,
                "classes": len(classes),
                "versions": versions,
                "runs": project["runs"],
                "last_run": last_run,
                "updated": max(times) if times else None,
                "covers": covers,
                "example": is_example_project(ProjectLayout(config.project_root), name),
            })
        return {"projects": out}

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

    @app.post("/api/projects/{project_name}/rename")
    def rename_project_endpoint(project_name: str, request: RenameProjectRequest = Body(...)) -> dict[str, Any]:
        """Rename a project, rewriting every path and name recorded inside it."""
        from granum.core.projects import ProjectError, rename_project

        busy = [j for j in jobs.all() if j.status == "running" and j.payload == project_name]
        if busy:
            raise _error(409, f"{project_name} is busy ({busy[0].kind}); wait for it to finish or cancel it")
        try:
            done = rename_project(config.project_root, project_name, request.new_name)
        except ProjectError as exc:
            status = 404 if "no project named" in str(exc) else 409 if "already exists" in str(exc) else 400
            raise _error(status, str(exc)) from exc
        index.refresh(force=True)
        return {"name": done["new"], "files_updated": done["files_updated"]}

    @app.post("/api/projects/{project_name}/delete")
    def delete_project(project_name: str, request: DeleteProjectRequest = Body(...)) -> dict[str, Any]:
        """Delete a project for good: its datasets, versions, runs, reviews, shipments and import
        reports, and the model weights its runs wrote. Original image files are not touched."""
        import shutil

        from granum.core.layout import sanitize

        if request.confirm != project_name:
            raise _error(400, "type the project name exactly to confirm")
        summary = next((p for p in index.projects() if p["name"] == project_name), None)
        layout = ProjectLayout(config.project_root)
        folder = layout.project(project_name)
        if summary is None and not folder.exists():
            raise _error(404, f"no project named {project_name!r}")
        if sanitize(project_name) != project_name or folder.parent.path.rstrip("/") != layout.projects_dir.path.rstrip("/"):
            raise _error(400, "this project cannot be deleted from here")
        outside = [e for e in index.entries() if e.project_name == project_name and not str(e.url).startswith(str(folder))]
        if outside:
            raise _error(400, f"{project_name} has data outside {folder}; delete it there instead")
        busy = [j for j in jobs.all() if j.status == "running" and j.payload == project_name]
        if busy:
            raise _error(409, f"{project_name} is busy ({busy[0].kind}); wait for it to finish or cancel it")

        # Training output that belongs to this project's runs: only folders its runs recorded.
        removed_training: list[str] = []
        if config.project_root.scheme == "file":
            from granum.cli.desktop import training_dir

            work = training_dir(Path(config.project_root.path)).resolve()
            for entry in index.runs(project_name):
                try:
                    weights = Run.from_url(entry.url).parameters.get("weights")
                except GranumError:
                    continue
                for kind in ("runs", "exports"):
                    candidate = (work / kind / entry.name).resolve()
                    recorded = weights and str(Path(str(weights)).resolve()).startswith(str(work / "runs" / entry.name))
                    if recorded and candidate.is_relative_to(work) and candidate.is_dir():
                        shutil.rmtree(candidate, ignore_errors=True)
                        removed_training.append(str(candidate))

        tables = summary["tables"] if summary else 0
        runs = summary["runs"] if summary else 0
        try:
            folder.fs.rm(folder.path, recursive=True)
        except FileNotFoundError:
            pass
        index.refresh(force=True)
        return {"deleted": project_name, "tables": tables, "runs": runs, "training_output": removed_training}

    def _dataset_tasks(project: str) -> dict[str, list[str]]:
        """Dataset name -> the tasks chosen when it was imported (object detection before tasks existed)."""
        from granum.importing.tasks import DEFAULT_TASK, tasks_of

        tasks: dict[str, list[str]] = {}
        for entry in index.tables(project):
            found = tasks_of((entry.payload.get("producer") or {}).get("args") or {})
            if found:
                tasks[entry.dataset_name] = found
            else:
                tasks.setdefault(entry.dataset_name, [DEFAULT_TASK])
        return tasks

    @app.get("/api/projects/{project_name}/tables")
    def project_tables(project_name: str) -> dict[str, Any]:
        out = []
        tasks = _dataset_tasks(project_name)
        for entry in index.tables(project_name):
            payload = entry.to_dict()
            payload["tasks"] = tasks.get(entry.dataset_name)
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
                instance_properties=request.instance_properties,
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
                    "observations": item["observations"],
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

    # Findings read every stored box of every round; metrics tables are write-once, so the
    # set of them is the cache key. Review decisions are merged fresh on every request.
    findings_cache: dict[str, tuple[tuple[str, ...], list[dict[str, Any]]]] = {}

    def _findings_splits(run: Run) -> list[dict[str, Any]]:
        """What each set of a run's recorded predictions says about its labels.

        Two kinds of evidence, read by the same rules. A training run watched every image
        over many rounds, and a finding earns its place by recurring. A label check saw each
        image once, and a finding is worth what the model's confidence is worth. Which one
        this was is decided by the recorded rounds rather than by what the run calls itself,
        so a training run that only ever finished one round is still read for what it holds.
        """
        from granum.metrics.findings import (
            FindingPolicy,
            competent_from,
            image_findings,
            image_trust,
            pass_competence,
            pass_findings,
        )

        tables = [t for t in run.metrics_tables()
                  if t.foreign_table_url is not None and {"bbs_predicted", "gt_match", "epoch"} <= set(t.columns)]
        key = tuple(sorted(str(t.url) for t in tables))
        hit = findings_cache.get(str(run.url))
        if hit is not None and hit[0] == key:
            return hit[1]
        policy = FindingPolicy()
        by_split: dict[str, list[MetricsTable]] = {}
        for table in tables:
            by_split.setdefault(str(table.constants.get("split") or "all"), []).append(table)
        train_url = str(run.parameters.get("train_table") or "")
        # A model that was never taught some of this dataset's classes has no opinion on
        # their labels, and the rules must not read its silence as a finding.
        known = (None if run.parameters.get("covers_all_classes", True)
                 else {int(c) for c in (run.parameters.get("known_classes") or [])})
        screening = run.parameters.get("kind") == "screening"
        out = []
        for split, split_tables in by_split.items():
            source_url = str(split_tables[0].foreign_table_url)
            records: list[dict[str, Any]] = []
            for table in split_tables:
                if str(table.foreign_table_url) != source_url:
                    continue  # a set re-collected on another version is not mixed in
                records.extend(table.to_arrow().select(["example_id", "epoch", "tp", "fn", "bbs_predicted", "gt_match"]).to_pylist())
            try:
                source = Table.from_url(source_url)
            except GranumError:
                continue
            box_column = next((n for n in source.columns if isinstance(source.schema[n], Geometry2DSchema)), None)
            if box_column is None:
                continue
            arrow = source.to_arrow()
            images = arrow.column("image").to_pylist() if "image" in source.columns else [None] * len(source)
            truths = arrow.column(box_column).to_pylist()
            value_map = source.schema[box_column].value_map or {}
            start = competent_from(records, policy)
            # One round of stored boxes is one pass over the set, whoever recorded it.
            with_boxes = {int(r["epoch"]) for r in records
                          if r.get("epoch") is not None and r.get("bbs_predicted") is not None}
            single_pass = len(with_boxes) == 1
            rounds: dict[int, dict[int, dict[str, Any]]] = {}
            for record in records:
                example = int(record["example_id"])
                current = rounds.setdefault(example, {}).get(int(record["epoch"]))
                if current is not None and current.get("bbs_predicted") is not None and record.get("bbs_predicted") is None:
                    continue  # a round recorded twice: keep the copy with boxes
                rounds[example][int(record["epoch"])] = record
            # One pass is judged against what the pass was worth on this set as a whole:
            # a class the model cannot find here is not a class it can accuse labels of.
            competence = None
            if single_pass:
                only = next(iter(with_boxes), None)
                competence = pass_competence(
                    ((truths[example] or {}).get("instances", []), per_round[only])
                    for example, per_round in rounds.items()
                    if example < len(truths) and only in per_round
                )
            flagged = []
            window = observed = 0
            for example, per_round in rounds.items():
                if example >= len(truths):
                    continue
                truth = (truths[example] or {}).get("instances", [])
                if single_pass:
                    only = next(iter(with_boxes), None)
                    record = per_round.get(only) if only is not None else None
                    found = (pass_findings(truth, record, policy, known=known, competence=competence)
                             if record else [])
                    info = {"observed": 1, "window": 1 if record else 0}
                else:
                    found, info = image_findings(truth, per_round, policy, from_epoch=start)
                window = max(window, info["window"])
                observed = max(observed, info["observed"])
                if found:
                    labelled = len([t for t in truth if not t.get("iscrowd")])
                    flagged.append({
                        "example_id": example,
                        "image": images[example],
                        "width": (truths[example] or {}).get("width"),
                        "height": (truths[example] or {}).get("height"),
                        "labels": labelled,
                        "score": found[0]["score"],
                        # How much of this image's labelling to trust, decided by its worst
                        # box rather than by the average of them.
                        "trust": image_trust(found, labelled, policy),
                        "findings": found,
                    })
            flagged.sort(key=lambda item: (-item["score"], item["example_id"]))
            out.append({
                "split": split,
                "table": source_url,
                "table_name": source.name,
                "dataset": source.dataset_name,
                "project": source.project_name,
                "held_out": source_url != train_url if train_url else split != "train",
                "images_total": len(rounds),
                # One pass has no warm-up to skip and no rounds to count: saying an epoch
                # here would dress a screening up as a run.
                "single_pass": single_pass,
                # What the pass was worth per class, so the page can say which classes were
                # judged at all rather than leaving the reader to wonder where they went.
                "competence": competence.to_dict() if competence is not None else None,
                "competent_from": None if single_pass else start,
                "observed": observed,
                "window": window,
                "classes": {str(k): (v.display_name or v.internal_name) for k, v in value_map.items()},
                "images": flagged,
            })
        order = {"train": 0, "valid": 1, "val": 1, "test": 2}
        out.sort(key=lambda s_: order.get(s_["split"], 9))
        for split in out:
            split["screening"] = screening
        findings_cache[str(run.url)] = (key, out)
        return out

    @app.get("/api/run/findings")
    def run_findings(url: str = Query(...)) -> dict[str, Any]:
        """Labels worth a reviewer's time, per set, ranked, with the evidence for each."""
        from granum.core.reviews import ReviewLog
        from granum.core.url import sample_key
        from granum.metrics.findings import RULES, RULES_VERSION, FindingPolicy

        run = _run_at(url)
        splits = []
        for split in _findings_splits(run):
            decided = ReviewLog(split["project"], split["dataset"], config=config).current() if split["dataset"] else {}
            images = []
            counts = dict.fromkeys(RULES, 0)
            #: (labelled class, the class the model says) -> how often. A pair that keeps
            #: coming back is a distinction the dataset does not draw consistently, which is
            #: a fact about the labelling rather than about any one box.
            swaps: dict[tuple[int, int], int] = {}
            for item in split["images"]:
                event = decided.get(sample_key(item["image"])) if item["image"] else None
                images.append({**item, "review": {k: event.get(k) for k in ("status", "reason", "time", "reviewer")} if event else None})
                for finding in item["findings"]:
                    counts[finding["rule"]] += 1
                    if finding["rule"] == "wrong_class" and finding.get("predicted_label") is not None:
                        pair = (int(finding["label"]), int(finding["predicted_label"]))
                        swaps[pair] = swaps.get(pair, 0) + 1
            top = sorted(swaps.items(), key=lambda item: (-item[1], item[0]))[:8]
            splits.append({**{k: v for k, v in split.items() if k != "images"}, "counts": counts,
                           "swaps": [{"label": a, "predicted": b, "count": n} for (a, b), n in top],
                           "images": images})
        return {
            "url": str(run.url),
            "name": run.name,
            "rules_version": RULES_VERSION,
            "policy": FindingPolicy().to_dict(),
            # What produced the predictions, so the page can say how strong the evidence is.
            "kind": "screening" if run.parameters.get("kind") == "screening" else "training",
            "model": {
                "with": run.parameters.get("screened_with"),
                "from_run": run.parameters.get("screened_from_run"),
                "version": run.parameters.get("version"),
                "covers_all_classes": bool(run.parameters.get("covers_all_classes", True)),
                "known_classes": run.parameters.get("known_classes") or [],
            } if run.parameters.get("kind") == "screening" else None,
            # Runs that did not save the model's boxes each round have nothing to judge.
            "stores_boxes": any(s_["observed"] > 0 for s_ in splits),
            "splits": splits,
        }

    # -- reading one run: confusion, per class, threshold -------------------------------

    #: One evaluation per (run, split, operating point). The sweep walks every threshold
    #: over every image, which is seconds on a large set and instant from here.
    evaluation_cache: dict[str, dict[str, Any]] = {}

    #: One split's records per (run, split): reading them is most of the cost, and every
    #: operating point the reader tries asks the same question of the same rows.
    evaluation_records: dict[str, dict[str, Any]] = {}

    def _evaluation_records(run: Run, split: str | None) -> tuple[dict[str, Any] | None, list[str]]:
        """One split's per-image records, and the names of the splits there are."""
        order = {"valid": 0, "val": 0, "test": 1, "train": 2}
        names = sorted({str(table.constants.get("split") or "all") for table in run.metrics_tables()
                        if table.foreign_table_url is not None},
                       key=lambda name: (order.get(name, 9), name))
        chosen = split if split in names else (names[0] if names else None)
        if chosen is None:
            return None, names
        key = f"{run.url}|{chosen}"
        entry = evaluation_records.get(key)
        if entry is None:
            entry = _evaluation_data(run, only=chosen).get(chosen)
            if entry is None or entry.get("unread"):
                return None, names
            if len(evaluation_records) > 4:
                evaluation_records.pop(next(iter(evaluation_records)))
            evaluation_records[key] = entry
        return entry, names

    def _evaluation(run: Run, split: str | None, confidence: float) -> dict[str, Any]:
        from granum.metrics.evaluation import (
            EVALUATION_VERSION,
            EvalPolicy,
            best_threshold,
            class_matches,
            confusion,
            per_class,
            scores,
            sweep,
        )

        key = f"{run.url}|{split}|{round(confidence, 3)}"
        hit = evaluation_cache.get(key)
        if hit is not None:
            return hit
        entry, names = _evaluation_records(run, split)
        if entry is None:
            return {"url": str(run.url), "name": run.name, "splits": names, "split": None,
                    "version": EVALUATION_VERSION, "stores_boxes": False}
        policy = EvalPolicy(operating_confidence=confidence)
        records = [{**record, "image": image} for image, record in entry["images"].items()]
        classes = {int(k): v for k, v in entry["classes"].items()}
        # One matching pass feeds both the table and the sweep; on a set of 39,000 labels
        # that is the difference between a second and three quarters of a minute.
        matches = class_matches(records, policy)
        rows = per_class(records, policy, classes, matches=matches)
        tp = sum(row["tp"] for row in rows)
        fp = sum(row["fp"] for row in rows)
        fn = sum(row["fn"] for row in rows)
        aps = [row["ap"] for row in rows if row["ap"] is not None]
        curve = sweep(records, policy, matches=matches)
        payload = {
            "url": str(run.url),
            "name": run.name,
            "version": EVALUATION_VERSION,
            "splits": names,
            "split": entry["split"],
            "set": entry["set"],
            "table": entry["table"],
            "dataset": entry["dataset"],
            "project": entry["project"],
            "epoch": entry["epoch"],
            "stores_boxes": True,
            "policy": policy.to_dict(),
            "images": len(records),
            "headline": {"tp": tp, "fp": fp, "fn": fn, "labels": tp + fn, **scores(tp, fp, fn),
                         "map50": round(float(sum(aps) / len(aps)), 4) if aps else None},
            "classes": entry["classes"],
            "per_class": rows,
            "confusion": confusion(records, policy),
            "curve": curve,
            # Where the pooled F1 peaks: the threshold a team would usually ship with, which
            # is otherwise guessed.
            "best_confidence": best_threshold(curve),
        }
        if len(evaluation_cache) > 8:
            evaluation_cache.pop(next(iter(evaluation_cache)))
        evaluation_cache[key] = payload
        return payload

    @app.get("/api/run/evaluation")
    def run_evaluation(url: str = Query(...), split: str | None = Query(None),
                       confidence: float = Query(0.25, ge=0.01, le=0.99)) -> dict[str, Any]:
        """What a run's predictions say about one set: confusion, per class, and a sweep."""
        return _evaluation(_run_at(url), split, confidence)

    @app.get("/api/run/evaluation/examples")
    def run_evaluation_examples(
        url: str = Query(...),
        split: str | None = Query(None),
        truth: int | None = Query(None, description="labelled class; omitted means a box over nothing"),
        predicted: int | None = Query(None, description="predicted class; omitted means nothing predicted"),
        confidence: float = Query(0.25, ge=0.01, le=0.99),
        limit: int = Query(60, ge=1, le=200),
    ) -> dict[str, Any]:
        """The objects behind one cell of the matrix, as crops with the image they came from."""
        from granum.metrics.evaluation import EvalPolicy, examples

        if truth is None and predicted is None:
            raise _error(400, "ask for a labelled class, a predicted class, or both")
        entry, _names = _evaluation_records(_run_at(url), split)
        if entry is None:
            raise _error(404, "this run did not store the model's boxes")
        records = [{**record, "image": image} for image, record in entry["images"].items()]
        found = examples(records, truth_label=truth, predicted_label=predicted,
                         policy=EvalPolicy(operating_confidence=confidence), limit=limit)
        return {"split": entry["split"], "dataset": entry["dataset"], "project": entry["project"],
                "classes": entry["classes"], "truth": truth, "predicted": predicted, "examples": found}

    # -- comparing two runs ------------------------------------------------------------

    def _evaluation_data(run: Run, only: str | None = None) -> dict[str, dict[str, Any]]:
        """Per split: the last round the run recorded, as per-image results keyed by image.

        The round chosen is the last one whose boxes were kept, because that is the only
        round a class or size slice can be computed from; when no round kept boxes it is
        simply the last one, and the caller learns that from ``stores_boxes``.

        ``only`` reads one split and names the rest without touching them. A run that
        tracked learning on a large training set holds twelve rounds of boxes for every
        image of it; reading those to answer a question about the validation set costs
        forty seconds and tells the reader nothing.
        """
        from granum.core.url import sample_key

        by_split: dict[str, list[MetricsTable]] = {}
        for table in run.metrics_tables():
            if table.foreign_table_url is None or not {"example_id", "tp", "fp", "fn"} <= set(table.columns):
                continue
            by_split.setdefault(str(table.constants.get("split") or "all"), []).append(table)

        out: dict[str, dict[str, Any]] = {}
        for split, tables in by_split.items():
            if only is not None and split != only:
                # Named, not read: enough for a picker, and the split itself is one click away.
                out[split] = {"split": split, "unread": True, "stores_boxes": True, "images": {}}
                continue
            # A split re-collected on a newer version of its set is not mixed with the old one.
            source_url = str(sorted(tables, key=lambda t: t.name)[-1].foreign_table_url)
            records: list[dict[str, Any]] = []
            for table in tables:
                if str(table.foreign_table_url) != source_url:
                    continue
                columns = [c for c in ("example_id", "epoch", "tp", "fp", "fn", "bbs_predicted", "gt_match")
                           if c in table.columns]
                records.extend(table.to_arrow().select(columns).to_pylist())
            if not records:
                continue
            with_boxes = [r for r in records if r.get("bbs_predicted")]
            epochs = [int(r["epoch"]) for r in (with_boxes or records) if r.get("epoch") is not None]
            epoch = max(epochs) if epochs else None
            chosen: dict[int, dict[str, Any]] = {}
            for record in records:
                if epoch is not None and int(record.get("epoch") or 0) != epoch:
                    continue
                example = int(record["example_id"])
                current = chosen.get(example)
                if current is not None and current.get("bbs_predicted") and not record.get("bbs_predicted"):
                    continue  # the same round written twice: keep the copy with boxes
                chosen[example] = record
            try:
                source = Table.from_url(source_url)
            except GranumError:
                continue
            box_column = next((n for n in source.columns if isinstance(source.schema[n], Geometry2DSchema)), None)
            arrow = source.to_arrow()
            images = arrow.column("image").to_pylist() if "image" in source.columns else [None] * len(source)
            truths = arrow.column(box_column).to_pylist() if box_column else [None] * len(source)
            value_map = (source.schema[box_column].value_map or {}) if box_column else {}
            rows: dict[str, dict[str, Any]] = {}
            for example, record in chosen.items():
                if example >= len(images) or images[example] is None:
                    continue
                rows[sample_key(images[example])] = {
                    "example_id": example,
                    "tp": int(record.get("tp") or 0),
                    "fp": int(record.get("fp") or 0),
                    "fn": int(record.get("fn") or 0),
                    "truth": truths[example],
                    "predicted": record.get("bbs_predicted"),
                    "gt_match": record.get("gt_match"),
                }
            out[split] = {
                "split": split,
                "set": f"{source.dataset_name}/{source.base_name or split}",
                "table": source_url,
                "table_name": source.name,
                "dataset": source.dataset_name,
                "project": source.project_name,
                "epoch": epoch,
                "stores_boxes": bool(with_boxes),
                "classes": {str(k): (v.display_name or v.internal_name) for k, v in value_map.items()},
                "images": rows,
            }
        return out

    def _table_labels(url_text: str | None) -> dict[str, Any] | None:
        """A table's labelled boxes keyed by image, for diffing one version against another."""
        from granum.core.url import sample_key

        if not url_text:
            return None
        try:
            table = Table.from_url(_check_within_roots(Url(url_text)))
        except (GranumError, HTTPException):
            return None
        box_column = next((n for n in table.columns if isinstance(table.schema[n], Geometry2DSchema)), None)
        if box_column is None or "image" not in table.columns:
            return None
        arrow = table.to_arrow()
        images = arrow.column("image").to_pylist()
        boxes = arrow.column(box_column).to_pylist()
        return {sample_key(image): value for image, value in zip(images, boxes) if image is not None}

    def _data_change(baseline_url: str | None, candidate_url: str | None, policy: Any) -> dict[str, Any]:
        """How one run's set differs from the other's, or why that could not be worked out."""
        from granum.metrics.comparison import label_change

        if not baseline_url or not candidate_url:
            return {"known": False, "reason": "one of the runs did not record which version it used"}
        if baseline_url == candidate_url:
            return {"known": True, "identical": True, "baseline": baseline_url, "candidate": candidate_url}
        before, after = _table_labels(baseline_url), _table_labels(candidate_url)
        if before is None or after is None:
            return {"known": False, "reason": "a version used by these runs is no longer readable"}
        return {"known": True, "identical": False, "baseline": baseline_url, "candidate": candidate_url,
                **label_change(before, after, policy)}

    def _review_cost(project: str, dataset: str | None, since: str, until: str) -> dict[str, Any]:
        from granum.core.reviews import ReviewLog
        from granum.metrics.comparison import review_cost

        if not dataset:
            return {"known": False, "reason": "the runs' data is not part of a reviewed dataset"}
        events = ReviewLog(project, dataset, config=config).events()
        return {"known": True, "dataset": dataset, **review_cost(events, since=since, until=until)}

    def _held_out(run: Run, data: dict[str, dict[str, Any]], split: str) -> bool:
        train_table = str(run.parameters.get("train_table") or "")
        return data[split]["table"] != train_table if train_table else split != "train"

    @app.get("/api/runs/compare")
    def runs_compare(
        baseline: str = Query(...),
        candidate: str = Query(...),
        split: str | None = Query(None),
        limit: int = Query(200, ge=0, le=20_000),
        download: bool = Query(False, description="the whole report as a file, nothing left out"),
    ) -> Any:
        """Two runs on the same evaluation set: what improved, what regressed, and what it is worth.

        Refuses rather than averages when the two were not scored on the same set under the
        same rules (:func:`granum.metrics.comparison.compatibility_checks`). With
        ``download`` the same report comes back as a JSON file with every image in it.
        """
        from granum.core.layout import sanitize
        from granum.core.objects.base import utcnow
        from granum.metrics.comparison import (
            REPORT_VERSION,
            ComparePolicy,
            class_slices,
            compare_samples,
            compatibility_checks,
            headline,
            interpretation,
            run_cost,
            size_slices,
        )

        policy = ComparePolicy()
        runs = {"baseline": _run_at(baseline), "candidate": _run_at(candidate)}
        if str(runs["baseline"].url) == str(runs["candidate"].url):
            raise _error(400, "a run cannot be compared with itself")
        data = {side: _evaluation_data(run) for side, run in runs.items()}
        shared = [s for s in data["baseline"] if s in data["candidate"]]
        order = {"test": 0, "valid": 1, "val": 1, "train": 8, "all": 9}
        shared.sort(key=lambda s: (0 if _held_out(runs["candidate"], data["candidate"], s) else 1, order.get(s, 5), s))
        chosen = split or (shared[0] if shared else None)
        if chosen is not None and chosen not in data["candidate"]:
            raise _error(404, f"run {runs['candidate'].name!r} has no per-image results for {chosen!r}")

        sides = {}
        for side, run in runs.items():
            parameters = run.parameters
            evaluation = data[side].get(chosen) if chosen else None
            sides[side] = {
                "url": str(run.url),
                "name": run.name,
                "created": run.created,
                "status": run.status,
                "set": evaluation["set"] if evaluation else None,
                "table": evaluation["table"] if evaluation else None,
                "dataset": evaluation["dataset"] if evaluation else None,
                "table_name": evaluation["table_name"] if evaluation else None,
                "epoch": evaluation["epoch"] if evaluation else None,
                "stores_boxes": bool(evaluation and evaluation["stores_boxes"]),
                "classes": evaluation["classes"] if evaluation else {},
                "evaluator": parameters.get("evaluator") or {},
                "seed": parameters.get("seed"),
                "recipe": {k: parameters.get(k) for k in ("framework", "version", "epochs", "imgsz", "batch")},
                "train_table": parameters.get("train_table"),
                "train_version": parameters.get("train_version"),
                "score_labels": parameters.get("score_labels"),
                "map50": parameters.get("score_map50"),
                "splits": sorted(data[side]),
            }

        checks = compatibility_checks(sides["baseline"], sides["candidate"])
        train_change = _data_change(sides["baseline"]["train_table"], sides["candidate"]["train_table"], policy)
        data_changed = bool(train_change.get("known") and not train_change.get("identical"))
        reading = interpretation(checks, data_changed)
        report: dict[str, Any] = {
            "report_version": REPORT_VERSION,
            "generated": utcnow(),
            "project": runs["candidate"].project_name,
            "policy": policy.to_dict(),
            "split": chosen,
            "shared_splits": shared,
            "runs": sides,
            "checks": checks,
            "interpretation": reading,
            "training_data": train_change,
        }
        if reading["kind"] == "blocked":
            return report

        baseline_rows = data["baseline"][chosen]["images"]
        candidate_rows = data["candidate"][chosen]["images"]
        samples = compare_samples(baseline_rows, candidate_rows, policy)
        pairs = [(baseline_rows[key], candidate_rows[key]) for key in baseline_rows if key in candidate_rows]
        with_boxes = [p for p in pairs if p[0].get("predicted") is not None and p[1].get("predicted") is not None]
        names = {int(k): v for k, v in (data["candidate"][chosen]["classes"] or {}).items()}

        report["headline"] = {
            **headline({"map50": sides["baseline"]["map50"]}, {"map50": sides["candidate"]["map50"]}, policy),
            "scored_on": {side: sides[side]["score_labels"] for side in sides},
            "same_labels": sides["baseline"]["score_labels"] == sides["candidate"]["score_labels"],
            "source": "each run's own final score, recorded when it finished",
        }
        report["samples"] = {
            "counts": samples["counts"],
            "baseline": samples["baseline"],
            "candidate": samples["candidate"],
            "shared": samples["shared"],
            "images": samples["images"] if download or limit == 0 else samples["images"][:limit],
            "shown": len(samples["images"]) if download else min(limit, len(samples["images"])),
            "only_baseline": samples["only_baseline"] if download else samples["only_baseline"][:limit],
            "only_candidate": samples["only_candidate"] if download else samples["only_candidate"][:limit],
        }
        report["slices"] = {
            "known": bool(with_boxes),
            "images": len(with_boxes),
            "reason": None if with_boxes else "neither run kept its predicted boxes, so slices cannot be computed",
            "classes": class_slices(with_boxes, policy, names) if with_boxes else [],
            "sizes": size_slices(with_boxes, policy) if with_boxes else [],
        }
        report["evaluation_data"] = (
            {"known": True, "identical": True, "baseline": sides["baseline"]["table"], "candidate": sides["candidate"]["table"]}
            if sides["baseline"]["table"] == sides["candidate"]["table"]
            else _data_change(sides["baseline"]["table"], sides["candidate"]["table"], policy)
        )
        report["cost"] = {
            "baseline": run_cost(runs["baseline"].created, runs["baseline"].aggregate_metrics(), sides["baseline"]["recipe"]),
            "candidate": run_cost(runs["candidate"].created, runs["candidate"].aggregate_metrics(), sides["candidate"]["recipe"]),
            "review": _review_cost(
                runs["candidate"].project_name, data["candidate"][chosen]["dataset"],
                min(runs["baseline"].created, runs["candidate"].created),
                max(runs["baseline"].created, runs["candidate"].created),
            ),
        }
        if not download:
            return report
        name = sanitize(f"{runs['baseline'].name}-vs-{runs['candidate'].name}")
        return JSONResponse(report, headers={"content-disposition": f'attachment; filename="{name}.json"'})

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

    version_images: dict[str, list[str]] = {}

    def _version_images(table: Table) -> list[str]:
        """The image references of a version. Versions never change, so this is cached."""
        key = str(table.url)
        if key not in version_images:
            from granum.core.curation import CurationError, image_column

            try:
                column = image_column(table)
                version_images[key] = [v for v in table.to_arrow().column(column).to_pylist() if v]
            except CurationError:
                version_images[key] = []
            if len(version_images) > 512:
                version_images.pop(next(iter(version_images)))
        return version_images[key]

    def _set_versions(project: str, dataset: str) -> dict[str, list[dict[str, Any]]]:
        """Every version of every reviewable set, newest first."""
        from granum.core.curation import HOLDING_SETS, is_release

        by_set: dict[str, list[dict[str, Any]]] = {}
        for entry in index.tables(project):
            if entry.dataset_name != dataset:
                continue
            try:
                table = Table.from_url(entry.url)
            except GranumError:
                continue
            if table.base_name in HOLDING_SETS or is_release(table):
                continue
            by_set.setdefault(table.base_name, []).append({
                "url": str(table.url), "name": table.name, "row_count": len(table), "created": table.created,
                "change": table.producer.get("op"), "description": table.description, "table": table,
            })
        for versions in by_set.values():
            versions.sort(key=lambda v: v["created"], reverse=True)
        return by_set

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
        shipped = log.shipped_urls()
        versions = _set_versions(project, dataset)
        for item in sets:
            item["ready"] = item["counts"]["reviewed"] == len(item["images"]) and len(item["images"]) > 0
            item["shipped"] = item["url"] in shipped
            item["versions"] = []
            for v in versions.get(item["set"], []):
                images = _version_images(v["table"])
                reviewed = sum(1 for image in images if current.get(image, {}).get("status") == "reviewed")
                item["versions"].append({**{k: val for k, val in v.items() if k != "table"},
                                         "shipped": v["url"] in shipped, "images": len(images), "reviewed": reviewed,
                                         "ready": bool(images) and reviewed == len(images)})
        return {
            "sets": sets,
            "isolated": isolated,
            "statuses": current,
            "shipments": shipments,
            "ready": bool(sets) and all(s["ready"] for s in sets),
            # Every set's newest version has been shipped: nothing new to ship.
            "up_to_date": bool(sets) and all(s["shipped"] for s in sets),
        }

    @app.get("/api/qa/version")
    def qa_version(project: str = Query(...), dataset: str = Query(...), table: str = Query(...)) -> dict[str, Any]:
        """Review counts for one version of a set, to decide whether it can ship."""
        log = _qa_log(project, dataset)
        version = _table_at(table)
        if isinstance(version, MetricsTable) or version.project_name != project or version.dataset_name != dataset:
            raise _error(400, "choose a version of this dataset")
        current = log.current()
        images = _set_images(version)
        counts = {status: 0 for status in ("unreviewed", "reviewed", "rework")}
        for item in images:
            counts[current.get(item["image"], {}).get("status", "unreviewed")] += 1
        return {**_version_payload(version), "images": len(images), "counts": counts,
                "ready": counts["reviewed"] == len(images) and len(images) > 0,
                "shipped": str(version.url) in log.shipped_urls()}

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
            "instance_properties": dict(source.schema[box_column].instance_properties) if box_column else {},
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
        if request.sets is None:
            chosen = _review_sets(request.project, request.dataset)
        else:
            if not request.sets:
                raise _error(400, "choose at least one set to ship")
            known = _set_versions(request.project, request.dataset)
            chosen = {}
            for name, url in request.sets.items():
                if name not in known:
                    raise _error(400, f"{request.dataset} has no set named {name!r}")
                if url not in {v["url"] for v in known[name]}:
                    raise _error(400, f"that is not a version of {name}")
                chosen[name] = Table.from_url(url)
        already = log.shipped_urls()
        repeats = [name for name, table in chosen.items() if str(table.url) in already]
        if repeats:
            raise _error(409, f"already shipped: {', '.join(f'{n} ({chosen[n].name})' for n in repeats)}")
        versions = {
            name: {"url": str(table.url), "name": table.name, "images": [i["image"] for i in _set_images(table)]}
            for name, table in chosen.items()
        }
        try:
            shipment = log.ship(versions, statuses, author=request.author, note=request.note)
        except QaError as exc:
            raise _error(409, str(exc)) from exc
        return {"shipment": shipment}

    @app.post("/api/qa/release")
    def qa_release(request: ReleaseRequest = Body(...)) -> dict[str, Any]:
        """Create a dataset version from the newest version of every set.

        With ``mode="verified"`` a set holding unverified images is frozen as a copy of just
        its verified ones; otherwise the set's version is used as it is. With ``augmentation``
        the train set is frozen with augmented copies added; that runs as a job, and the
        response is ``{"job": ...}`` whose result is the usual ``{"release": ...}``.
        """
        from granum.core.augment import AugmentError, normalize_recipe, write_augmented_set
        from granum.core.curation import CurationError, write_release_set
        from granum.core.qa import QaError, new_release_id

        log = _qa_log(request.project, request.dataset)
        if request.mode not in ("all", "verified"):
            raise _error(400, "mode must be 'all' or 'verified'")
        try:
            recipe = normalize_recipe(request.augmentation)
        except AugmentError as exc:
            raise _error(400, str(exc)) from exc
        try:
            name = log.release_name(request.name)
        except QaError as exc:
            raise _error(409 if "already" in str(exc) else 400, str(exc)) from exc
        statuses = {k: v["status"] for k, v in log.current().items()}
        release_id = new_release_id()
        order = ["train", "valid", "val", "validation", "test"]
        chosen = sorted(_review_sets(request.project, request.dataset).items(),
                        key=lambda kv: (order.index(kv[0]) if kv[0] in order else len(order), kv[0]))
        augmented_set = next((n for n, _ in chosen if n.lower().startswith("train")), None)
        if recipe and augmented_set is None:
            raise _error(400, "augmentation needs a train set; this dataset has none")

        def build(job: Any | None) -> dict[str, Any]:
            versions: dict[str, dict[str, Any]] = {}
            for set_name, table in chosen:
                images = _version_images(table)
                verified = [i for i in images if statuses.get(i) == "reviewed"]
                partial = request.mode == "verified" and len(verified) < len(images)
                if partial and not verified:
                    continue
                if recipe and set_name == augmented_set:
                    def report(done: int, total: int, set_name: str = set_name) -> None:
                        if job is not None:
                            job.progress(f"Augmenting {set_name}", done, total)

                    copy, counts = write_augmented_set(
                        table, recipe, release_id=release_id, release_name=name,
                        keep=set(verified) if partial else None, progress=report,
                        cancel=job.cancel if job is not None else None,
                    )
                    versions[set_name] = {"url": str(copy.url), "name": copy.name, "images": len(copy),
                                          "verified": len(verified) + (counts["augmented"] if partial else 0),
                                          **counts}
                elif partial:
                    copy = write_release_set(table, verified, release_id=release_id, release_name=name)
                    versions[set_name] = {"url": str(copy.url), "name": copy.name, "images": len(copy), "verified": len(copy)}
                else:
                    versions[set_name] = {"url": str(table.url), "name": table.name, "images": len(images), "verified": len(verified)}
            if not versions:
                raise _error(409, "no image is verified yet; verify images or include the whole dataset")
            if job is not None:
                job.progress("Saving the dataset version", 1, 1)
            release = log.release(name, versions, description=request.description, mode=request.mode,
                                  author=request.author, release_id=release_id, augmentation=recipe)
            index.refresh(force=True)
            return {"release": {**release, "dataset": request.dataset}}

        if recipe:
            # Writing thousands of images takes minutes: a job the dialog follows.
            def work(job: Any) -> Any:
                try:
                    return build(job)
                except HTTPException as exc:
                    raise AugmentError(str(exc.detail)) from exc
                except (CurationError, QaError) as exc:
                    raise AugmentError(str(exc)) from exc

            return {"job": jobs.start("release", work).to_dict()}
        try:
            return build(None)
        except (CurationError, QaError) as exc:
            raise _error(400, str(exc)) from exc

    def _train_set(project: str, dataset: str) -> Table:
        sets = _review_sets(project, dataset)
        train = next((t for n, t in sorted(sets.items()) if n.lower().startswith("train")), None)
        if train is None:
            raise _error(404, "this dataset has no train set to augment")
        return train

    @app.post("/api/augment/examples")
    def augment_examples(request: AugmentExamplesRequest = Body(...)) -> dict[str, Any]:
        """One train image as it is and under each recipe at a fixed end: what a setting does.

        ``bytes_per_image`` is the train set's typical file size, for estimating what the
        copies will take on disk.
        """
        from granum.core.augment import (
            AugmentError,
            average_image_bytes,
            examples,
            normalize_recipe,
        )

        items: dict[str, tuple[dict[str, Any], str]] = {}
        for key, item in request.items.items():
            if item.at not in ("min", "max"):
                raise _error(400, "at must be 'min' or 'max'")
            try:
                recipe = normalize_recipe({**item.recipe, "copies": 1})
            except AugmentError as exc:
                raise _error(400, f"{key}: {exc}") from exc
            if recipe:
                items[key] = (recipe, item.at)
        train = _train_set(request.project, request.dataset)
        return {"set": train.base_name, "bytes_per_image": average_image_bytes(train),
                **examples(train, items, row=request.row, size=request.size)}

    def _release_folder(project: str, dataset: str, release_id: str) -> Url:
        """Where a version's own files live: frozen set copies and augmented images."""
        import re

        from granum.core.layout import sanitize

        if not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", release_id):
            raise _error(400, "not a dataset version id")
        return ProjectLayout(config.project_root).project(project) / "releases" / sanitize(dataset) / release_id

    def _release_usage(project: str, release: dict[str, Any]) -> dict[str, Any]:
        """The files a version wrote, and the runs that trained or scored on its sets."""
        folder = _release_folder(project, release["dataset"], release["id"])
        files = size = 0
        if folder.scheme == "file" and os.path.isdir(folder.path):
            for base, _dirs, names in os.walk(folder.path):
                for name in names:
                    files += 1
                    try:
                        size += os.path.getsize(os.path.join(base, name))
                    except OSError:
                        pass
        urls = {str(s["url"]) for s in release["sets"].values()}
        runs = []
        for entry in index.runs(project):
            try:
                run = Run.from_url(entry.url)
                used = {str(v) for k, v in run.parameters.items() if k.endswith("_table")}
                used |= {str(t.foreign_table_url) for t in run.metrics_tables() if t.foreign_table_url}
            except GranumError:
                continue
            if used & urls:
                runs.append(entry.name)
        return {"files": files, "bytes": size, "runs": sorted(runs)}

    def _find_release(project: str, dataset: str, release_id: str) -> tuple[Any, dict[str, Any]]:
        log = _qa_log(project, dataset)
        found = next((s for s in log.shipments() if s["id"] == release_id), None)
        if found is None:
            raise _error(404, f"no dataset version {release_id!r} in {dataset}")
        return log, {**found, "dataset": dataset}

    @app.get("/api/releases/usage")
    def release_usage(project: str = Query(...), dataset: str = Query(...), release_id: str = Query(...)) -> dict[str, Any]:
        """What deleting a dataset version would remove, and which runs used it."""
        _log, release = _find_release(project, dataset, release_id)
        return _release_usage(project, release)

    @app.post("/api/releases/delete")
    def delete_release(request: DeleteReleaseRequest = Body(...)) -> dict[str, Any]:
        """Delete a dataset version: its entry, and the files written for it alone.

        Set versions it merely pointed at stay (they belong to the dataset); the frozen
        copies and augmented images under its own folder go. Runs keep their scores.
        """
        import shutil

        if _running_training() is not None:
            raise _error(409, "a model is training; wait for it to finish before deleting dataset versions")
        log, release = _find_release(request.project, request.dataset, request.release_id)
        usage = _release_usage(request.project, release)
        folder = _release_folder(request.project, request.dataset, request.release_id)
        log.delete_release(request.release_id, author=request.author)
        if folder.scheme == "file":
            shutil.rmtree(folder.path, ignore_errors=True)
        index.refresh(force=True)
        return {"deleted": release["id"], "name": release.get("name"), **usage}

    @app.get("/api/releases")
    def releases(project: str = Query(...)) -> dict[str, Any]:
        """Every dataset version of the project, newest first: the only data training accepts."""
        from granum.core.qa import QaLog

        found: list[dict[str, Any]] = []
        tasks = _dataset_tasks(project)
        for name in sorted({t.dataset_name for t in index.tables(project) if t.dataset_name}):
            shipments = QaLog(project, name, config=config).shipments()
            for number, shipment in enumerate(reversed(shipments), start=1):
                # Shipments from before dataset versions had names read as numbered versions.
                found.append({"version": number, "name": f"Version {number}", "mode": "verified",
                              **shipment, "dataset": name, "tasks": tasks.get(name)})
        found.sort(key=lambda r: (r["time"], r["version"]), reverse=True)
        return {"releases": found}

    # -- pulling images from existing projects ---------------------------------

    library_cache: dict[str, dict[str, dict[str, Any]]] = {}

    def _library_sets(project: str) -> list[Table]:
        """The newest train/valid/test sets of every dataset in a project."""
        names = sorted({t.dataset_name for t in index.tables(project) if t.dataset_name})
        out: list[Table] = []
        for name in names:
            try:
                out.extend(_review_sets(project, name).values())
            except HTTPException:
                continue
        return out

    @app.get("/api/library")
    def library() -> dict[str, Any]:
        """Every project with its classes, and every class across projects, matched by name."""
        from granum.importing.library import table_classes

        projects = []
        overall: dict[str, dict[str, Any]] = {}
        for entry in sorted({t.project_name for t in index.tables() if t.project_name}):
            sets = _library_sets(entry)
            if not sets:
                continue
            classes: dict[str, dict[str, Any]] = {}
            images = 0
            for table in sets:
                key = str(table.url)
                if key not in library_cache:
                    library_cache[key] = table_classes(table)
                    if len(library_cache) > 256:
                        library_cache.pop(next(iter(library_cache)))
                images += len(table)
                for ckey, info in library_cache[key].items():
                    known = classes.setdefault(ckey, {"key": ckey, "name": info["name"], "images": 0, "boxes": 0})
                    known["images"] += info["images"]
                    known["boxes"] += info["boxes"]
            by_dataset = _dataset_tasks(entry)
            projects.append({
                "name": entry, "images": images, "tasks": sorted({t for ts in by_dataset.values() for t in ts}),
                "sets": sorted({t.base_name for t in sets}),
                "classes": sorted(classes.values(), key=lambda c: -c["images"]),
            })
            for ckey, info in classes.items():
                known = overall.setdefault(ckey, {"key": ckey, "name": info["name"], "images": 0, "boxes": 0, "projects": []})
                known["images"] += info["images"]
                known["boxes"] += info["boxes"]
                known["projects"].append(entry)
        return {"projects": projects, "classes": sorted(overall.values(), key=lambda c: (-c["images"], c["key"]))}

    @app.post("/api/library/pull")
    def library_pull(request: PullRequest = Body(...)) -> dict[str, Any]:
        """Write COCO files of the chosen projects' images holding the chosen classes."""
        import uuid

        from granum.importing.library import PullError, pull

        known = {t.project_name for t in index.tables()}
        missing = [p for p in request.selection if p not in known]
        if missing:
            raise _error(404, f"no project named {missing[0]!r}")
        sets = [(project, table, classes) for project, classes in request.selection.items() for table in _library_sets(project)]
        try:
            return pull(sets, keep_other_labels=request.keep_other_labels,
                        out_dir=_pulls_dir() / uuid.uuid4().hex[:12])
        except PullError as exc:
            raise _error(409, str(exc)) from exc

    # -- browsing images -----------------------------------------------------

    def _image_rows(table: Table) -> list[dict[str, Any]]:
        """Every image of a set with the classes it uses, for the Images tab.

        Separate from ``_set_images``: the class list is only wanted here, and on a large
        set it is the bulk of the payload.
        """
        from granum.core.curation import CurationError, image_column
        from granum.importing.library import count_instances

        try:
            column = image_column(table)
        except CurationError:
            return []
        arrow = table.to_arrow()
        images = arrow.column(column).to_pylist()
        box_column = next((n for n in table.columns if isinstance(table.schema[n], Geometry2DSchema)), None)
        counted = count_instances(arrow.column(box_column), len(images)) if box_column else None
        if counted is None:
            boxes = arrow.column(box_column).to_pylist() if box_column else [None] * len(arrow)
            counted = ([], [])
            for value in boxes:
                instances = [x for x in (value or {}).get("instances", []) if not x.get("iscrowd")]
                counted[0].append(len(instances))
                counted[1].append(sorted({x["label"] for x in instances if x.get("label") is not None}))
        objects, classes = counted
        # Boxes a model drafted, per image. Only for a set that has been pre-labelled: a
        # column with no source property has nothing to count and pays nothing for it.
        drafted: list[int] = []
        if box_column and SOURCE in (table.schema[box_column].instance_properties or {}):
            for value in arrow.column(box_column).to_pylist():
                instances = (value or {}).get("instances") or []
                drafted.append(sum(1 for x in instances if x.get(SOURCE) == PRELABEL_MODEL))
        return [{"row": i, "image": image, "objects": objects[i], "classes": classes[i],
                 **({"drafted": drafted[i]} if drafted else {})}
                for i, image in enumerate(images) if image]

    @app.get("/api/images")
    def images_overview(project: str = Query(...), dataset: str = Query(...)) -> dict[str, Any]:
        """Every image of the dataset's newest sets, with its classes and review status.

        One call feeds the whole Images tab: filtering by class, split and status, and
        ordering by name or by when the image was last touched, all happen in the browser.
        """
        log = _qa_log(project, dataset)
        current = log.current()
        sets: list[dict[str, Any]] = []
        images: list[dict[str, Any]] = []
        labels: dict[str, str] = {}
        from granum.core.curation import ISOLATED_SET, image_column

        newest = _newest_sets(project, dataset)
        chosen = list(_review_sets(project, dataset).values())
        # Images set aside in review come along, marked, so they can be fixed and returned.
        if ISOLATED_SET in newest and len(newest[ISOLATED_SET]):
            chosen.append(newest[ISOLATED_SET])
        for table in chosen:
            box_column = next((n for n in table.columns if isinstance(table.schema[n], Geometry2DSchema)), None)
            value_map = (table.schema[box_column].value_map or {}) if box_column else {}
            for label, entry in value_map.items():
                labels.setdefault(str(label), entry.display_name or entry.internal_name)
            rows = _image_rows(table)
            origins: dict[str, Any] = {}
            if table.base_name == ISOLATED_SET and "removed_from" in table.columns:
                arrow = table.to_arrow()
                column = image_column(table)
                origins = dict(zip(arrow.column(column).to_pylist(),
                                   zip(arrow.column("removed_from").to_pylist(), arrow.column("removed_reason").to_pylist())))
            sets.append({**_version_payload(table), "created": table.created, "images": len(rows)})
            for row in rows:
                extra = {}
                if row["image"] in origins:
                    extra = {"from": origins[row["image"]][0], "reason": origins[row["image"]][1] or ""}
                images.append({**row, **extra, "set": table.base_name, "table": str(table.url), "added": table.created})
        order = ["train", "valid", "val", "validation", "test", ISOLATED_SET]
        sets.sort(key=lambda s: (order.index(s["set"]) if s["set"] in order else len(order), s["set"]))
        return {
            "sets": sets,
            "labels": labels,
            "images": images,
            "statuses": {image: current[image] for image in {i["image"] for i in images} & set(current)},
        }

    # Tables kept warm between box requests: to_arrow caches per instance, and the
    # gallery asks for one screenful at a time as the reader scrolls.
    box_tables: dict[str, Table] = {}

    def _box_table(url: str) -> Table:
        if url not in box_tables:
            if len(box_tables) > 4:
                box_tables.pop(next(iter(box_tables)))
            box_tables[url] = _table_at(url)
        return box_tables[url]

    @app.post("/api/images/boxes")
    def images_boxes(request: ImageBoxesRequest = Body(...)) -> dict[str, Any]:
        """Box geometry for the images on screen, addressed by the rows /api/images gave.

        Only what is being looked at: the aerial set's 11,882 images carry 644,000 boxes,
        far more than a browser should hold to draw a screenful of thumbnails.
        Coordinates are fractions of the image, rounded to a thousandth -- about a pixel
        at 1000px, and a third of the bytes.
        """
        from granum.core.curation import CurationError, image_column

        _qa_log(request.project, request.dataset)  # 404s when the dataset is not in the project
        wanted: dict[str, list[int]] = {}
        for item in request.items:
            wanted.setdefault(item.table, []).append(item.row)

        out: dict[str, Any] = {}
        for url, rows in wanted.items():
            table = _box_table(url)
            if isinstance(table, MetricsTable) or table.project_name != request.project or table.dataset_name != request.dataset:
                raise _error(400, "choose a version of this dataset")
            try:
                column = image_column(table)
            except CurationError:
                continue
            box_column = next((n for n in table.columns if isinstance(table.schema[n], Geometry2DSchema)), None)
            if box_column is None:
                continue
            arrow = table.to_arrow()
            images, values = arrow.column(column), arrow.column(box_column)
            for row in rows:
                if not 0 <= row < len(arrow):
                    continue
                image = images[row].as_py()
                if not image or image in out:
                    continue
                value = values[row].as_py() or {}
                width, height = float(value.get("width") or 0), float(value.get("height") or 0)
                if not width or not height:
                    continue
                boxes = []
                drafts = []
                for instance in value.get("instances", []):
                    vertices = instance.get("vertices") or []
                    if instance.get("iscrowd") or len(vertices) != 4:
                        continue
                    x0, y0, x1, y1 = (float(v) for v in vertices)
                    boxes.append([
                        instance.get("label"),
                        round(x0 / width, 3), round(y0 / height, 3),
                        round(x1 / width, 3), round(y1 / height, 3),
                    ])
                    drafts.append(instance.get(SOURCE) == PRELABEL_MODEL)
                out[image] = {"w": width, "h": height, "b": boxes,
                              # Only when some of them are drafts: a hand-labelled set
                              # should not pay a list of falses per image for the question.
                              **({"d": drafts} if any(drafts) else {})}
        return {"boxes": out}

    # -- removing images from sets ------------------------------------------

    def _newest_sets(project: str, dataset: str) -> dict[str, Table]:
        """The newest version of every set (train, valid, removed, ...) in a dataset."""
        from granum.core.curation import is_release

        tables = []
        for entry in index.tables(project):
            if entry.dataset_name != dataset:
                continue
            try:
                table = Table.from_url(entry.url)
            except GranumError:
                continue
            if not is_release(table):
                tables.append(table)
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
        done = None
        try:
            done = subprocess.run([console_python(sys.executable), "-c", probe], capture_output=True, text=True, timeout=120,
                                  **no_window())
            found = json.loads(done.stdout.strip().splitlines()[-1])
        except Exception as exc:  # noqa: BLE001 - reported to the user
            # Most often PyTorch is installed but cannot load (a missing system library): say why.
            lines = [line for line in (done.stderr if done is not None else "").splitlines() if line.strip()]
            found = {"ultralytics": False, "torch": False, "error": lines[-1].strip()[:300] if lines else str(exc)}
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
            "reason": None if available else (
                f"PyTorch is installed but could not load: {found['error']}" if found.get("error")
                else "Training needs PyTorch and a detector package, for example: pip install ultralytics"),
        })
        return training_check

    def _running_addon_install() -> Any:
        return next((j for j in jobs.all() if j.kind == "training-install" and j.status == "running"), None)

    @app.post("/api/training/install")
    def install_training_support() -> dict[str, Any]:
        """Install PyTorch and Ultralytics into Granum's own add-on folder (not the system Python)."""
        from granum import addons

        running = _running_addon_install()
        if running is not None:
            return running.to_dict()
        if _training_environment()["available"]:
            raise _error(409, "training support is already installed")

        def work(job: Any) -> Any:
            job.progress(f"Downloading PyTorch and Ultralytics ({addons.TRAINING_DOWNLOAD})", 0, 0)

            def on_line(line: str) -> None:
                if line.startswith(("Collecting", "Downloading", "Installing")):
                    job.phase = line[:120]
                job.log.append(line)

            target = addons.install_training(on_line, cancelled=job.cancel.is_set)
            training_check.clear()
            job.phase = "Checking the GPU"
            _training_environment()
            return {"installed": str(target)}

        return jobs.start("training-install", work).to_dict()

    def _running_training() -> Any:
        return next((j for j in jobs.all() if j.kind == "training" and j.status == "running"), None)

    def _running_screening() -> Any:
        return next((j for j in jobs.all() if j.kind == "screening" and j.status == "running"), None)

    def _running_model_job() -> Any:
        """A training or a label check: one machine, one GPU, so each waits for the other."""
        return _running_training() or _running_screening()

    def _rfdetr_steps(record: Any) -> Any:
        """In-round progress for RF-DETR trainers started before they reported steps: its own
        metrics.csv logs the optimizer step, and a round is rows / (batch 4 x accumulation 4) steps."""
        import csv
        import math

        if config.project_root.scheme != "file":
            return None
        from granum.cli.desktop import training_dir

        try:
            run = Run.from_url(ProjectLayout(config.project_root).run(record.project, record.run_name))
        except GranumError:
            return None
        if run.parameters.get("framework") != "rfdetr":
            return None
        dataset, _, version = str(run.parameters.get("train_version", "")).partition("/")
        entry = next((e for e in index.tables(record.project) if e.dataset_name == dataset and e.name == version), None)
        if entry is None:
            return None
        rows = Table.from_url(entry.url).row_count
        steps = max(1, math.ceil(rows / 16))
        metrics = training_dir(Path(config.project_root.path)) / "runs" / record.run_name / "metrics.csv"

        def read() -> tuple[int, int] | None:
            try:
                with metrics.open() as handle:
                    last = None
                    for row in csv.DictReader(handle):
                        if row.get("step", "").isdigit() and row.get("epoch", "").isdigit():
                            last = row
            except OSError:
                return None
            if last is None:
                return None
            within = int(last["step"]) + 1 - int(last["epoch"]) * steps
            return (min(max(within, 0), steps), steps)

        return read

    def _finish_training(record: Any, cancelled: bool, code: int | None) -> Any:
        from granum.service import trainers

        status = trainers.finish_run(ProjectLayout(config.project_root).run(record.project, record.run_name), cancelled, code)
        index.refresh(force=True)
        if cancelled:
            return {"run_name": record.run_name, "cancelled": True}
        if status in ("failed", "interrupted") or (code is not None and code != 0):
            raise GranumError(f"training stopped with an error (exit code {code}); see the technical log"
                              if code is not None else "training stopped while Granum was not watching it")
        return {"run_name": record.run_name, "exit_code": code}

    def _resume_trainers() -> None:
        """Reattach to trainers that survived a restart; mark abandoned dashboard runs interrupted."""
        from granum.service import trainers

        live: set[tuple[str, str]] = set()
        for record in trainers.TrainerRecord.load_all(str(config.project_root)):
            if trainers.is_trainer_alive(record.pid, record.module):
                live.add((record.project, record.run_name))
                # A label check survives a restart exactly as a training run does, and is
                # followed the same way; only what it is called differs.
                checking = record.module == trainers.SCREEN_MODULE
                job = jobs.start("screening" if checking else "training", lambda job, record=record, checking=checking: trainers.follow(
                    job, record, None, _finish_screening if checking else _finish_training,
                    fallback_step=None if checking else _rfdetr_steps(record)))
                job.payload = record.project
                job.started = record.started  # elapsed time counts from when training began
            else:
                trainers.finish_run(ProjectLayout(config.project_root).run(record.project, record.run_name), False, None)
                record.remove()
        for entry in index.runs():
            if (entry.project_name, entry.name) in live:
                continue
            try:
                run = Run.from_url(entry.url)
            except GranumError:
                continue
            if run.status == "running" and run.parameters.get("framework") in trainers.DASHBOARD_FRAMEWORKS:
                run.set_status("interrupted")
        index.refresh(force=True)

    @app.get("/api/training/status")
    def training_status(project: str = Query(...)) -> dict[str, Any]:
        from granum.addons import TRAINING_DOWNLOAD

        environment = _training_environment()
        running = _running_training()
        return {
            **environment,
            "running_job": running.to_dict() if running is not None and running.payload == project else None,
            "busy_elsewhere": running is not None and running.payload != project,
            "shipped": sorted(_shipped_urls(project)),
            "installable": not environment["available"],
            "install_size": TRAINING_DOWNLOAD,
            "install_job": _running_addon_install().to_dict() if _running_addon_install() is not None else None,
        }

    @app.post("/api/training")
    def start_training(request: TrainingRequest = Body(...)) -> dict[str, Any]:
        import re
        import sys
        import time as _time

        environment = _training_environment()
        if not environment["available"]:
            raise _error(400, environment["reason"])
        if _running_model_job() is not None:
            raise _error(409, "a model is already running on this computer; wait for it to finish or cancel it")
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
        chosen_tables = [request.train_table, request.valid_table, *([request.test_table] if request.test_table else [])]
        for url in chosen_tables:
            _check_within_roots(Url(url))
            if url not in tables:
                raise _error(404, f"{url} is not a dataset version in {request.project}")
        if request.train_table == request.valid_table:
            raise _error(400, "train and check on different datasets; using the same images for both hides mistakes")
        if request.test_table in (request.train_table, request.valid_table):
            raise _error(400, "the test set must differ from the training and validation sets, or its score means nothing")
        runs = {e.name for e in index.runs(request.project)}
        if request.compare_with and request.compare_with not in runs:
            raise _error(404, f"no run named {request.compare_with!r} in {request.project}")
        name = request.run_name or f"run-{_time.strftime('%m%d-%H%M%S')}"
        if not re.fullmatch(r"[A-Za-z0-9._-]{1,80}", name):
            raise _error(400, "run names may use letters, numbers, dots, dashes and underscores")
        shipped = _shipped_urls(request.project)
        for url in chosen_tables:
            if url not in shipped:
                raise _error(409, f"{tables[url].name} is not part of a dataset version; create one from Images first")

        from granum.cli.desktop import app_executable, running_appimage
        from granum.service import trainers

        # Inside the self-contained app the trainer runs from the installed app, so it keeps
        # working if this service (and the app mount it runs from) restarts.
        executable = [*app_executable(), "--python"] if running_appimage() else [console_python(sys.executable)]
        command = [
            *trainers.trainer_prefix(executable),
            "--project-root", str(config.project_root), "--project", request.project,
            "--train-table", request.train_table, "--valid-table", request.valid_table,
            "--run-name", name, "--epochs", str(request.rounds), "--imgsz", str(request.image_size),
            "--family", request.family, "--version", request.version,
            *(["--test-table", request.test_table] if request.test_table else []),
            *(["--track-learning"] if request.track_learning else []),
            *(["--compare-with", request.compare_with] if request.compare_with else []),
        ]

        def work(job: Any) -> Any:
            job.progress("Starting", 0, request.rounds)
            # Run in the training folder beside the project root, so pretrained weights the
            # trainer downloads land there, not wherever the service happened to be started.
            workdir = None
            if config.project_root.scheme == "file":
                from granum.cli.desktop import training_dir

                workdir = training_dir(Path(config.project_root.path))
                workdir.mkdir(parents=True, exist_ok=True)
            process, record = trainers.launch(command, cwd=workdir, project_root=str(config.project_root),
                                              project=request.project, run_name=name, rounds=request.rounds)
            return trainers.follow(job, record, process, _finish_training,
                                   fallback_step=_rfdetr_steps(record) if request.family == "rfdetr" else None)

        job = jobs.start("training", work)
        job.payload = request.project
        return job.to_dict()

    # -- writing a dataset out in somebody else's format ---------------------------------

    @app.get("/api/formats")
    def formats() -> dict[str, Any]:
        """What Granum can write a dataset as, and read one from."""
        from granum.formats.exchange import EXPORTS, IMPORTS

        return {"exports": EXPORTS, "imports": IMPORTS, "images": ["symlink", "copy", "hardlink", "none"]}

    def _export_sets(project: str, dataset: str, release_id: str | None) -> tuple[dict[str, Table], str]:
        """The sets to write out: a frozen dataset version, or the working sets."""
        from granum.core.curation import HOLDING_SETS

        if release_id:
            _log, release = _find_release(project, dataset, release_id)
            tables = {name: Table.from_url(entry["url"]) for name, entry in release["sets"].items()}
            name = str(release["name"]).strip()
            label = name if name.lower().startswith(str(release["dataset"]).lower()) else f"{release['dataset']}-{name}"
            return tables, label.replace(" ", "-")
        tables = {name: table for name, table in _newest_sets(project, dataset).items()
                  if name not in HOLDING_SETS}
        return tables, dataset

    @app.post("/api/datasets/export")
    def export_dataset(request: ExportRequest = Body(...)) -> dict[str, Any]:
        """Write a dataset out for another tool, under the project's ``exports`` folder."""
        import time as _time

        from granum.core.layout import sanitize
        from granum.formats.exchange import EXPORTERS, EXPORTS

        if request.format not in {entry["id"] for entry in EXPORTS}:
            raise _error(400, f"format must be one of {[e['id'] for e in EXPORTS]}")
        if request.images not in ("symlink", "copy", "hardlink", "none"):
            raise _error(400, "images must be symlink, copy, hardlink or none")
        if request.images == "none" and request.format in ("yolo", "folders"):
            # In these two layouts the images *are* the annotation: a YOLO tree is found by
            # walking the image folders, and a class is the folder an image sits in.
            raise _error(400, f"the {request.format} layout is made of the image files, so it cannot be written without them")
        if config.project_root.scheme != "file":
            raise _error(400, "exporting works on a local project root")
        tables, label = _export_sets(request.project, request.dataset, request.release_id)
        if not tables:
            raise _error(404, f"no sets to export in {request.dataset!r}")

        exports = Path(config.project_root.path) / "projects" / sanitize(request.project) / "exports"
        stem = exports / f"{sanitize(label)}-{request.format}-{_time.strftime('%m%d-%H%M%S')}"
        # Two exports of the same version in the same second must not write into one folder,
        # where they would silently merge. The folder is claimed here, before the job starts.
        folder, at = stem, 1
        while True:
            try:
                folder.mkdir(parents=True)
                break
            except FileExistsError:
                at += 1
                folder = stem.with_name(f"{stem.name}-{at}")
        strategy = None if request.images == "none" else request.images
        images = sum(len(table) for table in tables.values())

        def work(job: Any) -> Any:
            from granum import export_coco, export_yolo

            job.progress("Writing", 0, images)
            written = []
            done = 0
            if request.format == "yolo":
                # YOLO wants every split in one tree, so it is written in one call.
                data_yaml = export_yolo(tables, folder, image_strategy=strategy)
                written.append({"set": "all", "path": str(data_yaml), "images": images})
                done = images
                job.progress("Writing", done, images)
            else:
                for name, table in tables.items():
                    job.phase = f"Writing the {name} set"
                    if request.format == "coco":
                        target = folder / name / "annotations.json"
                        target.parent.mkdir(parents=True, exist_ok=True)
                        path = export_coco(table, target, image_strategy=strategy,
                                           images_dir=folder / name / "images" if strategy else None)
                    elif request.format in ("csv", "cvat", "label-studio"):
                        suffix = {"csv": "csv", "cvat": "xml", "label-studio": "json"}[request.format]
                        path = EXPORTERS[request.format](table, folder / f"{name}.{suffix}")
                    else:
                        path = EXPORTERS[request.format](table, folder / name, image_strategy=strategy)
                    written.append({"set": name, "path": str(path), "images": len(table)})
                    done += len(table)
                    job.progress(f"Writing the {name} set", done, images)
            return {"format": request.format, "folder": str(folder), "images": images, "sets": written}

        job = jobs.start("export", work)
        job.payload = request.project
        return job.to_dict()

    # -- is this dataset fit to train on ------------------------------------------------

    #: One health report per dataset, keyed on the set versions it was computed from.
    health_cache: dict[str, tuple[str, dict[str, Any]]] = {}

    def _label_counts(tables: dict[str, Table]) -> dict[str, Any]:
        """Labels per class over a dataset's sets, and how many boxes a model drafted."""
        from granum.core.prelabel import MODEL as DRAFTED

        counts: dict[int, int] = {}
        names: dict[int, str] = {}
        boxes = drafted = 0
        for table in tables.values():
            column = next((n for n in table.columns if isinstance(table.schema[n], Geometry2DSchema)), None)
            if column is None:
                continue
            for label, entry in (table.schema[column].value_map or {}).items():
                names.setdefault(int(label), entry.display_name or entry.internal_name)
            for value in table.to_arrow().column(column).to_pylist():
                for instance in (value or {}).get("instances") or []:
                    if instance.get("iscrowd"):
                        continue
                    boxes += 1
                    label = instance.get("label")
                    if label is not None:
                        counts[int(label)] = counts.get(int(label), 0) + 1
                    if instance.get(SOURCE) == DRAFTED:
                        drafted += 1
        return {"class_counts": counts, "class_names": names, "boxes": boxes, "drafted_boxes": drafted}

    def _newest_findings(project: str, dataset: str) -> dict[str, Any] | None:
        """What the newest check of this dataset found, if one has been run."""
        checks = []
        for entry in index.runs(project):
            try:
                run = Run.from_url(entry.url)
            except GranumError:
                continue
            if run.parameters.get("kind") == "screening":
                checks.append(run)
        checks.sort(key=lambda run: str(run.created), reverse=True)
        for run in checks:
            splits = [s for s in _findings_splits(run) if s["dataset"] == dataset]
            if not splits:
                continue
            counts = dict.fromkeys(RULES_FOR_HEALTH, 0)
            images = 0
            for split in splits:
                images += len(split["images"])
                for item in split["images"]:
                    for finding in item["findings"]:
                        counts[finding["rule"]] += 1
            return {"images": images, "counts": counts, "from": run.name, "run": str(run.url)}
        return None

    @app.get("/api/datasets/health")
    def dataset_health(project: str = Query(...), dataset: str = Query(...)) -> dict[str, Any]:
        """Everything Granum knows about whether this dataset is fit to train on."""
        from granum.core.curation import HOLDING_SETS
        from granum.core.qa import QaLog
        from granum.metrics.health import report

        tables = {name: table for name, table in _newest_sets(project, dataset).items()
                  if name not in HOLDING_SETS}
        if not tables:
            raise _error(404, f"no dataset {dataset!r} in {project}")
        stamp = "|".join(sorted(f"{name}:{table.url}" for name, table in tables.items()))
        hit = health_cache.get(f"{project}/{dataset}")
        if hit is not None and hit[0] == stamp:
            return hit[1]

        sets = {name: len(table) for name, table in tables.items()}
        labels = _label_counts(tables)
        images = sum(sets.values())
        statuses = QaLog(project, dataset, config=config).current()
        verified = sum(1 for state in statuses.values() if state.get("status") == "reviewed")

        graph = None
        try:
            found = _embedding_report(project, dataset)
            graph = {
                "leaks": len(found["leaks"]),
                "redundant": found["duplicates"]["redundant"],
                "alone": sum(1 for row in found["outliers"] if row.get("alone")),
                "read": found.get("images"),
            }
        except Exception:  # noqa: BLE001 - no vectors, or an unreadable store: not looked at
            graph = None

        summary = {
            "images": images,
            "sets": sets,
            "verified": verified,
            "findings": _newest_findings(project, dataset),
            "graph": graph,
            **labels,
        }
        payload = {
            "project": project,
            "dataset": dataset,
            "images": images,
            "sets": sets,
            "verified": verified,
            "graph": graph,
            "boxes": labels["boxes"],
            "drafted_boxes": labels["drafted_boxes"],
            "findings": summary["findings"],
            "class_names": {str(k): v for k, v in labels["class_names"].items()},
            **report(summary),
        }
        health_cache[f"{project}/{dataset}"] = (stamp, payload)
        return payload

    # -- tags and saved views ---------------------------------------------------------

    @app.get("/api/tags")
    def tags_overview(project: str = Query(...), dataset: str = Query(...)) -> dict[str, Any]:
        """Every image of this dataset that carries a tag, and how much each tag is used."""
        from granum.core.tags import TagStore

        store = TagStore(project, dataset, config=config)
        return {"project": project, "dataset": dataset,
                "images": store.current(), "counts": store.counts()}

    @app.post("/api/tags")
    def tags_record(request: TagRequest = Body(...)) -> dict[str, Any]:
        """Tag images, untag them, or both at once for a whole selection."""
        from granum.core.tags import TagError, TagStore

        store = TagStore(request.project, request.dataset, config=config)
        try:
            written = store.record(request.samples, add=request.add, remove=request.remove,
                                   author=request.author or None)
        except TagError as exc:
            raise _error(400, str(exc)) from exc
        return {**written, "images_tagged": store.current(), "counts": store.counts()}

    @app.get("/api/views")
    def views_list(project: str = Query(...), dataset: str = Query(...)) -> dict[str, Any]:
        """Named filter sets for this dataset, newest first."""
        from granum.core.tags import ViewStore

        return {"views": ViewStore(project, dataset, config=config).all()}

    @app.post("/api/views")
    def views_save(request: ViewRequest = Body(...)) -> dict[str, Any]:
        """Save the filters in front of the reader under a name, replacing one of that name."""
        from granum.core.tags import TagError, ViewStore

        store = ViewStore(request.project, request.dataset, config=config)
        try:
            view = store.save(request.name, request.state, author=request.author or None)
        except TagError as exc:
            raise _error(400, str(exc)) from exc
        return {"view": view, "views": store.all()}

    @app.delete("/api/views")
    def views_delete(project: str = Query(...), dataset: str = Query(...), id: str = Query(...)) -> dict[str, Any]:
        from granum.core.tags import ViewStore

        store = ViewStore(project, dataset, config=config)
        if not store.delete(id):
            raise _error(404, f"no saved view {id!r}")
        return {"views": store.all()}

    # -- checking labels with a model (one pass, no training) ------------------------

    def _trained_models(project: str) -> list[dict[str, Any]]:
        """Runs of this project whose weights are still on this computer, newest first.

        A model trained on this data knows its classes exactly, which makes it the best
        thing to check the data with -- including labels edited since it was trained.
        """
        found = []
        for entry in index.runs(project):
            try:
                run = Run.from_url(entry.url)
            except GranumError:
                continue
            weights = run.parameters.get("weights")
            if run.parameters.get("kind") == "screening" or not weights or not Path(str(weights)).exists():
                continue
            found.append({
                "name": run.name,
                "framework": run.parameters.get("framework"),
                "version": run.parameters.get("version"),
                "created": run.created,
                "trained_on": run.parameters.get("train_version"),
                "map50": run.parameters.get("score_map50"),
                "image_size": run.parameters.get("imgsz") or 640,
            })
        found.sort(key=lambda item: str(item["created"]), reverse=True)
        return found

    def _model_options(project: str) -> dict[str, Any]:
        """The models this computer can read a dataset with, and whether it can at all.

        The same answer serves a label check and a pre-labelling pass: both are one model
        over one set of images, and the only difference is what is done with the boxes.
        """
        from granum.training.models import version_ids

        environment = _training_environment()
        busy = _running_model_job()
        return {
            "available": environment["available"],
            "reason": environment.get("reason"),
            "gpu": environment.get("gpu"),
            "models": _trained_models(project),
            # A detector that has never seen this data. It knows the classes it was trained
            # on; how many of this dataset's it can speak about is only known once it runs.
            "pretrained": version_ids("yolo") if environment["available"] else [],
            "busy_elsewhere": busy is not None and busy.payload != project,
        }

    def _model_for(project: str, weights_run: str | None, pretrained: str | None) -> tuple[str | None, str]:
        """The weights to read with, or the pretrained version, whichever was asked for."""
        from granum.training.models import version_ids

        if bool(weights_run) == bool(pretrained):
            raise _error(400, "choose one model: a run you trained, or a model that has not seen this data")
        if weights_run:
            model = next((m for m in _trained_models(project) if m["name"] == weights_run), None)
            if model is None:
                raise _error(404, f"no run named {weights_run!r} in {project} with weights on this computer")
            if model["framework"] not in (None, "yolo", "rtdetr"):
                raise _error(400, f"{model['framework']} models cannot read labels yet; choose a YOLO or RT-DETR run")
            weights = str(Run.from_url(ProjectLayout(config.project_root).run(project, weights_run)).parameters["weights"])
            return weights, str(model["version"] or Path(weights).name)
        if pretrained not in version_ids("yolo"):
            raise _error(400, f"pretrained must be one of {version_ids('yolo')}")
        return None, str(pretrained)

    @app.get("/api/models")
    def model_options(project: str = Query(...)) -> dict[str, Any]:
        """Which models this computer could read a dataset with."""
        return _model_options(project)

    @app.get("/api/findings/screen")
    def screening_options(project: str = Query(...)) -> dict[str, Any]:
        """What a label check can be run with on this computer, and whether one is running."""
        running = _running_screening()
        return {
            **_model_options(project),
            "running_job": running.to_dict() if running is not None and running.payload == project else None,
            "shipped": sorted(_shipped_urls(project)),
        }

    def _finish_screening(record: Any, cancelled: bool, code: int | None) -> Any:
        from granum.service import trainers

        status = trainers.finish_run(ProjectLayout(config.project_root).run(record.project, record.run_name), cancelled, code)
        findings_cache.pop(str(ProjectLayout(config.project_root).run(record.project, record.run_name)), None)
        index.refresh(force=True)
        if cancelled:
            return {"run_name": record.run_name, "cancelled": True}
        if status in ("failed", "interrupted") or (code is not None and code != 0):
            raise GranumError(f"the check stopped with an error (exit code {code}); see the technical log"
                              if code is not None else "the check stopped while Granum was not watching it")
        return {"run_name": record.run_name, "exit_code": code}

    @app.post("/api/findings/screen")
    def start_screening(request: ScreeningRequest = Body(...)) -> dict[str, Any]:
        """Read a dataset version with one model and record what it says about the labels."""
        import re
        import sys
        import time as _time

        environment = _training_environment()
        if not environment["available"]:
            raise _error(400, environment["reason"])
        if _running_model_job() is not None:
            raise _error(409, "a model is already running on this computer; wait for it to finish or cancel it")
        if request.image_size not in (640, 960, 1280):
            raise _error(400, "image_size must be 640, 960 or 1280")
        weights, _version = _model_for(request.project, request.weights_run, request.pretrained)

        tables = {str(e.url): e for e in index.tables(request.project)}
        shipped = _shipped_urls(request.project)
        for name, url in request.sets.items():
            _check_within_roots(Url(url))
            if url not in tables:
                raise _error(404, f"{url} is not a dataset version in {request.project}")
            if url not in shipped:
                raise _error(409, f"{tables[url].name} is not part of a dataset version; create one from Images first")
            if not re.fullmatch(r"[A-Za-z0-9._-]{1,40}", name):
                raise _error(400, "set names may use letters, numbers, dots, dashes and underscores")

        name = request.run_name or f"check-{_time.strftime('%m%d-%H%M%S')}"
        if not re.fullmatch(r"[A-Za-z0-9._-]{1,80}", name):
            raise _error(400, "names may use letters, numbers, dots, dashes and underscores")
        if name in {e.name for e in index.runs(request.project)}:
            raise _error(409, f"{request.project} already has a run named {name!r}")

        from granum.cli.desktop import app_executable, running_appimage
        from granum.service import trainers

        executable = [*app_executable(), "--python"] if running_appimage() else [console_python(sys.executable)]
        command = [
            *trainers.trainer_prefix(executable, trainers.SCREEN_MODULE),
            "--project-root", str(config.project_root), "--project", request.project,
            "--run-name", name, "--imgsz", str(request.image_size),
            *[arg for set_name, url in request.sets.items() for arg in ("--set", f"{set_name}={url}")],
            *(["--weights", weights, "--from-run", str(request.weights_run)] if weights
              else ["--pretrained", str(request.pretrained)]),
        ]
        images = sum(tables[url].row_count or 0 for url in request.sets.values())

        def work(job: Any) -> Any:
            job.progress("Starting", 0, images)
            workdir = None
            if config.project_root.scheme == "file":
                from granum.cli.desktop import training_dir

                workdir = training_dir(Path(config.project_root.path))
                workdir.mkdir(parents=True, exist_ok=True)
            process, record = trainers.launch(command, cwd=workdir, project_root=str(config.project_root),
                                              project=request.project, run_name=name, rounds=images,
                                              module=trainers.SCREEN_MODULE)
            return trainers.follow(job, record, process, _finish_screening)

        job = jobs.start("screening", work)
        job.payload = request.project
        return job.to_dict()

    # -- pre-labelling: a model drafts a set's labels --------------------------------

    def _finish_prelabel(record: Any, cancelled: bool, code: int | None) -> Any:
        from granum.service import trainers

        written = trainers.last_result(record)
        index.refresh(force=True)
        if cancelled:
            return {"cancelled": True, **(written or {})}
        if code not in (0, None) or written is None:
            raise GranumError(
                f"pre-labelling stopped with an error (exit code {code}); see the technical log"
                if code not in (0, None) else
                "pre-labelling stopped before it wrote anything; see the technical log")
        return written

    @app.post("/api/datasets/prelabel")
    def start_prelabel(request: PrelabelRequest = Body(...)) -> dict[str, Any]:
        """Draw a model's boxes into a set as labels to correct, as a new version of it."""
        import sys

        from granum.core.prelabel import MODES

        environment = _training_environment()
        if not environment["available"]:
            raise _error(400, environment["reason"])
        if _running_model_job() is not None:
            raise _error(409, "a model is already running on this computer; wait for it to finish or cancel it")
        if request.mode not in MODES:
            raise _error(400, f"mode must be one of {list(MODES)}")
        if request.image_size not in (640, 960, 1280):
            raise _error(400, "image_size must be 640, 960 or 1280")
        weights, version = _model_for(request.project, request.weights_run, request.pretrained)

        # Only the newest version of a set may be drafted on: writing off an older one
        # would fork its history, and the fork nobody is looking at would be the live one.
        newest = {str(table.url): name for name, table in _newest_sets(request.project, request.dataset).items()}
        for url in request.tables:
            _check_within_roots(Url(url))
            if url not in newest:
                raise _error(409, f"{url} is not the newest version of a set in {request.dataset}")
        images = sum(Table.from_url(url).row_count for url in request.tables)

        from granum.cli.desktop import app_executable, running_appimage
        from granum.service import trainers

        executable = [*app_executable(), "--python"] if running_appimage() else [console_python(sys.executable)]
        command = [
            *trainers.trainer_prefix(executable, trainers.PRELABEL_MODULE),
            "--project-root", str(config.project_root), "--project", request.project,
            "--mode", request.mode, "--conf", str(request.confidence), "--imgsz", str(request.image_size),
            *[arg for url in request.tables for arg in ("--table", url)],
            *(["--weights", weights, "--from-run", str(request.weights_run)] if weights
              else ["--pretrained", version]),
        ]

        from granum.core.layout import sanitize

        def work(job: Any) -> Any:
            job.progress("Starting", 0, images)
            workdir = None
            if config.project_root.scheme == "file":
                from granum.cli.desktop import training_dir

                workdir = training_dir(Path(config.project_root.path))
                workdir.mkdir(parents=True, exist_ok=True)
            # Named for the dataset rather than a run: this writes data, not a run.
            process, record = trainers.launch(command, cwd=workdir, project_root=str(config.project_root),
                                              project=request.project, run_name=f"prelabel-{sanitize(request.dataset)}",
                                              rounds=images, module=trainers.PRELABEL_MODULE)
            return trainers.follow(job, record, process, _finish_prelabel)

        job = jobs.start("prelabel", work)
        job.payload = request.project
        return job.to_dict()

    # Now that every kind of job and every finisher exists, pick up whatever survived a
    # restart: a trainer, a label check, a pre-labelling pass, or runs left behind by a
    # service that was killed.
    _resume_trainers()

    # -- import -------------------------------------------------------------

    # -- embeddings: duplicates, leaks, neighbours ------------------------------------

    #: One report per dataset, rebuilt when its vectors change (they are write-once per run).
    embedding_cache: dict[str, tuple[str, dict[str, Any]]] = {}

    def _dataset_image_rows(project: str, dataset: str) -> list[tuple[str, str, str]]:
        """Every image of a dataset's current sets, as (image key, set name, source picture).

        Images the dataset has set aside or removed are left out: they are not part of what a
        duplicate or a leak would mean for the data you are about to train on.

        The source is what the image is a copy of, so that augmented copies are never counted
        as duplicates of each other. Granum's own augmented sets record it in ``augmented_from``;
        for everything else it is read off the filename (see :func:`source_key`).
        """
        from granum.core.curation import HOLDING_SETS
        from granum.core.url import sample_key
        from granum.metrics.embeddings import source_key

        rows: list[tuple[str, str, str]] = []
        seen: set[str] = set()
        for set_name, table in sorted(_newest_sets(project, dataset).items()):
            if set_name in HOLDING_SETS:
                continue
            if "image" not in table.columns:
                continue
            arrow = table.to_arrow()
            images = arrow.column("image").to_pylist()
            made_from = (arrow.column("augmented_from").to_pylist()
                         if "augmented_from" in table.columns else [None] * len(images))
            for image, origin in zip(images, made_from):
                if image is None:
                    continue
                key = sample_key(image)
                if key in seen:
                    continue
                seen.add(key)
                rows.append((key, set_name, source_key(key, origin)))
        return rows

    def _embedding_report(project: str, dataset: str) -> dict[str, Any]:
        """What the neighbour graph says about a dataset, computed once per set of vectors.

        Judged against the dataset as it stands now rather than as it stood when the vectors
        were made: an image deleted since is no longer a duplicate of anything, and an image
        that has moved between sets leaks, or stops leaking, accordingly. The vectors outlive
        both -- they describe a picture, not a version -- so a move costs a neighbour graph,
        not an afternoon of embedding.
        """
        import numpy as np

        from granum.core.embeddings import EmbeddingStore
        from granum.metrics.embeddings import NeighbourPolicy, neighbours, summarise

        store = EmbeddingStore(project, dataset, config=config)
        status = store.status()
        rows = _dataset_image_rows(project, dataset)
        current = {key: (name, source) for key, name, source in rows}
        signature = hashlib.blake2s(
            "\n".join(f"{key}\t{name}" for key, name, _ in rows).encode(), digest_size=8
        ).hexdigest()
        stamp = f"{(status or {}).get('created')}:{(status or {}).get('images')}:{signature}"
        hit = embedding_cache.get(f"{project}/{dataset}")
        if hit is not None and hit[0] == stamp:
            return hit[1]
        images, _, vectors = store.load()
        keep = np.asarray([row for row, key in enumerate(images) if key in current], dtype=int)
        keys = [images[row] for row in keep]
        sets = [current[key][0] for key in keys]
        sources = [current[key][1] for key in keys]
        policy = NeighbourPolicy()
        index_array, distance = neighbours(vectors[keep], policy.k)
        report = summarise(keys, sets, vectors[keep], index_array, distance, policy, sources)
        report["embedder"] = (status or {}).get("embedder")
        #: Images in the dataset with no vector yet: added since, and in no group until embedded.
        report["missing"] = len(current) - len(keys)
        #: Vectors kept for images the dataset no longer holds. Left alone: they may come back.
        report["dropped"] = len(images) - len(keys)
        embedding_cache[f"{project}/{dataset}"] = (stamp, report)
        return report

    @app.get("/api/embeddings")
    def embeddings_status(project: str = Query(...), dataset: str = Query(...)) -> dict[str, Any]:
        """Whether this dataset has vectors, what made them, and how many images lack one."""
        from granum.core.embeddings import EmbeddingError, EmbeddingStore
        from granum.metrics.embeddings import available_embedder, describe_embedder

        store = EmbeddingStore(project, dataset, config=config)
        try:
            status = store.status()
        except EmbeddingError as exc:
            raise _error(409, str(exc)) from exc
        rows = _dataset_image_rows(project, dataset)
        missing = store.missing([key for key, _, _ in rows]) if status else [key for key, _, _ in rows]
        return {
            "project": project,
            "dataset": dataset,
            "status": status,
            "images": len(rows),
            "missing": len(missing),
            "available": describe_embedder(available_embedder()),
        }

    @app.post("/api/embeddings")
    def embeddings_compute(request: EmbeddingRequest = Body(...)) -> dict[str, Any]:
        """Embed every image of a dataset. A job: minutes on a large set, seconds on a small one."""
        from granum.core.embeddings import EmbeddingStore
        from granum.metrics.embeddings import available_embedder, describe_embedder, embed_images

        rows = _dataset_image_rows(request.project, request.dataset)
        if not rows:
            raise _error(404, f"no images in dataset {request.dataset!r}")
        embedder = available_embedder(request.embedder)

        def work(job: Any) -> Any:
            job.progress("Reading the images", 0, len(rows))
            paths = [_media_path(key) for key, _, _ in rows]

            def report(done: int, total: int) -> None:
                if job.cancel.is_set():
                    raise GranumError("stopped")
                job.progress(f"Looking at the images with {describe_embedder(embedder)['name']}", done, total)

            vectors, failed = embed_images(paths, embedder=embedder, progress=report)
            job.progress("Saving", len(rows), len(rows))
            store = EmbeddingStore(request.project, request.dataset, config=config)
            status = store.save([key for key, _, _ in rows], [name for _, name, _ in rows], vectors,
                                embedder=embedder, unreadable=len(failed))
            embedding_cache.pop(f"{request.project}/{request.dataset}", None)
            return {"status": status, "unreadable": len(failed)}

        return jobs.start("embeddings", work).to_dict()

    def _media_path(key: str) -> str:
        """An image reference as a path the embedder can open.

        The keys come from the dataset's own indexed tables, so they are already inside the
        roots the service may read; nothing from a client reaches here.
        """
        return Url(key).path

    @app.get("/api/embeddings/report")
    def embeddings_report(project: str = Query(...), dataset: str = Query(...),
                          limit: int = Query(200, ge=0, le=5000)) -> dict[str, Any]:
        """Duplicate groups, cross-split leaks and outliers for one dataset."""
        from granum.core.embeddings import EmbeddingError

        try:
            report = _embedding_report(project, dataset)
        except EmbeddingError as exc:
            raise _error(404, str(exc)) from exc
        duplicates = report["duplicates"]
        exports = report["exports"]
        return {
            **{k: v for k, v in report.items() if k not in ("uniqueness", "duplicates", "exports", "leaks")},
            "duplicates": {**duplicates, "groups": duplicates["groups"][:limit],
                           "spreads": duplicates["spreads"][:limit],
                           "families": duplicates["families"][:limit],
                           "shown": min(limit, len(duplicates["groups"])),
                           "total": len(duplicates["groups"])},
            "exports": {**exports, "groups": exports["groups"][:limit],
                        "shown": min(limit, len(exports["groups"]))},
            "leaks": report["leaks"][:limit],
            "leaks_total": len(report["leaks"]),
            "outliers": report["outliers"][:limit],
        }

    @app.get("/api/embeddings/scores")
    def embeddings_scores(project: str = Query(...), dataset: str = Query(...)) -> dict[str, Any]:
        """Uniqueness per image, for sorting a gallery. Small enough to send whole."""
        from granum.core.embeddings import EmbeddingError

        try:
            report = _embedding_report(project, dataset)
        except EmbeddingError as exc:
            raise _error(404, str(exc)) from exc
        duplicated = {image for group in report["duplicates"]["groups"] for image in group}
        return {"uniqueness": report["uniqueness"], "duplicated": sorted(duplicated)}

    @app.get("/api/embeddings/similar")
    def embeddings_similar(project: str = Query(...), dataset: str = Query(...),
                           image: str = Query(...), k: int = Query(24, ge=1, le=200)) -> dict[str, Any]:
        """The images most like one image, nearest first.

        Answered over the dataset as it stands now, like every other reading of the graph: an
        image deleted since is not a neighbour worth offering, and the set beside each one is
        the set it is in today rather than the set it was embedded in. The image asked about
        may itself be outside that -- it is the question, not one of the answers.
        """
        import numpy as np

        from granum.core.embeddings import EmbeddingError, EmbeddingStore
        from granum.core.url import sample_key
        from granum.metrics.embeddings import similar_to, typical_distance

        store = EmbeddingStore(project, dataset, config=config)
        try:
            images, _, vectors = store.load()
        except EmbeddingError as exc:
            raise _error(404, str(exc)) from exc
        key = sample_key(image)
        try:
            row = images.index(key)
        except ValueError as exc:
            raise _error(404, "this image has no vector; compute embeddings again") from exc
        current = {name: set_name for name, set_name, _ in _dataset_image_rows(project, dataset)}
        keep = [i for i, name in enumerate(images) if name in current]
        # An image the dataset no longer holds goes on the end: asked about, never answered with.
        at = keep.index(row) if row in keep else len(keep)
        if at == len(keep):
            keep = [*keep, row]
        held = vectors[np.asarray(keep, dtype=int)]
        return {
            "image": key,
            "set": current.get(key),
            #: What a distance is read against: the median distance between two random images.
            "scale": round(typical_distance(held), 4),
            "neighbours": [
                {"image": images[keep[i]], "set": current[images[keep[i]]], "distance": distance}
                for i, distance in similar_to(held, at, k)
            ],
        }

    @app.get("/api/embeddings/map")
    def embeddings_map(project: str = Query(...), dataset: str = Query(...)) -> dict[str, Any]:
        """A 2D point per image, for a map of the set."""
        from granum.core.embeddings import EmbeddingError, EmbeddingStore
        from granum.metrics.embeddings import project as project_vectors

        store = EmbeddingStore(project, dataset, config=config)
        try:
            images, sets, vectors = store.load()
        except EmbeddingError as exc:
            raise _error(404, str(exc)) from exc
        points = project_vectors(vectors)
        return {
            "images": images,
            "sets": sets,
            "points": [[round(float(x), 4), round(float(y), 4)] for x, y in points],
        }

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

    def _detect_other(folder: Url) -> list[dict[str, Any]]:
        """Datasets in a layout that is not COCO, as sources the wizard can offer.

        Each is marked with the format it is in; the import converts it to COCO before
        anything is checked, so a VOC folder and a COCO file go through exactly the same
        preflight, media handling and findings rather than through two code paths.
        """
        if folder.scheme != "file":
            return []
        root = Path(folder.path)
        found: list[dict[str, Any]] = []
        try:
            children = sorted(root.iterdir())
        except OSError:
            return found

        def source(kind: str, path: Path, split: str, images: Path | None = None) -> dict[str, Any]:
            return {"split": split, "annotations": str(path), "images": str(images or path.parent),
                    "format": kind}

        for child in children:
            name = child.name.lower()
            if child.is_file() and name in ("data.yaml", "data.yml", "dataset.yaml"):
                try:
                    import yaml as yaml_module

                    document = yaml_module.safe_load(child.read_text()) or {}
                except (OSError, ValueError):
                    continue
                for split in ("train", "val", "valid", "test"):
                    if document.get(split):
                        found.append({**source("yolo", child, split), "yolo_split": split})
            elif child.is_file() and child.suffix.lower() == ".csv":
                found.append(source("csv", child, child.stem or "train"))
        if found:
            return found

        # A folder of VOC XML or KITTI text, either here or one level down per split.
        def look(place: Path, split: str) -> None:
            annotations = place / "Annotations" if (place / "Annotations").is_dir() else place
            if any(annotations.glob("*.xml")):
                found.append(source("voc", annotations, split, place))
                return
            labels = next((place / n for n in ("label_2", "labels", "label") if (place / n).is_dir()), None)
            if labels and any(labels.glob("*.txt")):
                found.append(source("kitti", labels, split, place))

        look(root, "train")
        if not found:
            for child in children:
                if child.is_dir():
                    look(child, child.name)
        if not found:
            # Folders of images, one per class: a classification set.
            classes = [c for c in children if c.is_dir()
                       and any(p.suffix.lower() in IMAGE_SUFFIXES_FOR_IMPORT for p in c.iterdir() if p.is_file())]
            if len(classes) >= 2:
                found.append(source("folders", root, "train"))
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
            found.append({"split": split, "annotations": str(candidate), "images": str(candidate.parent),
                          "format": "coco"})
        return found or _detect_other(folder)

    def _convert_to_coco(item: Any, annotations: Path, images: Path | None) -> Path:
        """Write somebody else's layout as a COCO file the importer can check.

        The converted file is kept beside the source under a Granum name rather than in a
        temporary folder: an import is worth being able to look at afterwards, and a file
        that vanishes the moment a job ends cannot be checked by hand.
        """
        import json as json_module

        from granum.formats.exchange import CONVERTERS

        convert = CONVERTERS.get(item.format)
        if convert is None:
            raise _error(400, f"format must be coco or one of {sorted(CONVERTERS)}")
        try:
            if item.format == "yolo":
                payload = convert(annotations, item.yolo_split or item.split or "train")
            elif item.format in ("voc", "kitti"):
                payload = convert(annotations, images_dir=images)
            elif item.format == "csv":
                payload = convert(annotations, images_dir=images)
            else:
                payload = convert(annotations)
        except GranumError as exc:
            raise _error(400, str(exc)) from exc
        except (OSError, ValueError) as exc:
            raise _error(400, f"{annotations.name} could not be read as {item.format}: {exc}") from exc
        if not payload.get("images"):
            raise _error(400, f"no images found in {annotations}")
        target_dir = annotations if annotations.is_dir() else annotations.parent
        target = target_dir / f"granum-{item.format}-{item.split or 'train'}.coco.json"
        try:
            target.write_text(json_module.dumps(payload))
        except OSError as exc:
            raise _error(400, f"cannot write the converted file beside the data: {exc}") from exc
        return target

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
            if item.format and item.format != "coco":
                annotations = Url(str(_convert_to_coco(item, Path(str(annotations)),
                                                       Path(str(images)) if images else None)))
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
        from granum.importing import example

        existing = {p["name"] for p in index.projects()}
        layout = ProjectLayout(config.project_root)
        # The generated example is for trying Granum: it never uses up a plan's projects.
        from_example = all(_within(Url(s.annotations), [example.examples_dir(config.project_root)])
                           for s in preflight.payload.sources)
        new_project = request.project_name.strip() not in existing
        if new_project and not from_example:
            try:
                licensing.require_new_project(len(example.counted_projects(layout)))
            except LicenceError as exc:
                raise _error(402, str(exc)) from exc
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
        from granum.importing.tasks import normalize_tasks

        try:
            normalize_tasks(request.tasks)
        except ValueError as exc:
            raise _error(400, str(exc)) from exc
        if request.split_plan is not None:
            unknown = sorted(set(request.split_plan) - splits)
            if unknown:
                raise _error(400, f"no split named {', '.join(unknown)} in this report")
            if any(count < 0 for count in request.split_plan.values()):
                raise _error(400, "a split cannot have fewer than no images")

        def work(job: Any) -> Any:
            result = import_coco(
                preflight.payload,
                project_name=request.project_name.strip(),
                resolutions=request.resolutions,
                dataset_name=dataset_name,
                description=request.description,
                split_plan=request.split_plan,
                tasks=request.tasks,
                progress=job.progress,
                config=config,
            )
            if from_example and new_project:
                example.mark_example_project(layout, request.project_name.strip())
            elif not from_example:
                example.unmark_example_project(layout, request.project_name.strip())
            job.progress("Indexing", 0, 1)
            index.refresh(force=True)
            return result

        return jobs.start("import", work).to_dict()

    @app.post("/api/examples/shapes")
    def example_shapes() -> dict[str, Any]:
        """Draw the generated example dataset (once) and hand its splits to the import flow."""
        from granum.importing import example

        sources = example.sources(config.project_root)
        return {
            "sources": sources,
            "images": sum(example.SPLITS.values()),
            "description": example.DESCRIPTION,
            "project_name": "shapes-example",
            "tasks": ["object_detection"],
        }

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
