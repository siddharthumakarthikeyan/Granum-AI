"""Per-sample metrics: collectors, the predictor wrapper, and the collection loop.

Collectors and ``Predictor`` live here rather than on the top-level namespace, which
keeps ``granum.*`` to the short list of nouns and verbs you build with.
"""

from granum.metrics.aggregators import (
    Aggregator,
    MaxAggregator,
    MeanAggregator,
    MinAggregator,
    SumAggregator,
    aggregate_metrics_table,
)
from granum.metrics.collect import CollectionError, collect_metrics, iter_batches
from granum.metrics.collectors import (
    ClassificationMetricsCollector,
    CollectorError,
    FunctionalMetricsCollector,
    MetricsCollector,
)
from granum.metrics.detection import DetectionMetricsCollector
from granum.metrics.dynamics import (
    DynamicsThresholds,
    compute_dynamics,
    epoch_summary,
    training_dynamics,
)
from granum.metrics.predictor import Prediction, Predictor, PredictorError

__all__ = [
    "Aggregator",
    "ClassificationMetricsCollector",
    "CollectionError",
    "CollectorError",
    "DetectionMetricsCollector",
    "DynamicsThresholds",
    "FunctionalMetricsCollector",
    "MaxAggregator",
    "MeanAggregator",
    "MetricsCollector",
    "MinAggregator",
    "Prediction",
    "Predictor",
    "PredictorError",
    "SumAggregator",
    "aggregate_metrics_table",
    "collect_metrics",
    "compute_dynamics",
    "epoch_summary",
    "iter_batches",
    "training_dynamics",
]
