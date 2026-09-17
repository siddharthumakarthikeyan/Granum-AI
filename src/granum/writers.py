"""Incremental Table construction.

Use ``TableWriter`` when data arrives a row or batch at a time, or when it is produced
programmatically rather than read from a known format. Declare the schema up front so
columns render correctly without inference guessing.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from typing import Any

from granum.core.config import Config
from granum.core.objects.run import EXAMPLE_ID_COLUMN, Run, get_active_run
from granum.core.objects.table import WEIGHT_COLUMN, Table
from granum.core.schemas import SampleWeightSchema, Schema, TableSchema
from granum.core.url import Url
from granum.errors import SchemaError, TableError


class TableWriter:
    """Accumulate rows, then ``finalize()`` into an immutable Table.

    ::

        writer = TableWriter(
            project_name="demo",
            dataset_name="train",
            schema={"image": ImageSchema(sample_type="url"),
                    "label": CategoricalLabelSchema(classes=["cat", "dog"])},
        )
        for path, label in source:
            writer.add_row({"image": path, "label": label})
        table = writer.finalize()
    """

    def __init__(
        self,
        *,
        schema: dict[str, Schema] | TableSchema,
        project_name: str = "default",
        dataset_name: str = "default",
        table_name: str = "initial",
        description: str = "",
        add_weight_column: bool = True,
        config: Config | None = None,
    ) -> None:
        resolved = schema if isinstance(schema, TableSchema) else TableSchema(schema)
        if not resolved.names:
            raise SchemaError("TableWriter needs at least one column")
        if add_weight_column and WEIGHT_COLUMN not in resolved:
            resolved = resolved.with_column(WEIGHT_COLUMN, SampleWeightSchema())
        self.schema = resolved
        self.project_name = project_name
        self.dataset_name = dataset_name
        self.table_name = table_name
        self.description = description
        self._config = config
        self._columns: dict[str, list[Any]] = {name: [] for name in resolved.names}
        self._finalized = False

    def __len__(self) -> int:
        first = next(iter(self._columns.values()), [])
        return len(first)

    def add_row(self, row: dict[str, Any]) -> None:
        """Append one row. Missing weights default to 1.0; anything else must be present."""
        if self._finalized:
            raise TableError("this writer has already been finalized")
        unknown = [key for key in row if key not in self._columns]
        if unknown:
            raise SchemaError(f"row has columns not in the schema: {unknown}")
        for name in self._columns:
            if name in row:
                self._columns[name].append(row[name])
            elif name == WEIGHT_COLUMN:
                self._columns[name].append(1.0)
            else:
                raise SchemaError(f"row is missing required column {name!r}")

    def add_batch(self, batch: dict[str, Sequence[Any]]) -> None:
        """Append many rows given as columns."""
        if self._finalized:
            raise TableError("this writer has already been finalized")
        unknown = [key for key in batch if key not in self._columns]
        if unknown:
            raise SchemaError(f"batch has columns not in the schema: {unknown}")
        lengths = {len(values) for values in batch.values()}
        if len(lengths) > 1:
            raise TableError("every column in a batch must have the same length")
        size = lengths.pop() if lengths else 0
        for name in self._columns:
            if name in batch:
                self._columns[name].extend(batch[name])
            elif name == WEIGHT_COLUMN:
                self._columns[name].extend([1.0] * size)
            else:
                raise SchemaError(f"batch is missing required column {name!r}")

    def extend(self, rows: Iterable[dict[str, Any]]) -> None:
        for row in rows:
            self.add_row(row)

    def finalize(self) -> Table:
        """Write the accumulated rows as a Table."""
        if self._finalized:
            raise TableError("this writer has already been finalized")
        if len(self) == 0:
            raise TableError("nothing to write -- add rows before finalizing")
        self._finalized = True
        return Table._write(
            data=self._columns,
            schema=self.schema,
            project_name=self.project_name,
            dataset_name=self.dataset_name,
            table_name=self.table_name,
            description=self.description,
            config=self._config,
        )

    def __enter__(self) -> TableWriter:
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        if exc_type is None and not self._finalized and len(self) > 0:
            self.finalize()


class MetricsTableWriter:
    """Push per-sample metrics from a validation loop you already own.

    Use it as a context manager -- on exit it finalizes the table *and* attaches it to
    the Run::

        with MetricsTableWriter(foreign_table_url=val_table.url) as writer:
            for example_ids, batch in loader:
                writer.add_batch({"example_id": example_ids, "loss": losses})

    ``foreign_table_url`` and an ``example_id`` per row are required together. Without
    both, the rows cannot be traced back to the samples that produced them, and the
    metrics become free-floating numbers.
    """

    def __init__(
        self,
        *,
        foreign_table_url: Url | str | None = None,
        run: Run | None = None,
        schema: dict[str, Schema] | None = None,
        constants: dict[str, Any] | None = None,
        description: str = "",
    ) -> None:
        self.foreign_table_url = Url(foreign_table_url) if foreign_table_url else None
        self._run = run
        self.schema = dict(schema or {})
        self.constants = dict(constants or {})
        self.description = description
        self._columns: dict[str, list[Any]] = {}
        self._finalized = False
        self.table: Table | None = None

    @property
    def run(self) -> Run:
        target = self._run or get_active_run()
        if target is None:
            raise TableError("no active Run -- call granum.init() first, or pass run=")
        return target

    def __len__(self) -> int:
        return len(next(iter(self._columns.values()), []))

    def add_batch(self, batch: dict[str, Sequence[Any]]) -> None:
        """Append a batch of metrics given as columns."""
        if self._finalized:
            raise TableError("this writer has already been finalized")
        if not batch:
            return

        lengths = {len(values) for values in batch.values()}
        if len(lengths) > 1:
            raise TableError(
                f"every column in a batch must have the same length; got "
                f"{ {k: len(v) for k, v in batch.items()} }"
            )
        size = lengths.pop()

        if self.foreign_table_url is not None and EXAMPLE_ID_COLUMN not in batch:
            raise SchemaError(
                f"each batch must include {EXAMPLE_ID_COLUMN!r} when foreign_table_url "
                f"is set -- that column is what joins a metric back to its sample"
            )

        if self._columns:
            new_keys = set(batch) - set(self._columns)
            missing = set(self._columns) - set(batch)
            if new_keys or missing:
                raise SchemaError(
                    f"every batch must carry the same columns. "
                    f"unexpected={sorted(new_keys)} missing={sorted(missing)}"
                )
        else:
            self._columns = {name: [] for name in batch}

        for name, values in batch.items():
            self._columns[name].extend(values)
        del size

    def add_row(self, row: dict[str, Any]) -> None:
        self.add_batch({name: [value] for name, value in row.items()})

    def finalize(self) -> Table:
        """Write the metrics table and attach it to the Run."""
        if self._finalized:
            raise TableError("this writer has already been finalized")
        if len(self) == 0:
            raise TableError("nothing to write -- add metrics before finalizing")
        self._finalized = True
        table = self.run.add_metrics(
            self._columns,
            foreign_table_url=self.foreign_table_url,
            schema=self.schema,
            constants=self.constants,
            description=self.description,
        )
        self.table = table
        return table

    def __enter__(self) -> MetricsTableWriter:
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        if exc_type is None and not self._finalized and len(self) > 0:
            self.finalize()
