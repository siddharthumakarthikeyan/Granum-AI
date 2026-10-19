---
title: Connect Detectron2
summary: Register Granum tables and collect detection, instance-mask or keypoint predictions with a Detectron2 evaluator.
status: partial
---

The Detectron2 integration exposes tables through its dataset catalogue and records predictions with
`GranumEvaluator`. Install Detectron2 for your chosen PyTorch, compiler and CUDA environment before
using this optional adapter.

## Register a dataset

```python
from granum.integration.detectron2 import register_dataset, GranumEvaluator
from detectron2.evaluation import inference_on_dataset

register_dataset("granum_validation", table)
evaluator = GranumEvaluator(table, run=run, task="segment", split="val", epoch=0)
summary = inference_on_dataset(model, validation_loader, evaluator)
```

Here `validation_loader` must be built from the registered dataset using your Detectron2 loader
configuration. Its mapper must preserve `image_id` and `__granum_table_url`. Use the task matching
your table and model: detection, instance segmentation or pose.

## Preserve annotation meaning

Category IDs are mapped to contiguous model classes and mapped back when recording metrics.
Check class names rather than assuming dataset IDs already match model output positions.
For bitmap masks, configure `cfg.INPUT.MASK_FORMAT = "bitmask"`.

The adapter handles the COCO/Detectron2 half-pixel keypoint convention. Avoid applying that conversion
a second time in a custom mapper. Keep source image dimensions so predictions can be related to
original geometry.

## Integrate with training

Return a `GranumEvaluator` from your `DefaultTrainer.build_evaluator` override or combine it with
another evaluator. `iteration=lambda: trainer.iter` can record the active training step.
Keep the Run available across evaluations and finish it when the training process concludes.

Verify a small shuffled evaluation set and inspect joined predictions before extending training.
Development evidence includes the real dataset catalogue/mapper, class and keypoint mapping,
Mask R-CNN optimisation and inference on CPU.

## Not yet included

Rotated-box input is refused by this adapter. Dedicated semantic/panoptic adapters, embedding hooks
and qualified distributed/GPU workflows are not yet included. Use the
[YOLO OBB path](/docs/integrations/ultralytics) for supported rotated-box work, or the
[custom collector contract](/docs/python/custom-metrics) for an explicit model-output adapter.
