---
title: Create and revise tables
summary: Construct datasets, read rows and bulk data, and keep subsets and edits as traceable revisions.
status: available
---

`granum.Table` represents one persisted dataset revision. Choose a table constructor for a known
format or create typed columns explicitly. Configure the project root before writing data; the
examples below use the active configuration.

## Create and load

```python
from granum import Table
from granum.schemas import Float32Schema, StringSchema

table = Table.from_dict_data(
    {"sample": ["a", "b", "c"], "score": [0.2, 0.8, 0.5]},
    schema={"sample": StringSchema(), "score": Float32Schema()},
    project_name="table-demo", dataset_name="train",
)
loaded = Table.from_url(table.url)
assert len(loaded) == 3
print(loaded[0])
```

`from_pandas`, `from_parquet`, `from_csv`, `from_image_folder`, `from_coco`, `from_yolo_url` and
`from_semantic_masks` provide other constructors. CSV fields begin as strings; explicitly convert
them if the intended values are numeric.

## Read samples and bulk data

`table[index]` reads a sample according to each column's schema. `to_arrow()` exposes the backing
Arrow table, `to_pydict()` returns columns, and `to_pandas()` converts to a DataFrame. These bulk
operations can materialise the dataset in memory. A large dataset is not automatically a streaming
iterator merely because it uses Parquet storage.

Image schemas can return a stored URL or decoded PIL image. Use [transforms](/docs/python/transforms)
for model-specific preprocessing without rewriting the original table.

## Make revisions

`set_values`, `set_weights`, `add_column`, `delete_columns`, `delete_rows` and `apply_edits` return new
tables. Keep the returned object or URL. `parent`, `children`, `siblings`, `descendants`, `lineage`
and `depth` expose history. `latest()` follows the safe revision path; ambiguous branches need an
explicit selection. Pin a URL for reproducible training instead of resolving latest during every epoch.

## Subsets and new data

`filter(predicate)` creates a persisted subset. `subset(include_probability=..., seed=...)` samples a
row range. `join_tables(other)` appends compatible rows and records both parents; it is not a
relational key-based join. Check schema/class-map compatibility and duplicate media before combining.
The dashboard's [pull from projects](/docs/guides/pull-from-projects) workflow adds preflight and review.

## Write rows and batches

`TableWriter(schema=..., project_name=..., dataset_name=...)` accepts `add_row`, `add_batch` or
`extend`, then `finalize()` writes a table. Declare all required fields; weights can default to 1.
The writer currently accumulates data in memory. External bulk-array storage and a plugin sample-type
registry are [Not yet included](/docs/planned/extensions).
