"""Review decisions persist, keep their history, and stay tied to the image."""

import pytest
from fastapi.testclient import TestClient

import granum
from granum import Table
from granum.core.index import Index
from granum.core.reviews import ReviewError, ReviewLog
from granum.core.schemas import CategoricalLabelSchema, ImageSchema
from granum.core.url import Url
from granum.service.app import create_app


def test_latest_decision_wins_and_history_is_kept(isolated_project):
    log = ReviewLog("demo", "train")
    assert log.record(["/a.jpg", "/b.jpg", "/a.jpg"], "ambiguous", reason="blurry", reviewer="ana") == 2
    log.record(["/a.jpg"], "corrected", reason="it is a van", reviewer="ben")
    current = log.current()
    assert current["/a.jpg"]["status"] == "corrected" and current["/a.jpg"]["reviewer"] == "ben"
    assert current["/b.jpg"]["reason"] == "blurry"
    assert [e["status"] for e in log.history("/a.jpg")] == ["ambiguous", "corrected"]
    assert log.counts() == {"corrected": 1, "ambiguous": 1}


def test_clearing_records_an_event_instead_of_erasing(isolated_project):
    log = ReviewLog("demo", "train")
    log.record(["/a.jpg"], "deferred")
    log.record(["/a.jpg"], "unreviewed")
    assert log.current() == {}
    assert len(log.history("/a.jpg")) == 2


def test_invalid_status_and_torn_lines(isolated_project):
    log = ReviewLog("demo", "train")
    with pytest.raises(ReviewError):
        log.record(["/a.jpg"], "maybe")
    log.record(["/a.jpg"], "correct")
    with log.url.fs.open(log.url.path, "ab") as handle:
        handle.write(b'{"sample": "/b.jpg", "stat')  # an interrupted write
    assert list(log.current()) == ["/a.jpg"]


def test_decisions_survive_a_revision_that_removes_rows(isolated_project, tmp_path):
    table = Table.from_dict_data(
        {"image": [str(Url("/x/0.png")), str(Url("/x/1.png")), str(Url("/x/2.png"))], "label": [0, 1, 0]},
        schema={"image": ImageSchema(sample_type="url"), "label": CategoricalLabelSchema(classes=["cat", "dog"])},
        project_name="demo", dataset_name="train",
    )
    ReviewLog("demo", "train").record([str(Url("/x/2.png"))], "excluded", table_url=str(table.url))
    smaller = table.delete_rows([0])
    by_image = {row["image"]: ReviewLog("demo", "train").current().get(row["image"]) for row in smaller}
    assert by_image[str(Url("/x/2.png"))]["status"] == "excluded" and by_image[str(Url("/x/1.png"))] is None


def test_review_endpoints(isolated_project):
    table = Table.from_dict_data(
        {"image": ["/x/0.png", "/x/1.png"], "label": [0, 1]},
        schema={"image": ImageSchema(sample_type="url"), "label": CategoricalLabelSchema(classes=["cat", "dog"])},
        project_name="demo", dataset_name="train",
    )
    index = Index([isolated_project])
    index.refresh()
    api = TestClient(create_app(index=index, config=granum.get_config(), allowed_hosts=["testserver"], serve_dashboard=False))

    body = {"project": "demo", "dataset": "train", "samples": ["/x/0.png"], "status": "ambiguous",
            "reason": "partly hidden", "table": str(table.url)}
    assert api.post("/api/reviews", json=body).json() == {"recorded": 1, "counts": {"ambiguous": 1}}
    statuses = api.get("/api/reviews", params={"project": "demo", "dataset": "train"}).json()["statuses"]
    assert statuses["/x/0.png"]["status"] == "ambiguous" and statuses["/x/0.png"]["reason"] == "partly hidden"
    history = api.get("/api/reviews/history", params={"project": "demo", "dataset": "train", "sample": "/x/0.png"}).json()
    assert len(history["events"]) == 1

    assert api.post("/api/reviews", json={**body, "status": "nope"}).status_code == 400
    assert api.post("/api/reviews", json={**body, "dataset": "../../etc"}).status_code == 404
    assert api.post("/api/reviews", json={**body, "table": "/etc"}).status_code == 403
