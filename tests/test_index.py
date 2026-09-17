import pytest

import granum
from granum import Table
from granum.core.index import Index
from granum.core.objects.run import set_active_run


@pytest.fixture(autouse=True)
def clear_active_run():
    set_active_run(None)
    yield
    set_active_run(None)


@pytest.fixture
def populated(isolated_project):
    table = Table.from_dict_data(
        {"a": [1, 2, 3]}, project_name="p1", dataset_name="d1", table_name="initial"
    )
    child = table.delete_rows([0])
    grandchild = child.add_column("b", [9, 9])
    other = Table.from_dict_data({"a": [1]}, project_name="p2", dataset_name="d2")
    run = granum.init("p1", "exp")
    run.add_metrics({"example_id": [0, 1, 2], "loss": [1.0, 2.0, 3.0]},
                    foreign_table_url=table.url)
    index = Index([isolated_project])
    index.refresh()
    return index, table, child, grandchild, other, run


def test_discovers_tables_and_runs(populated):
    index = populated[0]
    assert {p["name"] for p in index.projects()} == {"p1", "p2"}
    assert len(index.tables("p1")) == 3
    assert len(index.runs("p1")) == 1


def test_project_counts(populated):
    index = populated[0]
    p1 = next(p for p in index.projects() if p["name"] == "p1")
    assert p1["tables"] == 3
    assert p1["runs"] == 1


def test_lineage_edges(populated):
    index, table, child, grandchild, *_ = populated
    edges = index.lineage_edges("p1")
    assert {"from": str(table.url), "to": str(child.url)} in edges
    assert {"from": str(child.url), "to": str(grandchild.url)} in edges


def test_children_and_latest(populated):
    index, table, child, grandchild, *_ = populated
    assert [e.url for e in index.children_of(table.url)] == [child.url]
    assert index.latest_revision(table.url).url == grandchild.url


def test_resolve_returns_live_objects(populated):
    index, table, _, _, _, run = populated
    assert isinstance(index.resolve(table.url), Table)
    assert index.resolve(run.url).name == "exp"


def test_unchanged_root_is_skipped(populated):
    index = populated[0]
    visited_before = index.stats.locations_visited
    skipped_before = index.stats.locations_skipped
    index.refresh()
    assert index.stats.locations_visited == visited_before
    assert index.stats.locations_skipped == skipped_before + 1


def test_force_rescans(populated):
    index = populated[0]
    visited_before = index.stats.locations_visited
    index.refresh(force=True)
    assert index.stats.locations_visited == visited_before + 1


def test_new_object_is_picked_up(populated):
    index = populated[0]
    before = len(index.tables("p1"))
    Table.from_dict_data({"a": [7]}, project_name="p1", dataset_name="d1",
                         table_name="added-later")
    index.refresh()
    assert len(index.tables("p1")) == before + 1


def test_static_root_is_scanned_once(populated, isolated_project):
    index = populated[0]
    index.mark_static(isolated_project)
    visited_before = index.stats.locations_visited
    Table.from_dict_data({"a": [7]}, project_name="p1", dataset_name="d1", table_name="ignored")
    index.refresh()
    assert index.stats.locations_visited == visited_before


def test_entries_survive_a_skipped_pass(populated):
    index = populated[0]
    before = len(index.entries())
    index.refresh()
    assert len(index.entries()) == before


def test_failure_is_recorded_and_clearable(populated, isolated_project):
    index = populated[0]
    broken = isolated_project / "projects" / "p1" / "datasets" / "d1" / "tables" / "broken"
    broken.mkdir()
    (broken / "object.granum.json").write_text("{ this is not json")
    index.refresh(force=True)
    assert index.stats.failures >= 1
    index.clear_skip(broken)
    assert str(broken) not in index._skips


def test_one_bad_object_does_not_stop_the_scan(populated, isolated_project):
    index = populated[0]
    broken = isolated_project / "projects" / "p1" / "datasets" / "d1" / "tables" / "broken"
    broken.mkdir()
    (broken / "object.granum.json").write_text("nonsense")
    index.refresh(force=True)
    assert len(index.tables("p1")) == 3  # the good ones are still there


def test_unknown_object_type_is_skipped(populated, isolated_project):
    index = populated[0]
    odd = isolated_project / "projects" / "p1" / "odd_object"
    odd.mkdir()
    (odd / "object.granum.json").write_text('{"type": "spaceship", "name": "x"}')
    index.refresh(force=True)
    assert all(e.type_name != "spaceship" for e in index.entries())


def test_background_thread_starts_and_stops(populated):
    index = populated[0]
    index.start(interval=0.05)
    assert index._thread is not None and index._thread.is_alive()
    index.stop()
    assert index._thread is None


def test_markers_reach_the_scan_root(isolated_project):
    """A write must touch the marker the indexer actually watches, or it is invisible."""
    from granum.core.layout import INDEX_FILENAME

    Table.from_dict_data({"a": [1]}, project_name="p", dataset_name="d")
    assert (isolated_project / "projects" / INDEX_FILENAME).exists()
    assert (isolated_project / INDEX_FILENAME).exists()


def test_index_notices_writes_without_force(isolated_project):
    """The regression that matters: a live service must see new objects."""
    Table.from_dict_data({"a": [1]}, project_name="p", dataset_name="d", table_name="first")
    index = Index([isolated_project])
    index.refresh()
    assert len(index.tables("p")) == 1

    Table.from_dict_data({"a": [2]}, project_name="p", dataset_name="d", table_name="second")
    index.refresh()          # no force
    assert len(index.tables("p")) == 2

    granum.init("p", "later-run")
    index.refresh()
    assert len(index.runs("p")) == 1
