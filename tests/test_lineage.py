"""Lineage is the load-bearing guarantee. If these break, every recorded history lies."""

import pytest

from granum import Table
from granum.errors import TableError


def root_table():
    return Table.from_dict_data(
        {"a": [1, 2, 3, 4]}, project_name="demo", dataset_name="train", table_name="initial"
    )


def test_root_has_no_parents():
    assert root_table().parents == ()


def test_parent_links_back():
    root = root_table()
    child = root.add_column("b", [1, 2, 3, 4])
    assert child.parent().url == root.url


def test_lineage_is_root_first():
    root = root_table()
    second = root.delete_rows([0])
    third = second.add_column("b", [9, 9, 9])
    chain = third.lineage()
    assert [t.url for t in chain] == [root.url, second.url, third.url]


def test_children_and_descendants():
    root = root_table()
    left = root.delete_rows([0])
    right = root.delete_rows([1])
    grandchild = left.add_column("b", [1, 2, 3])

    child_urls = {t.url for t in root.children()}
    assert child_urls == {left.url, right.url}

    descendant_urls = {t.url for t in root.descendants()}
    assert descendant_urls == {left.url, right.url, grandchild.url}


def test_latest_returns_newest_descendant():
    root = root_table()
    first = root.delete_rows([0])
    second = first.add_column("b", [1, 2, 3])
    assert root.latest().url == second.url


def test_latest_of_a_leaf_is_itself():
    root = root_table()
    assert root.latest().url in {root.url, root.latest().url}
    leaf = root.delete_rows([0])
    assert leaf.latest().url == leaf.url


def test_revision_by_name():
    root = root_table()
    child = root.add_column("b", [1, 2, 3, 4])
    assert root.revision(table_name=child.name).url == child.url


def test_revision_by_url_and_tag():
    root = root_table()
    child = root.add_column("b", [1, 2, 3, 4])
    assert root.revision(table_url=child.url).url == child.url
    assert root.revision(tag="latest").url == child.url


def test_revision_rejects_non_descendant():
    root = root_table()
    stranger = Table.from_dict_data(
        {"a": [1]}, project_name="demo", dataset_name="train", table_name="unrelated"
    )
    with pytest.raises(TableError):
        root.revision(table_url=stranger.url)


def test_revision_requires_an_argument():
    with pytest.raises(TableError):
        root_table().revision()


def test_revision_names_do_not_collide():
    root = root_table()
    first = root.add_column("b", [1, 2, 3, 4])
    second = root.add_column("c", [1, 2, 3, 4])
    assert first.url != second.url


def test_editing_chain_preserves_every_step():
    """The Stage 6 loop in miniature: correct a label, drop a sample, zero a weight."""
    table = Table.from_dict_data(
        {"image": ["/a.jpg", "/b.jpg", "/c.jpg"], "label": [0, 1, 0]},
        project_name="demo",
        dataset_name="train",
    )
    corrected = table.set_values("label", {0: 1})
    trimmed = corrected.delete_rows([2])
    weighted = trimmed.set_weights({0: 0.0})

    assert len(weighted.lineage()) == 4
    assert weighted[0]["label"] == 1
    assert weighted[0]["weight"] == 0.0
    assert len(weighted) == 2
    # the original is untouched
    assert table[0]["label"] == 0 and len(table) == 3


def test_revision_names_do_not_accrete_suffixes():
    """A long editing session must not produce initial_edit_delete_rows_edit_..."""
    table = Table.from_dict_data(
        {"a": list(range(20))},
        project_name="demo", dataset_name="train", table_name="initial",
    )
    for _ in range(5):
        table = table.delete_rows([0])
    assert table.name.count("delete_rows") == 1
    assert len(table.name) < 40
    assert table.base_name == "initial"


def test_squash_resets_the_naming_base():
    squashed = root_table().delete_rows([0]).squash()
    assert squashed.base_name == squashed.name
