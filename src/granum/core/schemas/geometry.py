"""Geometry columns: a variable number of labelled shapes per row.

One container serves every 2D geometry type. A value is::

    {
        "width": 640.0, "height": 480.0,          # scene bounds, in pixels
        "instances": [
            {"vertices": [x_min, y_min, x_max, y_max], "label": 3, "confidence": 0.91},
            ...
        ],
    }

``vertices`` is a flat coordinate list whose meaning the schema fixes -- four numbers for
an axis-aligned box today; keypoints, polygons and oriented boxes later reuse the same
container with a different vertex layout. Every other key on an instance is a declared
*instance property* with a type, so per-box confidence, IoU or a COCO annotation id are
typed columns in Arrow rather than untyped JSON.

Coordinates are absolute pixels, stored as float64 so that converting COCO's
``[x, y, w, h]`` in and back out does not drift.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any, ClassVar

import pyarrow as pa

from granum.core.schemas import Schema, ValueMapEntry, _coerce_value_map, register_schema
from granum.errors import SchemaError

#: Instance property types and their Arrow storage.
PROPERTY_TYPES: dict[str, pa.DataType] = {
    "float32": pa.float32(),
    "float64": pa.float64(),
    "int32": pa.int32(),
    "int64": pa.int64(),
    "bool": pa.bool_(),
    "string": pa.string(),
}

RESERVED_INSTANCE_KEYS = ("vertices", "label")


def _check_property(name: str, kind: str, value: Any) -> Any:
    if value is None:
        return None
    if kind in ("float32", "float64"):
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise SchemaError(f"instance property {name!r} must be a number, got {value!r}")
        return float(value)
    if kind in ("int32", "int64"):
        if isinstance(value, bool) or not isinstance(value, int):
            raise SchemaError(f"instance property {name!r} must be an integer, got {value!r}")
        return value
    if kind == "bool":
        if not isinstance(value, bool):
            raise SchemaError(f"instance property {name!r} must be true/false, got {value!r}")
        return value
    if not isinstance(value, str):
        raise SchemaError(f"instance property {name!r} must be text, got {value!r}")
    return value


@register_schema
@dataclass(frozen=True)
class Geometry2DSchema(Schema):
    """Labelled 2D shapes with free vertex counts. Subclasses fix the layout."""

    kind: ClassVar[str] = "geometry_2d"
    #: Vertices per instance, or None when it varies (polygons).
    vertex_count: ClassVar[int | None] = None

    value_map: dict[int, ValueMapEntry] = None  # type: ignore[assignment]
    instance_properties: dict[str, str] = None  # type: ignore[assignment]
    writable: bool = True

    def __init__(
        self,
        classes: Iterable[str] | None = None,
        value_map: Any = None,
        instance_properties: dict[str, str] | None = None,
        *,
        description: str = "",
        writable: bool = True,
        default_visible: bool = True,
        number_role: str | None = None,
    ) -> None:
        if classes is not None and value_map:
            raise SchemaError("pass either classes or value_map, not both")
        resolved = (
            {i: ValueMapEntry(internal_name=str(c)) for i, c in enumerate(classes)}
            if classes is not None
            else _coerce_value_map(value_map)
        )
        properties = dict(instance_properties or {})
        for name, kind in properties.items():
            if name in RESERVED_INSTANCE_KEYS:
                raise SchemaError(f"{name!r} is reserved and cannot be an instance property")
            if kind not in PROPERTY_TYPES:
                raise SchemaError(
                    f"instance property {name!r} has unknown type {kind!r}; "
                    f"choose one of {sorted(PROPERTY_TYPES)}"
                )
        object.__setattr__(self, "value_map", resolved)
        object.__setattr__(self, "instance_properties", properties)
        object.__setattr__(self, "description", description)
        object.__setattr__(self, "writable", writable)
        object.__setattr__(self, "default_visible", default_visible)
        object.__setattr__(self, "number_role", number_role)

    # -- arrow ---------------------------------------------------------------

    def instance_type(self) -> pa.StructType:
        fields = [pa.field("vertices", pa.list_(pa.float64())), pa.field("label", pa.int32())]
        fields += [pa.field(name, PROPERTY_TYPES[kind]) for name, kind in self.instance_properties.items()]
        return pa.struct(fields)

    def arrow_type(self) -> pa.DataType:
        return pa.struct([
            pa.field("width", pa.float64()),
            pa.field("height", pa.float64()),
            pa.field("instances", pa.list_(self.instance_type())),
        ])

    # -- values --------------------------------------------------------------

    def check_vertices(self, vertices: list[float], where: str) -> None:
        if self.vertex_count is not None and len(vertices) != self.vertex_count:
            raise SchemaError(f"{where}: expected {self.vertex_count} vertex values, got {len(vertices)}")

    def to_storage(self, value: Any) -> Any:
        if value is None:
            return None
        if hasattr(value, "to_value"):
            value = value.to_value()
        if not isinstance(value, dict) or "instances" not in value:
            raise SchemaError(
                f"a {self.kind} value is a dict with width, height and instances, got {type(value).__name__}"
            )
        instances = []
        for position, instance in enumerate(value.get("instances") or []):
            where = f"instance {position}"
            unknown = set(instance) - set(RESERVED_INSTANCE_KEYS) - set(self.instance_properties)
            if unknown:
                raise SchemaError(
                    f"{where}: undeclared properties {sorted(unknown)}; declare them in instance_properties"
                )
            vertices = [float(v) for v in instance.get("vertices") or []]
            self.check_vertices(vertices, where)
            label = instance.get("label")
            if label is not None:
                if isinstance(label, bool) or not isinstance(label, int):
                    raise SchemaError(f"{where}: label must be a class index, got {label!r}")
                if self.value_map and label not in self.value_map:
                    raise SchemaError(f"{where}: label {label} is not one of {sorted(self.value_map)}")
            stored = {"vertices": vertices, "label": label}
            for name, kind in self.instance_properties.items():
                stored[name] = _check_property(name, kind, instance.get(name))
            instances.append(stored)
        return {
            "width": float(value.get("width") or 0.0),
            "height": float(value.get("height") or 0.0),
            "instances": instances,
        }

    def from_storage(self, value: Any) -> Any:
        return value

    # -- serialization ---------------------------------------------------------

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "description": self.description,
            "writable": self.writable,
            "default_visible": self.default_visible,
            "number_role": self.number_role,
            "value_map": {str(k): v.to_dict() for k, v in self.value_map.items()},
            "instance_properties": dict(self.instance_properties),
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> Geometry2DSchema:
        return cls(
            value_map=payload.get("value_map", {}),
            instance_properties=payload.get("instance_properties", {}),
            description=payload.get("description", ""),
            writable=payload.get("writable", True),
            default_visible=payload.get("default_visible", True),
            number_role=payload.get("number_role"),
        )

    @property
    def classes(self) -> list[str]:
        return [self.value_map[k].internal_name for k in sorted(self.value_map)]


@register_schema
@dataclass(frozen=True, init=False)
class BoundingBoxes2DSchema(Geometry2DSchema):
    """Axis-aligned boxes: ``vertices = [x_min, y_min, x_max, y_max]`` in pixels."""

    kind: ClassVar[str] = "bounding_boxes_2d"
    vertex_count: ClassVar[int | None] = 4

    def check_vertices(self, vertices: list[float], where: str) -> None:
        super().check_vertices(vertices, where)
        x_min, y_min, x_max, y_max = vertices
        if x_max < x_min or y_max < y_min:
            raise SchemaError(f"{where}: box {vertices} has max below min; expected [x_min, y_min, x_max, y_max]")
