---
title: Transform samples on read
summary: Use different training and evaluation views while keeping one immutable source table.
status: available
---

`table.with_transform(function)` returns a `TableView`. It applies a function whenever a sample is
read and leaves the stored table unchanged. Use it for decoding, normalisation and model input
preparation.

## Make a read view

```python
from granum import Table

table = Table.from_dict_data(
    {"signal": [1.0, 2.0, 3.0]}, project_name="transform-demo", dataset_name="samples",
)

def scale(sample):
    return {**sample, "signal": sample["signal"] / 3.0}

view = table.with_transform(scale)
assert view[0]["signal"] != table[0]["signal"]
```

The returned values are transient. To preserve a derived measurement, explicitly write a typed
column in a new revision. To preserve augmented images/annotations as a dataset, use
[versioned augmentation](/docs/guides/augmentation).

## Use with a training loader

A model-training view can return whatever sample structure its loader expects. With multiple worker
processes, use a picklable module-level function and handle platform multiprocessing requirements.
Keep random seeds and augmentation settings with the run parameters.

The metrics collection path requires a dictionary per sample so collectors can address columns by
name. It also needs predictions aligned with the canonical input labels. Do not reuse a randomly
cropped or shuffled training view without a clear identity and coordinate-restoration contract.

## Keep geometry consistent

A spatial transform must update every affected annotation: boxes, masks, oriented corners and keypoints.
A horizontal pose flip also needs a landmark swap mapping. Cropping an image while leaving its boxes
in the old coordinates creates invalid evaluation evidence.

Use model adapters that restore predictions to original-image coordinates, or do that restoration
explicitly before a collector receives them. Semantic prediction masks must match the source resolution.

## Limits and next steps

TableView is a Python read-time view, not a materialised browser subset or a new dataset revision.
A public custom sample-type/plugin registration system and automatic logging of every randomly
augmented training observation are **Not yet included**. See [extensions](/docs/planned/extensions)
and the [reserved recipes](/docs/measure/recipes#reserved-example-recipes).
