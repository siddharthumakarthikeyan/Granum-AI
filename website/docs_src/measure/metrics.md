---
title: Record per sample metrics
summary: Link model measurements to exact input samples, splits and epochs so errors remain inspectable.
status: available
---

Aggregate metrics describe a run. Per-sample metrics explain which inputs produced that result.
Granum stores these as metrics tables referencing the input table and its sample IDs.

## Choose a collector

| Task | Collector or path | Measurements |
|---|---|---|
| Classification | `ClassificationMetricsCollector` | Prediction, confidence, loss and related classification measures |
| Detection | `DetectionMetricsCollector(task="detect")` | Object matches and per-image precision, recall and F1 |
| Instance segmentation | `DetectionMetricsCollector(task="segment")` | Matching based on mask IoU |
| Pose | `DetectionMetricsCollector(task="pose")` | Matching based on OKS, with landmark properties |
| Oriented boxes | `DetectionMetricsCollector(task="obb")` | Matching based on rotated IoU |
| Semantic masks | `SemanticMetricsCollector` | Pixel accuracy and class intersections/unions/IoU |
| Features or custom measures | Embedding or functional collector | Typed vectors or your own per-sample columns |

## Attach observations to a run

The following fragment assumes `table`, `model` and `preprocess` have been configured for your inputs:

```python
import granum
from granum.metrics import ClassificationMetricsCollector, Predictor

run = granum.init("inspection", "baseline", parameters={"seed": 7})
metrics = granum.collect_metrics(
    table, [ClassificationMetricsCollector(classes=["acceptable", "defect"])],
    predictor=Predictor(model, preprocess=preprocess),
    run=run, split="validation", constants={"epoch": 0},
)
print(metrics.join_input()[0])
run.set_status("finished")
```

The class order must match the model output and table labels. Collect at each epoch if you need
learning dynamics or recurring findings. Logging a single aggregate loss cannot reconstruct missing
per-sample predictions later.

## Preserve identity

The core collection pass traverses canonical table order. Each collector returns one value per input
sample for every metric column. Framework adapters preserve explicit IDs through supported shuffle
and subset operations. Do not attach arbitrary reordered predictions by positional guesswork.

Keep the input version, split, epoch and evaluation settings with the measurements. Record the
thresholds and task-specific geometry convention. Predictions should be in original-image coordinates;
semantic masks should use the original resolution.

## Check the result

Open the run, inspect several joined rows and compare predictions with their source images. Count
collected samples and explain any intentional exclusions. Use [custom metrics](/docs/python/custom-metrics)
for a runnable model-free example and [run comparison](/docs/guides/compare) before comparing experiments.
