---
title: Define column schemas
summary: Give values their types, display meaning and edit rules before storing them in a table.
status: available
---

Schemas describe stored values and how Granum should interpret them. Use explicit schemas when a
number represents a class, weight, probability or sample reference; inference cannot reliably infer
that meaning from its magnitude.

## Core schema families

Import these types from `granum.schemas`.

| Family | Types |
|---|---|
| Scalar values | `BoolSchema`, `Int32Schema`, `Int64Schema`, `Float32Schema`, `StringSchema`, `UrlSchema` |
| Measurements | `ConfidenceSchema`, `FractionSchema`, `ProbabilitySchema`, `IoUSchema` |
| Sample and run context | `SampleWeightSchema`, `ExampleIdSchema`, `EpochSchema`, `ForeignTableIdSchema` |
| Categories | `CategoricalLabelSchema`, `CategoricalLabelListSchema`, `ValueMapEntry` |
| Media and vectors | `ImageSchema`, `VideoUrlSchema`, `EmbeddingSchema`, `Int32ListSchema` |
| Geometry and tables | `Geometry2DSchema`, `BoundingBoxes2DSchema`, `TableSchema` |

A video URL column stores a reference; it does not provide the reserved video ingestion/timeline
workflow. Likewise, an embedding column describes vectors, not a point-cloud annotation type.

## Declare categories and geometry

```python
from granum.schemas import BoundingBoxes2DSchema, CategoricalLabelSchema

label = CategoricalLabelSchema(classes=["acceptable", "defect"])
boxes = BoundingBoxes2DSchema(
    classes=["part"],
    instance_properties={"confidence": "float32", "source": "string"},
)
```

A value map associates stable integer IDs with names and display information. Do not silently reuse
an ID for another class. Geometry instance properties must be declared with a supported type;
undeclared fields are rejected. Vision importers preserve masks, keypoints and rotated geometry in
the appropriate annotation representation.

## Configure display and access

Column metadata includes `description`, `writable`, `default_visible` and `number_role`. Metrics
should not become editable ground truth merely because they look like a label column. Some context
columns identify source tables, rows and epochs for joining; keep them distinct from user annotations.

`ImageSchema(sample_type="url")` returns a location. The `pil_png`, `pil_jpeg` and `pil_webp` modes
load referenced images through Pillow; writing a PIL object directly is not supported.
`EmbeddingSchema(shape=(128,))` declares a vector's intended width. Projection also validates actual
row dimensions and numeric values.

## Validate a small sample

Write a few rows, reload them, inspect the Arrow schema and open them in the dashboard. Catch class-map,
coordinate and type mistakes before importing a large collection. User-defined external sample types
and arbitrary bulk-array adapters are [Not yet included](/docs/planned/extensions).
