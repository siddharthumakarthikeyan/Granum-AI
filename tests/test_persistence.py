"""A Table written now must read back identically later, including its lineage."""

from granum import Table
from granum.core.schemas import CategoricalLabelSchema, ImageSchema
from granum.core.url import register_url_alias


def test_reopen_by_url_preserves_everything():
    original = Table.from_dict_data(
        {"image": ["/data/a.jpg"], "label": [1]},
        schema={"image": ImageSchema(sample_type="url"),
                "label": CategoricalLabelSchema(classes=["cat", "dog"])},
        project_name="demo",
        dataset_name="train",
        description="first import",
    )
    reopened = Table.from_url(original.url)
    assert reopened.name == original.name
    assert reopened.columns == original.columns
    assert reopened.description == "first import"
    assert reopened.row_count == 1
    assert reopened[0] == original[0]
    assert reopened.get_simple_value_map("label") == {0: "cat", 1: "dog"}


def test_reopen_by_names():
    Table.from_dict_data(
        {"a": [1]}, project_name="demo", dataset_name="train", table_name="initial"
    )
    assert Table.from_names("demo", "train", "initial").columns == ["a", "weight"]


def test_lineage_survives_a_reload():
    root = Table.from_dict_data({"a": [1, 2]}, project_name="demo", dataset_name="train")
    child = root.add_column("b", [3, 4])
    reopened = Table.from_url(child.url)
    assert reopened.parents == (root.url,)
    assert [t.url for t in reopened.lineage()] == [root.url, child.url]


def test_paths_are_stored_aliased(tmp_path):
    """A Table written with an alias active resolves on a machine that repoints it."""
    data_dir = tmp_path / "images"
    data_dir.mkdir()
    register_url_alias("PROJECT_DATA", str(data_dir))

    table = Table.from_dict_data(
        {"image": [str(data_dir / "1.jpg")]},
        schema={"image": ImageSchema(sample_type="url")},
        project_name="demo",
        dataset_name="train",
    )
    stored = table.to_arrow().column("image")[0].as_py()
    assert stored == "<PROJECT_DATA>/1.jpg"


def test_row_cache_is_lazily_loaded():
    table = Table.from_dict_data({"a": [1, 2, 3]}, project_name="demo", dataset_name="train")
    reopened = Table.from_url(table.url)
    assert reopened._arrow is None
    assert len(reopened.to_arrow()) == 3
    assert reopened._arrow is not None
