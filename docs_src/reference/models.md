---
title: Models you can train
summary: YOLO, RT-DETR and RF-DETR — sizes, hardware and when each is the right choice.
---

All three families are trained from the same dialog, recorded the same way, and scored by the same
framework-neutral scorer, so their numbers compare.

## YOLO — Ultralytics

Fast, reliable and the most widely used detector. The right first choice in almost every case.

| Weights | Size | Note |
|---|---|---|
| `yolo26n.pt` | nano | Fastest. Good for trying things out |
| `yolo26s.pt` | small | A good balance of speed and accuracy |
| `yolo26m.pt` | medium | More accurate, about three times slower |
| `yolo11n.pt`, `yolo11s.pt` | nano, small | Previous generation, very well tested |
| `yolov8n.pt` | nano | Older; use it to match an existing YOLOv8 setup |

## RT-DETR — Baidu, through Ultralytics

A transformer detector that sees the whole image at once, which helps when many objects overlap. Slower
to train and hungrier for graphics memory.

| Weights | Size | Note |
|---|---|---|
| `rtdetr-l.pt` | large | About 8 GB of graphics memory at batch 8 |
| `rtdetr-x.pt` | extra large | Most accurate, slowest |

## RF-DETR — Roboflow

A modern transformer on a large pretrained backbone, so it often learns from fewer images. It uses its
own input size, so the image-size setting does not apply.

| Weights | Size | Note |
|---|---|---|
| `nano` | nano | Fastest RF-DETR |
| `small` | small | A good balance |
| `medium` | medium | More accurate, slower |

## Choosing

| Situation | Try |
|---|---|
| First run on a new dataset | YOLO nano, few rounds — confirm the pipeline before spending hours |
| Normal production run | YOLO small or medium at 640 px |
| Small objects, aerial or satellite | YOLO medium at 1024 px or more |
| Dense, overlapping objects | RT-DETR large, if you have the memory |
| Few hundred images total | RF-DETR small |
| Matching an existing deployment | The family and version already in production |

## Hardware

Training needs the PyTorch add-on (about 3 GB with CUDA) and, realistically, an NVIDIA GPU. Without one
training still runs, on the CPU, slowly enough that nano models and small datasets are the only sensible
combination.

Rules of thumb on one modern laptop GPU: a nano model on a few thousand images at 640 px is minutes per
round; a medium model on 11,000 images at 640 px is a few minutes per round; doubling the image size
roughly quadruples both memory and time.

If a run stops with an out-of-memory error, reduce the image size first, then the model size. The batch
size is chosen per family and is usually not the thing to change first.
