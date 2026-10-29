"""Collect Lightning validation/test outputs without losing sample identity.

``IndexedDataset`` wraps a Table (or transformed Table view). The step returns logits,
or a caller-supplied output transform produces a ``Prediction``. Metrics are computed
against the canonical Table labels; restore predicted geometry to original coordinates.
Distributed evaluation gathers metrics once per epoch and writes only on rank zero.
"""
from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any

try:
    import torch.distributed as dist
    from lightning.pytorch import Callback
except ImportError as exc:
    raise ImportError("install granum[lightning] to use the Lightning integration") from exc

from granum.core.objects.run import Run
from granum.core.objects.table import Table, TableView
from granum.integration._metrics import SAMPLE_ID, SOURCE_URL, MetricAccumulator, log_scalars
from granum.metrics.collect import CollectionError
from granum.metrics.collectors import MetricsCollector
from granum.metrics.predictor import Prediction


class IndexedDataset:
    """A DataLoader-compatible wrapper. Subset and shuffle preserve source row IDs."""
    def __init__(self, source: Table | TableView):
        self.source = source
        self.table = source.table if isinstance(source, TableView) else source

    def __len__(self):
        return len(self.table)

    def __getitem__(self, index):
        sample = self.source[index]
        if not isinstance(sample, dict) or SAMPLE_ID in sample or SOURCE_URL in sample:
            raise CollectionError("IndexedDataset transforms must return a dict without reserved identity columns")
        return {**sample, SAMPLE_ID: index, SOURCE_URL: self.table.url.resolved}


@dataclass
class Evaluation:
    table: Table
    collectors: Sequence[MetricsCollector]
    split: str


class GranumCallback(Callback):
    """Attach one Evaluation per validation/test loader, in the same order as the loaders.

    ``output_transform(outputs, batch)`` defaults to the returned tensor, Prediction,
    or ``outputs['logits']``. Loss-only steps must explicitly return predictions. Sanity
    validation is skipped; repeated distributed padding samples are deduplicated only
    when their metrics agree. This callback never collects changing training weights
    halfway through an epoch. ``close_run`` opts into managing the supplied Run's status.
    """
    def __init__(self, run: Run, *, validation: Sequence[Evaluation] = (),
                 test: Sequence[Evaluation] = (),
                 output_transform: Callable[[Any, Any], Prediction | Any] | None = None,
                 collect_every: int = 1, close_run: bool = False):
        if collect_every < 1:
            raise CollectionError("collect_every must be at least 1")
        self.run = run
        self.evaluations = {"validation": list(validation), "test": list(test)}
        self.output_transform = output_transform
        self.collect_every = collect_every
        self.close_run = close_run
        self._buffers: dict[str, list[MetricAccumulator]] = {}

    def _enabled(self, trainer, stage):
        return not trainer.sanity_checking and (stage == "test" or (trainer.current_epoch + 1) % self.collect_every == 0)

    def _start(self, trainer, stage):
        self._buffers[stage] = [MetricAccumulator(e.table, e.collectors) for e in self.evaluations[stage]]

    def _batch(self, trainer, stage, outputs, batch, dataloader_idx):
        if not self._enabled(trainer, stage) or not self.evaluations[stage]:
            return
        if dataloader_idx >= len(self.evaluations[stage]):
            raise CollectionError(f"no Granum {stage} Table configured for loader {dataloader_idx}")
        buffer = self._buffers[stage][dataloader_idx]
        if not isinstance(batch, dict) or SAMPLE_ID not in batch or SOURCE_URL not in batch:
            raise CollectionError("use IndexedDataset and preserve its identity columns in the collator")
        urls = batch[SOURCE_URL]
        if len(urls) != len(batch[SAMPLE_ID]) or any(url != buffer.table.url.resolved for url in urls):
            raise CollectionError("the loader batch belongs to a different Table version")
        if self.output_transform:
            prediction = self.output_transform(outputs, batch)
        elif isinstance(outputs, dict):
            if "logits" not in outputs:
                raise CollectionError("step outputs need logits, or pass output_transform")
            prediction = outputs["logits"]
        else:
            prediction = outputs
        buffer.add(batch[SAMPLE_ID], prediction)

    def _finish(self, trainer, stage):
        buffers = self._buffers.pop(stage, [])
        if not self._enabled(trainer, stage) or not self.evaluations[stage]:
            return
        payload = [buffer.rows for buffer in buffers]
        distributed = dist.is_available() and dist.is_initialized()
        if trainer.world_size > 1 and not distributed:
            raise CollectionError("this distributed strategy does not expose torch.distributed; use a supported strategy")
        workers = [payload]
        if distributed:
            workers = [None] * dist.get_world_size()
            dist.all_gather_object(workers, payload)
        error = [None]
        if trainer.is_global_zero:
            try:
                for index, (buffer, evaluation) in enumerate(zip(buffers, self.evaluations[stage])):
                    for worker in workers:
                        buffer.merge(worker[index])
                    buffer.write(self.run, split=evaluation.split, epoch=trainer.current_epoch,
                                 iteration=trainer.global_step)
                log_scalars(self.run, {**trainer.callback_metrics, "epoch": trainer.current_epoch,
                                      "iteration": trainer.global_step})
            except Exception as exc:
                if not distributed:
                    raise
                error[0] = str(exc)
        if distributed:
            dist.broadcast_object_list(error, src=0)
            if error[0]:
                raise CollectionError(error[0])

    def on_validation_epoch_start(self, trainer, pl_module):
        self._start(trainer, "validation")

    def on_validation_batch_end(self, trainer, pl_module, outputs, batch, batch_idx, dataloader_idx=0):
        self._batch(trainer, "validation", outputs, batch, dataloader_idx)

    def on_validation_end(self, trainer, pl_module):
        self._finish(trainer, "validation")

    def on_test_epoch_start(self, trainer, pl_module):
        self._start(trainer, "test")

    def on_test_batch_end(self, trainer, pl_module, outputs, batch, batch_idx, dataloader_idx=0):
        self._batch(trainer, "test", outputs, batch, dataloader_idx)

    def on_test_end(self, trainer, pl_module):
        self._finish(trainer, "test")

    def on_fit_end(self, trainer, pl_module):
        if self.close_run and trainer.is_global_zero:
            self.run.set_status("completed")

    def on_exception(self, trainer, pl_module, exception):
        self._buffers.clear()
        if self.close_run and trainer.is_global_zero:
            self.run.set_status("failed")
