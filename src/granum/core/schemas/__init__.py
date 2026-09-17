"""Column schemas.

A column is data *plus* a schema. The schema is what lets a dashboard render a class
dropdown instead of an integer, and what tells the training loop how to turn a stored
value into a Python object. Getting these right is most of the work of making a Table
useful; a ``label`` column with no schema is just an int.

Schemas are registered by ``kind`` so custom ones round-trip through serialization the
same way built-ins do::

    @register_schema
    class MySchema(Schema):
        kind = "my_schema"
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Any, ClassVar

import pyarrow as pa

from granum.errors import SchemaError

__all__ = [
    "Schema",
    "BoolSchema",
    "Int32Schema",
    "Int64Schema",
    "Float32Schema",
    "StringSchema",
    "UrlSchema",
    "ImageSchema",
    "VideoUrlSchema",
    "CategoricalLabelSchema",
    "CategoricalLabelListSchema",
    "EmbeddingSchema",
    "Int32ListSchema",
    "ConfidenceSchema",
    "FractionSchema",
    "ProbabilitySchema",
    "IoUSchema",
    "SampleWeightSchema",
    "ExampleIdSchema",
    "EpochSchema",
    "ForeignTableIdSchema",
    "ValueMapEntry",
    "TableSchema",
    "register_schema",
    "schema_from_dict",
    "infer_metric_schema",
]

_REGISTRY: dict[str, type[Schema]] = {}


def register_schema(cls: type[Schema]) -> type[Schema]:
    """Register a schema class so it can be reconstructed from disk."""
    if not getattr(cls, "kind", ""):
        raise SchemaError(f"{cls.__name__} must define a non-empty 'kind'")
    _REGISTRY[cls.kind] = cls
    return cls


@dataclass(frozen=True)
class Schema:
    """Base class for every column schema."""

    kind: ClassVar[str] = "unknown"

    description: str = ""
    writable: bool = False
    default_visible: bool = True
    number_role: str | None = None

    # -- arrow ---------------------------------------------------------------

    def arrow_type(self) -> pa.DataType:
        raise NotImplementedError

    # -- value conversion ----------------------------------------------------

    def to_storage(self, value: Any) -> Any:
        """Python value -> the value stored in Parquet."""
        return value

    def from_storage(self, value: Any) -> Any:
        """Stored value -> the value a sample exposes."""
        return value

    # -- serialization -------------------------------------------------------

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {"kind": self.kind}
        for key, value in self.__dict__.items():
            if not key.startswith("_"):
                payload[key] = value
        return payload

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> Schema:
        data = {k: v for k, v in payload.items() if k != "kind"}
        return cls(**data)


def schema_from_dict(payload: dict[str, Any]) -> Schema:
    """Rebuild a schema from its serialized form."""
    kind = payload.get("kind")
    if kind not in _REGISTRY:
        raise SchemaError(f"unknown schema kind {kind!r}. Registered: {sorted(_REGISTRY)}")
    return _REGISTRY[kind].from_dict(payload)


# ---------------------------------------------------------------------------
# scalars
# ---------------------------------------------------------------------------


@register_schema
@dataclass(frozen=True)
class BoolSchema(Schema):
    kind: ClassVar[str] = "bool"

    def arrow_type(self) -> pa.DataType:
        return pa.bool_()


@register_schema
@dataclass(frozen=True)
class Int32Schema(Schema):
    kind: ClassVar[str] = "int32"

    def arrow_type(self) -> pa.DataType:
        return pa.int32()


@register_schema
@dataclass(frozen=True)
class Int64Schema(Schema):
    kind: ClassVar[str] = "int64"

    def arrow_type(self) -> pa.DataType:
        return pa.int64()


@register_schema
@dataclass(frozen=True)
class Float32Schema(Schema):
    kind: ClassVar[str] = "float32"

    def arrow_type(self) -> pa.DataType:
        return pa.float32()


@register_schema
@dataclass(frozen=True)
class StringSchema(Schema):
    kind: ClassVar[str] = "string"

    def arrow_type(self) -> pa.DataType:
        return pa.string()


@register_schema
@dataclass(frozen=True)
class UrlSchema(Schema):
    """A location. Stored as a string, never dereferenced on read."""

    kind: ClassVar[str] = "url"

    def arrow_type(self) -> pa.DataType:
        return pa.string()


# ---------------------------------------------------------------------------
# bounded numerics -- the ranges let a UI bin and colour them correctly
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _BoundedFloat(Schema):
    minimum: float = 0.0
    maximum: float = 1.0

    def arrow_type(self) -> pa.DataType:
        return pa.float32()


@register_schema
@dataclass(frozen=True)
class ConfidenceSchema(_BoundedFloat):
    kind: ClassVar[str] = "confidence"


@register_schema
@dataclass(frozen=True)
class FractionSchema(_BoundedFloat):
    kind: ClassVar[str] = "fraction"


@register_schema
@dataclass(frozen=True)
class ProbabilitySchema(_BoundedFloat):
    kind: ClassVar[str] = "probability"


@register_schema
@dataclass(frozen=True)
class IoUSchema(_BoundedFloat):
    kind: ClassVar[str] = "iou"


# ---------------------------------------------------------------------------
# system columns
# ---------------------------------------------------------------------------


@register_schema
@dataclass(frozen=True)
class SampleWeightSchema(Schema):
    """How often a sample should be seen during training. 0 excludes it entirely."""

    kind: ClassVar[str] = "sample_weight"
    writable: bool = True
    minimum: float = 0.0

    def arrow_type(self) -> pa.DataType:
        return pa.float32()


@register_schema
@dataclass(frozen=True)
class ExampleIdSchema(Schema):
    """Row index into the input Table. Half of the metric-to-sample join."""

    kind: ClassVar[str] = "example_id"

    def arrow_type(self) -> pa.DataType:
        return pa.int64()


@register_schema
@dataclass(frozen=True)
class EpochSchema(Schema):
    kind: ClassVar[str] = "epoch"

    def arrow_type(self) -> pa.DataType:
        return pa.int32()


@register_schema
@dataclass(frozen=True)
class ForeignTableIdSchema(Schema):
    """Which input Table a metrics row refers to. The other half of the join."""

    kind: ClassVar[str] = "foreign_table_id"

    def arrow_type(self) -> pa.DataType:
        return pa.int32()


# ---------------------------------------------------------------------------
# media
# ---------------------------------------------------------------------------

IMAGE_SAMPLE_TYPES = ("url", "pil_png", "pil_jpeg", "pil_webp")


@register_schema
@dataclass(frozen=True)
class ImageSchema(Schema):
    """An image column.

    ``sample_type="url"`` passes the location straight through in both directions and is
    the right choice when the images already live on disk. The ``pil_*`` modes decode to
    a ``PIL.Image`` on read, so a training loop gets pixels without knowing where they
    came from.
    """

    kind: ClassVar[str] = "image"
    sample_type: str = "url"

    def __post_init__(self) -> None:
        if self.sample_type not in IMAGE_SAMPLE_TYPES:
            raise SchemaError(
                f"sample_type must be one of {IMAGE_SAMPLE_TYPES}, got {self.sample_type!r}"
            )

    def arrow_type(self) -> pa.DataType:
        return pa.string()

    def to_storage(self, value: Any) -> Any:
        from granum.core.url import Url

        if value is None:
            return None
        if hasattr(value, "save") and not isinstance(value, (str, bytes)):
            raise SchemaError(
                "Writing PIL images into a Table is not supported yet -- store a URL "
                "instead. Granum keeps Tables as thin metadata over your data."
            )
        return str(Url(str(value)).aliased())

    def from_storage(self, value: Any) -> Any:
        if value is None or self.sample_type == "url":
            return value
        from granum.core.url import Url

        try:
            from PIL import Image
        except ImportError as exc:  # pragma: no cover - depends on optional extra
            raise SchemaError(
                "sample_type='pil_*' needs Pillow. Install granum[images]."
            ) from exc
        import io

        return Image.open(io.BytesIO(Url(value).read_bytes()))


@register_schema
@dataclass(frozen=True)
class VideoUrlSchema(UrlSchema):
    kind: ClassVar[str] = "video_url"


# ---------------------------------------------------------------------------
# categorical
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ValueMapEntry:
    """One class in a value map."""

    internal_name: str
    display_name: str = ""
    color: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "internal_name": self.internal_name,
            "display_name": self.display_name or self.internal_name,
            "color": self.color,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> ValueMapEntry:
        return cls(
            internal_name=payload["internal_name"],
            display_name=payload.get("display_name", ""),
            color=payload.get("color", ""),
        )


def _coerce_value_map(value: Any) -> dict[int, ValueMapEntry]:
    if value is None:
        return {}
    out: dict[int, ValueMapEntry] = {}
    for key, entry in dict(value).items():
        index = int(key)
        if isinstance(entry, ValueMapEntry):
            out[index] = entry
        elif isinstance(entry, dict):
            out[index] = ValueMapEntry.from_dict(entry)
        else:
            out[index] = ValueMapEntry(internal_name=str(entry))
    return out


@register_schema
@dataclass(frozen=True)
class CategoricalLabelSchema(Schema):
    """An integer class index plus the names behind it."""

    kind: ClassVar[str] = "categorical_label"
    value_map: dict[int, ValueMapEntry] = field(default_factory=dict)
    writable: bool = True

    def __init__(
        self,
        classes: Iterable[str] | None = None,
        value_map: Any = None,
        *,
        description: str = "",
        writable: bool = True,
        default_visible: bool = True,
        number_role: str | None = None,
    ) -> None:
        if classes is not None and value_map:
            raise SchemaError("pass either classes or value_map, not both")
        if classes is not None:
            resolved = {i: ValueMapEntry(internal_name=str(c)) for i, c in enumerate(classes)}
        else:
            resolved = _coerce_value_map(value_map)
        object.__setattr__(self, "value_map", resolved)
        object.__setattr__(self, "description", description)
        object.__setattr__(self, "writable", writable)
        object.__setattr__(self, "default_visible", default_visible)
        object.__setattr__(self, "number_role", number_role)

    @property
    def classes(self) -> list[str]:
        return [self.value_map[k].internal_name for k in sorted(self.value_map)]

    def arrow_type(self) -> pa.DataType:
        return pa.int32()

    def name_of(self, index: int) -> str | None:
        entry = self.value_map.get(int(index))
        return entry.internal_name if entry else None

    def index_of(self, name: str) -> int | None:
        for index, entry in self.value_map.items():
            if entry.internal_name == name:
                return index
        return None

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "description": self.description,
            "writable": self.writable,
            "default_visible": self.default_visible,
            "number_role": self.number_role,
            "value_map": {str(k): v.to_dict() for k, v in self.value_map.items()},
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> CategoricalLabelSchema:
        return cls(
            value_map=payload.get("value_map", {}),
            description=payload.get("description", ""),
            writable=payload.get("writable", True),
            default_visible=payload.get("default_visible", True),
            number_role=payload.get("number_role"),
        )


@register_schema
@dataclass(frozen=True)
class CategoricalLabelListSchema(CategoricalLabelSchema):
    """Multi-label: a list of class indices per row."""

    kind: ClassVar[str] = "categorical_label_list"

    def arrow_type(self) -> pa.DataType:
        return pa.list_(pa.int32())


@register_schema
@dataclass(frozen=True)
class Int32ListSchema(Schema):
    """A variable-length list of integers per row -- e.g. which prediction matched each
    ground-truth box."""

    kind: ClassVar[str] = "int32_list"

    def arrow_type(self) -> pa.DataType:
        return pa.list_(pa.int32())


# ---------------------------------------------------------------------------
# embeddings
# ---------------------------------------------------------------------------


@register_schema
@dataclass(frozen=True)
class EmbeddingSchema(Schema):
    """A fixed-width float vector.

    The ``nn_embedding`` number role marks a column as raw activations, which tells the
    service not to ship full-width vectors to a browser and marks the column as an input
    to dimensionality reduction.
    """

    kind: ClassVar[str] = "embedding"
    shape: tuple[int, ...] = ()
    number_role: str | None = "nn_embedding"
    default_visible: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(self, "shape", tuple(int(x) for x in self.shape))

    def arrow_type(self) -> pa.DataType:
        return pa.list_(pa.float32())

    def to_dict(self) -> dict[str, Any]:
        payload = super().to_dict()
        payload["shape"] = list(self.shape)
        return payload


# ---------------------------------------------------------------------------
# table schema
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class TableSchema:
    """The ordered set of column schemas describing a Table."""

    columns: dict[str, Schema] = field(default_factory=dict)

    def __init__(self, columns: dict[str, Schema] | None = None) -> None:
        object.__setattr__(self, "columns", dict(columns or {}))

    def __iter__(self):
        return iter(self.columns)

    def __len__(self) -> int:
        return len(self.columns)

    def __contains__(self, name: object) -> bool:
        return name in self.columns

    def __getitem__(self, name: str) -> Schema:
        try:
            return self.columns[name]
        except KeyError:
            raise SchemaError(
                f"no column {name!r}. Columns: {list(self.columns)}"
            ) from None

    @property
    def names(self) -> list[str]:
        return list(self.columns)

    def arrow_schema(self) -> pa.Schema:
        return pa.schema([(name, s.arrow_type()) for name, s in self.columns.items()])

    def with_column(self, name: str, schema: Schema) -> TableSchema:
        merged = dict(self.columns)
        merged[name] = schema
        return TableSchema(merged)

    def without_columns(self, names: Iterable[str]) -> TableSchema:
        drop = set(names)
        return TableSchema({k: v for k, v in self.columns.items() if k not in drop})

    def to_dict(self) -> dict[str, Any]:
        return {name: schema.to_dict() for name, schema in self.columns.items()}

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> TableSchema:
        return cls({name: schema_from_dict(body) for name, body in payload.items()})


# ---------------------------------------------------------------------------
# metric-shaped inference
# ---------------------------------------------------------------------------

_METRIC_HINTS: tuple[tuple[tuple[str, ...], type[Schema]], ...] = (
    (("confidence", "score", "prob"), ConfidenceSchema),
    (("iou", "overlap"), IoUSchema),
    (("accuracy", "acc", "recall", "precision", "f1"), FractionSchema),
)


def infer_metric_schema(values, name: str = "") -> Schema:
    """Pick a schema for a metrics column, using the column name as a hint.

    A column called ``confidence`` gets a bounded 0..1 schema rather than a bare float,
    so a UI can bin and colour it correctly without being told.
    """
    lowered = name.lower()
    sample = next((v for v in values if v is not None), None)

    if isinstance(sample, (list, tuple)):
        return EmbeddingSchema(shape=(len(sample),))
    if isinstance(sample, bool):
        return BoolSchema()
    if isinstance(sample, str):
        return StringSchema()
    if lowered in {"epoch", "iteration", "step"}:
        return EpochSchema()
    if lowered in {"example_id", "sample_id"}:
        return ExampleIdSchema()
    if isinstance(sample, (int,)) and not isinstance(sample, bool):
        for hints, schema_cls in _METRIC_HINTS:
            if any(hint in lowered for hint in hints):
                return schema_cls()
        return Int64Schema()
    for hints, schema_cls in _METRIC_HINTS:
        if any(hint in lowered for hint in hints):
            return schema_cls()
    return Float32Schema()


# Geometry schemas live in their own module; importing it registers them.
from granum.core.schemas.geometry import (  # noqa: E402
    BoundingBoxes2DSchema,
    Geometry2DSchema,
)

__all__ += ["Geometry2DSchema", "BoundingBoxes2DSchema"]
