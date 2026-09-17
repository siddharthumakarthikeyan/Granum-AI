"""One commit = one revision: the contract the dashboard's commit relies on."""

import pytest

from granum import Table
from granum.core.schemas import CategoricalLabelSchema, ImageSchema
from granum.errors import TableError


def make_table():
    return Table.from_dict_data(
        {"image": ["a.png", "b.png", "c.png", "d.png"], "label": [0, 1, 0, 1], "score": [0.1, 0.2, 0.3, 0.4]},
        schema={"image": ImageSchema(sample_type="url"),
                "label": CategoricalLabelSchema(classes=["cat", "dog"])},
        project_name="p", dataset_name="d", table_name="initial",
    )


def test_one_commit_is_one_revision_holding_every_edit():
    table = make_table()
    edited = table.apply_edits(
        values={"label": {0: 1, 2: 2}, "weight": {3: 0.0}, "reviewed": {1: True}},
        new_columns={"reviewed": ("bool", False)},
        value_maps={"label": {0: "cat", 1: "dog", 2: {"internal_name": "fox", "color": "#ff8800"}}},
        table_name="cleaned-v1",
        description="fixed labels",
    )
    assert edited.parents == (table.url,)
    assert edited.name == "cleaned-v1"
    assert edited.description == "fixed labels"
    assert [edited[i]["label"] for i in range(4)] == [1, 1, 2, 1]
    assert edited[3]["weight"] == 0.0
    assert [edited[i]["reviewed"] for i in range(4)] == [False, True, False, False]
    assert edited.schema["reviewed"].writable
    assert edited.get_value_map("label")[2].color == "#ff8800"
    # the parent is untouched
    assert table[0]["label"] == 0 and "reviewed" not in table.schema
    # the latest revision is the commit
    assert table.latest().url == edited.url


def test_sparse_edits_are_recorded_on_the_revision():
    edited = make_table().apply_edits(values={"label": {2: 1}})
    assert edited.producer["op"] == "edit"
    assert edited.producer["args"]["cells"] == {"label": 1}
    assert edited.producer["edits"]["values"] == {"label": {"2": 1}}
    reopened = Table.from_url(edited.url)
    assert reopened.producer["edits"]["values"] == {"label": {"2": 1}}


def test_read_only_columns_cannot_be_edited():
    with pytest.raises(TableError, match="read-only"):
        make_table().apply_edits(values={"score": {0: 9.0}})
    with pytest.raises(TableError, match="read-only"):
        make_table().apply_edits(values={"image": {0: "x.png"}})


@pytest.mark.parametrize("column,value", [
    ("label", 7),            # not a class
    ("label", "dog"),        # a name, not an index
    ("weight", -1.0),        # below the minimum
    ("weight", True),        # a bool is not a weight
])
def test_invalid_values_are_refused(column, value):
    with pytest.raises(TableError):
        make_table().apply_edits(values={column: {0: value}})


def test_new_column_values_are_type_checked():
    with pytest.raises(TableError, match="whole numbers"):
        make_table().apply_edits(new_columns={"n": ("int32", 0)}, values={"n": {0: 1.5}})


def test_unknown_new_column_kind_is_refused():
    with pytest.raises(TableError, match="cannot create"):
        make_table().apply_edits(new_columns={"v": ("embedding", None)})


def test_removing_a_class_still_in_use_is_refused():
    with pytest.raises(TableError, match="still has rows"):
        make_table().apply_edits(value_maps={"label": {0: "cat"}})


def test_removing_a_class_after_relabelling_its_rows_is_allowed():
    edited = make_table().apply_edits(
        values={"label": {1: 0, 3: 0}}, value_maps={"label": {0: "cat"}},
    )
    assert edited.get_simple_value_map("label") == {0: "cat"}


def test_empty_commit_is_refused():
    with pytest.raises(TableError, match="nothing to commit"):
        make_table().apply_edits(values={"label": {}})


def test_row_out_of_range_is_refused():
    with pytest.raises(TableError, match="out of range"):
        make_table().apply_edits(values={"label": {4: 1}})
