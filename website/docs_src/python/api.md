---
title: Python API reference
summary: Find Granum public objects, constructors, metrics, configuration and integration entry points.
status: available
---

The Python package is imported as `granum`. The reference below groups its current public entry
points by task. Use the linked guides for complete workflows and the installed symbol's docstring
for the signature in your exact build. Granum is an alpha package; pin its revision with your environment.

## Top level objects

| Symbol | Purpose |
|---|---|
| `Table`, `TableView` | Persisted dataset revisions and read-time transformations |
| `TableWriter`, `MetricsTableWriter` | Construct table or metrics rows/batches and finalise them |
| `Run`, `MetricsTable` | Experiment records and measurements linked to input samples |
| `Config`, `get_config`, `set_config` | Resolve and select process configuration |
| `Index`, `get_index`, `set_index` | Discover and resolve project objects |
| `ProjectLayout`, `Url`, `load_object` | Object locations, filesystem access and object loading |
| `BoundingBoxes2D`, `box_iou`, `match_boxes`, `nms` | Detection geometry and matching utilities |
| `schemas`, `metrics`, `__version__` | Typed-column/measurement namespaces and package version |

## Table constructors and access

| Call | Behaviour |
|---|---|
| `Table.from_dict_data(data, schema=None, *, project_name=..., dataset_name=...)` | Create a table from equally sized columns |
| `Table.from_pandas(df, **kwargs)` | Convert a DataFrame |
| `Table.from_parquet(url, **kwargs)` | Read Parquet columns |
| `Table.from_csv(url, **kwargs)` | Read CSV fields as strings |
| `Table.from_image_folder(root, **kwargs)` | Register class-directory images |
| `Table.from_coco(annotations, image_folder=None, **kwargs)` | Read COCO annotations and referenced media |
| `Table.from_yolo_url(data_yaml, split="train", *, task=None, **kwargs)` | Read one YOLO split and task |
| `Table.from_semantic_masks(manifest, **kwargs)` | Read lossless class-ID mask data |
| `Table.from_url(url)` / `Table.from_names(project_name, dataset_name, table_name)` | Load an exact revision |
| `table[index]`, `to_arrow()`, `to_pydict()`, `to_pandas()`, `summary(column)` | Sample, bulk and summary access |

See [tables](/docs/python/tables) for revision methods, subsets, append operations and lineage.
See [schemas](/docs/python/schemas) for scalar, categorical, vector, media and geometry types.

## Run and metric functions

`init(project_name, run_name, *, parameters, constants, if_exists, config)` creates a Run;
`log(values, *, run=None)` records aggregates. `get_active_run` and `set_active_run` control implicit
run selection. Run methods include `set_parameters`, `set_status`, `add_metrics`, `metrics_tables`,
`aggregate_metrics` and `joined`. A MetricsTable exposes `input_table`, `join_input` and `to_pandas_joined`.

`collect_metrics(table, metrics_collectors, *, predictor=None, model=None, run=None, split=None,
constants=None, batch_size=32, exclude_zero_weights=False, column_schemas=None, description="")`
returns a persisted MetricsTable. Each collector must produce one output per sample.

The `granum.metrics` namespace exposes `Prediction`, `Predictor`, `MetricsCollector`,
`FunctionalMetricsCollector`, `ClassificationMetricsCollector`, `DetectionMetricsCollector`,
`SemanticMetricsCollector` and `EmbeddingsMetricsCollector`. It also includes `iter_batches`,
`Aggregator`, `MeanAggregator`, `SumAggregator`, `MinAggregator`, `MaxAggregator`,
`aggregate_metrics_table`, `DynamicsThresholds`, `compute_dynamics`, `epoch_summary` and
`training_dynamics`. Read [metrics](/docs/measure/metrics) and [collectors](/docs/python/custom-metrics)
before providing custom model outputs.

## Sampling export and reduction

`create_weighted_sampler`, `create_random_sampler`, `create_sequential_sampler` and
`create_repeat_by_weight_sampler` operate on table weights. See [weight semantics](/docs/improve/weights).

`export_coco`, `export_yolo` and `export_semantic_masks` write supported interchange formats. Select
an explicit task and image strategy appropriate to the destination. `granum.reduction` provides
`Reducer`, `methods`, `reduce_table` and `reduce_run`; see [projections](/docs/explore/embeddings).

## Configuration and integrations

`register_url_alias`, `unregister_url_alias` and `get_registered_url_aliases` manage process URL aliases.
`Config.load(overrides=..., config_file=..., use_config_files=..., use_env=...)` resolves settings.
Read [configuration](/docs/operate/configuration) before changing the root of an existing service.

Framework modules are `granum.integration.ultralytics`, `hugging_face`, `lightning`, `detectron2`,
`super_gradients`, `rfdetr` and `sam`. Use the [framework guides](/docs#integrations) for dependency and
output contracts. A module's presence does not imply every model family/task combination is supported.

## Errors and extension boundaries

Top-level errors include `GranumError`, `TableError`, `SchemaError`, `ConfigError`, `RunError`,
`ImmutableError`, `ObjectNotFoundError` and `AliasConflictError`. Metrics adds `CollectionError`,
`CollectorError` and `PredictorError`. Keep the original error when reporting a failed operation.

A public compute-plugin SDK, arbitrary sample-type registry and third-party URL-adapter registration
are [Not yet included](/docs/planned/extensions). Internal helpers are not interchangeable with a
supported plugin contract.
