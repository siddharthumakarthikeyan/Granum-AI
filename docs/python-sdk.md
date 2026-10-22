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

`summary` asks what one column adds up to — the same readings the dashboard shows for the images
a ribbon has left, over the whole column here. Missing values are counted as missing rather than
read as zero, and nothing numeric is reported for a column that is not numbers:

```python
table.summary("width")
# {"count": 12429, "present": 12429, "missing": 0, "distinct": 46,
#  "min": 640.0, "max": 3840.0, "sum": ..., "mean": ..., "std": ...,
#  "quantiles": {"0.25": ..., "0.5": ..., "0.75": ...}, "top": [{"value": 1920.0, "count": 5102}, ...]}

table.summary("sequence")["top"][:3]        # the commonest values of a text column
```

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

YOLO detection, instance segmentation, pose and oriented boxes are supported. Set
`task="segment"`, `task="pose"` or `task="obb"` on `export_yolo`; predictions retain
their masks, keypoints or rotated corners. Matching uses mask IoU, keypoint OKS or
rotated IoU respectively. Pose predictions expose `keypoint_0_oks`,
`keypoint_0_confidence`, etc. as numeric instance properties for filtering and charts.
An unlabelled ground-truth keypoint has a null score. Horizontal pose augmentation
requires `flip_idx` metadata so left/right landmark names remain correct.

### Hugging Face

Install `granum[huggingface]`. Create a Dataset with explicit sample IDs, then apply
your tokenizer or image processor while preserving the two `__granum_*` columns:

```python
from granum.integration.hugging_face import to_dataset, collect_predictions
from granum.metrics import ClassificationMetricsCollector

dataset = to_dataset(table, columns=["features", "label"])
dataset = dataset.shuffle(seed=7).select(range(100))
metrics = collect_predictions(
    trainer, table, dataset, [ClassificationMetricsCollector(classes=classes)],
    run=run, split="validation", epoch=1,
)
```

The model receives a copy without the identity columns. IDs survive shuffle, filtering
and subset selection; a Dataset from another Table version is rejected. Default
collection uses logits. For hidden states or vision outputs, pass
`prediction_transform=lambda result: Prediction(outputs, {layer_id: embeddings})`.
The transform receives Hugging Face's complete `PredictionOutput`. Detected geometry
must use the original image coordinates, and semantic masks must use the original
resolution. Call collection on every distributed rank; only the world process zero writes.

`GranumTrainer(..., granum_run=run, granum_evaluations={"validation":
Evaluation(table, dataset, collectors)})` logs aggregate metrics and adds a prediction
pass after each evaluation. `collect_every` controls the evaluation interval. The Run
stays open for the caller to finish. This integration was exercised with Transformers
5.20.1, Datasets 5.1.0 and Accelerate 1.15.0; other supported dependency versions still
need qualification.

### Lightning

Install `granum[lightning]`. Wrap an evaluation Table view with `IndexedDataset`:

```python
from granum.integration.lightning import IndexedDataset, Evaluation, GranumCallback

dataset = IndexedDataset(table.with_transform(load_sample_dict))
callback = GranumCallback(
    run, validation=[Evaluation(table, collectors, "val")],
    test=[Evaluation(test_table, test_collectors, "test")],
)
trainer = lightning.Trainer(callbacks=[callback], ...)
```

The transform returns a dict; its collator must preserve the added identity fields.
Validation/test steps return a logits tensor, `{"logits": tensor}`, or a `Prediction`.
Use `output_transform(outputs, batch)` for other return formats. Sanity validation is
skipped. The callback computes metrics against canonical labels, gathers distributed
metrics, and deduplicates sampler padding only when the repeated metrics agree.
`close_run=True` opts into managing Run completion/failure. Single-process CPU training,
test collection, and two-process CPU/Gloo validation with sampler padding have been
verified with Lightning 2.6.6. GPU and other distributed strategies remain to be qualified.

### Detectron2

Install [Detectron2 for your PyTorch/CUDA environment](https://detectron2.readthedocs.io/en/latest/tutorials/install.html).
Its native extension requires a C++ compiler. Register a Granum Table and attach an evaluator:

```python
from granum.integration.detectron2 import register_dataset, GranumEvaluator
from detectron2.evaluation import inference_on_dataset

register_dataset("granum_validation", table)
evaluator = GranumEvaluator(table, run=run, task="segment", split="val", epoch=0)
summary = inference_on_dataset(model, validation_loader, evaluator)
```

Build `validation_loader` from the registered dataset with Detectron2's data-loader
utilities. Its mapper must preserve `image_id` and `__granum_table_url`. For bitmap
annotations set `cfg.INPUT.MASK_FORMAT="bitmask"`. Category IDs are mapped to contiguous
model classes and mapped back when writing metrics. COCO keypoint coordinates are
converted to/from Detectron2's half-pixel convention. Detection, masks and keypoints
are supported; the adapter refuses rotated annotations. `GranumEvaluator` can also be
returned by a custom `DefaultTrainer.build_evaluator` or combined with `COCOEvaluator`.
Pass `iteration=lambda: trainer.iter` to record the current training step.

The real Mask R-CNN mapper, one optimization step, inference and shuffled metric joins
were verified on CPU against Detectron2 revision `1e3e13b`. Multi-GPU collection and
larger datasets remain to be qualified.

### SuperGradients

SuperGradients 3.7.1 pins NumPy 1.23.0 and older torchmetrics. Use a separate Python
3.10 environment; the current verification used PyTorch 2.5.1 CPU, torchvision 0.20.1
and setuptools 66.1.1 (SG imports `pkg_resources`). Install Granum in that environment.

```python
from granum.integration.super_gradients import (
    IndexedDataset, identity_collate, Evaluation, GranumCallback,
)

# load_sample returns (inputs, target), optionally with a third extras dictionary.
dataset = IndexedDataset(table.with_transform(load_sample))
loader = torch.utils.data.DataLoader(dataset, batch_size=16, collate_fn=identity_collate)
callback = GranumCallback(run, validation=[Evaluation(table, collectors, "val")])
trainer.train(..., valid_loader=loader, training_params={
    # Include your ordinary SuperGradients training parameters here.
    "phase_callbacks": [callback],
})
```

`IdentityCollate(DetectionCollateFN())` retains source IDs when collating variable-sized
detection targets. For custom outputs, pass `output_transform=lambda context: ...` on
the Evaluation; returning `Prediction(outputs, activations)` supports embedding
collectors. Geometry from an indexed loader must be restored to source coordinates.

For YOLO-NAS detection and pose, an extra canonical prediction pass handles that
restoration through the model's configured SuperGradients processing pipeline:

```python
from granum.integration.super_gradients import SuperGradientsPredictor
from granum.metrics import DetectionMetricsCollector

evaluation = Evaluation(
    table, [DetectionMetricsCollector("bbs", task="pose", value_map=table.schema["bbs"].value_map)], "val",
    predictor_factory=lambda model: SuperGradientsPredictor(
        model, table.schema["bbs"].value_map, task="pose", conf=0.25,
    ),
)
callback = GranumCallback(run, validation=[evaluation], collect_every=2)
```

Configure `model.set_dataset_processing_params(...)` for the model's input size and
normalization first. Detection classes map back to Table IDs by name. Pose supports one
declared object class; provide `pose_label` for a Table with multiple classes. A canonical
pass uses the evaluation model (including EMA), preserves its training flags and avoids
fusing a cached copy of its weights. The caller manages Run completion/failure.

Real two-epoch CPU training, shuffled validation/test joins, embedding collection and
YOLO-NAS detection/pose inference passed with SG 3.7.1. The vision models were randomly
initialized, so these checks establish integration behavior, not accuracy. GPU, distributed
callbacks and full native YOLO-NAS training recipes remain to be qualified.

### Semantic masks and embeddings

`SemanticMetricsCollector(value_map, ignore_index=255)` accepts one integer class-ID
map per image. It records pixel accuracy, mean IoU, per-class intersections/unions and
lossless predicted-mask overlays. Aggregate intersections and unions across images
before computing dataset IoU; averaging image IoUs gives a different statistic.

`EmbeddingsMetricsCollector(layer_index)` captures a `Predictor` forward-hook layer.
Use `reshape="mean"`, `"flatten"` or a pooling callable. `granum.reduction.Reducer`
supports PCA, UMAP and PaCMAP with two or three components; reuse one fitted reducer to
compare epochs in one coordinate system. `reducer.save(directory)` persists a model
without overwriting an existing directory. `Reducer.load(directory)` loads PCA safely;
UMAP/PaCMAP require `trusted=True` because their serialized backend uses pickle. Only
load those from a source you trust. Checksums detect corruption, not malicious models.

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
