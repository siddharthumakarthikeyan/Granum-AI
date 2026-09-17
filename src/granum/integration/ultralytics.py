"""Ultralytics YOLO: per-box metrics from a trained detector, and a training callback.

    from ultralytics import YOLO
    from granum.integration.ultralytics import add_granum_callback

    model = YOLO("yolov8n.pt")
    add_granum_callback(model, {"train": train_table, "val": val_table}, project_name="coco128")
    model.train(data=granum.export_yolo({"train": train_table, "val": val_table}, "export"))

Every epoch logs YOLO's own validation numbers (mAP, precision, recall, losses) to a Granum
Run; on collection epochs it also predicts over each Table with that epoch's weights and
writes per-box metrics, so the dashboard can show which boxes the model missed or
invented, epoch by epoch.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import numpy as np

import granum
from granum.core.objects.run import Run, get_active_run
from granum.core.objects.table import Table
from granum.core.schemas.geometry import BoundingBoxes2DSchema
from granum.core.url import Url
from granum.errors import GranumError
from granum.metrics import DetectionMetricsCollector, collect_metrics


class IntegrationError(GranumError):
    """The framework's model or output does not fit the Table."""


def _load_yolo(model: Any) -> Any:
    """A YOLO or RT-DETR model from a weights path (both share Ultralytics' prediction API)."""
    if isinstance(model, (str, Path)):
        if "rtdetr" in Path(str(model)).name.lower():
            from ultralytics import RTDETR

            return RTDETR(str(model))
        from ultralytics import YOLO

        return YOLO(str(model))
    return model


def _box_column(table: Table, column: str | None) -> str:
    candidates = [n for n in table.columns if isinstance(table.schema[n], BoundingBoxes2DSchema)]
    if column:
        return column
    if len(candidates) != 1:
        raise IntegrationError(f"pass gt_column=...: {len(candidates)} box columns in {table.name!r}")
    return candidates[0]


class YOLOPredictor:
    """Calls a YOLO model on a batch's image paths; maps its classes to the Table's by name.

    Mapping by name rather than index matters: a model trained on an ``export_yolo``
    dataset numbers classes 0..K-1, while a COCO-imported Table keeps COCO's ids.
    """

    def __init__(
        self,
        model: Any,
        value_map: dict[int, Any],
        *,
        image_column: str = "image",
        conf: float = 0.25,
        iou: float = 0.7,
        imgsz: int = 640,
        device: Any = None,
    ) -> None:
        self.model = _load_yolo(model)
        by_name = {entry.internal_name: key for key, entry in value_map.items()}
        names = dict(self.model.names)
        unknown = sorted(name for name in names.values() if name not in by_name)
        if unknown:
            raise IntegrationError(
                f"the model predicts classes the Table does not have: {unknown[:5]}"
                f"{' ...' if len(unknown) > 5 else ''}"
            )
        self.class_map = {int(index): by_name[name] for index, name in names.items()}
        self.image_column = image_column
        self.options = {"conf": conf, "iou": iou, "imgsz": imgsz, "device": device, "verbose": False}

    def __call__(self, batch: dict[str, list[Any]]) -> list[dict[str, np.ndarray]]:
        paths = [Url(p).resolved for p in batch[self.image_column]]
        outputs = []
        for result in self.model.predict(paths, **self.options):
            detected = result.boxes
            classes = detected.cls.cpu().numpy().astype(int)
            outputs.append({
                "boxes": detected.xyxy.cpu().numpy().astype(np.float64),
                "scores": detected.conf.cpu().numpy().astype(np.float64),
                "labels": np.array([self.class_map[c] for c in classes], dtype=np.int64),
            })
        return outputs


def collect_detection_metrics(
    model: Any,
    table: Table,
    *,
    run: Run | None = None,
    gt_column: str | None = None,
    epoch: int | None = None,
    split: str | None = None,
    conf: float = 0.25,
    iou: float = 0.7,
    iou_threshold: float = 0.5,
    imgsz: int = 640,
    batch_size: int = 16,
    device: Any = None,
    store_boxes: bool = True,
    predictor: Any = None,
):
    """Predict over ``table`` and write per-box detection metrics to ``run``.

    ``store_boxes=False`` writes only per-image counts and scores, marked ``summary_only``
    so run views skip it; ``predictor`` replaces the YOLO predictor (e.g. for RF-DETR).
    """
    column = _box_column(table, gt_column)
    value_map = table.schema[column].value_map  # type: ignore[attr-defined]
    predictor = predictor or YOLOPredictor(model, value_map, conf=conf, iou=iou, imgsz=imgsz, device=device)
    constants: dict[str, Any] = {}
    if epoch is not None:
        constants["epoch"] = epoch
    if not store_boxes:
        constants["summary_only"] = 1  # constants are stored as columns; an int keeps the type simple
    return collect_metrics(
        table,
        [DetectionMetricsCollector(column, value_map=value_map, iou_threshold=iou_threshold, store_boxes=store_boxes)],
        predictor=predictor,
        run=run,
        split=split,
        constants=constants or None,
        batch_size=batch_size,
    )


_METRIC_NAMES = {
    "metrics/precision(B)": "precision",
    "metrics/recall(B)": "recall",
    "metrics/mAP50(B)": "map50",
    "metrics/mAP50-95(B)": "map50_95",
}


def _scalar_name(key: str) -> str:
    return _METRIC_NAMES.get(key) or re.sub(r"[^0-9a-zA-Z]+", "_", key).strip("_").lower()


def add_granum_callback(
    model: Any,
    tables: dict[str, Table],
    *,
    project_name: str | None = None,
    run_name: str | None = None,
    collect_every: int = 1,
    conf: float = 0.25,
    iou_threshold: float = 0.5,
    final_only: tuple[str, ...] = (),
    parameters: dict[str, Any] | None = None,
    track_learning: bool = False,
) -> None:
    """Log each epoch to a Granum Run and collect per-box metrics from its weights.

    The Run is created when training starts, named after the Ultralytics run unless
    ``run_name`` is given. Metrics are collected every ``collect_every`` epochs and always
    on the final epoch; splits named in ``final_only`` (typically a large training split)
    only on the final epoch. ``parameters`` are recorded on the Run beside the trainer's.
    ``track_learning`` also records every split on every epoch, predicted boxes included,
    so how each image was learned can be shown round by round. For the aerial set that is
    roughly 0.75 KB per image per epoch.
    """
    if collect_every < 1:
        raise IntegrationError("collect_every must be at least 1")
    state: dict[str, Any] = {}

    def on_train_start(trainer: Any) -> None:
        first = next(iter(tables.values()), None)
        project = project_name or (first.project_name if first is not None else "default")
        arguments = {k: v for k, v in vars(trainer.args).items() if isinstance(v, (int, float, str, bool)) and v is not None}
        state["run"] = granum.init(
            project, run_name or Path(str(trainer.save_dir)).name,
            parameters={
                **{k: arguments[k] for k in ("model", "epochs", "batch", "imgsz", "lr0", "optimizer", "seed") if k in arguments},
                **(parameters or {}),
            },
            description=f"Ultralytics training, {trainer.args.epochs} epochs",
        )

    def on_fit_epoch_end(trainer: Any) -> None:
        run: Run = state.get("run") or get_active_run()
        epoch = int(trainer.epoch)
        # Ultralytics fires this once more after training to validate the best weights,
        # with the epoch counter past the end. That is not another round of training.
        if epoch >= int(trainer.epochs):
            return
        scalars: dict[str, Any] = {"epoch": epoch}
        for key, value in (trainer.metrics or {}).items():
            scalars[_scalar_name(key)] = float(value)
        if getattr(trainer, "tloss", None) is not None:
            for key, value in trainer.label_loss_items(trainer.tloss, prefix="train").items():
                scalars[_scalar_name(key)] = float(value)
        granum.log(scalars, run=run)

        final = epoch + 1 >= int(trainer.epochs)
        full = final or (epoch + 1) % collect_every == 0
        if not (full or track_learning):
            return
        weights = Path(str(trainer.last))
        if not weights.exists():
            return
        for split, table in tables.items():
            with_boxes = track_learning or (full and not (split in final_only and not final))
            if not (with_boxes or track_learning):
                continue
            collect_detection_metrics(
                str(weights), table, run=run, epoch=epoch, split=split,
                conf=conf, iou_threshold=iou_threshold, imgsz=int(trainer.args.imgsz),
                store_boxes=with_boxes,
            )

    def on_train_end(trainer: Any) -> None:
        run = state.get("run")
        if run is not None:
            run.set_status("finished")

    model.add_callback("on_train_start", on_train_start)
    model.add_callback("on_fit_epoch_end", on_fit_epoch_end)
    model.add_callback("on_train_end", on_train_end)
