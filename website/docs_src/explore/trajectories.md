---
title: Follow samples across epochs
summary: Connect repeated observations and measure changes without losing sample identity.
status: partial
---

A trajectory links measurements of the same sample through an ordered sequence. It can reveal
unstable predictions, changing embeddings or examples that a model learns and later forgets.
Collect more than one observation per sample before using this view.

## Prepare the observations

Record per-sample metrics with an epoch or another numeric iteration column. Preserve each metrics
row's input table reference and sample ID. A row number after sorting is not a stable identity across
datasets. If the input revision changes, keep that change explicit rather than silently joining it
to an earlier sample position.

## Draw a path

Open the run workspace and create a scatter using two or three numerical axes. Configure the
trajectory's grouping field and numeric order field. Use the identity representing one sample and
order by epoch. Filter to a manageable selection and inspect a few paths against their image
observations before interpreting the whole chart.

Embedding trajectories should share a fitted [projection](/docs/explore/embeddings). Independently
fitting each epoch can rotate or rearrange the chart and create apparent movement unrelated to
changes in the model representation.

## Measure full-vector travel

With a vector embedding column, create a **Previous observation** calculation grouped by source
and sample identity, ordered by epoch. Then calculate **Euclidean distance** between the current and
previous vectors. Sum those distances within the same identity groups. The first observation has
no previous vector and therefore no step distance.

This produces travel in the original vector space. Chart distance in a reduced projection answers
a different question. Different sampling intervals and numbers of recorded epochs also affect the
summed distance.

## What remains reserved

A guided, arbitrary N-column travel-distance wizard and component-comparison plot are **Not yet
included**. See [advanced analysis](/docs/planned/advanced-analysis). Existing vector calculations
and trajectory charts can be saved as [analysis workflows](/docs/explore/workflows).

Treat unusually long paths as a review priority, not an automatic instruction to remove an image or
increase its weight. Use [sample learning](/docs/guides/learning) and the source labels as supporting
evidence.
