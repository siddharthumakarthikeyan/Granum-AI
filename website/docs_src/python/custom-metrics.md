---
title: Write custom collectors
summary: Record your own measurements or embeddings with a consistent per-sample output contract.
status: available
---

A collector receives a batch of source columns and optional predictions. It returns a dictionary of
metric names to equally sized lists. Every output position must describe the corresponding input
sample. Granum handles batching, input IDs and persistence around that contract.

## A complete model-free example

```python
import granum
from granum.metrics import FunctionalMetricsCollector
from granum.schemas import Float32Schema

table = granum.Table.from_dict_data(
    {"value": [1.0, -2.0, 3.0]},
    project_name="collector-demo", dataset_name="samples",
)
run = granum.init("collector-demo", "absolute-values")
collector = FunctionalMetricsCollector(
    lambda batch, prediction: {"magnitude": [abs(v) for v in batch["value"]]},
    column_schemas={"magnitude": Float32Schema()},
)
metrics = granum.collect_metrics(table, [collector], run=run, constants={"epoch": 0})
assert metrics.to_pydict()["magnitude"] == [1.0, 2.0, 3.0]
run.set_status("finished")
```

The callback does not require a model. Use this pattern for an image statistic, external quality score
or domain-specific measurement. For per-object statistics, declare typed properties on the geometry
rather than confusing one object value with one image value.

## Adapt model output

Wrap a model with `Predictor` or supply a compatible callable. `Prediction` carries outputs and a
mapping of activation layers. Keep labels, class order, geometry coordinates and array dimensions
consistent with the chosen collector.

Subclass `MetricsCollector` when a functional wrapper is insufficient. Implement `collect` and
`column_schemas`. Collector names must not collide with reserved identity fields or with other
collectors in the same call. Missing columns or unequal lengths are refused to prevent corrupted joins.

## Collect embeddings

`EmbeddingsMetricsCollector(layer=..., column="embedding", reshape="mean")` reads a captured layer.
Configure the same layer index on `Predictor(layers=[...])`. Mean pooling reduces spatial dimensions;
flattening keeps them and can greatly increase storage. A callable can implement model-specific
pooling. Verify one vector per sample before [projection](/docs/explore/embeddings).

## Aggregate without losing meaning

`MeanAggregator`, `SumAggregator`, `MinAggregator`, `MaxAggregator` and `aggregate_metrics_table`
provide explicit aggregation. Choose a statistic suited to the metric. For example, averaging
per-image IoU is different from summing class intersections and unions before calculating IoU.
Keep the underlying sample measurements so the aggregate can be investigated later.
