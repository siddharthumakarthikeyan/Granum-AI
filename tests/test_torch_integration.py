"""Stage 2 against a real torch model.

The point of these is that the SDK attaches to a training loop it does not own, without
the loop being rewritten.
"""

import numpy as np
import pytest

torch = pytest.importorskip("torch")

import granum  # noqa: E402
from granum import Table  # noqa: E402
from granum.core.objects.run import set_active_run  # noqa: E402
from granum.core.schemas import CategoricalLabelSchema  # noqa: E402
from granum.metrics import (  # noqa: E402
    ClassificationMetricsCollector,
    Predictor,
    collect_metrics,
)


@pytest.fixture(autouse=True)
def clear_active_run():
    set_active_run(None)
    yield
    set_active_run(None)


class TinyNet(torch.nn.Module):
    def __init__(self, in_features: int = 4, num_classes: int = 3) -> None:
        super().__init__()
        self.hidden = torch.nn.Linear(in_features, 8)
        self.relu = torch.nn.ReLU()
        self.head = torch.nn.Linear(8, num_classes)

    def forward(self, x):
        return self.head(self.relu(self.hidden(x)))


def feature_table(n: int = 12) -> Table:
    rng = np.random.default_rng(0)
    features = rng.normal(size=(n, 4)).astype(np.float32)
    labels = (features[:, 0] > 0).astype(int) + (features[:, 1] > 0).astype(int)
    return Table.from_dict_data(
        {"features": features.tolist(), "label": labels.tolist()},
        schema={"label": CategoricalLabelSchema(classes=["low", "mid", "high"])},
        project_name="demo",
        dataset_name="synthetic",
    )


def to_tensor(batch):
    return torch.tensor(np.asarray(batch["features"], dtype=np.float32))


def test_collect_metrics_from_a_real_model():
    table = feature_table(12)
    model = TinyNet()
    granum.init("demo", "torch-exp", parameters={"lr": 1e-3, "epochs": 2})

    metrics = collect_metrics(
        table,
        [ClassificationMetricsCollector(classes=["low", "mid", "high"])],
        predictor=Predictor(model, preprocess=to_tensor),
        split="val",
        constants={"epoch": 0},
        batch_size=5,
    )

    assert len(metrics) == 12
    joined = metrics.join_input()
    assert len(joined) == 12
    assert all(0.0 <= row["confidence"] <= 1.0 for row in joined)
    assert all(row["loss"] >= 0.0 for row in joined)
    assert all("features" in row for row in joined)


def test_predictor_captures_hidden_activations():
    """Forward hooks land now; the embeddings collector that consumes them is Stage 8."""
    table = feature_table(6)
    model = TinyNet()
    hidden_index = [i for i, (name, _) in enumerate(model.named_modules()) if name == "hidden"][0]

    granum.init("demo", "torch-exp")
    with Predictor(model, preprocess=to_tensor, layers=[hidden_index]) as predictor:
        _, batch = next(iter(granum.metrics.iter_batches(table, batch_size=6)))
        prediction = predictor(batch)

    assert hidden_index in prediction.activations
    assert prediction.activations[hidden_index].shape == (6, 8)
    assert prediction.as_numpy().shape == (6, 3)


def test_predictor_rejects_layers_on_a_plain_callable():
    from granum.metrics.predictor import PredictorError

    with pytest.raises(PredictorError):
        Predictor(lambda batch: np.zeros((1, 3)), layers=[0])


def test_predictor_rejects_out_of_range_layer():
    from granum.metrics.predictor import PredictorError

    with pytest.raises(PredictorError):
        Predictor(TinyNet(), layers=[9999])


def test_table_drives_a_dataloader():
    """A Table is a Dataset. No conversion step, no rewrite of the loop."""
    table = feature_table(8)

    def as_tensors(sample):
        return (
            torch.tensor(sample["features"], dtype=torch.float32),
            int(sample["label"]),
        )

    loader = torch.utils.data.DataLoader(table.with_transform(as_tensors), batch_size=4)
    batches = list(loader)
    assert len(batches) == 2
    features, labels = batches[0]
    assert features.shape == (4, 4)
    assert labels.shape == (4,)


def test_three_line_training_loop_produces_a_full_run():
    """The Stage 2 client test: an ordinary loop, three added lines, per-sample metrics."""
    table = feature_table(16)
    model = TinyNet()
    optimizer = torch.optim.SGD(model.parameters(), lr=0.05)
    loss_fn = torch.nn.CrossEntropyLoss()

    def as_tensors(sample):
        return torch.tensor(sample["features"], dtype=torch.float32), int(sample["label"])

    loader = torch.utils.data.DataLoader(
        table.with_transform(as_tensors), batch_size=4, shuffle=True
    )

    run = granum.init("demo", "training", parameters={"lr": 0.05, "epochs": 3})

    for epoch in range(3):
        model.train()
        total = 0.0
        for features, labels in loader:
            optimizer.zero_grad()
            loss = loss_fn(model(features), labels)
            loss.backward()
            optimizer.step()
            total += loss.detach().item()

        granum.log({"epoch": epoch, "train_loss": total / len(loader)})
        collect_metrics(
            table,
            [ClassificationMetricsCollector(classes=["low", "mid", "high"])],
            predictor=Predictor(model, preprocess=to_tensor),
            constants={"epoch": epoch},
            split="train",
        )

    assert len(run.metrics_tables()) == 3
    assert len(run.aggregate_metrics()) == 3
    assert [r["epoch"] for r in run.aggregate_metrics()] == [0, 1, 2]

    # every epoch's metrics still resolve to their samples
    for table_index, metrics in enumerate(run.metrics_tables()):
        joined = metrics.join_input()
        assert len(joined) == 16
        assert joined[0]["epoch"] == table_index
