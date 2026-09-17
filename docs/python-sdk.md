# Python SDK

```bash
pip install -e ".[images,pandas]"          # add s3, gcs or azure for cloud storage
```

## Tables

A **Table** is an immutable, versioned dataset. Every operation returns a new version that names its parent.

```python
import granum
from granum import Table

table = Table.from_image_folder("data/cats-and-dogs", project_name="demo", dataset_name="train")
table = Table.from_coco("instances_train.json", "images/", project_name="aerial", dataset_name="human_aerial")
table = Table.from_yolo_url("data.yaml", "train", task="detect")

len(table), table.columns
row = table[0]                              # {"image": "<path>", "label": 0, "weight": 1.0}

cleaned = table.delete_rows([3, 17]).set_weights({0: 0.0})
cleaned.lineage()                           # the version chain back to the root
Table.from_names("aerial", "human_aerial", "initial").latest()   # newest version of that line
```

Edits made in the dashboard or the Review tab become new versions too, so a training script that
loads `.latest()` picks them up by name.

## Runs and per-sample metrics

Add three calls to an existing training loop:

```python
run = granum.init("demo", "baseline", parameters={"lr": 1e-3})

for epoch in range(epochs):
    ...                                                     # your loop, unchanged
    granum.log({"epoch": epoch, "train_loss": mean_loss})
    granum.collect_metrics(
        table,
        [granum.metrics.ClassificationMetricsCollector(classes=classes)],
        predictor=granum.metrics.Predictor(model, preprocess=to_tensor),
        constants={"epoch": epoch},
    )
```

Every metric resolves back to the sample that produced it:

```python
worst = sorted(run.metrics_tables()[-1].join_input(), key=lambda r: -r["loss"])[:20]
for row in worst:
    print(row["loss"], row["image"], row["label"], row["predicted"])
```

## Samplers

```python
from torch.utils.data import DataLoader

table = Table.from_names("cifar10", "train", "initial").latest()
loader = DataLoader(table.with_transform(load), sampler=granum.create_weighted_sampler(table))
```

| Sampler | Behaviour |
|---|---|
| `create_weighted_sampler` | Draws proportional to weight; never draws weight 0 |
| `create_random_sampler` | Each non-zero-weight sample once, shuffled |
| `create_sequential_sampler` | Each non-zero-weight sample once, in order |
| `create_repeat_by_weight_sampler` | Weight 2 means twice per epoch |

## Object detection

Boxes are a `bounding_boxes_2d` column. Per image:
`{width, height, instances: [{vertices: [x_min, y_min, x_max, y_max], label, ...properties}]}` in pixels.

```python
granum.export_coco(table.latest(), "out/instances.json", image_strategy="copy")
granum.export_yolo({"train": train.latest(), "val": val.latest()}, "out/yolo")   # weight-0 rows are left out

granum.match_boxes(...), granum.box_iou(...), granum.nms(...)                    # box utilities
```

YOLO export renumbers classes 0..K-1.

### Ultralytics

```python
from granum.integration.ultralytics import add_granum_callback

add_granum_callback(model, {"train": train_table, "val": val_table})
model.train(...)
```

Every epoch is logged, and per-box metrics are written from that epoch's weights: predicted boxes
with `confidence`, `iou` and `matched`, `gt_match` per labelled box, and `tp/fp/fn/precision/recall/f1` per image.

### RF-DETR

`granum.integration.rfdetr` provides `load_rfdetr(variant)` and `export_rfdetr_dataset(splits, output)`.
Dashboard training (`python -m granum.training.train`) uses both.

## Training dynamics

`granum.metrics.compute_dynamics` counts one observation per sample per epoch (re-evaluated epochs count
once) and reports `ever_correct`, `first_correct_epoch`, `current_streak`, `stable_by_end`, the observed
range and `max_epoch_gap`. `learned_epoch` is retrospective, and `learning_speed` uses
`"not stable by end"` for samples that were learned and later forgotten. Pass
`allow_loss_probability=False` when the loss is not unweighted hard-label cross-entropy;
`probability_source` records which was used.

## Review, curation and shipping from Python

```python
from granum.core.qa import QaLog
from granum.core.reviews import ReviewLog

QaLog("aerial", "human_aerial").current()        # annotation review statuses and comment counts
QaLog("aerial", "human_aerial").shipped_urls()   # versions approved for training
ReviewLog("aerial", "human_aerial").current()    # curation decisions from the workspace
```

`granum.core.curation.remove_images` and `restore_images` move images between a set and the
dataset's `removed` or `isolated` set, writing new versions of both.

## Examples

| Script | What it shows |
|---|---|
| `examples/01_tables_and_revisions.py` | Tables, versions, lineage |
| `examples/02_runs_and_metrics.py` | A training loop producing per-sample metrics |
| `examples/03_label_error_ranking.py` | A repeatable benchmark: how well planted label errors are found |
| `examples/04_object_service.py` | The REST API end to end |
| `examples/05_cifar10_resnet.py` | ResNet-18 on CIFAR-10 with 3% corrupted labels (GPU recommended) |
| `examples/06_retrain_on_latest.py` | Retrain on corrected data and compare with a 95% interval |
| `examples/07_detection_yolo.py` | COCO128 with YOLO and per-box metrics |
| `examples/08_aerial_pipeline.py` | Import, select, train, review and retrain on a real aerial dataset |

On 10k CIFAR-10 images and 8 epochs, the 50 highest-loss samples in `05` held 45 of the planted errors.
