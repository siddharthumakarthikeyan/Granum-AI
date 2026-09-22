"""Pre-labelling: a model's boxes written into a set as labels, to be corrected.

Labelling from nothing is the expensive part of a dataset. A detector that is roughly right
turns it into correction, which is several times faster and far less tiring -- and Granum
already has the pieces: a trained model from this project, or one that has never seen the
data, and a review surface for fixing boxes.

What makes that safe rather than reckless is that every box it writes says where it came
from. The set's box column gains two instance properties, ``source`` and ``confidence``, and
every existing label is marked ``manual`` on the way through, so from then on a person can
always ask which boxes a machine put there -- in the gallery, in the editor, and in anything
exported afterwards. A model-made box is a *draft*, and nothing downstream should be able to
mistake it for a labelled one.

Two ways to write, and the difference matters:

``empty``     only images with no labels at all get boxes. Nothing a person did is touched.
``replace``   every image given boxes has its labels replaced. For a set the model should
              re-draft wholesale; the previous labels are not lost, because a version is
              written rather than a file overwritten.
"""

from __future__ import annotations

from typing import Any

import pyarrow as pa

from granum.core.objects.table import Table
from granum.core.schemas.geometry import Geometry2DSchema
from granum.errors import GranumError

#: The instance properties a pre-labelled set carries, and what goes in them.
SOURCE = "source"
CONFIDENCE = "confidence"
MODEL = "model"
MANUAL = "manual"

#: How a set may be written.
MODES = ("empty", "replace")


class PrelabelError(GranumError):
    """A set cannot be pre-labelled as asked."""


def box_column(table: Table) -> str:
    """The set's geometry column: what a model's boxes would be written into."""
    for name in table.columns:
        if isinstance(table.schema[name], Geometry2DSchema):
            return name
    raise PrelabelError(f"{table.name} has no box column to write labels into")


def with_source(schema: Geometry2DSchema) -> Geometry2DSchema:
    """The same box schema, able to say where each box came from.

    Existing properties are kept: a COCO import carries its annotation ids and crowd flags
    through pre-labelling like everything else.
    """
    properties = {**schema.instance_properties}
    properties.setdefault(SOURCE, "string")
    properties.setdefault(CONFIDENCE, "float32")
    return type(schema)(
        value_map=schema.value_map,
        instance_properties=properties,
        description=schema.description,
        writable=schema.writable,
        default_visible=schema.default_visible,
        number_role=schema.number_role,
    )


def mark(instances: list[dict[str, Any]], source: str, *, confidence: float | None = None) -> list[dict[str, Any]]:
    """Instances with their origin recorded, leaving one that already says so alone."""
    out = []
    for instance in instances or []:
        marked = dict(instance)
        if not marked.get(SOURCE):
            marked[SOURCE] = source
        if confidence is not None and marked.get(CONFIDENCE) is None:
            marked[CONFIDENCE] = float(confidence)
        out.append(marked)
    return out


def labelled(value: Any) -> bool:
    """Whether a row already holds labels a person would not want overwritten."""
    return bool((value or {}).get("instances"))


def write_prelabelled(
    source: Table,
    predictions: dict[int, dict[str, Any]],
    *,
    model: str,
    mode: str = "empty",
    confidence: float = 0.25,
    column: str | None = None,
) -> dict[str, Any]:
    """A new version of ``source`` with the model's boxes in it, and what changed.

    ``predictions`` maps row to ``{"width", "height", "instances"}`` as the model saw it;
    each instance is ``{"vertices", "label", "confidence"}``. Rows not in it are untouched,
    and in ``empty`` mode so is every row that already has a label.

    The image's own size is taken from the prediction when the row had no geometry at all,
    which is the usual case here: an unlabelled set has no box column value to read it from.
    """
    if mode not in MODES:
        raise PrelabelError(f"mode must be one of {list(MODES)}")
    name = column or box_column(source)
    schema = source.schema[name]
    if not isinstance(schema, Geometry2DSchema):
        raise PrelabelError(f"{name!r} is not a box column")
    if not schema.writable:
        raise PrelabelError(f"{name!r} cannot be written to")

    values = source.to_arrow().column(name).to_pylist()
    updated = with_source(schema)
    new_schema = source.schema.with_column(name, updated)

    written = 0
    boxes = 0
    left = 0
    rows: list[Any] = []
    for row, value in enumerate(values):
        prediction = predictions.get(row)
        existing = mark(list((value or {}).get("instances") or []), MANUAL)
        if prediction is None or (mode == "empty" and existing):
            if prediction is not None:
                left += 1
            rows.append({**(value or {"width": 0.0, "height": 0.0}), "instances": existing})
            continue
        drafted = mark(list(prediction.get("instances") or []), MODEL)
        # Replacing means replacing: the previous labels stay in the previous version,
        # which is the only place they were ever safe anyway.
        instances = drafted if mode == "replace" else [*existing, *drafted]
        rows.append({
            "width": float((value or {}).get("width") or prediction.get("width") or 0.0),
            "height": float((value or {}).get("height") or prediction.get("height") or 0.0),
            "instances": instances,
        })
        written += 1
        boxes += len(drafted)

    data = source.to_pydict()
    data[name] = [updated.to_storage(value) for value in rows]
    arrow = pa.Table.from_pydict(
        {key: data[key] for key in new_schema.names},
        schema=new_schema.arrow_schema(),
    )
    from granum.core.curation import write_version

    table = write_version(
        project_name=source.project_name,
        dataset_name=source.dataset_name,
        base_name=source.base_name,
        name=f"{source.base_name}_prelabelled",
        arrow=arrow,
        schema=new_schema,
        parents=(source.url,),
        op="prelabel",
        args={"model": model, "mode": mode, "confidence": confidence,
              "images": written, "boxes": boxes, "column": name},
        description=(f"Pre-labelled {written} image{'' if written == 1 else 's'} with {model}: "
                     f"{boxes} box{'' if boxes == 1 else 'es'} to check"),
    )
    return {
        "table": table,
        "url": str(table.url),
        "name": table.name,
        "images": written,
        "boxes": boxes,
        #: Images the model had boxes for that were left alone because a person had
        #: labelled them already. In ``replace`` mode there are none by definition.
        "kept": left,
        "rows": len(rows),
    }
