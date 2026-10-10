"""The columns of a set that are worth sorting, grouping, filtering and summarising by.

A set's schema usually holds more than the Images tab ever showed. An aerial import carries
``width``, ``height``, ``capture_time`` and whatever else the COCO file put on an image; a
version written by review carries ``removed_from`` and ``removed_reason``; a weighted set
carries ``weight``. Until now the ribbon offered four fixed orders and a fixed set of
filters, so none of that was reachable: the data was in the table and there was no way to
ask anything of it.

This module answers two questions about a table, and nothing else:

**Which columns mean something to a reader** -- :func:`scalar_fields`. Images, geometry,
embeddings and list columns are not sortable or groupable in any useful sense, so they are
left out; everything scalar is described by a *kind the browser can build a widget from*
(``number``, ``string``, ``bool``, ``class``) rather than by its storage type, and a class
column brings its names along.

**What a column adds up to** -- :func:`summarize`. Bounds, mean, standard deviation,
quantiles and distinct counts, in one pass, with the missing values counted rather than
quietly skewing the mean. The dashboard recomputes the same numbers over whatever the
ribbon has left, which is the reading that matters; this one is for the Python side, where
the question is asked of a whole column.

Both are pure functions over values, so they can be tested without a service.
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Mapping, Sequence
from typing import TYPE_CHECKING, Any

from granum.core.schemas import CategoricalLabelSchema, Schema
from granum.core.schemas.geometry import Geometry2DSchema

if TYPE_CHECKING:  # pragma: no cover - typing only
    from granum.core.objects.table import Table

#: Storage kinds that make a number a reader can order and average.
NUMBER_KINDS = frozenset({
    "int32", "int64", "float32", "confidence", "fraction", "probability", "iou",
    "sample_weight", "epoch",
})

#: Kinds with nothing to offer a sort, a group or a filter: the picture itself, a vector, a
#: link, and the list columns where one row holds many values. Geometry is excluded by type
#: rather than by name -- every box schema is a subclass, each with its own ``kind``.
UNUSABLE_KINDS = frozenset({
    "image", "embedding", "url", "video_url", "unknown",
    "int32_list", "categorical_label_list",
})

#: Identifiers by type. Identifiers by *content* -- a column with nearly one value per image
#: -- are found in :func:`usable_fields`, which is the only place the answer is knowable: a
#: name is a guess, and guessing puts a drone set's ``sequence`` (208 flights over eleven
#: thousand images, the most useful facet it has) in the drawer with the hashes.
IDENTIFIER_KINDS = frozenset({"example_id", "foreign_table_id"})

#: Distinct values past which a column is nearly unique, as a share of the images that have
#: one. A hash or a row id is 1.0; a file name shared by a handful of crops is not.
IDENTIFIER_SHARE = 0.9

#: Images below which uniqueness says nothing. In a set of five, every column looks like an
#: identifier; the question only has an answer once there are enough rows to repeat a value.
IDENTIFIER_MIN = 20

#: A field is described at most this many times over: past this the payload costs more than
#: the questions it answers. Columns are taken in schema order, which puts the import's own
#: columns before anything a later pass added.
MAX_FIELDS = 32

#: Values listed for the browser to build a value list from. Past this a column is offered
#: as a "contains" box instead: seven thousand file names are a search, not a list. Set well
#: above the number a reader will scan because the alternative is worse -- a drone set's 260
#: flight sequences are its most useful facet, and a cap of a hundred would hide them.
MAX_LISTED_VALUES = 500

#: A string longer than this is a payload rather than a property. A COCO import keeps the
#: original image record in ``coco_image`` as a JSON blob of a couple of hundred characters;
#: nobody filters on it, and sending one per image would cost megabytes to say nothing.
MAX_VALUE_CHARS = 120

#: What every field's values together may cost, in bytes of the images payload. A CSV import
#: with thirty metadata columns over twelve thousand images would otherwise turn one call
#: into tens of megabytes. Cheap columns are kept and the dear ones dropped, in schema order,
#: so what a reader loses is the tail of a wide import rather than the front of it.
MAX_VALUES_BYTES = 2_000_000


def field_kind(schema: Schema) -> str | None:
    """What kind of widget a column deserves, or None when it deserves none."""
    kind = schema.kind
    if kind in UNUSABLE_KINDS or isinstance(schema, Geometry2DSchema):
        return None
    if isinstance(schema, CategoricalLabelSchema):
        return "class"
    if kind == "bool":
        return "bool"
    if kind == "string":
        return "string"
    if kind in NUMBER_KINDS or kind in IDENTIFIER_KINDS:
        return "number"
    return None


def field_label(name: str) -> str:
    """A column name as a person would write it: ``removed_from`` -> ``Removed from``."""
    words = str(name).replace("_", " ").replace("-", " ").split()
    if not words:
        return str(name)
    return " ".join([words[0][:1].upper() + words[0][1:], *(w for w in words[1:])])


def describe_field(name: str, schema: Schema) -> dict[str, Any] | None:
    """One field descriptor, or None when the column is not worth offering."""
    kind = field_kind(schema)
    if kind is None:
        return None
    field: dict[str, Any] = {"name": name, "label": field_label(name), "kind": kind}
    if schema.kind in IDENTIFIER_KINDS:
        field["identifier"] = True
    if isinstance(schema, CategoricalLabelSchema):
        field["classes"] = {str(index): entry.display_name or entry.internal_name
                            for index, entry in schema.value_map.items()}
    if schema.description:
        field["detail"] = schema.description
    return field


def scalar_fields(table: Table, *, skip: Iterable[str] = ()) -> list[dict[str, Any]]:
    """Every column of a table a reader can sort, group, filter or summarise by.

    ``skip`` names columns the caller already shows in its own right -- the image column
    and the boxes are skipped anyway, but the Images tab also has the set and the review
    status as ribbon controls, and offering them twice would be two ways to say one thing.
    """
    skipped = set(skip)
    out: list[dict[str, Any]] = []
    for name in table.columns:
        if name in skipped:
            continue
        field = describe_field(name, table.schema[name])
        if field is not None:
            out.append(field)
        if len(out) >= MAX_FIELDS:
            break
    return out


def field_values(table: Table, fields: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Per row, the value of each named field, with nulls left out.

    Left out rather than sent as null: on a set of twelve thousand images a column that is
    mostly empty would otherwise pay for every row it says nothing about, and a missing key
    and a null key mean the same thing to every reader of this payload.
    """
    if not fields:
        return [{} for _ in range(len(table.to_arrow()))]
    arrow = table.to_arrow()
    columns = {}
    for field in fields:
        name = str(field["name"])
        if name in arrow.column_names:
            columns[name] = arrow.column(name).to_pylist()
    out: list[dict[str, Any]] = []
    for row in range(len(arrow)):
        values: dict[str, Any] = {}
        for name, column in columns.items():
            value = column[row]
            if value is None or (isinstance(value, float) and not math.isfinite(value)):
                continue
            values[name] = value
        out.append(values)
    return out


def usable_fields(fields: Sequence[Mapping[str, Any]], rows: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """The fields that actually vary, with how many values each one has.

    Three things are dropped, and each one would otherwise be a control that lies:

    A column holding one value for every image -- a constant ``licence``, a ``set`` that is
    the set the rows came from -- cannot narrow, order or group anything. One value on *some*
    of the images is kept: there, having it and not having it are two groups.

    A column whose values are long strings is a payload, not a property: an imported
    ``coco_image`` holds the original record as JSON, and one per image would be megabytes
    spent on a control nobody can use.

    A nearly-unique *string* -- a content hash, a uuid -- is dropped too. Sorting by one says
    nothing, grouping by one makes a group per image, and forty characters per image buys a
    search box for something a reader would have to paste in. A nearly-unique *number* is
    kept and marked as an identifier: ordering by an image id is ordering by import order,
    which is a real question, and an integer is cheap to send.

    Counted over the rows the caller is about to send rather than per table, because a column
    can be constant in one set and vary across the dataset, and it is the dataset in front of
    the reader.
    """
    seen: dict[str, set[Any]] = {str(f["name"]): set() for f in fields}
    present: dict[str, int] = dict.fromkeys(seen, 0)
    longest: dict[str, int] = dict.fromkeys(seen, 0)
    cost: dict[str, int] = dict.fromkeys(seen, 0)
    total = 0
    for row in rows:
        total += 1
        for name, values in seen.items():
            if name not in row:
                continue
            value = row[name]
            present[name] += 1
            values.add(value)
            # What this value will cost in the payload: the key, the quotes and the value.
            cost[name] += len(name) + 4 + (len(value) if isinstance(value, str) else 8)
            if isinstance(value, str) and len(value) > longest[name]:
                longest[name] = len(value)
    budget = MAX_VALUES_BYTES
    out = []
    for field in fields:
        name = str(field["name"])
        distinct = len(seen[name])
        if distinct == 0 or (distinct == 1 and present[name] == total):
            continue
        if longest[name] > MAX_VALUE_CHARS:
            continue
        unique = (present[name] >= IDENTIFIER_MIN and distinct >= present[name] * IDENTIFIER_SHARE)
        if unique and field["kind"] == "string":
            continue
        if cost[name] > budget:
            continue
        budget -= cost[name]
        entry = {**field, "present": present[name], "distinct": distinct}
        if field["kind"] == "number":
            pass  # a number is a range whatever its cardinality
        elif distinct > MAX_LISTED_VALUES:
            # Too many to list: the browser offers a "contains" box instead.
            entry["wide"] = True
        else:
            entry["values"] = sorted(seen[name], key=lambda v: (v is None, str(v)))
        if unique:
            entry["identifier"] = True
        out.append(entry)
    return out


def _quantile(sorted_values: Sequence[float], fraction: float) -> float:
    """Linear interpolation between order statistics, as numpy and pandas both do it."""
    if not sorted_values:
        return float("nan")
    position = fraction * (len(sorted_values) - 1)
    low = math.floor(position)
    high = math.ceil(position)
    if low == high:
        return float(sorted_values[int(position)])
    weight = position - low
    return float(sorted_values[low]) * (1 - weight) + float(sorted_values[high]) * weight


def summarize(values: Iterable[Any], *, quantiles: Sequence[float] = (0.25, 0.5, 0.75)) -> dict[str, Any]:
    """What a column adds up to: counts, bounds, mean, deviation, quantiles, distinct.

    Numbers get the numeric readings; anything else gets the counts and its most common
    values, because "which of these 40 strings, and how often" is the only summary of a
    string column anyone wants. ``missing`` counts None and non-finite floats, which are
    excluded from every other number here rather than being read as zero.
    """
    total = 0
    missing = 0
    numbers: list[float] = []
    counts: dict[Any, int] = {}
    numeric = True
    for value in values:
        total += 1
        if value is None or (isinstance(value, float) and not math.isfinite(value)):
            missing += 1
            continue
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            numeric = False
        else:
            numbers.append(float(value))
        key = value if not isinstance(value, (list, dict)) else str(value)
        counts[key] = counts.get(key, 0) + 1

    out: dict[str, Any] = {
        "count": total,
        "present": total - missing,
        "missing": missing,
        "distinct": len(counts),
    }
    ranked = sorted(counts.items(), key=lambda item: (-item[1], str(item[0])))
    out["top"] = [{"value": value, "count": count} for value, count in ranked[:12]]
    if not numeric or not numbers:
        return out

    numbers.sort()
    mean = sum(numbers) / len(numbers)
    # Population deviation, not the sample one: this describes the values in hand, it does
    # not estimate a wider population from them.
    variance = sum((value - mean) ** 2 for value in numbers) / len(numbers)
    out.update({
        "min": numbers[0],
        "max": numbers[-1],
        "sum": sum(numbers),
        "mean": mean,
        "std": math.sqrt(variance),
        "quantiles": {f"{fraction:g}": _quantile(numbers, fraction) for fraction in quantiles},
    })
    return out
