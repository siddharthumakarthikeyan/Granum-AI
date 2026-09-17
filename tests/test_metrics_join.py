"""The join contract. If these fail, a metric no longer resolves to its sample."""

import pytest

import granum
from granum import MetricsTableWriter, Table
from granum.core.objects.run import RunError, set_active_run
from granum.core.schemas import CategoricalLabelSchema, ImageSchema
from granum.core.url import Url


@pytest.fixture(autouse=True)
def clear_active_run():
    set_active_run(None)
    yield
    set_active_run(None)


def input_table(n: int = 5) -> Table:
    return Table.from_dict_data(
        {"image": [f"/data/{i}.jpg" for i in range(n)], "label": [i % 2 for i in range(n)]},
        schema={"image": ImageSchema(sample_type="url"),
                "label": CategoricalLabelSchema(classes=["cat", "dog"])},
        project_name="demo",
        dataset_name="train",
    )


# -- add_metrics ------------------------------------------------------------


def test_add_metrics_writes_a_joined_table():
    table = input_table(3)
    run = granum.init("demo", "exp")
    metrics = run.add_metrics(
        {"example_id": [0, 1, 2], "loss": [0.1, 0.9, 0.3]},
        foreign_table_url=table.url,
    )
    assert len(metrics) == 3
    assert metrics.foreign_table_url == table.url
    assert metrics.input_table().url == table.url


def test_metrics_without_example_id_are_refused():
    table = input_table(3)
    run = granum.init("demo", "exp")
    with pytest.raises(RunError) as exc:
        run.add_metrics({"loss": [0.1, 0.2, 0.3]}, foreign_table_url=table.url)
    assert "example_id" in str(exc.value)


def test_ragged_metrics_refused():
    run = granum.init("demo", "exp")
    with pytest.raises(RunError):
        run.add_metrics({"example_id": [0, 1], "loss": [0.1]})


def test_join_resolves_metric_to_sample():
    """The operation the product exists for."""
    table = input_table(5)
    run = granum.init("demo", "exp")
    run.add_metrics(
        {"example_id": [0, 1, 2, 3, 4], "loss": [0.1, 2.4, 0.2, 0.05, 1.9]},
        foreign_table_url=table.url,
    )
    joined = run.joined()
    assert len(joined) == 5

    worst = sorted(joined, key=lambda r: -r["loss"])[0]
    assert worst["loss"] == pytest.approx(2.4)
    assert worst["example_id"] == 1
    assert worst["image"] == str(Url("/data/1.jpg"))   # the metric resolved to its image
    assert worst["label"] == 1


def test_join_detects_a_broken_link():
    table = input_table(3)
    run = granum.init("demo", "exp")
    metrics = run.add_metrics(
        {"example_id": [0, 1, 99], "loss": [0.1, 0.2, 0.3]}, foreign_table_url=table.url
    )
    with pytest.raises(RunError) as exc:
        metrics.join_input()
    assert "out of range" in str(exc.value)


def test_metrics_table_reopens_with_its_link():
    from granum import MetricsTable

    table = input_table(2)
    run = granum.init("demo", "exp")
    written = run.add_metrics(
        {"example_id": [0, 1], "loss": [0.1, 0.2]}, foreign_table_url=table.url
    )
    reopened = MetricsTable.from_url(written.url)
    assert reopened.foreign_table_url == table.url
    assert reopened.join_input()[0]["image"] == str(Url("/data/0.jpg"))


def test_metrics_are_stored_as_float32():
    """Metrics columns are float32 by design -- half the storage, ample precision."""
    table = input_table(1)
    run = granum.init("demo", "exp")
    metrics = run.add_metrics(
        {"example_id": [0], "loss": [2.4]}, foreign_table_url=table.url
    )
    assert metrics.schema["loss"].kind == "float32"
    assert metrics[0]["loss"] == pytest.approx(2.4, rel=1e-6)


def test_metric_schemas_inferred_by_name():
    table = input_table(2)
    run = granum.init("demo", "exp")
    metrics = run.add_metrics(
        {"example_id": [0, 1], "confidence": [0.9, 0.8], "loss": [0.1, 0.2]},
        foreign_table_url=table.url,
    )
    assert metrics.schema["confidence"].kind == "confidence"
    assert metrics.schema["example_id"].kind == "example_id"


def test_run_lists_its_metrics_tables():
    table = input_table(2)
    run = granum.init("demo", "exp")
    for epoch in range(3):
        run.add_metrics(
            {"example_id": [0, 1], "loss": [0.1, 0.2]},
            foreign_table_url=table.url,
            constants={"epoch": epoch},
        )
    tables = run.metrics_tables()
    assert len(tables) == 3
    assert [t.name for t in tables] == ["metrics_0000", "metrics_0001", "metrics_0002"]


# -- MetricsTableWriter -----------------------------------------------------


def test_writer_streams_batches():
    table = input_table(4)
    run = granum.init("demo", "exp")
    with MetricsTableWriter(foreign_table_url=table.url) as writer:
        writer.add_batch({"example_id": [0, 1], "loss": [0.5, 0.6]})
        writer.add_batch({"example_id": [2, 3], "loss": [0.7, 0.8]})
    assert writer.table is not None
    assert len(writer.table) == 4
    assert run.metrics_tables()[0].join_input()[3]["image"] == str(Url("/data/3.jpg"))


def test_writer_requires_example_id():
    table = input_table(2)
    granum.init("demo", "exp")
    writer = MetricsTableWriter(foreign_table_url=table.url)
    with pytest.raises(granum.SchemaError) as exc:
        writer.add_batch({"loss": [0.1, 0.2]})
    assert "example_id" in str(exc.value)


def test_writer_rejects_inconsistent_columns():
    table = input_table(2)
    granum.init("demo", "exp")
    writer = MetricsTableWriter(foreign_table_url=table.url)
    writer.add_batch({"example_id": [0], "loss": [0.1]})
    with pytest.raises(granum.SchemaError):
        writer.add_batch({"example_id": [1], "iou": [0.4]})


def test_writer_rejects_ragged_batch():
    granum.init("demo", "exp")
    writer = MetricsTableWriter()
    with pytest.raises(granum.TableError):
        writer.add_batch({"a": [1, 2], "b": [1]})


def test_writer_without_a_run_is_an_error():
    set_active_run(None)
    writer = MetricsTableWriter()
    writer.add_batch({"a": [1]})
    with pytest.raises(granum.TableError):
        writer.finalize()


def test_writer_double_finalize_rejected():
    granum.init("demo", "exp")
    writer = MetricsTableWriter()
    writer.add_batch({"a": [1]})
    writer.finalize()
    with pytest.raises(granum.TableError):
        writer.finalize()
