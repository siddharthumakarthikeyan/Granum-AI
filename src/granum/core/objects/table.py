"""The Table: an immutable, schema-aware, versioned view of a dataset.

A Table is simultaneously the thing a training loop iterates and the record of what data
produced a Run. It is never mutated -- every operation writes a new revision that names
its parents, which is what makes lineage trustworthy and editing safe.

Rows are materialized to ``row_cache.parquet`` beside the object body. The metadata
records *how* the revision was produced (``producer``), so the chain stays inspectable
even though reads are a single Parquet load rather than a replay.
"""

from __future__ import annotations

import random
from collections.abc import Callable, Iterable, Iterator, Sequence
from typing import Any

import pyarrow as pa
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
from granum.core.schemas import (
    BoolSchema,
    CategoricalLabelSchema,
    EmbeddingSchema,
    Float32Schema,
    ImageSchema,
    Int32Schema,
    Int64Schema,
    SampleWeightSchema,
    Schema,
    StringSchema,
    TableSchema,
    ValueMapEntry,
)
from granum.core.url import Url
from granum.errors import SchemaError, TableError

WEIGHT_COLUMN = "weight"

#: Column types a user can create from the dashboard.
EDITABLE_COLUMN_KINDS = {
    "bool": BoolSchema,
    "string": StringSchema,
    "float32": Float32Schema,
    "int32": Int32Schema,
}

_IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".bmp", ".gif", ".webp", ".tif", ".tiff"}


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


#: Revision operations that keep every row at its position. Per-sample metrics address
#: rows by position, so they can be shown beside a descendant only through these.
ROW_PRESERVING_OPS = frozenset({
    "edit", "set_values", "add_column", "delete_columns",
    "set_value_map", "add_value_map_item", "set_value_map_item", "delete_value_map_item",
})


def infer_schema(values: Sequence[Any], name: str = "") -> Schema:
    """Guess a column schema from its values. Explicit schemas always beat this."""
    sample = next((v for v in values if v is not None), None)
    if sample is None:
        return StringSchema()
    if isinstance(sample, bool):
        return BoolSchema()
    if isinstance(sample, int):
        return Int64Schema()
    if isinstance(sample, float):
        return Float32Schema()
    if isinstance(sample, (list, tuple)):
        return EmbeddingSchema(shape=(len(sample),))
    text = str(sample)
    if name.lower() in {"image", "image_url", "img"} or any(
        text.lower().endswith(suffix) for suffix in _IMAGE_SUFFIXES
    ):
        return ImageSchema(sample_type="url")
    return StringSchema()


def _build_arrow(schema: TableSchema, data: dict[str, list[Any]]) -> pa.Table:
    missing = [name for name in schema.names if name not in data]
    if missing:
        raise SchemaError(f"schema declares columns with no data: {missing}")
    extra = [name for name in data if name not in schema.columns]
    if extra:
        raise SchemaError(f"data has columns with no schema: {extra}")

    lengths = {len(values) for values in data.values()}
    if len(lengths) > 1:
        raise TableError(f"columns have differing lengths: { {k: len(v) for k, v in data.items()} }")

    arrays = []
    for name in schema.names:
        column = schema[name]
        stored = [column.to_storage(value) for value in data[name]]
        try:
            arrays.append(pa.array(stored, type=column.arrow_type()))
        except (pa.ArrowInvalid, pa.ArrowTypeError) as exc:
            raise SchemaError(f"column {name!r} does not match {column.kind}: {exc}") from exc
    return pa.Table.from_arrays(arrays, schema=schema.arrow_schema())


def _check_edit_value(column: str, schema: Schema, value: Any) -> None:
    """Reject an edit that would silently store something meaningless."""
    if isinstance(schema, CategoricalLabelSchema):
        if isinstance(value, bool) or not isinstance(value, int) or value not in schema.value_map:
            raise TableError(
                f"{value!r} is not a class of {column!r}; known indices: {sorted(schema.value_map)}"
            )
    elif isinstance(schema, SampleWeightSchema):
        if isinstance(value, bool) or not isinstance(value, (int, float)) or value < schema.minimum:
            raise TableError(f"weight for {column!r} must be a number >= {schema.minimum}, got {value!r}")
    elif isinstance(schema, BoolSchema):
        if not isinstance(value, bool):
            raise TableError(f"{column!r} holds true/false, got {value!r}")
    elif isinstance(schema, (Int32Schema, Int64Schema)):
        if isinstance(value, bool) or not isinstance(value, int):
            raise TableError(f"{column!r} holds whole numbers, got {value!r}")
    elif isinstance(schema, Float32Schema):
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise TableError(f"{column!r} holds numbers, got {value!r}")
    elif isinstance(schema, StringSchema):
        if not isinstance(value, str):
            raise TableError(f"{column!r} holds text, got {value!r}")


def _take(arrow: pa.Table, indices: Sequence[int]) -> pa.Table:
    """``Table.take`` that preserves column types when nothing is selected."""
    if not indices:
        return arrow.schema.empty_table()
    return arrow.take(pa.array(list(indices), type=pa.int64()))


def _unique_url(base: Url, name: str) -> Url:
    """Pick a table directory name that is not already taken."""
    candidate = base / sanitize(name)
    if not candidate.exists():
        return candidate
    for index in range(1, 10_000):
        candidate = base / sanitize(f"{name}_{index}")
        if not candidate.exists():
            return candidate
    raise TableError(f"could not find a free table name near {name!r}")


# ---------------------------------------------------------------------------
# views
# ---------------------------------------------------------------------------


class TableView:
    """A Table with a transform applied on read.

    Hand this to a ``DataLoader``. The transform runs per sample on access and the Table
    itself is untouched, so the same Table can back an augmented training view and a
    clean evaluation view at once.

    The transform must be picklable when used with ``num_workers > 0`` -- use a
    module-level function, not a lambda.
    """

    def __init__(self, table: Table, transform: Callable[[dict[str, Any]], Any]) -> None:
        self.table = table
        self.transform = transform

    def __len__(self) -> int:
        return len(self.table)

    def __getitem__(self, index: int) -> Any:
        return self.transform(self.table[index])

    def __iter__(self) -> Iterator[Any]:
        for i in range(len(self)):
            yield self[i]

    def __repr__(self) -> str:
        return f"TableView({self.table.name!r}, rows={len(self)})"


# ---------------------------------------------------------------------------
# Table
# ---------------------------------------------------------------------------


@register_object_type
class Table(GranumObject):
    """One revision of a dataset."""

    type_name = "table"

    def __init__(
        self,
        *,
        url: Url,
        name: str,
        project_name: str,
        dataset_name: str,
        schema: TableSchema,
        row_count: int,
        parents: tuple[Url, ...] = (),
        producer: dict[str, Any] | None = None,
        description: str = "",
        created: str = "",
        base_name: str = "",
        arrow: pa.Table | None = None,
    ) -> None:
        self.url = Url(url)
        self.name = name
        self.base_name = base_name or name
        self.project_name = project_name
        self.dataset_name = dataset_name
        self.schema = schema
        self.row_count = int(row_count)
        self.parents = tuple(Url(p) for p in parents)
        self.producer = dict(producer or {})
        self.description = description
        self.created = created or utcnow()
        self._arrow = arrow
        if type(self) is Table:
            self._seal()

    # -- construction -------------------------------------------------------

    @staticmethod
    def _write(
        *,
        data: dict[str, list[Any]],
        schema: TableSchema,
        project_name: str,
        dataset_name: str,
        table_name: str,
        description: str = "",
        parents: tuple[Url, ...] = (),
        producer: dict[str, Any] | None = None,
        config: Config | None = None,
        url: Url | None = None,
    ) -> Table:
        config = config or get_config()
        layout = ProjectLayout(config.project_root)
        target = (
            Url(url)
            if url is not None
            else _unique_url(layout.tables_dir(project_name, dataset_name), table_name)
        )
        arrow = _build_arrow(schema, data)

        table = Table(
            url=target,
            name=target.name,
            project_name=project_name,
            dataset_name=dataset_name,
            schema=schema,
            row_count=arrow.num_rows,
            parents=parents,
            producer=producer or {"op": "create"},
            description=description,
            arrow=arrow,
        )
        target.mkdir()
        pq.write_table(arrow, (target / ROW_CACHE_FILENAME).path, filesystem=target.fs)
        write_object_payload(target, table.to_dict())
        return table

    def _derive(
        self,
        *,
        arrow: pa.Table,
        schema: TableSchema,
        op: str,
        args: dict[str, Any] | None = None,
        suffix: str | None = None,
        description: str = "",
        name: str | None = None,
        edits: dict[str, Any] | None = None,
    ) -> Table:
        """Write a new revision descending from this one."""
        layout = ProjectLayout(get_config().project_root)
        base = layout.tables_dir(self.project_name, self.dataset_name)
        target = _unique_url(base, name or f"{self.base_name}_{suffix or op}")

        table = Table(
            url=target,
            name=target.name,
            base_name=self.base_name,
            project_name=self.project_name,
            dataset_name=self.dataset_name,
            schema=schema,
            row_count=arrow.num_rows,
            parents=(self.url,),
            producer={"op": op, "args": args or {}, **({"edits": edits} if edits else {})},
            description=description,
            arrow=arrow,
        )
        target.mkdir()
        pq.write_table(arrow, (target / ROW_CACHE_FILENAME).path, filesystem=target.fs)
        write_object_payload(target, table.to_dict())
        return table

    # -- serialization ------------------------------------------------------

    def to_dict(self) -> dict[str, Any]:
        return {
            "type": self.type_name,
            "name": self.name,
            "project_name": self.project_name,
            "dataset_name": self.dataset_name,
            "base_name": self.base_name,
            "description": self.description,
            "created": self.created,
            "row_count": self.row_count,
            "parents": [str(p.aliased()) for p in self.parents],
            "producer": self.producer,
            "schema": self.schema.to_dict(),
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any], url: Url) -> Table:
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
        )

    # -- data access --------------------------------------------------------

    def to_arrow(self) -> pa.Table:
        """The backing Arrow table, loaded from the row cache on first access."""
        if self._arrow is None:
            path = self.url / ROW_CACHE_FILENAME
            if not path.exists():
                raise TableError(f"{self.url} has no row cache")
            object.__setattr__(self, "_arrow", pq.read_table(path.path, filesystem=path.fs))
        return self._arrow

    def to_pandas(self):
        return self.to_arrow().to_pandas()

    def to_pydict(self) -> dict[str, list[Any]]:
        return self.to_arrow().to_pydict()

    @property
    def columns(self) -> list[str]:
        return self.schema.names

    def __len__(self) -> int:
        return self.row_count

    def __getitem__(self, index: int) -> dict[str, Any]:
        """Return one sample, materialized according to its schema."""
        if index < 0:
            index += self.row_count
        if not 0 <= index < self.row_count:
            raise IndexError(f"row {index} out of range for a table with {self.row_count} rows")
        arrow = self.to_arrow()
        out: dict[str, Any] = {}
        for name in self.schema.names:
            value = arrow.column(name)[index].as_py()
            out[name] = self.schema[name].from_storage(value)
        return out

    def __iter__(self) -> Iterator[dict[str, Any]]:
        for index in range(self.row_count):
            yield self[index]

    def with_transform(self, transform: Callable[[dict[str, Any]], Any]) -> TableView:
        """A read-time view of this Table. Does not modify the Table."""
        return TableView(self, transform)

    def __repr__(self) -> str:
        return (
            f"Table(name={self.name!r}, rows={self.row_count}, "
            f"columns={self.columns}, url={str(self.url)!r})"
        )

    # -- revision operations ------------------------------------------------

    def add_column(
        self, name: str, values: Sequence[Any], schema: Schema | None = None
    ) -> Table:
        """New revision with one more column."""
        if name in self.schema:
            raise TableError(f"column {name!r} already exists")
        if len(values) != self.row_count:
            raise TableError(
                f"expected {self.row_count} values for {name!r}, got {len(values)}"
            )
        column_schema = schema or infer_schema(list(values), name)
        new_schema = self.schema.with_column(name, column_schema)
        data = self.to_pydict()
        data[name] = [column_schema.to_storage(v) for v in values]
        arrow = _build_arrow(new_schema, data)
        return self._derive(arrow=arrow, schema=new_schema, op="add_column", args={"name": name})

    def delete_column(self, name: str) -> Table:
        return self.delete_columns([name])

    def delete_columns(self, names: Iterable[str]) -> Table:
        """New revision with columns removed."""
        drop = list(names)
        unknown = [n for n in drop if n not in self.schema]
        if unknown:
            raise TableError(f"no such column(s): {unknown}")
        new_schema = self.schema.without_columns(drop)
        if not new_schema.names:
            raise TableError("cannot delete every column")
        arrow = self.to_arrow().select(new_schema.names)
        return self._derive(
            arrow=arrow, schema=new_schema, op="delete_columns", args={"names": drop}
        )

    def delete_rows(self, indices: Iterable[int]) -> Table:
        """New revision with rows removed."""
        drop = {i + self.row_count if i < 0 else i for i in indices}
        out_of_range = [i for i in drop if not 0 <= i < self.row_count]
        if out_of_range:
            raise TableError(f"row index out of range: {sorted(out_of_range)}")
        keep = [i for i in range(self.row_count) if i not in drop]
        arrow = _take(self.to_arrow(), keep)
        return self._derive(
            arrow=arrow, schema=self.schema, op="delete_rows", args={"count": len(drop)}
        )

    def filter(
        self,
        predicate: Callable[[dict[str, Any]], bool],
        *,
        name: str | None = None,
        description: str = "",
    ) -> Table:
        """New revision containing only rows for which ``predicate`` is true."""
        keep = [i for i in range(self.row_count) if predicate(self[i])]
        arrow = _take(self.to_arrow(), keep)
        return self._derive(
            arrow=arrow, schema=self.schema, op="filter", args={"kept": len(keep)},
            name=name, description=description,
        )

    def subset(
        self,
        include_probability: float = 1.0,
        *,
        range_factor_min: float = 0.0,
        range_factor_max: float = 1.0,
        seed: int | None = None,
    ) -> Table:
        """New revision holding a slice of the rows, optionally sampled within it."""
        if not 0.0 <= include_probability <= 1.0:
            raise TableError("include_probability must be between 0 and 1")
        start = int(self.row_count * range_factor_min)
        stop = int(self.row_count * range_factor_max)
        candidates = list(range(start, stop))
        if include_probability < 1.0:
            rng = random.Random(seed)
            candidates = [i for i in candidates if rng.random() < include_probability]
        arrow = _take(self.to_arrow(), candidates)
        return self._derive(
            arrow=arrow,
            schema=self.schema,
            op="subset",
            args={"include_probability": include_probability, "rows": len(candidates)},
        )

    def join_tables(self, other: Table) -> Table:
        """New revision concatenating ``other`` onto this Table."""
        if self.schema.names != other.schema.names:
            raise TableError(
                f"cannot join tables with different columns: "
                f"{self.schema.names} vs {other.schema.names}"
            )
        arrow = pa.concat_tables([self.to_arrow(), other.to_arrow()])
        table = self._derive(
            arrow=arrow,
            schema=self.schema,
            op="join_tables",
            args={"other": str(other.url.aliased())},
        )
        object.__setattr__(table, "parents", (self.url, other.url))
        write_object_payload(table.url, table.to_dict())
        return table

    def set_values(self, column: str, values: dict[int, Any]) -> Table:
        """New revision with individual cells replaced. The label-correction primitive."""
        if column not in self.schema:
            raise TableError(f"no such column: {column!r}")
        column_schema = self.schema[column]
        data = self.to_pydict()
        target = list(data[column])
        for index, value in values.items():
            position = index + self.row_count if index < 0 else index
            if not 0 <= position < self.row_count:
                raise TableError(f"row index out of range: {index}")
            target[position] = column_schema.to_storage(value)
        data[column] = target
        arrow = _build_arrow(self.schema, data)
        return self._derive(
            arrow=arrow,
            schema=self.schema,
            op="set_values",
            args={"column": column, "count": len(values)},
            suffix="edit",
        )

    def apply_edits(
        self,
        *,
        values: dict[str, dict[int, Any]] | None = None,
        new_columns: dict[str, tuple[str, Any]] | None = None,
        value_maps: dict[str, dict[int, Any]] | None = None,
        table_name: str | None = None,
        description: str = "",
    ) -> Table:
        """One new revision holding a whole editing session.

        This is what a dashboard commit calls. Correcting twenty labels, zeroing ten
        weights and adding a class should read as one step in the lineage, not
        thirty-one, so everything lands in a single revision:

        - ``new_columns``: ``{name: (kind, default)}`` with kind one of
          ``bool``, ``string``, ``float32``, ``int32``. Created writable.
        - ``value_maps``: ``{column: full value map}`` for categorical columns.
        - ``values``: ``{column: {row: value}}``, applied last, so a cell may use a class
          or column created in the same call.

        Only writable columns can be edited. The sparse edit set is recorded in the
        revision's ``producer`` so what changed stays inspectable without diffing.
        """
        from granum.core.schemas import _coerce_value_map

        values = {c: dict(cells) for c, cells in (values or {}).items() if cells}
        new_columns = dict(new_columns or {})
        value_maps = dict(value_maps or {})
        if not (values or new_columns or value_maps):
            raise TableError("nothing to commit: no edits were given")

        schema = self.schema
        data = self.to_pydict()

        for name, (kind, default) in new_columns.items():
            if name in schema:
                raise TableError(f"column {name!r} already exists")
            if kind not in EDITABLE_COLUMN_KINDS:
                raise TableError(
                    f"cannot create a {kind!r} column; choose one of {sorted(EDITABLE_COLUMN_KINDS)}"
                )
            column_schema = EDITABLE_COLUMN_KINDS[kind](writable=True)
            schema = schema.with_column(name, column_schema)
            data[name] = [column_schema.to_storage(default)] * self.row_count

        for column, value_map in value_maps.items():
            current = schema[column]
            if not isinstance(current, CategoricalLabelSchema):
                raise TableError(f"column {column!r} is not categorical; it has no classes")
            replacement = type(current)(
                value_map=_coerce_value_map(value_map),
                description=current.description,
                writable=current.writable,
                default_visible=current.default_visible,
                number_role=current.number_role,
            )
            schema = schema.with_column(column, replacement)

        for column, cells in values.items():
            column_schema = schema[column]
            if not column_schema.writable:
                raise TableError(f"column {column!r} is read-only")
            target = list(data[column])
            for raw_index, value in cells.items():
                index = int(raw_index)
                if not 0 <= index < self.row_count:
                    raise TableError(f"row index out of range for {column!r}: {index}")
                _check_edit_value(column, column_schema, value)
                try:
                    target[index] = column_schema.to_storage(value)
                except SchemaError as exc:
                    raise TableError(f"{column!r} row {index}: {exc}") from exc
            data[column] = target

        # A class may only be removed once no row uses it.
        for column in value_maps:
            known = set(schema[column].value_map)  # type: ignore[attr-defined]
            used = {v for v in data[column] if v is not None}
            orphaned = sorted(used - known)
            if orphaned:
                raise TableError(
                    f"{column!r} still has rows labelled with removed class index(es) {orphaned}"
                )

        arrow = _build_arrow(schema, data)
        summary = {
            "cells": {column: len(cells) for column, cells in values.items()},
            "columns_added": sorted(new_columns),
            "value_maps": sorted(value_maps),
        }
        sparse = {
            "values": {c: {str(i): v for i, v in cells.items()} for c, cells in values.items()},
            "new_columns": {n: [k, d] for n, (k, d) in new_columns.items()},
            "value_maps": {
                c: {str(i): e.to_dict() for i, e in schema[c].value_map.items()}  # type: ignore[attr-defined]
                for c in value_maps
            },
        }
        return self._derive(
            arrow=arrow,
            schema=schema,
            op="edit",
            args=summary,
            suffix="edit",
            description=description,
            name=table_name,
            edits=sparse,
        )

    def set_weights(self, weights: dict[int, float] | float) -> Table:
        """New revision with sample weights changed. 0 excludes a sample from training."""
        if WEIGHT_COLUMN not in self.schema:
            raise TableError(
                f"this table has no {WEIGHT_COLUMN!r} column -- create it with "
                f"add_weight_column=True"
            )
        if isinstance(weights, (int, float)):
            mapping = {i: float(weights) for i in range(self.row_count)}
        else:
            mapping = {int(k): float(v) for k, v in weights.items()}
        return self.set_values(WEIGHT_COLUMN, mapping)

    def squash(self, output_url: Url | str | None = None) -> Table:
        """Copy data and schema with lineage collapsed, producing an independent Table."""
        layout = ProjectLayout(get_config().project_root)
        target = (
            Url(output_url)
            if output_url is not None
            else _unique_url(
                layout.tables_dir(self.project_name, self.dataset_name), f"{self.name}_squashed"
            )
        )
        arrow = self.to_arrow()
        table = Table(
            url=target,
            name=target.name,
            project_name=self.project_name,
            dataset_name=self.dataset_name,
            schema=self.schema,
            row_count=arrow.num_rows,
            parents=(),
            base_name=target.name,
            producer={"op": "squash", "args": {"from": str(self.url.aliased())}},
            description=self.description,
            arrow=arrow,
        )
        target.mkdir()
        pq.write_table(arrow, (target / ROW_CACHE_FILENAME).path, filesystem=target.fs)
        write_object_payload(target, table.to_dict())
        return table

    # -- value maps ---------------------------------------------------------

    def get_value_map(self, column: str) -> dict[int, ValueMapEntry]:
        schema = self.schema[column]
        if not isinstance(schema, CategoricalLabelSchema):
            raise TableError(f"column {column!r} is not categorical")
        return dict(schema.value_map)

    def get_simple_value_map(self, column: str) -> dict[int, str]:
        return {k: v.internal_name for k, v in self.get_value_map(column).items()}

    def _with_value_map(self, column: str, value_map: dict[int, ValueMapEntry], op: str) -> Table:
        current = self.schema[column]
        if not isinstance(current, CategoricalLabelSchema):
            raise TableError(f"column {column!r} is not categorical")
        replacement = type(current)(
            value_map=value_map,
            description=current.description,
            writable=current.writable,
            default_visible=current.default_visible,
            number_role=current.number_role,
        )
        new_schema = self.schema.with_column(column, replacement)
        return self._derive(
            arrow=self.to_arrow(),
            schema=new_schema,
            op=op,
            args={"column": column},
            suffix="classes",
        )

    def set_value_map(self, column: str, value_map: dict[int, Any]) -> Table:
        from granum.core.schemas import _coerce_value_map

        return self._with_value_map(column, _coerce_value_map(value_map), "set_value_map")

    def add_value_map_item(
        self, column: str, internal_name: str, *, display_name: str = "", color: str = ""
    ) -> Table:
        """New revision with an extra class. Used when correction needs a class that
        does not exist yet."""
        value_map = self.get_value_map(column)
        if any(entry.internal_name == internal_name for entry in value_map.values()):
            raise TableError(f"class {internal_name!r} already exists in {column!r}")
        next_index = max(value_map, default=-1) + 1
        value_map[next_index] = ValueMapEntry(internal_name, display_name, color)
        return self._with_value_map(column, value_map, "add_value_map_item")

    def set_value_map_item(self, column: str, index: int, **changes: Any) -> Table:
        value_map = self.get_value_map(column)
        if index not in value_map:
            raise TableError(f"no class with index {index} in {column!r}")
        entry = value_map[index]
        value_map[index] = ValueMapEntry(
            internal_name=changes.get("internal_name", entry.internal_name),
            display_name=changes.get("display_name", entry.display_name),
            color=changes.get("color", entry.color),
        )
        return self._with_value_map(column, value_map, "set_value_map_item")

    def delete_value_map_item(self, column: str, index: int) -> Table:
        value_map = self.get_value_map(column)
        if index not in value_map:
            raise TableError(f"no class with index {index} in {column!r}")
        del value_map[index]
        return self._with_value_map(column, value_map, "delete_value_map_item")

    # -- lineage ------------------------------------------------------------

    def parent(self) -> Table | None:
        return Table.from_url(self.parents[0]) if self.parents else None

    def lineage(self) -> list[Table]:
        """Every revision from the root down to this one."""
        chain: list[Table] = [self]
        seen = {str(self.url)}
        current: Table | None = self
        while current is not None and current.parents:
            nxt = Table.from_url(current.parents[0])
            if str(nxt.url) in seen:
                break
            seen.add(str(nxt.url))
            chain.append(nxt)
            current = nxt
        return list(reversed(chain))

    def siblings(self) -> list[Table]:
        """Every Table in the same dataset, this one included."""
        layout = ProjectLayout(get_config().project_root)
        base = layout.tables_dir(self.project_name, self.dataset_name)
        out: list[Table] = []
        for candidate in base.ls():
            try:
                out.append(Table.from_url(candidate))
            except Exception:  # noqa: BLE001 - a non-Table directory is not an error
                continue
        return out

    def children(self) -> list[Table]:
        key = str(self.url)
        return [t for t in self.siblings() if key in {str(p) for p in t.parents}]

    def descendants(self) -> list[Table]:
        found: list[Table] = []
        queue = self.children()
        seen: set[str] = set()
        while queue:
            item = queue.pop()
            if str(item.url) in seen:
                continue
            seen.add(str(item.url))
            found.append(item)
            queue.extend(item.children())
        return found

    def depth(self) -> int:
        """How many revisions separate this Table from its root."""
        return len(self.lineage()) - 1

    def latest(self) -> Table:
        """The furthest descendant of this Table, or this Table if it is a leaf.

        Ranked by depth first so a long editing chain always beats a shallow sibling,
        then by creation time. Two revisions made in the same second must not be
        ordered by URL spelling.
        """
        candidates = self.descendants()
        if not candidates:
            return self
        return max(candidates, key=lambda t: (t.depth(), t.created, str(t.url)))

    def revision(
        self, *, table_name: str | None = None, table_url: Url | str | None = None,
        tag: str | None = None,
    ) -> Table:
        """Fetch a specific revision, checking that it descends from this Table."""
        if tag == "latest":
            return self.latest()
        if table_url is not None:
            wanted = Table.from_url(table_url)
        elif table_name is not None:
            matches = [t for t in self.siblings() if t.name == table_name]
            if not matches:
                raise TableError(f"no revision named {table_name!r} in this dataset")
            wanted = matches[0]
        else:
            raise TableError("pass table_name, table_url or tag='latest'")
        allowed = {str(self.url)} | {str(t.url) for t in self.descendants()}
        if str(wanted.url) not in allowed:
            raise TableError(f"{wanted.name!r} is not a descendant of {self.name!r}")
        return wanted

    # -- factories ----------------------------------------------------------

    @classmethod
    def from_url(cls, url: Url | str) -> Table:
        """Open an already-serialized Table."""
        url = Url(url)
        return cls.from_dict(read_object_payload(url), url)

    @classmethod
    def from_names(
        cls, project_name: str, dataset_name: str, table_name: str, config: Config | None = None
    ) -> Table:
        layout = ProjectLayout((config or get_config()).project_root)
        return cls.from_url(layout.table(project_name, dataset_name, table_name))

    @classmethod
    def from_dict_data(
        cls,
        data: dict[str, Sequence[Any]],
        schema: dict[str, Schema] | TableSchema | None = None,
        *,
        project_name: str = "default",
        dataset_name: str = "default",
        table_name: str = "initial",
        description: str = "",
        add_weight_column: bool = True,
        config: Config | None = None,
    ) -> Table:
        """Build a Table from columns plus an optional explicit schema."""
        columns = {name: list(values) for name, values in data.items()}
        if isinstance(schema, TableSchema):
            resolved = dict(schema.columns)
        else:
            resolved = dict(schema or {})
        for name, values in columns.items():
            resolved.setdefault(name, infer_schema(values, name))
        ordered = TableSchema({name: resolved[name] for name in columns})
        if add_weight_column and WEIGHT_COLUMN not in ordered:
            ordered = ordered.with_column(WEIGHT_COLUMN, SampleWeightSchema())
            columns[WEIGHT_COLUMN] = [1.0] * len(next(iter(columns.values()), []))
        return cls._write(
            data=columns,
            schema=ordered,
            project_name=project_name,
            dataset_name=dataset_name,
            table_name=table_name,
            description=description,
            config=config,
        )

    @classmethod
    def from_pandas(cls, df, **kwargs: Any) -> Table:
        return cls.from_dict_data({str(c): df[c].tolist() for c in df.columns}, **kwargs)

    @classmethod
    def from_parquet(cls, url: Url | str, **kwargs: Any) -> Table:
        source = Url(url)
        arrow = pq.read_table(source.path, filesystem=source.fs)
        return cls.from_dict_data(arrow.to_pydict(), **kwargs)

    @classmethod
    def from_csv(cls, url: Url | str, **kwargs: Any) -> Table:
        import csv
        import io

        text = Url(url).read_text()
        rows = list(csv.DictReader(io.StringIO(text)))
        if not rows:
            raise TableError(f"{url} contains no rows")
        columns: dict[str, list[Any]] = {key: [] for key in rows[0]}
        for row in rows:
            for key in columns:
                columns[key].append(row.get(key))
        return cls.from_dict_data(columns, **kwargs)

    @classmethod
    def from_coco(cls, annotations: Url | str, image_folder: Url | str | None = None, **kwargs: Any) -> Table:
        """A detection Table from a COCO annotation file. See ``granum.formats.coco``."""
        from granum.formats.coco import table_from_coco

        return table_from_coco(annotations, image_folder, **kwargs)

    @classmethod
    def from_yolo_url(
        cls, data_yaml: Url | str, split: str = "train", *, task: str = "detect", **kwargs: Any
    ) -> Table:
        """A detection Table from one split of a YOLO dataset YAML. See ``granum.formats.yolo``."""
        from granum.formats.yolo import table_from_yolo

        return table_from_yolo(data_yaml, split, task=task, **kwargs)

    @classmethod
    def from_image_folder(
        cls,
        root: Url | str,
        *,
        project_name: str = "default",
        dataset_name: str | None = None,
        table_name: str = "initial",
        description: str = "",
        image_column: str = "image",
        label_column: str = "label",
        add_weight_column: bool = True,
        config: Config | None = None,
    ) -> Table:
        """Build a classification Table from a directory-per-class folder.

        Only paths are stored. Images are never copied or decoded -- the Table stays a
        thin layer of metadata over data that lives where the user put it.
        """
        root_url = Url(root)
        if not root_url.is_dir():
            raise TableError(f"{root_url} is not a directory")

        class_dirs = [child for child in root_url.ls() if child.is_dir()]
        if not class_dirs:
            raise TableError(f"{root_url} has no class subdirectories")

        classes = [d.name for d in sorted(class_dirs, key=lambda d: d.name)]
        images: list[str] = []
        labels: list[int] = []
        for index, class_dir in enumerate(sorted(class_dirs, key=lambda d: d.name)):
            for entry in class_dir.ls():
                if entry.suffix.lower() in _IMAGE_SUFFIXES:
                    images.append(str(entry.aliased()))
                    labels.append(index)

        if not images:
            raise TableError(f"no images found under {root_url}")

        schema = TableSchema(
            {
                image_column: ImageSchema(sample_type="url"),
                label_column: CategoricalLabelSchema(classes=classes),
            }
        )
        data: dict[str, list[Any]] = {image_column: images, label_column: labels}
        if add_weight_column:
            schema = schema.with_column(WEIGHT_COLUMN, SampleWeightSchema())
            data[WEIGHT_COLUMN] = [1.0] * len(images)

        return cls._write(
            data=data,
            schema=schema,
            project_name=project_name,
            dataset_name=dataset_name or root_url.name,
            table_name=table_name,
            description=description or f"Imported from {root_url}",
            config=config,
        )
