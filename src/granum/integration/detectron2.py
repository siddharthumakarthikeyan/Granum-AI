"""Detectron2 dataset registration and an evaluator for Granum per-sample metrics.

Install Detectron2 following its official instructions for your PyTorch/CUDA version.
Use ``GranumEvaluator`` in ``inference_on_dataset`` or a DefaultTrainer evaluator. It
implements Detectron2's reset/process/evaluate protocol and can be combined with its
COCOEvaluator. Registration preserves canonical image IDs after excluding zero weights.
"""
from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

import numpy as np

from granum.core.objects.run import Run
from granum.core.objects.table import Table
from granum.core.url import Url
from granum.formats._common import geometry_column, image_column, kept_rows, root_producer
from granum.formats.vision import encode_mask, extra_of, mask_array
from granum.integration._metrics import SOURCE_URL, MetricAccumulator
from granum.metrics.collect import CollectionError
from granum.metrics.detection import DetectionMetricsCollector


def dataset_dicts(table: Table, *, column: str | None = None, weight_threshold: float | None = 0.0):
    from detectron2.structures import BoxMode

    column = geometry_column(table, column)
    image = image_column(table)
    remap = {label: i for i, label in enumerate(sorted(table.schema[column].value_map))}
    records = []
    for i in kept_rows(table, weight_threshold):
        row = table[i]
        geometry = row[column]
        width, height = int(geometry["width"]), int(geometry["height"])
        if width < 1 or height < 1:
            raise CollectionError("Detectron2 images need positive dimensions")
        annotations = []
        for instance in geometry["instances"]:
            annotation = {"bbox": list(instance["vertices"]), "bbox_mode": BoxMode.XYXY_ABS,
                          "category_id": remap[instance["label"]], "iscrowd": int(bool(instance.get("iscrowd")))}
            segmentation = instance.get("segmentation")
            if segmentation:
                segmentation = json.loads(segmentation) if isinstance(segmentation, str) else segmentation
                if isinstance(segmentation, dict):
                    from pycocotools.mask import encode

                    # Detectron2 expects compressed COCO RLE, including for bitmap edits.
                    segmentation = encode(np.asfortranarray(mask_array(segmentation, width, height), dtype=np.uint8))
                annotation["segmentation"] = segmentation
            extra = extra_of(instance)
            if extra.get("obb"):
                raise CollectionError("Detectron2 dataset_dicts supports axis-aligned instances; use the YOLO adapter for rotated boxes")
            if extra.get("keypoints"):
                points = np.asarray(extra["keypoints"], dtype=float).reshape(-1, 3).copy()
                points[points[:, 2] > 0, :2] += 0.5  # COCO pixel indices -> Detectron2 coordinates
                annotation["keypoints"] = points.reshape(-1).tolist()
            annotations.append(annotation)
        records.append({"file_name": Url(row[image]).resolved, "width": width, "height": height,
                        "image_id": i, SOURCE_URL: table.url.resolved, "annotations": annotations})
    return records


def register_dataset(name: str, table: Table, *, column: str | None = None,
                     weight_threshold: float | None = 0.0):
    from detectron2.data import DatasetCatalog, MetadataCatalog

    column = geometry_column(table, column)
    if name in DatasetCatalog.list():
        raise CollectionError(f"Detectron2 dataset {name!r} is already registered")
    classes = table.schema[column].value_map
    remap = {label: i for i, label in enumerate(sorted(classes))}
    metadata: dict[str, Any] = {"thing_classes": [classes[label].internal_name for label in sorted(classes)],
                                "thing_dataset_id_to_contiguous_id": remap,
                                "granum_table_url": table.url.resolved}
    origin = root_producer(table, "from_coco")
    layouts = [category["keypoints"] for category in origin.get("categories", []) if category.get("keypoints")]
    pose = origin.get("yolo") or (origin.get("top_level") or {}).get("granum_yolo") or {}
    if not layouts:
        layouts = list((pose.get("kpt_names") or {}).values())
    if layouts:
        if any(layout != layouts[0] for layout in layouts):
            raise CollectionError("Detectron2 expects a shared named keypoint layout across classes")
        metadata["keypoint_names"] = list(layouts[0])
        flip_indices = pose.get("flip_idx")
        if flip_indices:
            if len(flip_indices) != len(layouts[0]) or sorted(flip_indices) != list(range(len(layouts[0]))):
                raise CollectionError("invalid keypoint flip indices")
            metadata["keypoint_flip_map"] = [(layouts[0][i], layouts[0][j]) for i, j in enumerate(flip_indices) if i < j]
    # Validate before publishing the catalogue entry, then load fresh records per call.
    dataset_dicts(table, column=column, weight_threshold=weight_threshold)
    DatasetCatalog.register(name, lambda: dataset_dicts(table, column=column, weight_threshold=weight_threshold))
    return MetadataCatalog.get(name).set(**metadata)


def instance_predictions(instances: Any, table: Table, *, column: str, task: str):
    instances = instances.to("cpu")
    labels = sorted(table.schema[column].value_map)
    classes = instances.pred_classes.numpy()
    if any(int(i) != i or not 0 <= i < len(labels) for i in classes):
        raise CollectionError("Detectron2 predicted a class outside the registered dataset")
    boxes = instances.pred_boxes.tensor.numpy()
    if boxes.shape != (len(classes), 4):
        raise CollectionError("expected Detectron2 axis-aligned XYXY boxes")
    result = {"boxes": boxes, "scores": instances.scores.numpy(),
              "labels": np.array([labels[int(i)] for i in classes], dtype=np.int64)}
    if task == "segment":
        if not instances.has("pred_masks"):
            raise CollectionError("Detectron2 instance segmentation output has no pred_masks")
        masks = instances.pred_masks.numpy()
        if masks.shape != (len(classes), *instances.image_size):
            raise CollectionError("Detectron2 masks must be postprocessed to original image resolution")
        result["segmentations"] = [encode_mask(mask) for mask in masks]
    if task == "pose":
        if not instances.has("pred_keypoints"):
            raise CollectionError("Detectron2 pose output has no pred_keypoints")
        points = instances.pred_keypoints.numpy().copy()
        points[:, :, :2] -= 0.5
        result["keypoints"] = points
    return result


class GranumEvaluator:
    def __init__(self, table: Table, *, run: Run, split: str = "val", task: str = "detect",
                 column: str | None = None, epoch: int | None = None,
                 iteration: int | Callable[[], int] | None = None, iou_threshold: float = 0.5):
        if task not in ("detect", "segment", "pose"):
            raise CollectionError("Detectron2 evaluation supports detect, segment or pose")
        self.table, self.run, self.split, self.task = table, run, split, task
        self.column = geometry_column(table, column)
        self.epoch, self.iteration = epoch, iteration
        origin = root_producer(table, "from_coco")
        pose = origin.get("yolo") or (origin.get("top_level") or {}).get("granum_yolo") or {}
        self.collector = DetectionMetricsCollector(self.column, task=task, value_map=table.schema[self.column].value_map,
                                                   iou_threshold=iou_threshold, keypoint_sigmas=pose.get("kpt_oks_sigmas"))
        self.metrics_table = None
        self.reset()

    def reset(self):
        self.buffer = MetricAccumulator(self.table, [self.collector])
        self.metrics_table = None

    def process(self, inputs, outputs):
        if len(inputs) != len(outputs):
            raise CollectionError("Detectron2 returned a different number of images")
        ids, predictions = [], []
        for source, output in zip(inputs, outputs):
            if source.get(SOURCE_URL) != self.table.url.resolved:
                raise CollectionError("Detectron2 mapper must preserve the registered Granum Table identity")
            instances = output.get("instances")
            if instances is None or instances.image_size != (source["height"], source["width"]):
                raise CollectionError("Detectron2 outputs must be postprocessed to the original image dimensions")
            ids.append(source["image_id"])
            predictions.append(instance_predictions(instances, self.table, column=self.column, task=self.task))
        self.buffer.add(ids, predictions)

    def evaluate(self):
        from detectron2.utils import comm

        workers = comm.gather(self.buffer.rows, dst=0)
        error, summary = None, {}
        if comm.is_main_process():
            try:
                for rows in workers:
                    self.buffer.merge(rows)
                iteration = self.iteration() if callable(self.iteration) else self.iteration
                self.metrics_table = self.buffer.write(self.run, split=self.split, epoch=self.epoch, iteration=iteration)
                totals = {name: sum(row[name] for row in self.buffer.rows.values()) for name in ("tp", "fp", "fn")}
                tp, fp, fn = (totals[name] for name in ("tp", "fp", "fn"))
                summary = {**totals, "samples": len(self.buffer.rows),
                           "precision": tp / (tp + fp) if tp + fp else 1.,
                           "recall": tp / (tp + fn) if tp + fn else 1.}
            except Exception as exc:
                if comm.get_world_size() == 1:
                    raise
                error = str(exc)
        errors = comm.all_gather(error)
        if any(errors):
            raise CollectionError(next(error for error in errors if error))
        return {"granum": summary} if comm.is_main_process() else {}
