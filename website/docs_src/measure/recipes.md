---
title: Examples and complete workflows
summary: Choose a runnable Granum example or find the reserved place for a future model and dataset recipe.
status: partial
---

Use the guided course for a complete dashboard workflow. Use the Python examples when integrating an
existing pipeline. Each recipe has its own dataset, model and optional dependency requirements;
inspect them before running a download or starting training.

## Included examples

The following files live in the repository's `examples` directory. Run them from the project checkout
with Granum installed in the active environment. Read the file's inputs and output-root settings first.

| File | What it demonstrates |
|---|---|
| `01_tables_and_revisions.py` | Create data and preserve revisions |
| `02_runs_and_metrics.py` | Record runs and sample measurements |
| `03_label_error_ranking.py` | Rank candidates for label inspection |
| `04_object_service.py` | Serve registered data |
| `05_cifar10_resnet.py` | A concrete classification training loop |
| `06_retrain_on_latest.py` | Consume revised data in another experiment |
| `07_detection_yolo.py` | Object detection with YOLO |
| `08_aerial_pipeline.py` | The aerial-data workflow |

The [12-step aerial course](/docs/course/start) covers import, exploration, baseline training, review,
candidate training, results, comparison, handoff and backup with recorded evidence. It remains a small
example, not a capacity or accuracy promise for another dataset.

## Build a workflow from supported pieces

For COCO/YOLO detection, masks, pose and OBBs, begin with [formats](/docs/data/formats), inspect/edit
labels, freeze a [version](/docs/guides/dataset-versions), then connect the corresponding
[training adapter](/docs/integrations/ultralytics). For custom tabular samples, use
[TableWriter](/docs/python/tables#write-rows-and-batches) and
[custom metrics](/docs/python/custom-metrics).

To add image measurements such as brightness, compute one value per canonical input row and create
a typed column with `add_column`. Per-object measurements need a declared instance property.
Embedding collection and shared projections are covered in [embedding exploration](/docs/explore/embeddings).

## Reserved example recipes

These recipes are **Not yet included** as complete Granum examples. Related primitives may already
work; a reserved recipe still needs its own data preparation, executable training/evaluation path
and expected-result checks.

| Reserved recipe | Current starting point |
|---|---|
| Arbitrary PyTorch Dataset conversion; custom external sample loaders | Explicit Python tables and transforms |
| Video frame extraction and sequence splits | Import externally extracted images |
| FHIBE, ADE20K, Oxford-IIIT Pets, Pascal VOC semantic datasets | Prepare supported class-ID masks or COCO data |
| Separate instance-mask images and semantic-to-instance conversion | Prepare an instance-aware COCO dataset externally |
| MNIST and Fashion-MNIST training; autoencoder embeddings | PyTorch adapter and existing CIFAR-10 example |
| UNet, SegFormer and Mask2Former recipes | Semantic collector and framework output adapters |
| Hugging Face IMDb/text fine-tuning and CIFAR-100 embeddings | Indexed Trainer integration |
| Lightning classification and segmentation notebooks | Lightning callback |
| Detectron2 dataset-specific fine-tuning notebooks | Dataset registration and evaluator |
| YOLO classification and dataset-specific pose/mask/OBB tutorials | Supported task adapters; classification callback remains reserved |
| Full SuperGradients YOLO-NAS detection and pose recipes | Indexed callbacks and canonical predictors |
| SAM embeddings, batch auto-segmentation and active labelling | Interactive SAM proposals |
| Crop classifiers and per-instance embeddings | Explicit crop tables and custom collectors |
| Optimised weighted coreset selection | Weight-aware sampling |
| Live registration of augmented observations from a training loop | Explicit versioned augmentation |
| Point clouds, 3D points and PandaSet sensor examples | Reserved spatial-data support |

## Keep results reproducible

Record the exact source revisions, seed, preprocessing, model weights, class map and evaluation rules.
Retain the baseline before reviewing a candidate. Follow [comparison](/docs/guides/compare) and
[export](/docs/improve/export) to complete the loop without losing the evidence behind a change.
