"""Renaming a project keeps every link inside it working."""


import pytest

import granum
from granum.core.curation import ISOLATED_SET, remove_images, restore_images
from granum.core.objects.table import Table
from granum.core.projects import ProjectError, rename_project
from granum.core.qa import QaLog
from granum.core.schemas import ImageSchema
from granum.core.url import Url


def _project(isolated_project, name="aerial"):
    images = [str(Url(isolated_project.parent / f"img{i}.png")) for i in range(3)]
    table = Table.from_dict_data({"image": images, "label": [0, 1, 0]}, schema={"image": ImageSchema(sample_type="url")},
                                 project_name=name, dataset_name="data", table_name="train")
    child = table.delete_rows([2])
    run = granum.init(name, "exp")
    run.add_metrics({"example_id": [0, 1], "loss": [0.1, 0.2]}, foreign_table_url=child.url)
    isolated = remove_images(child, [images[0]], removed_set=None, holding=ISOLATED_SET)
    log = QaLog(name, "data")
    log.set_status([images[1]], "reviewed", table_url=str(isolated["version"].url))
    log.ship({"train": {"url": str(isolated["version"].url), "name": "x", "images": [images[1]]}}, {images[1]: "reviewed"})
    return images, isolated


def test_rename_rewrites_every_link(isolated_project):
    images, isolated = _project(isolated_project)
    _project(isolated_project, name="aerial2")  # a name that starts with the old one must not change

    done = rename_project(isolated_project, "aerial", "aerial-v2")
    assert done["files_updated"] > 0
    projects = isolated_project / "projects"
    assert not (projects / "aerial").exists() and (projects / "aerial-v2").is_dir()

    old = str(Url(projects / "aerial")) + "/"
    for path in (projects / "aerial-v2").rglob("*"):
        if path.suffix in (".json", ".jsonl"):
            assert old not in path.read_text(), path
    # Objects load under the new name, and their lineage and run links resolve.
    newest = Table.from_url(str(isolated["version"].url).replace("/aerial/", "/aerial-v2/"))
    assert newest.project_name == "aerial-v2"
    assert all(Table.from_url(parent).project_name == "aerial-v2" for parent in newest.parents)
    run = granum.Run.from_url(projects / "aerial-v2" / "runs" / "exp")
    assert run.metrics_tables()[0].foreign_table_url.path.startswith(str(Url(projects / "aerial-v2")))
    # Rows recording where isolated images came from point at the renamed project.
    holding = Table.from_url(str(isolated["removed"].url).replace("/aerial/", "/aerial-v2/"))
    assert all(v.startswith(str(Url(projects / "aerial-v2"))) for v in holding.to_arrow().column("removed_from_version").to_pylist())
    # Review status and shipments follow.
    log = QaLog("aerial-v2", "data")
    assert log.current()[images[1]]["status"] == "reviewed"
    assert all(u.startswith(str(Url(projects / "aerial-v2"))) for u in log.shipped_urls())
    # Putting an isolated image back still works after the rename.
    newest_sets = {"train": newest}
    restore_images(holding, [images[0]], newest_of=newest_sets)
    # The other project is untouched.
    other = (projects / "aerial2" / "reviews" / "data.ships.jsonl").read_text()
    assert str(Url(projects / "aerial2")) + "/" in other


@pytest.mark.parametrize("bad, message", [("", "needs a name"), ("a/b", "may use"), ("aerial2", "already exists"), ("aerial", "same")])
def test_rename_refuses_bad_names(isolated_project, bad, message):
    _project(isolated_project)
    _project(isolated_project, name="aerial2")
    with pytest.raises(ProjectError, match=message):
        rename_project(isolated_project, "aerial", bad)
    assert (isolated_project / "projects" / "aerial").is_dir()
