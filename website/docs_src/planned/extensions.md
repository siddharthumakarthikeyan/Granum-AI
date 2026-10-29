---
title: Custom data and storage extensions
summary: Reserved public extension contracts for sample types, bulk arrays, URL adapters and discovery.
status: planned
---

**Not yet included.** Granum exposes typed tables, read-time transforms, collectors and fsspec-backed
URLs. The extension systems below need additional public contracts before they can be documented as
supported plugin interfaces.

## Custom sample types

Reserved capabilities include user-defined external and inline sample types, acceptance/type detection,
custom serialisation, source-URL resolution and plugin registration. Built-in image URL/PIL reads and
`TableView` transformations remain available.

For now, store supported scalar/vector/media fields and decode them in your own transform. Keep
unsupported payloads outside the table and retain an explicit reference. A Python class existing
in your process does not make it reloadable in a separate service or installed desktop build.

## Bulk array and geometry storage

**Not yet included:** a public external-array store, inline-to-external conversion policy, configurable
chunked geometry/array storage and automatic bulk-data placement. `TableWriter` currently accumulates
rows in memory, and table access relies on the persisted Parquet payload.

The `bulk_data` directory in the project layout is not itself a supported array-storage API. Define
resource limits and a consistent reference contract before writing a custom pipeline around it.

## URL adapters and discovery

**Not yet included:** a Granum-specific public adapter registration interface with declared read/write
capabilities, precedence over built-in schemes, adapter-owned scan roots and custom discovery
invalidation. Existing storage backends use fsspec and the documented cloud extras.

Use [URL aliases](/docs/python/storage#urls-and-aliases) for relocating supported roots. Use an explicit
reindex when records need discovery. Neither operation grants a new service permission or implements
a new storage protocol.

## Import and export plugins

**Not yet included:** a general importer/exporter registry for third-party packages and an arbitrary
PyTorch Dataset converter. Use explicit `TableWriter` construction and the known
[exchange formats](/docs/data/formats), then validate class maps, sample IDs and media access.

A separate [compute-plugin SDK](/docs/planned/compute) is also reserved. When these extension contracts
are included, each will get an installable example, versioning rules, error behaviour and a
round-trip validation procedure. Internal helper functions are not presented here as stable plugin APIs.
