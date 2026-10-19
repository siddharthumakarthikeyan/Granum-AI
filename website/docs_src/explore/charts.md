---
title: Build linked charts
summary: Plot metrics, inspect images and select observations in two or three dimensions.
status: partial
---

Charts help you locate patterns and inspect the underlying samples. Start with a question such as
which images have high loss and low confidence; then choose axes that answer it.

## Create a chart

Select columns in Rows and create a chart. One numeric column plots against row position; two numeric
columns become the horizontal and vertical axes. An additional suitable column can provide colour.
An image column can create an image chart with labels in its corners.

Use the chart controls to change axes, colour, point size or a size column. Keep units and ranges in
mind: a large value does not automatically mean a poor sample. Missing or non-finite measurements
need investigation rather than an assumed zero.

## Select and inspect

Use the available rectangle, lasso, polygon or brush tools to select a region. Panning and zooming
change the camera; selection changes the observations under investigation. Inspect selected rows and
images before assigning labels or weights. Showing filtered-out observations can preserve context,
but those observations are still outside the active filter result.

Categorical colour emphasises a small set of distinguishable categories, with the remainder grouped
visually. Use the legend and filters to inspect a category whose colour is not currently emphasised.
Image charts can show labels and predictions together; confirm the chosen overlay and epoch.

## Work in three dimensions

A third numerical axis changes a scatter to an orbitable 3D view. Rotate it to inspect overlapping
clusters, then use the screen-space selection controls. Selection uses projected point centres at all
depths. It is **not a saved three-dimensional volume filter**; points behind another cluster can
still fall inside the same screen region.

Keep this distinction when sharing a selection. Save a [workflow](/docs/explore/workflows) for the
analysis configuration and a dataset subset for the actual data you intend to use.

## Reuse and limits

Save chart favourites or a workflow after checking the axes and required columns. Charts can depend
on calculated columns, embeddings or multi-epoch metrics that another table does not contain.

Parallel-coordinate component plots and dynamically reduced charts are
[Not yet included](/docs/planned/advanced-analysis#additional-plot-and-view-types). For spatial model
inputs and annotations, see the separate [3D data scope](/docs/planned/spatial).
