import numpy as np
import pytest

import granum
from granum import Table
from granum.core.objects.run import set_active_run
from granum.core.schemas import CategoricalLabelSchema, ImageSchema
from granum.metrics import (
    ClassificationMetricsCollector,
    CollectionError,
    FunctionalMetricsCollector,
    MeanAggregator,
    Predictor,
    aggregate_metrics_table,
    collect_metrics,
    iter_batches,
)
from granum.metrics.collectors import CollectorError


@pytest.fixture(autouse=True)
def clear_active_run():
    set_active_run(None)
    yield
    set_active_run(None)


def make_table(n: int = 6) -> Table:
    return Table.from_dict_data(
        {"image": [f"/data/{i}.jpg" for i in range(n)], "label": [i % 3 for i in range(n)]},
        schema={"image": ImageSchema(sample_type="url"),
                "label": CategoricalLabelSchema(classes=["cat", "dog", "bird"])},
        project_name="demo",
        dataset_name="train",
    )


# -- batching ---------------------------------------------------------------


def test_iter_batches_preserves_canonical_order():
    table = make_table(5)
    seen: list[int] = []
    for ids, batch in iter_batches(table, batch_size=2):
        seen.extend(ids)
        assert len(batch["label"]) == len(ids)
    assert seen == [0, 1, 2, 3, 4]


def test_iter_batches_excludes_zero_weights():
    table = make_table(4).set_weights({1: 0.0, 3: 0.0})
    ids = [i for chunk, _ in iter_batches(table, 2, exclude_zero_weights=True) for i in chunk]
    assert ids == [0, 2]


def test_iter_batches_rejects_bad_batch_size():
    with pytest.raises(CollectionError):
        list(iter_batches(make_table(2), batch_size=0))


def test_iter_batches_over_a_view_keeps_table_indices():
    table = make_table(4)
    view = table.with_transform(lambda s: {"label": s["label"]})
    ids = [i for chunk, _ in iter_batches(view, 2) for i in chunk]
    assert ids == [0, 1, 2, 3]


# -- collect_metrics --------------------------------------------------------


def constant_logits(batch):
    """A stand-in model: always predicts class 0 with high confidence."""
    size = len(batch["label"])
    return np.tile(np.array([5.0, 0.0, 0.0], dtype=np.float32), (size, 1))


def test_collect_metrics_end_to_end():
    table = make_table(6)
    granum.init("demo", "exp")
    metrics = collect_metrics(
        table,
        [ClassificationMetricsCollector(classes=["cat", "dog", "bird"])],
        predictor=Predictor(constant_logits),
        split="val",
        constants={"epoch": 0},
        batch_size=4,
    )
    assert len(metrics) == 6
    assert set(metrics.columns) >= {
        "example_id", "loss", "predicted", "confidence", "accuracy", "epoch", "split"
    }
    joined = metrics.join_input()
    assert joined[0]["image"] == "/data/0.jpg"
    # every sample whose true label is 0 is correct; the rest are not
    assert [round(r["accuracy"]) for r in joined] == [1, 0, 0, 1, 0, 0]


def test_collect_metrics_requires_a_run():
    set_active_run(None)
    with pytest.raises(CollectionError):
        collect_metrics(make_table(2), [FunctionalMetricsCollector(lambda b, p: {"x": [1, 1]})])


def test_collect_metrics_requires_a_collector():
    granum.init("demo", "exp")
    with pytest.raises(CollectionError):
        collect_metrics(make_table(2), [])


def test_collect_metrics_catches_length_mismatch():
    """A collector returning the wrong number of values must not silently misalign."""
    granum.init("demo", "exp")
    bad = FunctionalMetricsCollector(lambda batch, pred: {"x": [1]})
    with pytest.raises(CollectionError) as exc:
        collect_metrics(make_table(4), [bad], batch_size=2)
    assert "line up" in str(exc.value)


def test_collect_metrics_catches_non_dict_result():
    granum.init("demo", "exp")
    bad = FunctionalMetricsCollector(lambda batch, pred: [1, 2])
    with pytest.raises(CollectionError):
        collect_metrics(make_table(2), [bad], batch_size=2)


def test_collect_metrics_on_empty_selection():
    granum.init("demo", "exp")
    table = make_table(2).set_weights(0.0)
    with pytest.raises(CollectionError):
        collect_metrics(
            table,
            [FunctionalMetricsCollector(lambda b, p: {"x": [1] * len(b["label"])})],
            exclude_zero_weights=True,
        )


def test_collect_metrics_respects_zero_weights():
    table = make_table(4).set_weights({1: 0.0})
    granum.init("demo", "exp")
    metrics = collect_metrics(
        table,
        [FunctionalMetricsCollector(lambda b, p: {"x": [1.0] * len(b["label"])})],
        exclude_zero_weights=True,
    )
    assert [row["example_id"] for row in metrics] == [0, 2, 3]


def test_functional_collector_receives_batch_and_prediction():
    granum.init("demo", "exp")
    seen = {}

    def fn(batch, prediction):
        seen["columns"] = sorted(batch)
        seen["has_prediction"] = prediction is not None
        return {"n": [len(batch["label"])] * len(batch["label"])}

    collect_metrics(make_table(2), [FunctionalMetricsCollector(fn)],
                    predictor=Predictor(constant_logits))
    assert seen["has_prediction"] is True
    assert "image" in seen["columns"]


def test_model_argument_is_wrapped_automatically():
    granum.init("demo", "exp")
    metrics = collect_metrics(
        make_table(3),
        [ClassificationMetricsCollector(classes=["cat", "dog", "bird"])],
        model=constant_logits,
    )
    assert len(metrics) == 3


# -- collectors -------------------------------------------------------------


def test_classification_collector_needs_predictions():
    granum.init("demo", "exp")
    with pytest.raises(CollectorError):
        collect_metrics(make_table(2), [ClassificationMetricsCollector()])


def test_classification_collector_reports_missing_label_column():
    granum.init("demo", "exp")
    table = Table.from_dict_data({"x": [1, 2]}, project_name="demo", dataset_name="d")
    with pytest.raises(CollectorError) as exc:
        collect_metrics(
            table,
            [ClassificationMetricsCollector(label_column="label")],
            predictor=Predictor(lambda b: np.zeros((len(b["x"]), 3), dtype=np.float32)),
        )
    assert "label_column" in str(exc.value)


def test_classification_collector_detects_batch_size_mismatch():
    granum.init("demo", "exp")
    with pytest.raises(CollectorError) as exc:
        collect_metrics(
            make_table(4),
            [ClassificationMetricsCollector()],
            predictor=Predictor(lambda b: np.zeros((2, 3), dtype=np.float32)),
            batch_size=4,
        )
    assert "join would be wrong" in str(exc.value)


def test_classification_loss_is_correct():
    """A confident correct prediction has near-zero loss; a confident wrong one does not."""
    granum.init("demo", "exp")
    table = Table.from_dict_data(
        {"label": [0, 1]},
        schema={"label": CategoricalLabelSchema(classes=["a", "b"])},
        project_name="demo", dataset_name="d",
    )
    logits = np.array([[10.0, 0.0], [10.0, 0.0]], dtype=np.float32)
    metrics = collect_metrics(
        table, [ClassificationMetricsCollector(classes=["a", "b"])],
        predictor=Predictor(lambda b: logits), batch_size=2,
    )
    rows = list(metrics)
    assert rows[0]["loss"] < 0.001         # correct and confident
    assert rows[1]["loss"] > 5.0           # wrong and confident
    assert rows[0]["accuracy"] == 1.0 and rows[1]["accuracy"] == 0.0
    assert rows[0]["confidence"] > 0.99


# -- aggregation ------------------------------------------------------------


def test_aggregate_metrics_table():
    granum.init("demo", "exp")
    metrics = collect_metrics(
        make_table(6),
        [ClassificationMetricsCollector(classes=["cat", "dog", "bird"])],
        predictor=Predictor(constant_logits),
    )
    summary = aggregate_metrics_table(metrics, [MeanAggregator()])
    assert "loss" in summary and "accuracy" in summary
    assert summary["accuracy"] == pytest.approx(2 / 6, abs=1e-6)
    assert "example_id" not in summary
