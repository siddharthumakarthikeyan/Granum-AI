"""Actual, small framework runs: shuffled joins, embeddings and training callbacks."""
import numpy as np
import pytest

import granum
from granum import Table
from granum.core.schemas import CategoricalLabelSchema
from granum.integration._metrics import SAMPLE_ID, SOURCE_URL, MetricAccumulator
from granum.metrics import ClassificationMetricsCollector, EmbeddingsMetricsCollector
from granum.metrics.collect import CollectionError
from granum.metrics.predictor import Prediction


def source_table(name="features"):
    return Table.from_dict_data(
        {"features": [[3., 0.], [0., 4.], [2., 0.], [0., 1.], [5., 0.]],
         "label": [0, 1, 0, 1, 0]},
        schema={"label": CategoricalLabelSchema(classes=["a", "b"])},
        project_name="frameworks", dataset_name=name,
    )


def test_indexed_collection_rejects_corrupt_identity_and_conflicting_duplicates():
    table = source_table()
    collector = MetricAccumulator(table, [ClassificationMetricsCollector(["a", "b"])])
    collector.add([2, 0], np.array([[2, 0], [3, 0]]))
    collector.merge(dict(collector.rows))  # distributed sampler padding is safe to deduplicate
    with pytest.raises(CollectionError, match="conflicting"):
        collector.add([2], np.array([[0, 2]]))
    for ids in ([0, 0], [-1], [len(table)], [True], [0.0]):
        with pytest.raises(CollectionError):
            collector.add(ids, np.ones((len(ids), 2)))


def test_hugging_face_predictions_and_embeddings_follow_shuffled_ids(tmp_path):
    torch = pytest.importorskip("torch")
    pytest.importorskip("transformers")
    pytest.importorskip("datasets")
    from transformers import Trainer, TrainingArguments

    from granum.integration.hugging_face import collect_predictions, to_dataset

    class Model(torch.nn.Module):
        def forward(self, features, labels=None):
            logits = features.float()
            return {"loss": torch.nn.functional.cross_entropy(logits, labels), "logits": logits,
                    "hidden_states": logits * 2}

    table = source_table()
    dataset = to_dataset(table, columns=["features", "label"]).select([4, 1, 3])
    run = granum.init("frameworks", "huggingface")
    trainer = Trainer(model=Model(), args=TrainingArguments(
        output_dir=str(tmp_path / "hf"), per_device_eval_batch_size=2, report_to="none",
        use_cpu=True, disable_tqdm=True,
    ))
    result = collect_predictions(
        trainer, table, dataset, [ClassificationMetricsCollector(["a", "b"]), EmbeddingsMetricsCollector(0)],
        run=run, epoch=0.5, batch_size=2,
        prediction_transform=lambda result: Prediction(result.predictions[0], {0: result.predictions[1]}),
    )
    rows = result.join_input()
    assert [row["example_id"] for row in rows] == [1, 3, 4]
    assert [row["accuracy"] for row in rows] == [1., 1., 1.]
    assert [row["epoch"] for row in rows] == [0.5] * 3
    np.testing.assert_allclose([row["embedding"] for row in rows], [[0, 8], [0, 2], [10, 0]])
    assert result.schema["embedding"].shape == (2,)
    assert SAMPLE_ID in dataset.column_names and SOURCE_URL in dataset.column_names
    with pytest.raises(CollectionError, match="different Table"):
        collect_predictions(trainer, source_table("other"), dataset,
                            [ClassificationMetricsCollector()], run=run)
    with pytest.raises(CollectionError, match="duplicate"):
        collect_predictions(trainer, table, dataset.select([0, 0]), [ClassificationMetricsCollector()], run=run)


def test_hugging_face_trainer_collects_after_actual_training(tmp_path):
    torch = pytest.importorskip("torch")
    pytest.importorskip("transformers")
    pytest.importorskip("datasets")
    from transformers import TrainingArguments

    from granum.integration.hugging_face import Evaluation, GranumTrainer, to_dataset

    class Model(torch.nn.Module):
        def __init__(self):
            super().__init__()
            self.head = torch.nn.Linear(2, 2)

        def forward(self, features, labels=None):
            logits = self.head(features.float())
            return {"loss": torch.nn.functional.cross_entropy(logits, labels), "logits": logits}

    table = source_table()
    dataset = to_dataset(table, columns=["features", "label"])
    run = granum.init("frameworks", "hf-training")
    trainer = GranumTrainer(
        model=Model(), train_dataset=dataset, eval_dataset=dataset,
        args=TrainingArguments(output_dir=str(tmp_path / "hf-training"), max_steps=2,
                               per_device_train_batch_size=2, per_device_eval_batch_size=2,
                               eval_strategy="steps", eval_steps=1, save_strategy="no",
                               report_to="none", use_cpu=True, disable_tqdm=True),
        granum_run=run,
        granum_evaluations={"validation": Evaluation(table, dataset.shuffle(seed=7), [ClassificationMetricsCollector()])},
    )
    trainer.train()
    assert len(run.metrics_tables()) == 2
    for result in run.metrics_tables():
        assert [row["example_id"] for row in result] == list(range(len(table)))
        assert all(np.isfinite(row["loss"]) for row in result)
    assert run.aggregate_metrics()


def test_lightning_callback_collects_actual_training_and_shuffled_validation(tmp_path):
    torch = pytest.importorskip("torch")
    pl = pytest.importorskip("lightning.pytorch")
    from torch.utils.data import DataLoader, Subset

    from granum.integration.lightning import Evaluation, GranumCallback, IndexedDataset

    class Model(pl.LightningModule):
        def __init__(self):
            super().__init__()
            self.head = torch.nn.Linear(2, 2)

        def configure_optimizers(self):
            return torch.optim.SGD(self.parameters(), lr=0.01)

        def training_step(self, batch, batch_idx):
            return torch.nn.functional.cross_entropy(self.head(batch["features"]), batch["label"])

        def validation_step(self, batch, batch_idx):
            logits = self.head(batch["features"])
            self.log("val_loss", torch.nn.functional.cross_entropy(logits, batch["label"]), batch_size=len(logits))
            return {"logits": logits}

        def test_step(self, batch, batch_idx):
            return batch["features"]  # deterministic logits test the shuffled join

    table = source_table()
    view = table.with_transform(lambda row: {
        "features": torch.tensor(row["features"], dtype=torch.float32), "label": row["label"],
    })
    dataset = IndexedDataset(view)
    training = DataLoader(dataset, batch_size=2, shuffle=True)
    validation = DataLoader(Subset(dataset, [3, 0, 4]), batch_size=2)
    run = granum.init("frameworks", "lightning")
    callback = GranumCallback(run, validation=[Evaluation(table, [ClassificationMetricsCollector()], "val")],
                              test=[Evaluation(table, [ClassificationMetricsCollector()], "test")])
    trainer = pl.Trainer(accelerator="cpu", devices=1, max_epochs=2, logger=False,
                         enable_checkpointing=False, enable_progress_bar=False, enable_model_summary=False,
                         default_root_dir=str(tmp_path), callbacks=[callback], num_sanity_val_steps=1)
    model = Model()
    trainer.fit(model, train_dataloaders=training, val_dataloaders=validation)
    assert len(run.metrics_tables()) == 2  # sanity check produces no extra table
    trainer.test(model, dataloaders=validation)
    results = run.metrics_tables()
    assert len(results) == 3
    for result in results:
        assert [row["example_id"] for row in result] == [0, 3, 4]
    assert [row["accuracy"] for row in results[-1]] == [1., 1., 1.]


def test_lightning_distributed_padding_writes_each_sample_once(tmp_path):
    import sys

    if sys.platform != "linux":
        pytest.skip("CPU fork-based distributed verification runs on Linux")
    torch = pytest.importorskip("torch")
    pl = pytest.importorskip("lightning.pytorch")
    from torch.utils.data import DataLoader

    from granum.integration.lightning import Evaluation, GranumCallback, IndexedDataset

    class Model(pl.LightningModule):
        def __init__(self):
            super().__init__()
            self.scale = torch.nn.Parameter(torch.ones(()))

        def validation_step(self, batch, batch_idx):
            return batch["features"] * self.scale

    table = source_table()
    dataset = IndexedDataset(table.with_transform(lambda row: {
        "features": torch.tensor(row["features"], dtype=torch.float32), "label": row["label"],
    }))
    run = granum.init("frameworks", "distributed")
    callback = GranumCallback(run, validation=[Evaluation(table, [ClassificationMetricsCollector()], "val")])
    trainer = pl.Trainer(accelerator="cpu", devices=2, strategy="ddp_fork", logger=False,
                         enable_checkpointing=False, enable_progress_bar=False, enable_model_summary=False,
                         default_root_dir=str(tmp_path), callbacks=[callback])
    trainer.validate(Model(), dataloaders=DataLoader(dataset, batch_size=2))
    metrics = run.metrics_tables()
    assert len(metrics) == 1
    assert [row["example_id"] for row in metrics[0]] == list(range(5))
    assert [row["accuracy"] for row in metrics[0]] == [1.] * 5
