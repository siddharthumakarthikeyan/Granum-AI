"""Metrics collectors.

A collector turns one batch plus the model's output for it into a dict of per-sample
values. Everything else about collection -- iteration order, batching, the join columns,
writing -- is handled for you.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import Any

import numpy as np

from granum.core.schemas import (
    CategoricalLabelSchema,
    ConfidenceSchema,
    Float32Schema,
    FractionSchema,
    ProbabilitySchema,
    Schema,
)
from granum.errors import GranumError
from granum.metrics.predictor import Prediction


class CollectorError(GranumError):
    """A collector was given something it cannot interpret."""


class MetricsCollector:
    """Base class. Subclasses implement ``collect``."""

    def column_schemas(self) -> dict[str, Schema]:
        """Schemas for the columns this collector produces. May be empty."""
        return {}

    def collect(
        self, batch: dict[str, list[Any]], prediction: Prediction | None
    ) -> dict[str, list[Any]]:
        raise NotImplementedError

    def __call__(
        self, batch: dict[str, list[Any]], prediction: Prediction | None
    ) -> dict[str, list[Any]]:
        return self.collect(batch, prediction)


class FunctionalMetricsCollector(MetricsCollector):
    """Wrap any ``(batch, prediction) -> dict[str, list]`` callable."""

    def __init__(
        self,
        fn: Callable[[dict[str, list[Any]], Prediction | None], dict[str, list[Any]]],
        column_schemas: dict[str, Schema] | None = None,
    ) -> None:
        self.fn = fn
        self._schemas = dict(column_schemas or {})

    def column_schemas(self) -> dict[str, Schema]:
        return dict(self._schemas)

    def collect(
        self, batch: dict[str, list[Any]], prediction: Prediction | None
    ) -> dict[str, list[Any]]:
        return self.fn(batch, prediction)


def _softmax(logits: np.ndarray) -> np.ndarray:
    shifted = logits - logits.max(axis=-1, keepdims=True)
    exponentiated = np.exp(shifted)
    return exponentiated / exponentiated.sum(axis=-1, keepdims=True)


def _margin(probabilities: np.ndarray) -> np.ndarray:
    if probabilities.shape[-1] < 2:
        return np.ones(probabilities.shape[0])
    top_two = np.partition(probabilities, -2, axis=-1)[:, -2:]
    return top_two[:, 1] - top_two[:, 0]


class ClassificationMetricsCollector(MetricsCollector):
    """Loss, predicted class, accuracy and confidence for a classifier.

    Expects model output shaped ``(batch, num_classes)``. Logits are assumed unless
    ``already_softmax=True``.
    """

    def __init__(
        self,
        classes: Sequence[str] | None = None,
        *,
        label_column: str = "label",
        already_softmax: bool = False,
        epsilon: float = 1e-12,
    ) -> None:
        self.classes = list(classes) if classes else []
        self.label_column = label_column
        self.already_softmax = already_softmax
        self.epsilon = epsilon

    def column_schemas(self) -> dict[str, Schema]:
        label_schema: Schema = (
            CategoricalLabelSchema(classes=self.classes, writable=False)
            if self.classes
            else Float32Schema()
        )
        return {
            "loss": Float32Schema(description="Per-sample cross-entropy."),
            "predicted": label_schema,
            "confidence": ConfidenceSchema(description="Probability of the predicted class."),
            "accuracy": FractionSchema(description="1.0 when the prediction is correct."),
            "true_probability": ProbabilitySchema(description="Probability of the labelled class."),
            "margin": FractionSchema(description="Top-1 minus top-2 probability; small means unsure."),
        }

    def collect(
        self, batch: dict[str, list[Any]], prediction: Prediction | None
    ) -> dict[str, list[Any]]:
        if prediction is None:
            raise CollectorError(
                "ClassificationMetricsCollector needs model output -- pass a model or "
                "predictor to collect_metrics()"
            )
        if self.label_column not in batch:
            raise CollectorError(
                f"batch has no {self.label_column!r} column; pass label_column= to point "
                f"the collector at the right one. Columns: {list(batch)}"
            )

        logits = prediction.as_numpy()
        if logits.ndim != 2:
            raise CollectorError(
                f"expected model output shaped (batch, num_classes), got {logits.shape}"
            )

        labels = np.asarray(batch[self.label_column], dtype=np.int64)
        if labels.shape[0] != logits.shape[0]:
            raise CollectorError(
                f"model returned {logits.shape[0]} rows for a batch of {labels.shape[0]} "
                f"samples -- the metric-to-sample join would be wrong"
            )

        probabilities = logits if self.already_softmax else _softmax(logits)
        rows = np.arange(labels.shape[0])
        true_probability = probabilities[rows, labels]

        predicted = probabilities.argmax(axis=-1)
        return {
            "loss": (-np.log(np.clip(true_probability, self.epsilon, None))).tolist(),
            "predicted": predicted.astype(np.int32).tolist(),
            "confidence": probabilities[rows, predicted].tolist(),
            "accuracy": (predicted == labels).astype(np.float32).tolist(),
            "true_probability": true_probability.tolist(),
            "margin": _margin(probabilities).tolist(),
        }
