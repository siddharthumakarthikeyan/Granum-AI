import pytest

from granum import TableWriter
from granum.core.schemas import CategoricalLabelSchema, ImageSchema
from granum.errors import SchemaError, TableError


def writer(**kwargs):
    return TableWriter(
        schema={"image": ImageSchema(sample_type="url"),
                "label": CategoricalLabelSchema(classes=["cat", "dog"])},
        project_name="demo",
        dataset_name="train",
        **kwargs,
    )


def test_add_row_then_finalize():
    w = writer()
    w.add_row({"image": "/a.jpg", "label": 0})
    w.add_row({"image": "/b.jpg", "label": 1})
    table = w.finalize()
    assert len(table) == 2
    assert table.columns == ["image", "label", "weight"]
    assert table[1] == {"image": "/b.jpg", "label": 1, "weight": 1.0}


def test_add_batch():
    w = writer()
    w.add_batch({"image": ["/a.jpg", "/b.jpg"], "label": [0, 1]})
    assert len(w) == 2
    assert len(w.finalize()) == 2


def test_weight_defaults_but_can_be_given():
    w = writer()
    w.add_row({"image": "/a.jpg", "label": 0, "weight": 0.5})
    assert w.finalize()[0]["weight"] == 0.5


def test_missing_column_rejected():
    w = writer()
    with pytest.raises(SchemaError):
        w.add_row({"image": "/a.jpg"})


def test_unknown_column_rejected():
    w = writer()
    with pytest.raises(SchemaError):
        w.add_row({"image": "/a.jpg", "label": 0, "surprise": 1})


def test_ragged_batch_rejected():
    w = writer()
    with pytest.raises(TableError):
        w.add_batch({"image": ["/a.jpg", "/b.jpg"], "label": [0]})


def test_empty_writer_cannot_finalize():
    with pytest.raises(TableError):
        writer().finalize()


def test_double_finalize_rejected():
    w = writer()
    w.add_row({"image": "/a.jpg", "label": 0})
    w.finalize()
    with pytest.raises(TableError):
        w.finalize()


def test_empty_schema_rejected():
    with pytest.raises(SchemaError):
        TableWriter(schema={})


def test_context_manager_finalizes():
    with writer() as w:
        w.add_row({"image": "/a.jpg", "label": 0})
    assert w._finalized
