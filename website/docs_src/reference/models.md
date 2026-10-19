---
title: Models and task support
summary: Choose among the model families exposed by the current training catalogue and check their task requirements.
status: partial
---

The Training dialog reads the model catalogue from the running service. Available choices depend on
the installed build and model packages. Use the catalogue shown in your workspace as the final source
for which variants you can start there.

## Included families

| Family | Catalogue choices | Tasks |
|---|---|---|
| Ultralytics YOLO | YOLO26 nano/small/medium; YOLO11 nano/small; YOLOv8 nano | Detection |
| Ultralytics YOLO task variants | Nano/small YOLO26 and YOLO11 variants | Instance masks, pose, OBB |
| RT-DETR through Ultralytics | `rtdetr-l.pt`, `rtdetr-x.pt` | Detection |
| RF-DETR | nano, small, medium, base, large | Detection |
| Torchvision | `resnet18` | Whole-image classification |
| Torchvision | `lraspp-mobilenet-v3` | Semantic segmentation |

The new classification and semantic paths are development implementations with broader qualification
still in progress. See [training tasks](/docs/measure/tasks) for input requirements and current limits.
A model name in the catalogue is not a benchmark result for your data.

## Select a baseline

Begin with a small compatible model and a short run to confirm loading, task geometry, metrics and
checkpoint persistence. Then choose a model size and input resolution based on measured memory use,
throughput and your validation results. Preserve the seed and recipe with each run.

RF-DETR uses its own input-size behaviour; the same image-size control does not apply to every family.
A larger model or image does not guarantee a useful improvement. Compare compatible experiments and
inspect the [per-class errors](/docs/explore/evaluation) behind their headline scores.

## Dependencies and weights

Install training support where prompted and inspect its environment report. Model weights may download
on first use. A successful package installation does not guarantee CUDA availability or a completed
model run. If resources are insufficient, adjust the supported batch, image size or model choice and
record the changed recipe.

Framework integrations for Hugging Face, Lightning, Detectron2 and SuperGradients are available
through [Python guides](/docs#integrations); they are not all one-click training-catalogue entries.
SAM supplies interactive mask proposals rather than this training loop.

## Current boundaries

A universal model marketplace, automatic model recommendation system, qualified hardware matrix and
complete panoptic training path are **Not yet included**. Avoid comparing detection mAP directly with
classification accuracy or semantic IoU. Use [Compare runs](/docs/guides/compare) only with compatible
tasks and evaluation context.
