import pyarrow as pa
import pytest

from granum.core.schemas import (
    CategoricalLabelSchema,
    EmbeddingSchema,
    ImageSchema,
    SampleWeightSchema,
    StringSchema,
    TableSchema,
    ValueMapEntry,
    schema_from_dict,
)
from granum.errors import SchemaError


def test_arrow_types():
    assert CategoricalLabelSchema(classes=["a"]).arrow_type() == pa.int32()
    assert ImageSchema().arrow_type() == pa.string()
    assert SampleWeightSchema().arrow_type() == pa.float32()
    assert EmbeddingSchema(shape=(8,)).arrow_type() == pa.list_(pa.float32())


def test_categorical_names_and_indices():
    schema = CategoricalLabelSchema(classes=["cat", "dog", "bird"])
    assert schema.classes == ["cat", "dog", "bird"]
    assert schema.name_of(1) == "dog"
    assert schema.index_of("bird") == 2
    assert schema.name_of(99) is None


def test_categorical_rejects_both_forms():
    with pytest.raises(SchemaError):
        CategoricalLabelSchema(classes=["a"], value_map={0: "b"})


def test_schema_serialization_roundtrip():
    original = CategoricalLabelSchema(
        value_map={0: ValueMapEntry("cat", "Cat", "#ff0000"), 1: ValueMapEntry("dog")}
    )
    restored = schema_from_dict(original.to_dict())
    assert isinstance(restored, CategoricalLabelSchema)
    assert restored.classes == ["cat", "dog"]
    assert restored.value_map[0].color == "#ff0000"


def test_image_sample_type_validated():
    with pytest.raises(SchemaError):
        ImageSchema(sample_type="jpeg2000")


def test_image_url_mode_passes_through(tmp_path):
    schema = ImageSchema(sample_type="url")
    stored = schema.to_storage(str(tmp_path / "a.jpg"))
    assert schema.from_storage(stored) == stored


def test_embedding_carries_nn_role():
    assert EmbeddingSchema(shape=(4,)).number_role == "nn_embedding"
    assert EmbeddingSchema(shape=(4,)).default_visible is False


def test_table_schema_operations():
    schema = TableSchema({"a": StringSchema(), "b": StringSchema()})
    assert schema.names == ["a", "b"]
    assert "a" in schema
    bigger = schema.with_column("c", StringSchema())
    assert bigger.names == ["a", "b", "c"]
    assert schema.names == ["a", "b"]  # original untouched
    smaller = bigger.without_columns(["a"])
    assert smaller.names == ["b", "c"]


def test_table_schema_unknown_column_message():
    schema = TableSchema({"a": StringSchema()})
    with pytest.raises(SchemaError) as exc:
        schema["nope"]
    assert "nope" in str(exc.value)


def test_table_schema_roundtrip():
    schema = TableSchema({"image": ImageSchema(sample_type="url"), "w": SampleWeightSchema()})
    restored = TableSchema.from_dict(schema.to_dict())
    assert restored.names == schema.names
    assert restored["image"].sample_type == "url"
