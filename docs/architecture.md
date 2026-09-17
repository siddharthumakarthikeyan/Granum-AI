# Architecture

## Components

```
┌──────────────────────────── one machine ─────────────────────────────┐
│                                                                        │
│   Browser: dashboard (web/)                                            │
│     React + TypeScript + Vite, Zustand store, deck.gl charts           │
│        │  JSON for metadata and actions, Arrow IPC for rows            │
│        ▼                                                               │
│   Object Service (src/granum/service)                                  │
│     FastAPI app: index, tables, runs, media cache, jobs,               │
│     import, review and shipping, training launcher                     │
│        │                                   │                           │
│        ▼                                   ▼                           │
│   Core (src/granum/core)            Training subprocess                │
│     Tables, Runs, schemas, index,     granum.training.train            │
│     curation, reviews, qa             Ultralytics / RF-DETR            │
│        │                                   │                           │
│        ▼                                   ▼                           │
│   Storage: Parquet + JSON on local disk, S3, GCS or Azure (fsspec)    │
└────────────────────────────────────────────────────────────────────────┘
```

The Python SDK and the CLI use the same core directly, without the service.

## Data model

| Object | What it is |
|---|---|
| **Project** | A folder of datasets and runs |
| **Dataset** | A named group of sets (`train`, `valid`, `test`, plus the holding sets `removed` and `isolated`) |
| **Table** | One immutable version of one set: a schema, rows, parents and the operation that produced it |
| **Run** | One training run: parameters, scalar logs per epoch, and metrics tables |
| **Metrics table** | Per-sample (or per-box) metrics for one epoch, keyed by `example_id` to rows of an input table |
| **Review log** | Append-only curation decisions per dataset (`reviews/<dataset>.jsonl`) |
| **QA log** | Append-only annotation-review statuses and comments (`reviews/<dataset>.qa.jsonl`) |
| **Shipments** | Append-only record of which versions were approved for training (`reviews/<dataset>.ships.jsonl`) |

### Versions and lineage

Tables are never modified. Deleting rows, setting weights, committing dashboard edits, removing,
isolating or restoring images, and editing boxes in review all write a **new** table naming its
parent. The producer record stores the operation and, for edits, the sparse set of changed cells,
so what changed is inspectable without diffing.

A run shows the newest version of its input only when every version in between kept rows in
place. A version that deleted, filtered or reordered rows is never joined by position. When labels
changed after metrics were collected, the value used in training is shown beside the current one
as `<column>@collected`.

### Identity across versions

Review decisions, QA statuses and removal records identify images by their **image reference**, not
their row number. Rows move when a version deletes some; the image a decision was about does not.

### Shipping gate

A shipment lists, for each set, the exact table URL shipped. `POST /api/training` accepts only URLs
that appear in some shipment of the project, and the dashboard lists only those. Shipping requires
every image of every non-holding set to be *Reviewed* at that moment.

## Storage layout

```
<project_root>/
  projects/
    index.granum.json
    <project>/
      index.granum.json
      default_aliases.granum.yaml
      datasets/
        <dataset>/
          tables/
            <table>/
              object.granum.json        schema, parents, producer, row count
              row_cache.parquet         rows
          bulk_data/
          cache/thumbnails/
      runs/
        <run>/
          object.granum.json
          metrics_0000/object.granum.json
          cache/thumbnails/
      imports/<id>.json                 preflight reports and resolutions
      reviews/
        <dataset>.jsonl                 curation decisions
        <dataset>.qa.jsonl              annotation review statuses and comments
        <dataset>.ships.jsonl           shipments
```

A Granum object is always a directory containing `object.granum.json`, the way a web server treats
a directory containing `index.html`. The object's URL is the directory.

## Service internals

- **Index**: scans project roots in the background and keeps a list of tables and runs with their metadata and lineage.
- **Rows**: served as Arrow IPC streams (`/api/table/arrow`), so the browser never parses JSON for large tables.
- **Media**: thumbnails are generated on demand and kept in an in-memory cache with a size and time limit.
- **Jobs**: preflight, import and training run as background jobs with progress, logs and cancellation.
- **Append-only logs**: written with a per-file lock; a torn final line from an interrupted write is skipped on read.

## Dashboard internals

- **Routing**: hash routes, so the dashboard is a set of static files the service can serve from any path.
- **State**: one Zustand store for the inspection workspace (rows, filters, selection, edits, undo);
  page-level state for overview, review and training.
- **Rendering**: deck.gl for scatter charts; SVG overlays in image pixel coordinates for boxes, so the
  same markup works on a thumbnail and a full-size viewer.
- **Drafts**: uncommitted workspace edits are mirrored to IndexedDB for crash recovery.

## Design decisions

- **Local first.** Data stays on the user's machine; the service binds to loopback and validates every path.
- **Immutable versions over in-place edits.** Mistakes are recoverable, and training runs name exactly what they used.
- **Decisions are data, not edits.** Reviews and shipments are recorded immediately and independently of table versions.
- **Evidence before action.** Imports report findings with examples and defaults before writing anything.
