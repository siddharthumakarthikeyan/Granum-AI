---
title: Environment and capacity requirements
summary: Separate core application needs, browser graphics and optional model-framework dependencies.
status: partial
---

Requirements depend on the workflow. Importing and reviewing a small local image dataset does not
need the same environment as training a large segmentation model or collecting every epoch's vectors.
Use the approved artifact's platform information for desktop installation.

## Core and optional packages

Source installs require Python 3.10 or newer. The core uses Arrow, fsspec, NumPy, Pydantic, YAML,
cryptography and file locking. The `service` extra adds FastAPI/Uvicorn; `images` adds Pillow;
`pandas` enables DataFrame workflows; `desktop` supplies the window integration.

| Extra or environment | Purpose |
|---|---|
| `vision` | Mask/geometry support with Pillow, pycocotools and OpenCV |
| `reduction` | UMAP and PaCMAP; PCA uses core numeric dependencies |
| `huggingface` | Torch, Datasets, Transformers and Accelerate |
| `lightning` | Lightning integration |
| `s3`, `gcs`, `azure` | Provider-specific fsspec backends |
| Training add-on | Model-family packages and compatible PyTorch environment |

The `all` extra does not mean every model framework and vision/reduction extra is installed.
Detectron2 and SuperGradients have their own installation constraints. Read the
[integration guides](/docs#integrations) before combining dependency sets.

## Browser and GPU acceleration

Use a browser capable of the dashboard's graphics rendering. Enable hardware acceleration when the
browser/environment supports it and verify a real chart. Remote desktops, virtual machines and
restricted graphics drivers can change behaviour. A WebGL rendering problem is different from
PyTorch failing to detect CUDA.

GPU training requires a compatible driver and framework build. Check the detected device in Training
and its logs; selecting a CUDA device when none is available is an error. CPU operation can be useful
for a small smoke run but is not a training-time guarantee.

## Memory and storage

Plan for source images, new dataset revisions, prediction masks, per-epoch metrics, model checkpoints,
exports and backups. Copying media costs additional disk. Full-width embeddings and many mask
observations can be larger than ordinary scalar metrics.

Several operations materialise data in memory. Use [measured limits](/docs/reference/limits) instead of
extrapolating from a synthetic point demo. Interactive SAM has its own image/point limits.

## Qualification scope

A comprehensive certified OS/browser/GPU/framework matrix is **Not yet included**. Test the exact
artifact, environment and intended workload before depending on it. Keep build identity and logs with
a [troubleshooting report](/docs/help/troubleshooting).
