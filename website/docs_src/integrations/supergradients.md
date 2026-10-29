---
title: Connect SuperGradients
summary: Collect indexed evaluation results and canonical YOLO-NAS detection or pose predictions.
status: partial
---

Use a separate Python environment for SuperGradients. The verified development combination uses
SuperGradients 3.7.1 on Python 3.10 with PyTorch 2.5.1 CPU, torchvision 0.20.1 and setuptools 66.1.1.
Its dependency constraints differ from the main development environment; installing every framework
into one environment can produce incompatible packages.

## Preserve sample identity

```python
from granum.integration.super_gradients import (
    IndexedDataset, identity_collate, Evaluation, GranumCallback,
)
from torch.utils.data import DataLoader

dataset = IndexedDataset(table.with_transform(load_sample))
loader = DataLoader(dataset, batch_size=16, collate_fn=identity_collate)
callback = GranumCallback(run, validation=[Evaluation(table, collectors, "val")])
```

`load_sample` returns `(inputs, target)` and may include a third extras dictionary. Add the callback
to the Trainer's `phase_callbacks` and use the indexed loader for the corresponding evaluation.
For variable-size detection targets, `IdentityCollate(DetectionCollateFN())` preserves the source
fields around the native collation function.

## Adapt predictions

An evaluation's `output_transform` can convert the framework result into collector inputs.
Return `Prediction(outputs, activations)` to include embeddings. Restore predicted geometry to the
original image coordinates before comparing it with canonical labels.

`SuperGradientsPredictor` provides a separate prediction pass for YOLO-NAS detection and pose using
the model's configured processing pipeline. Supply it through an Evaluation `predictor_factory`.
Class vocabulary, pose layout and preprocessing still need to match the registered table.

## Verify the run

Check a shuffled subset, sample counts and a few image overlays. Development checks include real
two-epoch Trainer fitting, validation/test joins, embeddings, variable-target collation and actual
YOLO-NAS detection/pose prediction pipelines. Random-weight inference confirms integration behaviour,
not model accuracy.

## Not yet included

Full native YOLO-NAS training recipes, ready-made detection/pose Table transforms and qualified
GPU/distributed workflows are not yet included. Supply your model's transforms explicitly and
validate them on a small dataset. The [recipe catalogue](/docs/measure/recipes) records these gaps
without presenting a partially configured Trainer as a complete tutorial.
