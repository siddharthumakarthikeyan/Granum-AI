"""SuperGradients training callbacks and original-resolution YOLO-NAS predictions.

Install SuperGradients in a compatible environment before importing this module.
Its 3.7.1 release pins older dependencies; use a separate Python 3.10 environment.
"""
from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any

import numpy as np

try:
    import torch
    import torch.distributed as dist
    from super_gradients.training.utils.callbacks import Callback
    from torch.utils.data import default_collate
except ImportError as exc:
    raise ImportError("install SuperGradients and Granum in a compatible environment to use this integration") from exc

from granum.core.objects.run import Run
from granum.core.objects.table import Table, TableView
from granum.core.url import Url
from granum.integration._metrics import SAMPLE_ID, SOURCE_URL, MetricAccumulator, log_scalars
from granum.metrics.collect import CollectionError, iter_batches
from granum.metrics.collectors import MetricsCollector


class IndexedDataset:
    """A Table view returning (inputs, target[, extras]), with stable identity attached.

    Use ``identity_collate`` with the loader. The underlying transform owns model input
    and target preparation. Row subsets and shuffled sampling retain original Table IDs.
    """
    def __init__(self, source: Table | TableView):
        self.source = source
        self.table = source.table if isinstance(source, TableView) else source

    def __len__(self):
        return len(self.table)

    def __getitem__(self, index):
        item = self.source[index]
        if not isinstance(item, (list, tuple)) or len(item) not in (2, 3):
            raise CollectionError("SuperGradients transforms must return (inputs, target[, extras])")
        extras = dict(item[2]) if len(item) == 3 else {}
        if SAMPLE_ID in extras or SOURCE_URL in extras:
            raise CollectionError("the transform overwrote reserved sample identity")
        return item[0], item[1], {**extras, SAMPLE_ID: index, SOURCE_URL: self.table.url.resolved}


class IdentityCollate:
    """Keep identity while delegating variable-sized targets to an SG collator.

    With no ``collate_fn``, use PyTorch's default collator, including extras. A supplied
    collator receives each sample without Granum's two reserved identity fields; plain
    two-item samples work with DetectionCollateFN, and pose extras remain available to
    KeypointsCollate. The collator must preserve sample order and count.
    """
    def __init__(self, collate_fn: Callable | None = None):
        self.collate_fn = collate_fn

    def __call__(self, samples):
        if not samples:
            raise CollectionError("cannot collate an empty batch")
        ids, urls, stripped = [], [], []
        for inputs, target, extra in samples:
            if SAMPLE_ID not in extra or SOURCE_URL not in extra:
                raise CollectionError("use IndexedDataset to preserve sample identity")
            ids.append(extra[SAMPLE_ID])
            urls.append(extra[SOURCE_URL])
            extra = {k: v for k, v in extra.items() if k not in {SAMPLE_ID, SOURCE_URL}}
            stripped.append((inputs, target, extra) if extra else (inputs, target))
        result = (self.collate_fn or default_collate)(stripped)
        if not isinstance(result, (list, tuple)) or len(result) not in (2, 3):
            raise CollectionError("the collator must return (inputs, target[, extras])")
        extras = dict(result[2]) if len(result) == 3 else {}
        if SAMPLE_ID in extras or SOURCE_URL in extras:
            raise CollectionError("the collator overwrote reserved sample identity")
        if len(result[0]) != len(ids):
            raise CollectionError("the collator changed the number of samples")
        return result[0], result[1], {**extras, SAMPLE_ID: torch.tensor(ids), SOURCE_URL: urls}


identity_collate = IdentityCollate()


@dataclass
class Evaluation:
    table: Table
    collectors: Sequence[MetricsCollector]
    split: str
    # A factory runs an extra, canonical inference pass after the SG validation loop.
    # This avoids comparing augmented model coordinates against original annotations.
    predictor_factory: Callable[[Any], Any] | None = None
    # Indexed collection can instead decode context.preds and capture embeddings.
    output_transform: Callable[[Any], Any] | None = None


class GranumCallback(Callback):
    """Collect indexed validation/test batches or an additional canonical model pass.

    ``Evaluation.output_transform(context)`` defaults to ``context.preds`` and may return
    a Granum Prediction containing activations. Geometry must be restored to original
    coordinates. For YOLO-NAS detection/pose, use a ``predictor_factory`` constructing
    ``SuperGradientsPredictor``: SG's pipeline then restores coordinates automatically.

    Distributed indexed metrics are gathered and written on rank zero; canonical passes
    use the unwrapped evaluation model only on rank zero. The caller owns Run status.
    """
    def __init__(self, run: Run, *, validation: Sequence[Evaluation] = (),
                 test: Sequence[Evaluation] = (), collect_every: int = 1, batch_size: int = 16):
        super().__init__()
        if any(type(value) is not int or value < 1 for value in (collect_every, batch_size)):
            raise CollectionError("collect_every and batch_size must be positive integers")
        self.run, self.collect_every, self.batch_size = run, collect_every, batch_size
        self.evaluations = {"validation": list(validation), "test": list(test)}
        for evaluations in self.evaluations.values():
            urls = [e.table.url.resolved for e in evaluations if e.predictor_factory is None]
            if len(set(urls)) != len(urls):
                raise CollectionError("indexed evaluations in one stage must have different source Tables")
        self._buffers: dict[str, list[MetricAccumulator]] = {}
        self._models: dict[str, Any] = {}
        self._average_model = False

    def _enabled(self, context, stage):
        epoch = getattr(context, "epoch", None)
        return not self._average_model and (stage == "test" or epoch is None or (epoch + 1) % self.collect_every == 0)

    def _start(self, context, stage):
        self._buffers[stage] = [MetricAccumulator(e.table, e.collectors) for e in self.evaluations[stage]]
        self._models.pop(stage, None)

    def _batch(self, context, stage):
        if not self._enabled(context, stage) or not self.evaluations[stage]:
            return
        # SG passes the actual evaluation (possibly EMA) model on its batch context.
        self._models[stage] = context.net
        indexed = [(i, e) for i, e in enumerate(self.evaluations[stage]) if e.predictor_factory is None]
        if not indexed:
            return
        extras = context.additional_batch_items or {}
        ids, urls = extras.get(SAMPLE_ID), extras.get(SOURCE_URL)
        if ids is None or urls is None or len(urls) != len(ids) or not len(ids):
            raise CollectionError("use IndexedDataset and IdentityCollate for indexed SuperGradients collection")
        matching = [(i, e) for i, e in indexed if all(url == e.table.url.resolved for url in urls)]
        if len(matching) != 1:
            raise CollectionError("the batch does not belong to a configured Table version")
        index, evaluation = matching[0]
        prediction = evaluation.output_transform(context) if evaluation.output_transform else context.preds
        self._buffers[stage][index].add(ids, prediction)

    def _finish(self, context, stage):
        buffers = self._buffers.pop(stage, [])
        model = self._models.pop(stage, None)
        if not self._enabled(context, stage) or not self.evaluations[stage]:
            return
        distributed = dist.is_available() and dist.is_initialized()
        rank = dist.get_rank() if distributed else 0
        workers = [[buffer.rows for buffer in buffers]]
        if distributed:
            workers = [None] * dist.get_world_size()
            dist.all_gather_object(workers, [buffer.rows for buffer in buffers])
        error = [None]
        if rank == 0:
            try:
                for index, (evaluation, buffer) in enumerate(zip(self.evaluations[stage], buffers)):
                    if evaluation.predictor_factory:
                        if model is None:
                            raise CollectionError("no SuperGradients evaluation model was observed")
                        unwrapped = model.module if hasattr(model, "module") else model
                        predictor = evaluation.predictor_factory(unwrapped)
                        for ids, batch in iter_batches(evaluation.table, self.batch_size):
                            buffer.add(ids, predictor(batch))
                    else:
                        for worker in workers:
                            buffer.merge(worker[index])
                    buffer.write(self.run, split=evaluation.split, epoch=getattr(context, "epoch", None))
                log_scalars(self.run, {**(context.metrics_dict or {}), "epoch": getattr(context, "epoch", None)})
            except Exception as exc:
                if not distributed:
                    raise
                error[0] = str(exc)
        if distributed:
            dist.broadcast_object_list(error, src=0)
            if error[0]:
                raise CollectionError(error[0])

    def on_validation_loader_start(self, context):
        self._start(context, "validation")

    def on_validation_batch_end(self, context):
        self._batch(context, "validation")

    def on_validation_loader_end(self, context):
        self._finish(context, "validation")

    def on_test_loader_start(self, context):
        self._start(context, "test")

    def on_test_batch_end(self, context):
        self._batch(context, "test")

    def on_test_loader_end(self, context):
        self._finish(context, "test")

    def on_average_best_models_validation_start(self, context):
        self._average_model = True

    def on_average_best_models_validation_end(self, context):
        self._average_model = False


class SuperGradientsPredictor:
    """YOLO-NAS detection/pose through SG's original-image prediction pipeline.

    Set the model's dataset processing parameters before use. ``class_names`` lists
    the model classes, in model order; noncontiguous source IDs are mapped by name.
    Pose requires a single declared ``pose_label`` (inferred for a single-class Table).
    """
    def __init__(self, model: Any, value_map: dict, *, task: str = "detect",
                 class_names: Sequence[str] | None = None, pose_label: int | None = None,
                 image_column: str = "image", on_unknown: str = "raise", **predict_options):
        if task not in {"detect", "pose"} or on_unknown not in {"raise", "drop"}:
            raise CollectionError("use detect/pose and on_unknown='raise' or 'drop'")
        self.model, self.task, self.image_column = model, task, image_column
        if any(k in predict_options for k in ("images", "batch_size", "fuse_model")):
            raise CollectionError("images, batch_size and fuse_model are controlled by the adapter")
        self.options = {"fp16": False, **predict_options}
        if task == "pose":
            if pose_label is None and len(value_map) == 1:
                pose_label = next(iter(value_map))
            if pose_label not in value_map:
                raise CollectionError("declare pose_label using a class ID from the source Table")
            self.pose_label = pose_label
            self.class_map = {}
        else:
            names = list(class_names) if class_names is not None else list(getattr(model, "_class_names", None) or [])
            by_name = {entry.internal_name: label for label, entry in value_map.items()}
            if len(by_name) != len(value_map) or not names or len(set(names)) != len(names):
                raise CollectionError("declare unique model and Table class names")
            unknown = [name for name in names if name not in by_name]
            if unknown and on_unknown == "raise":
                raise CollectionError(f"model classes are absent from the Table: {unknown}")
            self.class_map = {i: by_name[name] for i, name in enumerate(names) if name in by_name}
            self.class_count = len(names)
            if not self.class_map:
                raise CollectionError("the model and Table have no classes in common")

    def __call__(self, batch):
        paths = [Url(path).resolved for path in batch[self.image_column]]
        modes = [(module, module.training) for module in self.model.modules()]
        try:
            result = self.model.predict(paths, batch_size=len(paths), fuse_model=False, **self.options)
            images = [result] if hasattr(result, "prediction") else list(result)
            if len(images) != len(paths):
                raise CollectionError("SuperGradients returned the wrong number of image predictions")
            return [self._prediction(image.prediction) for image in images]
        finally:
            for module, training in modes:
                module.training = training

    def _prediction(self, prediction):
        if self.task == "pose":
            points = np.asarray(prediction.poses, dtype=float)
            scores = np.asarray(prediction.scores, dtype=float)
            if points.ndim != 3 or points.shape[-1] != 3 or len(points) != len(scores):
                raise CollectionError("expected YOLO-NAS poses shaped (instances, keypoints, 3)")
            if prediction.bboxes_xyxy is None:
                raise CollectionError("pose metrics require YOLO-NAS bounding boxes")
            boxes = np.asarray(prediction.bboxes_xyxy, dtype=float)
            output = {"boxes": boxes, "scores": scores,
                      "labels": np.full(len(points), self.pose_label, dtype=np.int64), "keypoints": points}
        else:
            labels = np.asarray(prediction.labels)
            if labels.ndim != 1 or any(int(i) != i or not 0 <= i < self.class_count for i in labels):
                raise CollectionError("SuperGradients predicted an undeclared class index")
            boxes = np.asarray(prediction.bboxes_xyxy, dtype=float)
            scores = np.asarray(prediction.confidence, dtype=float)
            if boxes.shape != (len(labels), 4) or scores.shape != (len(labels),):
                raise CollectionError("SuperGradients boxes, classes and scores have different lengths")
            keep = [i for i, label in enumerate(labels) if int(label) in self.class_map]
            output = {"boxes": boxes[keep], "scores": scores[keep],
                      "labels": np.array([self.class_map[int(labels[i])] for i in keep], dtype=np.int64)}
        if output["boxes"].shape != (len(output["labels"]), 4) or not all(
            np.isfinite(output[name]).all() for name in ("boxes", "scores")
        ):
            raise CollectionError("SuperGradients returned invalid geometry or scores")
        if self.task == "pose" and not np.isfinite(output["keypoints"]).all():
            raise CollectionError("SuperGradients returned non-finite keypoints")
        return output
