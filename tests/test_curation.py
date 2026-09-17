"""Removing images from a set and putting them back keeps every version and the reason."""

import pytest
from fastapi.testclient import TestClient

import granum
from granum import Table
from granum.core.curation import CurationError, remove_images, restore_images
from granum.core.index import Index
from granum.core.reviews import ReviewLog
from granum.core.schemas import CategoricalLabelSchema, ImageSchema
from granum.core.url import Url
from granum.service.app import create_app


def P(path):
    """A local path as tables store it (``C:/t/0.png`` on Windows)."""
    return str(Url(path))


SCHEMA = {"image": ImageSchema(sample_type="url"), "label": CategoricalLabelSchema(classes=["cat", "dog"])}


def make(split, images):
    return Table.from_dict_data(
        {"image": images, "label": [i % 2 for i in range(len(images))]},
        schema=SCHEMA, project_name="demo", dataset_name="pets", table_name=split,
    )


def test_remove_then_put_back():
    train = make("train", [P("/t/0.png"), P("/t/1.png"), P("/t/2.png")])
    valid = make("valid", [P("/v/0.png"), P("/v/1.png")])

    first = remove_images(train, [P("/t/1.png"), P("/nope.png")], removed_set=None, reason="blurry")
    assert first["count"] == 1 and first["missing"] == [P("/nope.png")]
    newer = first["version"]
    assert newer.base_name == "train" and newer.parents == (train.url,)
    assert [r["image"] for r in newer] == [P("/t/0.png"), P("/t/2.png")]
    assert len(train) == 3  # the earlier version is untouched
    removed = first["removed"]
    assert removed.base_name == "removed" and removed.parents == ()
    row = removed[0]
    assert row["removed_from"] == "train" and row["removed_reason"] == "blurry" and row["label"] == 1
    assert ReviewLog("demo", "pets").current()[P("/t/1.png")]["status"] == "excluded"

    second = remove_images(valid, [P("/v/0.png"), P("/v/1.png")], removed_set=removed, reason="duplicate", reasons={P("/v/1.png"): "blurry"})
    removed = second["removed"]
    assert [r["removed_reason"] for r in removed] == ["blurry", "duplicate", "blurry"]
    assert ReviewLog("demo", "pets").current()[P("/v/1.png")]["reason"] == "blurry"
    assert len(removed) == 3 and removed.parents == (first["removed"].url,)

    with pytest.raises(CurationError):
        remove_images(newer, [P("/t/1.png")], removed_set=removed)

    back = restore_images(removed, [P("/t/1.png")], newest_of={"train": newer, "valid": second["version"]})
    assert len(back["versions"]) == 1
    restored = back["versions"][0]
    assert restored.base_name == "train" and sorted(r["image"] for r in restored) == [P("/t/0.png"), P("/t/1.png"), P("/t/2.png")]
    assert [r["image"] for r in back["removed"]] == [P("/v/0.png"), P("/v/1.png")]
    assert P("/t/1.png") not in ReviewLog("demo", "pets").current()


def test_removal_endpoints():
    train = make("train", [P("/t/0.png"), P("/t/1.png")])
    make("valid", [P("/v/0.png")])
    index = Index([granum.get_config().project_root])
    index.refresh()
    api = TestClient(create_app(index=index, config=granum.get_config(), allowed_hosts=["testserver"], serve_dashboard=False))

    body = {"project": "demo", "table": str(train.url), "samples": [P("/t/0.png")], "reason": "wrong labels"}
    done = api.post("/api/datasets/remove", json=body).json()
    assert done["count"] == 1 and done["version"]["row_count"] == 1
    # Removing from an older version would silently drop later changes.
    assert api.post("/api/datasets/remove", json={**body, "samples": [P("/t/1.png")]}).status_code == 409

    listing = api.get("/api/datasets/removed", params={"project": "demo", "dataset": "pets"}).json()
    assert [r["image"] for r in listing["images"]] == [P("/t/0.png")] and listing["images"][0]["removed_from"] == "train"

    back = api.post("/api/datasets/restore", json={"project": "demo", "dataset": "pets", "samples": [P("/t/0.png")]}).json()
    assert back["count"] == 1
    listing = api.get("/api/datasets/removed", params={"project": "demo", "dataset": "pets"}).json()
    assert listing["images"] == []


def test_sample_spreads_images():
    train = make("train", [P(f"/t/{i}.png") for i in range(30)])
    index = Index([granum.get_config().project_root])
    index.refresh()
    api = TestClient(create_app(index=index, config=granum.get_config(), allowed_hosts=["testserver"], serve_dashboard=False))
    images = api.get("/api/table/sample", params={"url": str(train.url), "n": 5}).json()["images"]
    assert [i["row"] for i in images] == [0, 6, 12, 18, 24] and images[1]["image"] == P("/t/6.png")
