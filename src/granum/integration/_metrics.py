"""Shared, identity-preserving collection for framework evaluation loops."""
from __future__ import annotations

from collections.abc import Iterable, Sequence
from numbers import Integral, Real
from typing import Any

import numpy as np

from granum.core.objects.run import EXAMPLE_ID_COLUMN, Run
from granum.core.objects.table import Table
from granum.core.schemas import EpochSchema, Float32Schema, StringSchema
from granum.metrics.collect import CollectionError
from granum.metrics.collectors import MetricsCollector
from granum.metrics.predictor import Prediction

SAMPLE_ID = "__granum_example_id"
SOURCE_URL = "__granum_table_url"


def validate_ids(table: Table, ids: Sequence[Any]) -> list[int]:
    if hasattr(ids, "detach"):
        ids = ids.detach().cpu().tolist()
    result = []
    for value in ids:
        if isinstance(value, (bool, np.bool_)) or not isinstance(value, Integral) or not 0 <= value < len(table):
            raise CollectionError("sample IDs must be integer row indices in the source Table")
        result.append(int(value))
    if len(set(result)) != len(result):
        raise CollectionError("duplicate sample IDs in an evaluation batch")
    return result


def equivalent(left: Any, right: Any) -> bool:
    """Distributed samplers can repeat a sample to pad a final batch."""
    if isinstance(left, dict) and isinstance(right, dict):
        return left.keys() == right.keys() and all(equivalent(left[k], right[k]) for k in left)
    if isinstance(left, (list, tuple)) and isinstance(right, (list, tuple)):
        return len(left) == len(right) and all(equivalent(a, b) for a, b in zip(left, right))
    if isinstance(left, Real) and isinstance(right, Real):
        return bool(np.isclose(left, right, rtol=1e-5, atol=1e-7, equal_nan=False))
    return left == right


class MetricAccumulator:
    def __init__(self, table: Table, collectors: Iterable[MetricsCollector]) -> None:
        self.table = table
        self.collectors = list(collectors)
        if not self.collectors:
            raise CollectionError("pass at least one metrics collector")
        self.rows: dict[int, dict[str, Any]] = {}
        self.columns: set[str] | None = None

    def add(self, ids: Sequence[int], prediction: Any) -> None:
        ids = validate_ids(self.table, ids)
        if not ids:
            return
        samples = [self.table[i] for i in ids]
        batch = {column: [sample[column] for sample in samples] for column in self.table.columns}
        prediction = prediction if isinstance(prediction, Prediction) else Prediction(prediction)
        produced: dict[str, list[Any]] = {}
        for collector in self.collectors:
            values = collector(batch, prediction)
            if not isinstance(values, dict):
                raise CollectionError("a collector must return a dictionary of metric columns")
            for name, column in values.items():
                if name in {EXAMPLE_ID_COLUMN, "epoch", "iteration", "split"} or name in produced:
                    raise CollectionError(f"duplicate or reserved metric column: {name}")
                if len(column) != len(ids):
                    raise CollectionError(f"metric {name!r} does not have one value per sample")
                produced[name] = list(column)
        if not produced:
            raise CollectionError("collectors produced no metrics")
        names = set(produced)
        if self.columns is not None and names != self.columns:
            raise CollectionError("metric columns changed between evaluation batches")
        self.columns = names
        self.merge({i: {name: values[j] for name, values in produced.items()} for j, i in enumerate(ids)})

    def merge(self, rows: dict[int, dict[str, Any]]) -> None:
        validate_ids(self.table, list(rows))
        for i, row in rows.items():
            if self.columns is not None and set(row) != self.columns:
                raise CollectionError("metric columns differ between workers")
            if i in self.rows and not equivalent(self.rows[i], row):
                raise CollectionError(f"conflicting metrics for repeated sample {i}; use deterministic evaluation")
            self.columns = set(row)
            self.rows[i] = row

    def write(self, run: Run, *, split: str, epoch: float | None = None, iteration: int | None = None):
        if not self.rows:
            raise CollectionError("no evaluation samples were collected")
        ids = sorted(self.rows)
        data = {name: [self.rows[i][name] for i in ids] for name in self.rows[ids[0]]}
        schemas = {}
        # Some collectors learn their embedding width from the first batch.
        for collector in self.collectors:
            schemas.update(collector.column_schemas())
        data[EXAMPLE_ID_COLUMN] = ids
        data["split"] = [split] * len(ids)
        schemas["split"] = StringSchema()
        if epoch is not None:
            if not np.isfinite(epoch):
                raise CollectionError("epoch must be finite")
            data["epoch"] = [epoch] * len(ids)
            schemas["epoch"] = EpochSchema() if float(epoch).is_integer() else Float32Schema()
        if iteration is not None:
            data["iteration"] = [iteration] * len(ids)
            schemas["iteration"] = EpochSchema()
        return run.add_metrics(data, foreign_table_url=self.table.url, schema=schemas,
                               constants={"split": split})


def log_scalars(run: Run, values: dict[str, Any]) -> None:
    scalars = {}
    for name, value in values.items():
        if hasattr(value, "numel") and value.numel() == 1:
            value = value.detach().cpu().item()
        if isinstance(value, Real) and np.isfinite(value):
            scalars[name] = float(value)
    if scalars:
        run.log(scalars)
