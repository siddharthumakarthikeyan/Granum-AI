"""Import preflight: every trap found in the aerial dataset, reproduced in miniature."""

import json

import pytest
from typer.testing import CliRunner

from granum import Table
from granum.cli.main import app as cli
from granum.importing import PreflightError, Source, import_coco, resolve_options, run_preflight

PNG_1x1 = bytes.fromhex(
    "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c4"
    "890000000a49444154789c6360000002000100fdff03fa0000000049454e44ae426082"
)


def _png(path, width=1, height=1):
    from PIL import Image

    Image.new("RGB", (width, height), (10, 20, 30)).save(path)


def _coco(folder, images, annotations, categories):
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / "_annotations.coco.json"
    path.write_text(json.dumps({"info": {"v": 1}, "images": images, "annotations": annotations, "categories": categories}))
    return path


CATEGORIES = [
    {"id": 0, "name": "people", "supercategory": "none"},
    {"id": 1, "name": "car"},
    {"id": 2, "name": "ignored regions"},
    {"id": 3, "name": "people"},
    {"id": 4, "name": "others"},
]


@pytest.fixture
def dataset(tmp_path):
    root = tmp_path / "aerial"
    train, valid = root / "train", root / "valid"
    train.mkdir(parents=True)
    valid.mkdir(parents=True)
    # Two export copies of one frame in train, a frame of the same sequence in valid.
    names = {
        "train": ["0000001_00001_d_1_jpg.rf.aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa.jpg",
                  "0000001_00001_d_1_jpg.rf.bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb.jpg",
                  "0000002_00001_d_2_jpg.rf.cccccccccccccccccccccccccccccccc.jpg",
                  "0000002_00002_d_3_jpg.rf.dddddddddddddddddddddddddddddddd.jpg"],
        "valid": ["0000001_00050_d_9_jpg.rf.eeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee.jpg",
                  "0000003_00001_d_7_jpg.rf.ffffffffffffffffffffffffffffffff.jpg"],
    }
    for folder, split in ((train, "train"), (valid, "valid")):
        for i, name in enumerate(names[split]):
            _png(folder / name, 100 + i, 80)  # distinct bytes per file
    train_images = [
        {"id": i, "file_name": n, "width": 100 + i, "height": 80, "extra": {"name": n.split("_jpg")[0] + ".jpg"}}
        for i, n in enumerate(names["train"])
    ]
    train_images.append({"id": 9, "file_name": "missing.jpg", "width": 10, "height": 10})
    train_annotations = [
        {"id": 1, "image_id": 0, "category_id": 1, "bbox": [10, 10, 20, 20], "iscrowd": 0},
        {"id": 2, "image_id": 0, "category_id": 2, "bbox": [0, 0, 30, 30], "iscrowd": 0},
        {"id": 3, "image_id": 1, "category_id": 3, "bbox": [5, 5, 0, 10], "iscrowd": 0},       # zero width
        {"id": 4, "image_id": 1, "category_id": 3, "bbox": [90, 70, 30, 30], "iscrowd": 0},    # past the edge
        {"id": 4, "image_id": 2, "category_id": 4, "bbox": [1, 1, 4, 4], "iscrowd": 0},        # repeated id, tiny
        {"id": 6, "image_id": 77, "category_id": 1, "bbox": [1, 1, 4, 4], "iscrowd": 0},       # orphan
    ]
    valid_images = [
        {"id": i, "file_name": n, "width": 100 + i, "height": 80, "extra": {"name": n.split("_jpg")[0] + ".jpg"}}
        for i, n in enumerate(names["valid"])
    ]
    valid_annotations = [{"id": 1, "image_id": 0, "category_id": 1, "bbox": [1, 1, 10, 10], "iscrowd": 0}]
    return [
        Source("train", str(_coco(train, train_images, train_annotations, CATEGORIES))),
        Source("valid", str(_coco(valid, valid_images, valid_annotations, CATEGORIES))),
    ]


def codes(report):
    return {f.code: f for f in report.findings}


def test_preflight_finds_each_problem(dataset):
    report = run_preflight(dataset, media="full")
    found = codes(report)
    assert report.verdict == "block"
    assert found["media.missing"].count == 1 and found["media.missing"].severity == "block"
    assert found["annotations.orphan"].count == 1
    assert found["annotations.zero_area"].count == 1
    assert found["annotations.out_of_bounds"].count == 1
    assert found["annotations.duplicate_id"].count == 1
    assert found["annotations.tiny"].count >= 1
    assert found["categories.duplicate_name"].examples[0]["ids"] == [0, 3]
    assert found["categories.unused"].examples == [{"category_id": 0, "name": "people"}]
    assert found["categories.ignore_region"].count == 1
    assert found["categories.catch_all"].severity == "info"
    assert found["images.export_copies"].count == 2
    shared = found["split.shared_sequence"]
    assert shared.severity == "warn" and shared.splits == {"train": 2, "valid": 1}
    assert found["images.unannotated"].splits == {"train": 2, "valid": 1}


def test_preflight_changes_nothing_and_serializes(dataset, isolated_project):
    before = [open(s.annotations).read() for s in dataset]
    body = run_preflight(dataset, media="sample").to_dict()
    assert [open(s.annotations).read() for s in dataset] == before
    json.dumps(body)
    severities = [f["severity"] for f in body["findings"]]
    assert severities == sorted(severities, key=["block", "warn", "info"].index)
    assert not (isolated_project / "projects").exists()


def test_unreadable_file_is_a_block_without_options(tmp_path):
    broken = tmp_path / "bad.json"
    broken.write_text("{not json")
    report = run_preflight([Source("train", str(broken))], media="none")
    assert report.verdict == "block"
    with pytest.raises(PreflightError, match="cannot import"):
        resolve_options(report, {})


def test_import_applies_defaults_and_records_provenance(dataset, isolated_project):
    report = run_preflight(dataset, media="full")
    result = import_coco(report, project_name="aerial")
    tables = {t["split"]: Table.from_url(t["url"]) for t in result.tables}
    train = tables["train"]

    assert len(train) == 4  # the missing image is excluded
    instances = [i for row in train for i in row["bbs"]["instances"]]
    labels = sorted(i["label"] for i in instances)
    assert 0 not in train.schema["bbs"].value_map  # placeholder merged away
    assert labels.count(3) == 1  # zero-area box dropped, out-of-bounds box kept (clipped)
    clipped = next(i for i in instances if i["annotation_id"] == 4 and i["label"] == 3)
    assert clipped["vertices"] == [90.0, 70.0, 101.0, 80.0]
    ignore = next(i for i in instances if i["label"] == 2)
    assert ignore["iscrowd"] is True
    assert len({i["annotation_id"] for i in instances}) == len(instances)  # renumbered

    assert train[0]["source_image"] == train[1]["source_image"]
    assert train[0]["sequence"] == "0000001" and tables["valid"][0]["sequence"] == "0000001"

    provenance = train.producer["args"]["preflight"]
    assert provenance["verdict"] == "block"
    assert provenance["resolutions"]["media.missing"] == "exclude"
    saved = json.loads(open(result.report_url).read())
    assert saved["import"]["effects"]["boxes_dropped_zero_area"] == 1
    assert saved["import"]["effects"]["images_excluded"] == 1


def test_import_respects_non_default_choices(dataset, isolated_project):
    report = run_preflight(dataset, media="full")
    result = import_coco(
        report, project_name="aerial",
        resolutions={"categories.ignore_region": "drop", "images.unannotated": "exclude", "categories.duplicate_name": "keep",
                     "split.shared_sequence": "ignore", "images.export_copies": "ignore", "annotations.zero_area": "keep"},
    )
    train = Table.from_url(result.tables[0]["url"])
    assert "sequence" not in train.columns and "source_image" not in train.columns
    assert 2 not in {i["label"] for row in train for i in row["bbs"]["instances"]}
    assert 3 in train.schema["bbs"].value_map
    assert len(train) == 3  # missing and unannotated images left out


def test_invalid_choice_is_refused(dataset):
    report = run_preflight(dataset, media="none")
    with pytest.raises(PreflightError, match="choose one of"):
        resolve_options(report, {"annotations.zero_area": "shrug"})
    with pytest.raises(PreflightError, match="no finding"):
        resolve_options(report, {"nope": "drop"})


def test_cli_check_only_reports_and_sets_exit_code(dataset, isolated_project):
    runner = CliRunner()
    args = ["--project-root-url", str(isolated_project), "import", "coco",
            f"train={dataset[0].annotations}", f"valid={dataset[1].annotations}", "--project", "aerial", "--check-only"]
    result = runner.invoke(cli, args)
    assert result.exit_code == 1, result.output
    assert "media.missing" in result.output and "BLOCK" in result.output
    result = runner.invoke(cli, args[:-1])
    assert result.exit_code == 0, result.output
    assert "imported aerial/train: 4 images" in result.output


def test_splits_become_tables_of_one_dataset(dataset, isolated_project):
    result = import_coco(run_preflight(dataset, media="none"), project_name="p")
    tables = {t["split"]: Table.from_url(t["url"]) for t in result.tables}
    assert {t.dataset_name for t in tables.values()} == {"aerial"}
    assert tables["train"].name == "train" and tables["valid"].name == "valid"
    revision = tables["train"].set_weights({0: 0.0})
    assert revision.base_name == "train"


def test_split_plan_moves_images_between_splits(dataset, isolated_project):
    """Re-cutting the splits keeps every image, and keeps each table self-consistent.

    The fixture's splits both number their images from 0, so anything that moves collides
    with an id already in its new home -- the case that must be renumbered.
    """
    report = run_preflight(dataset, media="full")
    plain = import_coco(report, project_name="before")
    sizes = {t["split"]: t["rows"] for t in plain.tables}
    assert sizes == {"train": 4, "valid": 2}

    result = import_coco(report, project_name="after", split_plan={"train": 2, "valid": 4})
    tables = {t["split"]: Table.from_url(t["url"]) for t in result.tables}
    assert (len(tables["train"]), len(tables["valid"])) == (2, 4)
    assert result.effects["images_moved_between_splits"] == 2

    # Nothing is lost, duplicated, or pointed at the wrong folder.
    moved = {row["image"] for row in tables["valid"]}
    every = {row["image"] for table in tables.values() for row in table}
    assert len(every) == 6
    assert sum(1 for image in moved if "/train/" in image) == 2
    for table in tables.values():
        ids = [row["image_id"] for row in table]
        assert len(set(ids)) == len(ids)
        instances = [i for row in table for i in row["bbs"]["instances"]]
        annotation_ids = [i["annotation_id"] for i in instances if i["annotation_id"] is not None]
        assert len(set(annotation_ids)) == len(annotation_ids)


def test_split_plan_is_validated(dataset, isolated_project):
    report = run_preflight(dataset, media="full")  # the missing image is excluded, leaving 6
    with pytest.raises(PreflightError, match="no split named"):
        import_coco(report, project_name="p", split_plan={"holdout": 2})
    with pytest.raises(PreflightError, match="at least one split"):
        import_coco(report, project_name="p", split_plan={"train": 0, "valid": 0})


def test_split_plan_counts_are_read_as_proportions(dataset, isolated_project):
    """The dashboard counts images in the annotation files; exclusions mean fewer arrive."""
    report = run_preflight(dataset, media="full")
    # 5 + 2 in the files, but the missing image is excluded: a 5/2 plan over 6 images.
    result = import_coco(report, project_name="p", split_plan={"train": 5, "valid": 2})
    assert {t["split"]: t["rows"] for t in result.tables} == {"train": 4, "valid": 2}



def test_generated_example_imports_and_does_not_use_up_a_plan():
    """The example project: preflight finds its planted problems, and a one-project plan
    still has room for a real project afterwards."""
    import time

    from fastapi.testclient import TestClient

    import granum
    from granum.core.index import Index
    from granum.core.layout import ProjectLayout
    from granum.importing.example import counted_projects
    from granum.licensing import Licensing, set_licensing
    from granum.service.app import create_app

    class OneProject(Licensing):
        def status(self, *, fresh=False):
            return {**super().status(fresh=fresh), "max_projects": 1}

    set_licensing(OneProject.open())
    root = granum.get_config().project_root
    index = Index([root])
    api = TestClient(create_app(index=index, config=granum.get_config(), allowed_hosts=["testserver"], serve_dashboard=False))

    def run(path, body):
        response = api.post(path, json=body)
        assert response.status_code == 200, response.text
        job = response.json()
        while job["status"] == "running":
            time.sleep(0.05)
            job = api.get(f"/api/jobs/{job['id']}").json()
        assert job["status"] == "done", job
        return job

    example = api.post("/api/examples/shapes").json()
    assert [s["split"] for s in example["sources"]] == ["train", "valid", "test"] and example["images"] == 120
    preflight = run("/api/import/preflight", {"sources": example["sources"], "media": "full"})
    codes = {f["code"] for f in preflight["result"]["findings"]}
    assert {"annotations.zero_area", "media.identical_files"} <= codes
    done = run("/api/import/commit", {"preflight_job": preflight["id"], "project_name": "shapes-example", "tasks": ["object_detection"]})
    assert sum(t["rows"] for t in done["result"]["tables"]) == 120
    assert (root / "projects" / "shapes-example" / "example.json").exists()

    # The example does not count: a real project still fits in a one-project plan.
    assert counted_projects(ProjectLayout(root)) == []
    granum.init("real-project", "first")
    assert counted_projects(ProjectLayout(root)) == ["real-project"]
    set_licensing(Licensing.open())
