---
title: Connect Hugging Face
summary: Preserve sample identity through Datasets and collect Trainer predictions or hidden-state embeddings.
status: available
---

Use the Hugging Face adapter with a configured Trainer, Dataset preprocessing and Granum collectors.
From a source checkout, install the `huggingface` extra in your selected Python environment. Keep
model-specific tokenisation and image processing in your own pipeline.

## Build an indexed dataset

```python
from granum.integration.hugging_face import to_dataset, collect_predictions
from granum.metrics import ClassificationMetricsCollector

dataset = to_dataset(table, columns=["features", "label"])
dataset = dataset.shuffle(seed=7).select(range(min(100, len(dataset))))
result = collect_predictions(
    trainer, table, dataset,
    [ClassificationMetricsCollector(classes=classes)],
    run=run, split="validation", epoch=1,
)
```

The fragment assumes `table`, `trainer`, `classes` and `run` already exist and the selected fields
match your model. Preserve both `__granum_*` identity columns through preprocessing. The integration
removes identity fields from the copy passed to the model while keeping them for joins. A dataset
from another table revision is rejected.

## Attach training collection

`GranumTrainer` accepts `granum_run` and a mapping of `granum_evaluations` built with `Evaluation`.
It logs aggregate measurements and runs prediction collection after evaluations. `collect_every`
controls frequency. The caller remains responsible for finishing the Granum Run.

For hidden states or nonstandard outputs, supply `prediction_transform` to return a Granum
`Prediction(outputs, activations)`. It receives the complete Hugging Face prediction result, not
only logits. Restore image geometry to source coordinates and semantic masks to source resolution.

## Verify the joins

Check a shuffled subset and confirm the joined source records before running a full dataset. This
is especially important after tokenisation, filtering or image preprocessing. Do not recreate IDs
from the final row positions.

Single-process Trainer prediction, embeddings and training callbacks have development verification.
Distributed use requires calling collection on all ranks, with the world process zero writing, but
broader distributed and task-specific vision qualification remains open. Ready-made recipes for
individual text and segmentation models are [Not yet included](/docs/measure/recipes#reserved-example-recipes).
