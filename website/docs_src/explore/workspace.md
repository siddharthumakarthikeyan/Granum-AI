---
title: Inspect tables and runs
summary: Use linked rows, filters and charts to investigate the samples behind your data and metrics.
status: available
---

Open a table for its dataset contents, or a run for measurements joined to those contents. The
workspace connects row selection, filters, charts and image previews so you can move from a pattern
to the examples behind it.

## Read the rows

The Rows panel presents typed columns. Select a row to inspect it, and use column headers to choose
columns for analysis. Sorting changes the displayed order; it does not rewrite source row identity.
Hide or reorder columns to keep the relevant information together, and use grid or patch views when
images or objects communicate more than a cell value.

Editable columns belong to source data. Metrics and calculated columns can be read-only. Add an
editable column when you need to store an actual annotation; use [Calculate](/docs/explore/calculations)
when the value should be derived. Saving source changes creates a revision.

## Narrow the evidence

Numerical filters select ranges, categorical filters select values, and boolean filters select
true/false. Geometry can expose object-level filters, such as confidence or class. Distinguish
selecting an image from selecting one object in that image before applying an edit.

A chart selection can narrow the same rows. Check the active filters and visible counts before
interpreting a distribution. Invert or clear a filter when you want to investigate the excluded cases.
A locked control preserves its intended state; it does not freeze the underlying dataset.

## Inspect the result

Create a [chart](/docs/explore/charts), open an image or object crop, and compare labels with predictions.
For repeated observations, verify the epoch and source table. Multiple rows may describe one sample
at different epochs; they are not necessarily duplicate source images.

Use the gallery's [Stats and Fields](/docs/guides/browse) controls for dataset distributions and pinned
summaries. Use a [workflow](/docs/explore/workflows) to preserve a useful analysis setup. When a filtered
set should become training data, create an explicit [dataset version](/docs/guides/dataset-versions)
or a [Python subset](/docs/python/tables#subsets-and-new-data).

## Boundaries

Dedicated aggregate-table tabs and arbitrary simultaneous multi-source views are
[Not yet included](/docs/planned/advanced-analysis). Compare runs through the supported
[comparison workflow](/docs/guides/compare). Browser view limits are listed in
[capacity limits](/docs/reference/limits).
