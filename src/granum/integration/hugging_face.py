"""Hugging Face Datasets and Trainer integration with explicit sample identity.

Install ``granum[huggingface]``. Dataset.map/shuffle/select retain the two identity
columns; they are removed from the copy sent to the model. Use ``collect_predictions``
with an existing Trainer, or ``GranumTrainer`` for automatic collection after evaluation.
"""
from __future__ import annotations

from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from typing import Any

try:
    from datasets import Dataset
    from transformers import Trainer
except ImportError as exc:
    raise ImportError("install granum[huggingface] to use the Hugging Face integration") from exc

from granum.core.objects.run import Run
from granum.core.objects.table import WEIGHT_COLUMN, Table
from granum.integration._metrics import (
    SAMPLE_ID,
    SOURCE_URL,
    MetricAccumulator,
    log_scalars,
    validate_ids,
)
from granum.metrics.collect import CollectionError
from granum.metrics.collectors import MetricsCollector
from granum.metrics.predictor import Prediction


def to_dataset(table: Table, *, columns: Sequence[str] | None = None,
               exclude_zero_weights: bool = False) -> Dataset:
    """Copy columns into a Dataset; image paths stay paths for the caller's processor."""
    wanted = list(columns if columns is not None else table.columns)
    if any(name in {SAMPLE_ID, SOURCE_URL} for name in table.columns):
        raise CollectionError("source Table uses reserved Granum identity columns")
    if any(name not in table.columns for name in wanted):
        raise CollectionError("requested Dataset columns do not exist in the Table")
    ids = [i for i in range(len(table)) if not exclude_zero_weights or table[i].get(WEIGHT_COLUMN, 1) != 0]
    data = {name: [table[i][name] for i in ids] for name in wanted}
    data[SAMPLE_ID] = ids
    data[SOURCE_URL] = [table.url.resolved] * len(ids)
    return Dataset.from_dict(data)


def _identity(table: Table, dataset: Dataset) -> list[int]:
    if not isinstance(dataset, Dataset) or not {SAMPLE_ID, SOURCE_URL}.issubset(dataset.column_names):
        raise CollectionError("use to_dataset(table) and preserve its Granum identity columns")
    raw = dataset.with_format(None)
    ids = validate_ids(table, list(raw[SAMPLE_ID]))
    if not ids or any(url != table.url.resolved for url in raw[SOURCE_URL]):
        raise CollectionError("the evaluation Dataset is empty or belongs to a different Table version")
    return ids


def collect_predictions(trainer: Trainer, table: Table, dataset: Dataset,
                        collectors: Iterable[MetricsCollector], *, run: Run,
                        split: str = "eval", epoch: float | None = None,
                        prediction_transform: Callable[[Any], Prediction | Any] | None = None,
                        batch_size: int = 256):
    """Collect a Trainer prediction pass, including shuffled/subset Datasets.

    Call on *every* distributed rank; Trainer gathers predictions and only the world
    process zero writes. The default uses logits (the first item when predictions are a
    tuple). ``prediction_transform`` receives the complete PredictionOutput and can
    return a Prediction with embeddings, decoded masks or task-specific detections.
    Geometry must be mapped back to the original image coordinates before collection.
    """
    ids = _identity(table, dataset)
    accumulator = MetricAccumulator(table, collectors)
    if batch_size < 1:
        raise CollectionError("batch_size must be at least 1")
    if getattr(trainer.args, "prediction_loss_only", False):
        raise CollectionError("prediction_loss_only must be False to collect per-sample predictions")
    result = trainer.predict(dataset.remove_columns([SAMPLE_ID, SOURCE_URL]), metric_key_prefix=split)
    if not trainer.is_world_process_zero():
        return None
    output = prediction_transform(result) if prediction_transform else result.predictions
    if not prediction_transform and isinstance(output, tuple):
        output = output[0]
    prediction = output if isinstance(output, Prediction) else Prediction(output)
    if prediction.outputs is None or len(prediction.outputs) != len(ids):
        raise CollectionError("Trainer prediction count does not match the evaluation sample IDs")
    if any(len(value) != len(ids) for value in prediction.activations.values()):
        raise CollectionError("embedding count does not match the evaluation sample IDs")
    for start in range(0, len(ids), batch_size):
        stop = start + batch_size
        accumulator.add(ids[start:stop], Prediction(prediction.outputs[start:stop],
                        {key: values[start:stop] for key, values in prediction.activations.items()}))
    metrics = accumulator.write(run, split=split, epoch=epoch, iteration=trainer.state.global_step)
    log_scalars(run, {**result.metrics, **({"epoch": epoch} if epoch is not None else {})})
    return metrics


@dataclass
class Evaluation:
    table: Table
    dataset: Dataset
    collectors: Sequence[MetricsCollector]
    prediction_transform: Callable[[Any], Prediction | Any] | None = None


class GranumTrainer(Trainer):
    """Trainer that logs aggregate scalars and collects configured Tables after evaluate.

    This adds a prediction pass on collection evaluations. The ordinary training and
    validation datasets, loss and compute_metrics functions remain controlled by Trainer.
    The supplied Run stays open so callers can attach further experiments or close it.
    """
    def __init__(self, *args, granum_run: Run, granum_evaluations: dict[str, Evaluation],
                 collect_every: int = 1, **kwargs):
        if collect_every < 1:
            raise CollectionError("collect_every must be at least 1")
        self.granum_run = granum_run
        self.granum_evaluations = dict(granum_evaluations)
        self.granum_collect_every = collect_every
        self._granum_evaluations = 0
        self._granum_evaluating = False
        for evaluation in self.granum_evaluations.values():
            _identity(evaluation.table, evaluation.dataset)
        super().__init__(*args, **kwargs)

    def log(self, logs, *args, **kwargs):
        result = super().log(logs, *args, **kwargs)
        if self.is_world_process_zero():
            log_scalars(self.granum_run, {**logs, "iteration": self.state.global_step})
        return result

    def evaluate(self, *args, **kwargs):
        if self._granum_evaluating:
            return super().evaluate(*args, **kwargs)
        self._granum_evaluating = True
        try:
            result = super().evaluate(*args, **kwargs)
            self._granum_evaluations += 1
            if self._granum_evaluations % self.granum_collect_every == 0:
                for split, evaluation in self.granum_evaluations.items():
                    collect_predictions(self, evaluation.table, evaluation.dataset, evaluation.collectors,
                                        run=self.granum_run, split=split, epoch=self.state.epoch,
                                        prediction_transform=evaluation.prediction_transform)
            return result
        finally:
            self._granum_evaluating = False
