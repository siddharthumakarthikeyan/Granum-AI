---
title: Storage paths and caches
summary: Understand object directories, URL aliases, cloud access, row caches and saved projections.
status: partial
---

Granum separates table metadata from referenced media. A project's records can remain small while its
images live elsewhere, but portability requires preserving or relocating those references.

## Object layout

A table URL names its directory, not the JSON file inside it:

```text
<project-root>/projects/<project>/
  datasets/<dataset>/tables/<table>/
    object.granum.json
    row_cache.parquet
  runs/<run>/
    object.granum.json
    metrics_0000/
```

`ProjectLayout` resolves these locations. Additional records track imports, review, releases, views
and other project state. Treat metadata and Parquet payloads as a unit; do not rename individual
object files to move a table. Use supported project and backup operations.

## URLs and aliases

`Url` handles local paths and fsspec-backed locations. Its path joining and read/write methods use
the selected filesystem. Install the corresponding cloud extra and configure credentials on the
machine doing the reading.

```python
import granum

granum.register_url_alias("IMAGES", "/data/images")
location = granum.Url("<IMAGES>/sample.png")
print(location.resolved)
print(granum.get_registered_url_aliases())
```

Aliases let a process resolve a logical root to its local storage location. Register matching aliases
wherever you use the data; a Python-only alias does not automatically configure a separately running
service. `GRANUM_ALIAS_<TOKEN>` is the environment form. Conflicting aliases need explicit resolution.

## Row caches and indexing

The Parquet row cache is the backing data used by `to_arrow()` and sample reads. Do not delete it as
though it were a disposable thumbnail. The `table.row-cache` configuration entry exists, but cacheless
reconstruction is **Not yet included** in the current table read path.

The object index discovers records beneath configured roots, watches changes and exposes projects,
tables and runs. A forced reindex can discover new records; it cannot repair missing source payloads.
See [service operation](/docs/operate/service).

## Saved projections

`Reducer.save` preserves a fitted coordinate system. `Reducer.load` restores it; nonlinear reducer
loading requires `trusted=True` because its serialised model can contain executable pickle state.
Load only artifacts from a trusted source. Reuse requires the same embedding model and preprocessing,
not merely equal vector width.

External chunked array/geometry storage and custom adapter registration are
[Not yet included](/docs/planned/extensions). Cloud media also has separate
[deployment and backup boundaries](/docs/operate/cloud).
