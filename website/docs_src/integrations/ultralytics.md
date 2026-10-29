---
title: Connect YOLO training
summary: Collect predictions and per-sample metrics from Ultralytics detection, mask, pose and rotated-box runs.
status: partial
---

Use the Ultralytics integration when you already train a compatible YOLO model. Granum records the
experiment and collects predictions against the registered tables. The dashboard training flow is
covered in [Train a model](/docs/guides/train).

## Prepare compatible data

Load the exact training and evaluation tables and export them to the task layout your model needs.
Use `detect`, `segment`, `pose` or `obb` consistently between import, export and the model. Confirm
class names and original image sizes before attaching callbacks.

```python
import granum
from granum.integration.ultralytics import add_granum_callback

granum.export_yolo({"train": train_table, "val": valid_table}, "out/yolo",
                   task="detect", image_strategy="copy")
add_granum_callback(model, {"train": train_table, "val": valid_table},
                   project_name="inspection", run_name="baseline",
                   collect_every=1, track_learning=True)
model.train(data="out/yolo/data.yaml", epochs=10)
```

This fragment assumes an instantiated compatible `model` and loaded table variables. Start with a
short run to verify the data and prediction contract before extending it.

## Choose collection frequency

`collect_every` controls collection intervals; recording every epoch enables finer learning dynamics
and recurring label findings at additional inference and storage cost. `final_only` can reserve a
named split for the final collection instead of exposing it to routine inspection each epoch.

Predicted geometry retains task information: masks for segmentation, landmarks for pose, corners for
oriented boxes. Matching follows the task's mask IoU, OKS or rotated IoU rather than replacing all
geometry with an ordinary bounding box.

## Existing model checks

`collect_detection_metrics(model, table, run=..., split=...)` supports a prediction pass without
training a new model. Inspect unknown-class handling and thresholds. A model trained on a different
class vocabulary cannot judge labels it does not understand.

## Current boundary

A dedicated YOLO classification callback and the legacy standalone
YOLOv5 repository adapter are **Not yet included**. Classification can use the generic
[PyTorch metrics contract](/docs/integrations/pytorch). GPU, model-version and customer-dataset
qualification remain specific to the environment used.
