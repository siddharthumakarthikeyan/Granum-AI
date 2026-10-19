---
title: Choose a training task
summary: Match dataset labels, model families and evaluation metrics before starting a training job.
status: partial
---

Start from a named dataset version and choose the model family that matches its labels. The current
development source includes the task paths below; each still needs compatible dependencies, readable
media and matching class definitions across splits.

## Task map

| Task | Current model path | Main recorded measurement |
|---|---|---|
| Object detection | YOLO, RT-DETR, RF-DETR | Detection precision, recall and average precision |
| Instance segmentation | YOLO segmentation variants | Mask-based object matching |
| Keypoints | YOLO pose variants | Keypoint similarity and per-landmark observations |
| Oriented detection | YOLO OBB variants | Rotated-overlap matching |
| Image classification | Torchvision ResNet-18 | Accuracy, loss and macro F1 |
| Semantic segmentation | Torchvision LR-ASPP MobileNetV3 | Mean class IoU and pixel accuracy |

Classification and semantic training are newly implemented development paths. Full representative
dataset/GPU/dashboard qualification is still in progress. Their model entries do not imply support
for arbitrary classifiers or every semantic architecture.

## Start a job

1. Open Datasets and select the frozen version to train on.
2. Choose **Train**, the model family, task variant and model size available in your build.
3. Confirm training, validation and any held-out test selection. Keep the test set outside routine tuning.
4. Set epochs, image size and supported recipe controls. Enable per-sample recording when you need
   repeated observations and overlays.
5. Read task-preflight errors before starting; fix the data rather than selecting an unrelated task.
6. Start the run, inspect progress/logs, then check the stored measurements and checkpoint.

## Data requirements

Task preflight checks readable media, compatible class maps, task geometry and split overlap.
Classification needs one valid whole-image class per image. Semantic training needs class-ID masks
with compatible ignore handling and labelled pixels. Both need at least two represented classes,
including background where it is part of the semantic task. Mask resizing that removes all labelled
pixels is an error; choose an appropriate resolution.

Training weights affect the training population/sampling. Evaluation retains its declared population;
inspect any exclusions before comparing scores. Semantic metrics aggregate class intersections/unions
rather than simply averaging image means.

## Not yet included

A complete panoptic trainer, dedicated YOLO classification callback, arbitrary architecture catalogue
and managed hyperparameter sweeps are not yet included. Specialised evaluation screens can still be
more limited than the underlying metric collector. Use the recorded run/table workspace and
[metrics guide](/docs/measure/metrics) for the exact outputs available.
