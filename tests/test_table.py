import pytest

from granum import Table
from granum.core.layout import OBJECT_FILENAME, ROW_CACHE_FILENAME
from granum.core.schemas import CategoricalLabelSchema, ImageSchema, StringSchema
from granum.errors import ImmutableError, SchemaError, TableError


def make_table(**kwargs):
    return Table.from_dict_data(
        {"image": ["/data/a.jpg", "/data/b.jpg", "/data/c.jpg"], "label": [0, 1, 0]},
        schema={"image": ImageSchema(sample_type="url"),
                "label": CategoricalLabelSchema(classes=["cat", "dog"])},
        project_name="demo",
        dataset_name="train",
        **kwargs,
    )


# -- creation ---------------------------------------------------------------


def test_from_dict_data_basics():
    table = make_table()
    assert len(table) == 3
    assert table.columns == ["image", "label", "weight"]
    assert table.project_name == "demo"
    assert table[0] == {"image": "/data/a.jpg", "label": 0, "weight": 1.0}


def test_weight_column_added_by_default():
    assert "weight" in make_table().columns
    bare = Table.from_dict_data({"a": [1, 2]}, add_weight_column=False)
    assert bare.columns == ["a"]


def test_negative_and_out_of_range_indexing():
    table = make_table()
    assert table[-1]["image"] == "/data/c.jpg"
    with pytest.raises(IndexError):
        table[3]


def test_iteration_yields_every_sample():
    assert len(list(make_table())) == 3


def test_files_written_to_disk():
    table = make_table()
    assert (table.url / OBJECT_FILENAME).exists()
    assert (table.url / ROW_CACHE_FILENAME).exists()


def test_index_markers_touched(isolated_project):
    table = make_table()
    assert (table.url.parent / "index.granum.json").exists()


def test_schema_mismatch_is_reported():
    with pytest.raises(SchemaError):
        Table.from_dict_data(
            {"label": ["not-an-int"]}, schema={"label": CategoricalLabelSchema(classes=["a"])}
        )


def test_ragged_columns_rejected():
    with pytest.raises(TableError):
        Table.from_dict_data({"a": [1, 2], "b": [1]})


# -- immutability -----------------------------------------------------------


def test_table_cannot_be_mutated():
    table = make_table()
    with pytest.raises(ImmutableError):
        table.name = "renamed"
    with pytest.raises(ImmutableError):
        table.row_count = 999
    with pytest.raises(ImmutableError):
        del table.schema


def test_immutability_message_points_at_the_fix():
    table = make_table()
    with pytest.raises(ImmutableError) as exc:
        table.description = "x"
    assert "new revision" in str(exc.value)


# -- revisions --------------------------------------------------------------


def test_add_column_creates_revision():
    table = make_table()
    revised = table.add_column("split", ["train", "train", "val"])
    assert revised.columns == ["image", "label", "weight", "split"]
    assert revised[2]["split"] == "val"
    assert table.columns == ["image", "label", "weight"]  # parent untouched
    assert revised.parents == (table.url,)
    assert revised.producer["op"] == "add_column"


def test_add_duplicate_or_wrong_length_column_rejected():
    table = make_table()
    with pytest.raises(TableError):
        table.add_column("label", [1, 2, 3])
    with pytest.raises(TableError):
        table.add_column("other", [1, 2])


def test_delete_columns():
    table = make_table().delete_columns(["weight"])
    assert table.columns == ["image", "label"]
    with pytest.raises(TableError):
        table.delete_column("nope")


def test_cannot_delete_every_column():
    table = Table.from_dict_data({"a": [1]}, add_weight_column=False)
    with pytest.raises(TableError):
        table.delete_columns(["a"])


def test_delete_rows():
    table = make_table().delete_rows([1])
    assert len(table) == 2
    assert [row["image"] for row in table] == ["/data/a.jpg", "/data/c.jpg"]


def test_delete_rows_validates_indices():
    with pytest.raises(TableError):
        make_table().delete_rows([99])


def test_filter():
    table = make_table().filter(lambda row: row["label"] == 0)
    assert len(table) == 2
    assert table.producer["op"] == "filter"


def test_subset_is_deterministic_with_seed():
    table = Table.from_dict_data({"a": list(range(100))})
    first = table.subset(0.5, seed=7)
    second = table.subset(0.5, seed=7)
    assert len(first) == len(second)


def test_subset_range_slicing():
    table = Table.from_dict_data({"a": list(range(10))})
    assert len(table.subset(range_factor_min=0.0, range_factor_max=0.5)) == 5


def test_join_tables_records_both_parents():
    left = make_table()
    right = make_table()
    joined = left.join_tables(right)
    assert len(joined) == 6
    assert set(joined.parents) == {left.url, right.url}


def test_join_requires_matching_columns():
    with pytest.raises(TableError):
        make_table().join_tables(Table.from_dict_data({"x": [1]}))


def test_set_values_edits_cells():
    table = make_table()
    corrected = table.set_values("label", {0: 1})
    assert corrected[0]["label"] == 1
    assert table[0]["label"] == 0
    assert corrected.producer["op"] == "set_values"


def test_set_weights_scalar_and_mapping():
    table = make_table()
    assert table.set_weights(0.0)[1]["weight"] == 0.0
    assert table.set_weights({2: 5.0})[2]["weight"] == 5.0


def test_set_weights_requires_column():
    table = Table.from_dict_data({"a": [1]}, add_weight_column=False)
    with pytest.raises(TableError):
        table.set_weights(0.0)


def test_squash_drops_lineage():
    table = make_table().add_column("x", [1, 2, 3])
    squashed = table.squash()
    assert squashed.parents == ()
    assert len(squashed) == 3
    assert squashed.columns == table.columns


# -- value maps -------------------------------------------------------------


def test_value_map_read():
    assert make_table().get_simple_value_map("label") == {0: "cat", 1: "dog"}


def test_add_value_map_item():
    table = make_table().add_value_map_item("label", "bird", color="#00ff00")
    assert table.get_simple_value_map("label") == {0: "cat", 1: "dog", 2: "bird"}
    assert table.get_value_map("label")[2].color == "#00ff00"


def test_add_duplicate_class_rejected():
    with pytest.raises(TableError):
        make_table().add_value_map_item("label", "cat")


def test_set_and_delete_value_map_item():
    table = make_table().set_value_map_item("label", 0, display_name="Feline")
    assert table.get_value_map("label")[0].display_name == "Feline"
    dropped = table.delete_value_map_item("label", 1)
    assert dropped.get_simple_value_map("label") == {0: "cat"}


def test_value_map_on_non_categorical_rejected():
    table = Table.from_dict_data({"a": ["x"]}, schema={"a": StringSchema()})
    with pytest.raises(TableError):
        table.get_value_map("a")


# -- views ------------------------------------------------------------------


def double_label(sample):
    return {"label": sample["label"] * 2}


def test_with_transform_does_not_change_table():
    table = make_table()
    view = table.with_transform(double_label)
    assert len(view) == 3
    assert view[1] == {"label": 2}
    assert table[1]["label"] == 1


def test_views_are_independent():
    table = make_table()
    assert table.with_transform(double_label)[1]["label"] == 2
    assert table.with_transform(lambda s: s)[1]["label"] == 1


def test_delete_all_rows_preserves_schema():
    """An empty result must keep its column types, not collapse to nulls."""
    table = make_table().delete_rows([0, 1, 2])
    assert len(table) == 0
    assert table.columns == ["image", "label", "weight"]
    assert table.to_arrow().schema.field("label").type == __import__("pyarrow").int32()


def test_filter_matching_nothing_preserves_schema():
    table = make_table().filter(lambda row: False)
    assert len(table) == 0
    assert table.columns == ["image", "label", "weight"]


def test_empty_table_can_be_reopened():
    emptied = make_table().filter(lambda row: False)
    assert len(Table.from_url(emptied.url)) == 0
