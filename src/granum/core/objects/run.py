"""Runs and metrics tables.

A Run holds what a model did: per-sample metrics, aggregate scalars, and the
hyperparameters that produced them. A metrics table carries two columns that matter more
than any metric -- ``example_id`` and the Run-level ``foreign_table_url`` -- because
together they are what turns a number back into the sample that produced it.

Break that join and the metrics are just floating numbers. Everything Granum is for
depends on it holding.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Sequence
from typing import Any

import pyarrow.parquet as pq

from granum.core.config import Config, get_config
from granum.core.layout import ROW_CACHE_FILENAME, ProjectLayout, sanitize
from granum.core.objects.base import (
    GranumObject,
    read_object_payload,
    register_object_type,
    utcnow,
    write_object_payload,
)
from granum.core.objects.table import Table, _build_arrow
from granum.core.schemas import (
    ExampleIdSchema,
    Schema,
    TableSchema,
    infer_metric_schema,
)
from granum.core.url import Url
from granum.errors import GranumError

EXAMPLE_ID_COLUMN = "example_id"
AGGREGATE_FILENAME = "aggregate_metrics.json"
METRICS_DIR_PREFIX = "metrics_"

IF_EXISTS_CHOICES = ("rename", "reuse", "overwrite", "raise")


class RunError(GranumError):
    """An invalid Run operation."""


# ---------------------------------------------------------------------------
# metrics tables
# ---------------------------------------------------------------------------


@register_object_type
class MetricsTable(Table):
    """Per-sample model output, joined to an input Table by ``example_id``."""

    type_name = "metrics_table"

    def __init__(self, *, foreign_table_url: Url | str | None = None,
                 constants: dict[str, Any] | None = None, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.foreign_table_url = Url(foreign_table_url) if foreign_table_url else None
        self.constants = dict(constants or {})
        self._seal()

    def to_dict(self) -> dict[str, Any]:
        payload = super().to_dict()
        payload["type"] = self.type_name
        payload["foreign_table_url"] = (
            str(self.foreign_table_url.aliased()) if self.foreign_table_url else None
        )
        payload["constants"] = self.constants
        return payload

    @classmethod
    def from_dict(cls, payload: dict[str, Any], url: Url) -> MetricsTable:
        return cls(
            url=url,
            name=payload.get("name", Url(url).name),
            project_name=payload.get("project_name", ""),
            dataset_name=payload.get("dataset_name", ""),
            schema=TableSchema.from_dict(payload.get("schema", {})),
            row_count=payload.get("row_count", 0),
            parents=tuple(Url(p) for p in payload.get("parents", [])),
            producer=payload.get("producer", {}),
            description=payload.get("description", ""),
            created=payload.get("created", ""),
            base_name=payload.get("base_name", ""),
            foreign_table_url=payload.get("foreign_table_url"),
            constants=payload.get("constants", {}),
        )

    # -- the join -----------------------------------------------------------

    def input_table(self) -> Table:
        """The Table these metrics were collected over."""
        if self.foreign_table_url is None:
            raise RunError(
                "this metrics table has no foreign_table_url, so its rows cannot be "
                "joined back to any sample"
            )
        return Table.from_url(self.foreign_table_url)

    def join_input(
        self, columns: Sequence[str] | None = None, *, input_table: Table | None = None
    ) -> list[dict[str, Any]]:
        """Every metrics row merged with the sample it describes.

        This is the operation the whole product exists to make possible: a metric you
        do not like, resolved to the image behind it.

        ``input_table`` joins against a different revision of the input -- typically its
        latest, so corrected labels show beside the metrics computed before the fix.
        It must have the same rows; ``example_id`` is a row position.
        """
        source = input_table if input_table is not None else self.input_table()
        if EXAMPLE_ID_COLUMN not in self.schema:
            raise RunError(f"metrics table has no {EXAMPLE_ID_COLUMN!r} column")

        wanted = list(columns) if columns else source.columns
        out: list[dict[str, Any]] = []
        for row in self:
            example_id = row[EXAMPLE_ID_COLUMN]
            if not 0 <= example_id < len(source):
                raise RunError(
                    f"{EXAMPLE_ID_COLUMN}={example_id} is out of range for input table "
                    f"{source.name!r} with {len(source)} rows -- the join is broken"
                )
            sample = source[example_id]
            merged = {key: sample[key] for key in wanted if key in sample}
            merged.update(row)
            merged.update(self.constants)
            out.append(merged)
        return out

    def to_pandas_joined(self):
        import pandas as pd

        return pd.DataFrame(self.join_input())


# ---------------------------------------------------------------------------
# runs
# ---------------------------------------------------------------------------


@register_object_type
class Run(GranumObject):
    """One experiment's metrics and hyperparameters."""

    type_name = "run"

    def __init__(
        self,
        *,
        url: Url,
        name: str,
        project_name: str,
        description: str = "",
        parameters: dict[str, Any] | None = None,
        constants: dict[str, Any] | None = None,
        created: str = "",
        status: str = "running",
    ) -> None:
        self.url = Url(url)
        self.name = name
        self.project_name = project_name
        self.description = description
        self.parameters = dict(parameters or {})
        self.constants = dict(constants or {})
        self.created = created or utcnow()
        self.status = status
        self._seal()

    # -- serialization ------------------------------------------------------

    def to_dict(self) -> dict[str, Any]:
        return {
            "type": self.type_name,
            "name": self.name,
            "project_name": self.project_name,
            "description": self.description,
            "created": self.created,
            "status": self.status,
            "parameters": self.parameters,
            "constants": self.constants,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any], url: Url) -> Run:
        return cls(
            url=url,
            name=payload.get("name", Url(url).name),
            project_name=payload.get("project_name", ""),
            description=payload.get("description", ""),
            parameters=payload.get("parameters", {}),
            constants=payload.get("constants", {}),
            created=payload.get("created", ""),
            status=payload.get("status", "running"),
        )

    @classmethod
    def from_url(cls, url: Url | str) -> Run:
        url = Url(url)
        return cls.from_dict(read_object_payload(url), url)

    def _save(self) -> Run:
        write_object_payload(self.url, self.to_dict())
        return self

    def __repr__(self) -> str:
        return f"Run(name={self.name!r}, project={self.project_name!r}, url={str(self.url)!r})"

    # -- hyperparameters ----------------------------------------------------

    def set_parameters(self, parameters: dict[str, Any]) -> Run:
        """Record or update hyperparameters. Safe to call after the Run starts."""
        merged = {**self.parameters, **parameters}
        object.__setattr__(self, "parameters", merged)
        return self._save()

    def set_status(self, status: str) -> Run:
        object.__setattr__(self, "status", status)
        return self._save()

    # -- metrics tables -----------------------------------------------------

    def _next_metrics_url(self) -> Url:
        existing = [u.name for u in self.url.ls() if u.name.startswith(METRICS_DIR_PREFIX)]
        return self.url / f"{METRICS_DIR_PREFIX}{len(existing):04d}"

    def metrics_tables(self) -> list[MetricsTable]:
        """Every metrics table on this Run, in creation order."""
        out: list[MetricsTable] = []
        for child in self.url.ls():
            if not child.name.startswith(METRICS_DIR_PREFIX):
                continue
            try:
                out.append(MetricsTable.from_url(child))
            except Exception:  # noqa: BLE001 - a partial write is not a fatal error
                continue
        return sorted(out, key=lambda t: t.name)

    def add_metrics(
        self,
        metrics: dict[str, Sequence[Any]],
        *,
        foreign_table_url: Url | str | None = None,
        schema: dict[str, Schema] | None = None,
        constants: dict[str, Any] | None = None,
        description: str = "",
    ) -> MetricsTable:
        """Write a complete metrics dict in one call.

        The right entry point when the numbers are already in hand. For a loop, use
        ``MetricsTableWriter`` so memory does not grow without bound.
        """
        columns = {name: list(values) for name, values in metrics.items()}
        if not columns:
            raise RunError("no metrics given")

        lengths = {len(values) for values in columns.values()}
        if len(lengths) > 1:
            raise RunError(
                f"every metric must have one value per sample; got lengths "
                f"{ {k: len(v) for k, v in columns.items()} }"
            )

        if foreign_table_url is not None and EXAMPLE_ID_COLUMN not in columns:
            raise RunError(
                f"metrics joined to an input Table must include an "
                f"{EXAMPLE_ID_COLUMN!r} column -- without it the rows cannot be "
                f"traced back to their samples"
            )

        resolved: dict[str, Schema] = dict(schema or {})
        for name, values in columns.items():
            resolved.setdefault(
                name,
                ExampleIdSchema() if name == EXAMPLE_ID_COLUMN else infer_metric_schema(values, name),
            )
        table_schema = TableSchema({name: resolved[name] for name in columns})

        target = self._next_metrics_url()
        arrow = _build_arrow(table_schema, columns)
        table = MetricsTable(
            url=target,
            name=target.name,
            project_name=self.project_name,
            dataset_name=self.name,
            schema=table_schema,
            row_count=arrow.num_rows,
            producer={"op": "add_metrics", "args": {"run": self.name}},
            description=description,
            foreign_table_url=foreign_table_url,
            constants=constants,
        )
        target.mkdir()
        pq.write_table(arrow, (target / ROW_CACHE_FILENAME).path, filesystem=target.fs)
        write_object_payload(target, table.to_dict())
        return table

    # -- aggregate metrics --------------------------------------------------

    @property
    def _aggregate_url(self) -> Url:
        return self.url / AGGREGATE_FILENAME

    def log(self, values: dict[str, Any]) -> Run:
        """Append a row of aggregate scalars.

        Anything keyed ``epoch`` or ``iteration`` becomes the x-axis of a chart later.
        Aggregate metrics live alongside the per-sample tables and are independent of
        them -- log both.
        """
        rows = self.aggregate_metrics()
        rows.append({**values, "_logged": utcnow()})
        self._aggregate_url.write_text(json.dumps(rows, indent=2, default=str))
        return self

    def aggregate_metrics(self) -> list[dict[str, Any]]:
        if not self._aggregate_url.exists():
            return []
        return json.loads(self._aggregate_url.read_text())

    # -- convenience --------------------------------------------------------

    def joined(
        self, input_for: Callable[[MetricsTable], Table] | None = None
    ) -> list[dict[str, Any]]:
        """Every metrics row from every metrics table, joined to its input sample.

        ``input_for`` picks the input revision per metrics table; by default each joins
        the exact Table it was collected over.
        """
        out: list[dict[str, Any]] = []
        for table in self.metrics_tables():
            if table.foreign_table_url is not None:
                source = input_for(table) if input_for is not None else None
                out.extend(table.join_input(input_table=source))
        return out


# ---------------------------------------------------------------------------
# lifecycle
# ---------------------------------------------------------------------------

_ACTIVE_RUN: Run | None = None


def get_active_run() -> Run | None:
    """The Run that metric writes attach to when none is named."""
    return _ACTIVE_RUN


def set_active_run(run: Run | None) -> None:
    global _ACTIVE_RUN
    _ACTIVE_RUN = run


def init(
    project_name: str = "default",
    run_name: str | None = None,
    *,
    description: str = "",
    parameters: dict[str, Any] | None = None,
    constants: dict[str, Any] | None = None,
    if_exists: str = "rename",
    config: Config | None = None,
) -> Run:
    """Start a Run and make it active.

    ``if_exists`` decides what happens when the name is taken: ``rename`` (default)
    picks a free name, ``reuse`` opens the existing Run, ``overwrite`` replaces it, and
    ``raise`` refuses.
    """
    if if_exists not in IF_EXISTS_CHOICES:
        raise RunError(f"if_exists must be one of {IF_EXISTS_CHOICES}, got {if_exists!r}")

    config = config or get_config()
    layout = ProjectLayout(config.project_root)
    base = run_name or f"run-{utcnow().replace(':', '-')}"
    target = layout.run(project_name, base)

    if target.exists():
        if if_exists == "raise":
            raise RunError(f"run {base!r} already exists in project {project_name!r}")
        if if_exists == "reuse":
            run = Run.from_url(target)
            if parameters:
                run.set_parameters(parameters)
            set_active_run(run)
            return run
        if if_exists == "overwrite":
            target.rm(recursive=True)
        else:  # rename
            for index in range(1, 10_000):
                candidate = layout.run(project_name, f"{base}_{index}")
                if not candidate.exists():
                    target = candidate
                    break
            else:
                raise RunError(f"could not find a free run name near {base!r}")

    run = Run(
        url=target,
        name=sanitize(target.name),
        project_name=project_name,
        description=description,
        parameters=parameters,
        constants=constants,
    )
    target.mkdir()
    run._save()
    set_active_run(run)
    return run


def log(values: dict[str, Any], *, run: Run | None = None) -> Run:
    """Log aggregate scalars to a Run, defaulting to the active one."""
    target = run or get_active_run()
    if target is None:
        raise RunError("no active Run -- call granum.init() first, or pass run=")
    return target.log(values)
