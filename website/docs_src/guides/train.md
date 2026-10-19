---
title: Train a model
summary: Choose a dataset version and matching model task, record sample measurements, and inspect the completed run.
status: partial
---

**Runs → Train model** starts a supervised model process using a named dataset version. The current
catalogue includes detection, instance segmentation, pose, oriented detection, classification and
semantic segmentation paths. See [task support](/docs/measure/tasks) for dependencies and development
qualification limits.

## Choose the data

Select the dataset version, then its training and validation sets and, optionally, a held-out test set.
If no versions are offered, create one from Images first. An exploratory version and an approved
version have different review guarantees; read the acknowledgement or approval requirement shown.

The task preflight checks the annotation contract, class maps, media and split overlap. Fix a mismatch
before starting the model. Choosing detection simply because the intended mask task fails preflight
would change what the experiment measures.

## Choose the model and recipe

Choose the family, prediction task and size offered by the running build. Detection families include
YOLO, RT-DETR and RF-DETR. YOLO also exposes mask, pose and rotated-box variants. The newer Torchvision
paths use ResNet-18 for classification and LR-ASPP MobileNetV3 for semantic masks.

Set epochs and the input-size controls supported by that family. Larger images and models can increase
memory and processing time; check a short representative run before committing to a long schedule.
RF-DETR has its own image-size behaviour. The [model reference](/docs/reference/models) describes the
catalogue without assuming one family is best for every dataset.

**Record per-sample metrics and predictions every epoch** retains the observations used for learning
analysis and supported Findings workflows. It adds inference work and storage; masks and embeddings
can be substantially larger than scalar metrics. Collect the frequency your investigation needs.

**Compare with** evaluates an earlier compatible model against the intended evaluation context.
Only compare matching tasks. The full [comparison guide](/docs/guides/compare) explains the evidence
needed before attributing a change to better data.

## Follow the job

The progress card shows preparation, model loading, training, metric collection and evaluation phases.
Inspect logs when progress stops or a dependency/device error appears. Closing the browser does not
cancel a job. Supervised trainers can survive a service restart and reconnect; a dead trainer may
instead be reported as interrupted.

Use **Cancel** when you intend to stop. Inspect the resulting status and partial records before
starting again. Conflicting model jobs can occupy the worker; the interface reports when a new request
cannot start.

## Inspect the result

Open the completed run and check its source version, class map, recipe, selected checkpoint and recorded
metrics. Classification uses accuracy/loss, semantic segmentation uses pixel and class-overlap metrics,
and detection-style tasks use their task-specific matching. These headline numbers are not interchangeable.

Where a test set was supplied, keep its final evaluation separate from iterative validation decisions.
Open several joined samples and inspect predictions against their actual labels before relying on a
score. Continue with [reading runs](/docs/guides/runs), [learning](/docs/guides/learning) and
[error inspection](/docs/explore/evaluation).

A complete panoptic trainer and managed training/sweep scheduler are **Not yet included**. Newly added
classification/semantic paths still require broader dataset, device and dashboard qualification.
