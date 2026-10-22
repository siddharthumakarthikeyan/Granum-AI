---
title: Save an analysis workflow
summary: Reuse calculations, charts, filters and layout settings across compatible tables and runs.
status: available
---

An analysis workflow saves how you inspect data. It contains calculations, chart definitions, active
or locked filters, sorting and display settings. It does not package image bytes, model weights or
editable source annotations.

## Capture a setup

1. Open a representative table or run and configure the views you need.
2. Check filters and axis choices, especially any calculations depending on sample identity.
3. Open **Workflows**, enter a descriptive unique name and choose **Save current setup**.
4. Apply it again to confirm that the setup answers the same question.

Saved workflows live in the browser's local storage. A different browser, profile or service origin
can have a different collection. Export workflows you need to retain outside that profile.

## Export and import

Choose **Export** beside a saved workflow to download its `.granum-workflow.json` file. In another
workspace, open Workflows and choose **Import JSON**. Give it a distinct name if a workflow with the
same name already exists, then choose **Apply** on a compatible dataset.

The importer validates its version, shapes and settings. The current limits include files below
2 MiB, 100 saved workflows, 32 charts per workflow and 64 calculations. Imported definitions cannot
supply executable Python or JavaScript.

## Resolve incompatibility

Required source columns must exist with compatible types. A workflow built around a confidence
column cannot be applied to a table with no confidence measurements. Inspect the error, supply the
correct metrics or select the intended source, then retry. Failed application validates before
replacing the current view.

A calculation error may also reveal that a source column was renamed or removed. Preserve a working
export before revising a complex setup.

## Analysis versus data selection

A workflow describes a question; its answer changes with the rows loaded. If another person must use
exactly the same samples for training, share the [dataset version](/docs/guides/dataset-versions) too.
The built-in [Evaluation](/docs/explore/evaluation) and [comparison](/docs/guides/compare) screens provide
specialised analysis. A managed catalogue of executable workflow plugins is
[Not yet included](/docs/planned/compute).
