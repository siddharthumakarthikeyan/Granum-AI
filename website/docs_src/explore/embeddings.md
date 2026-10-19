---
title: Explore embedding space
summary: Collect feature vectors and project them into a shared two- or three-dimensional coordinate system.
status: available
---

An embedding is a numeric description of a sample produced by a model or feature extractor. Nearby
points can suggest similar samples, but the relationship depends on the model and preprocessing.
Use the original images and labels to interpret a cluster.

## Collect vectors

Use [embedding collectors](/docs/python/custom-metrics#collect-embeddings) with your model, or the
image similarity workflow for its available descriptors. Store vector columns with a fixed-size
`EmbeddingSchema`; ragged vectors, missing values or non-finite components cannot be projected.
Keep the model, layer and preprocessing with the experiment so another run can reproduce them.

## Create a projection

1. Save pending edits and open a table or run containing an embedding column.
2. Choose **Embeddings**, then the vector column and projection method.
3. Select two or three dimensions. Set neighbours and seed where applicable.
4. Optionally choose **Save this coordinate system for reuse** and name it.
5. Start the job, inspect its result, then choose **Open projection**.

PCA is included with the core numeric dependencies. UMAP and PaCMAP require the `reduction` extra.
A table projection creates a new dataset revision; a run projection creates a separate analysis run.
For run data, a new fit uses the last available embedding table and transforms the other epochs
through that coordinate system.

## Reuse a coordinate system

Choose a saved projection when comparing another dataset or run. Use the same embedding model,
layer and preprocessing. The service checks vector width; equal width does not prove two models
produce compatible representations. Fitting each dataset independently makes axes incomparable.

Python users can use `Reducer`, `reduce_table` and `reduce_run` from `granum.reduction`. Saved nonlinear
reducers require trusted loading; see [storage](/docs/python/storage#saved-projections).

## Interpret carefully

Projection compresses information. A gap in a 2D chart is not itself evidence of a bad label, and
movement in a projection differs from distance in the full embedding space. Check several samples,
then use [duplicates](/docs/explore/duplicates), [trajectories](/docs/explore/trajectories) or a
[review queue](/docs/guides/review) to investigate. Large runs and additional GPU/browser combinations
still require workload-specific qualification.
