"""Aggregators reduce a per-sample metrics column to a single number."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

import numpy as np


class Aggregator:
    """Base class. Subclasses implement ``aggregate``."""

    name = "aggregate"

    def aggregate(self, values: Iterable[Any]) -> Any:
        raise NotImplementedError

    def __call__(self, values: Iterable[Any]) -> Any:
        return self.aggregate(values)


class MeanAggregator(Aggregator):
    name = "mean"

    def aggregate(self, values: Iterable[Any]) -> float:
        array = np.asarray([v for v in values if v is not None], dtype=np.float64)
        return float(array.mean()) if array.size else float("nan")


class SumAggregator(Aggregator):
    name = "sum"

    def aggregate(self, values: Iterable[Any]) -> float:
        array = np.asarray([v for v in values if v is not None], dtype=np.float64)
        return float(array.sum()) if array.size else 0.0


class MinAggregator(Aggregator):
    name = "min"

    def aggregate(self, values: Iterable[Any]) -> float:
        array = np.asarray([v for v in values if v is not None], dtype=np.float64)
        return float(array.min()) if array.size else float("nan")


class MaxAggregator(Aggregator):
    name = "max"

    def aggregate(self, values: Iterable[Any]) -> float:
        array = np.asarray([v for v in values if v is not None], dtype=np.float64)
        return float(array.max()) if array.size else float("nan")


DEFAULT_AGGREGATORS: tuple[Aggregator, ...] = (MeanAggregator(),)


def aggregate_metrics_table(table, aggregators: Iterable[Aggregator] | None = None
                            ) -> dict[str, float]:
    """Reduce every numeric column of a metrics table to scalars."""
    from granum.core.schemas import EmbeddingSchema

    chosen = list(aggregators or DEFAULT_AGGREGATORS)
    arrow = table.to_arrow()
    out: dict[str, float] = {}
    for name in table.columns:
        schema = table.schema[name]
        if isinstance(schema, EmbeddingSchema) or name == "example_id":
            continue
        values = arrow.column(name).to_pylist()
        if not values or not isinstance(
            next((v for v in values if v is not None), None), (int, float)
        ):
            continue
        for aggregator in chosen:
            key = name if aggregator.name == "mean" else f"{name}_{aggregator.name}"
            out[key] = aggregator(values)
    return out
