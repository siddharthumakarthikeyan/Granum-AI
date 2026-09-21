"""Golden identity checks (QA01): metrics recorded during training must stay attached to the
image they were measured on, after images are removed, sets get new versions, and labels
are edited. Metrics address images by row position, so every one of those operations is a
chance to attach a score to the wrong picture."""

import pytest
from fastapi.testclient import TestClient

import granum
from granum import BoundingBoxes2D, Table
from granum.core.curation import remove_images
from granum.core.index import Index
from granum.core.objects.run import set_active_run
from granum.core.url import Url
from granum.metrics import DetectionMetricsCollector, collect_metrics
from granum.service.app import create_app

EPOCHS = 4
# Which epochs each image's single box is found in; this decides its learning category.
FOUND_IN = {
    0: {0, 1, 2, 3},  # early
    1: {2, 3},        # learned later
    2: set(),         # never
    3: {1},           # found once, then lost
    4: {0, 1, 2, 3},  # early
}


def P(name):
    return str(Url(f"/golden/{name}.png"))


def box(i):
    # A different place per image, so a box shown on the wrong image is detectable.
    x = 10 * i
    return [x, x, x + 8, x + 8]


@pytest.fixture(autouse=True)
def clear_active_run():
    set_active_run(None)
    yield
    set_active_run(None)


@pytest.fixture
def trained():
    table = Table.from_dict_data(
        {"image": [P(i) for i in FOUND_IN],
         "bbs": [{"width": 100, "height": 100, "instances": [{"vertices": box(i), "label": 0}]} for i in FOUND_IN]},
        schema={"bbs": BoundingBoxes2D.schema(["car"])},
        project_name="golden", dataset_name="streets", table_name="train",
    )
    run = granum.init("golden", "run")
    for epoch in range(EPOCHS):
        def predictor(batch, epoch=epoch):
            out = []
            for path in batch["image"]:
                i = next(k for k in FOUND_IN if P(k) == path)
                hit = epoch in FOUND_IN[i]
                out.append({"boxes": [box(i)] if hit else [], "scores": [0.9] if hit else [], "labels": [0] if hit else []})
            return out

        collect_metrics(table, [DetectionMetricsCollector("bbs", value_map=table.schema["bbs"].value_map)],
                        predictor=predictor, constants={"epoch": epoch, "split": "train"}, batch_size=2)
    index = Index([granum.get_config().project_root])
    index.refresh()
    api = TestClient(create_app(index=index, config=granum.get_config(), allowed_hosts=["testserver"], serve_dashboard=False))
    return api, table, run, index


def learning(api, run):
    split = api.get("/api/run/learning", params={"url": str(run.url)}).json()["splits"][0]
    return {row["image"]: row for row in split["images"]}, split


def test_learning_rows_describe_the_image_they_name(trained):
    api, table, run, _ = trained
    rows, split = learning(api, run)
    assert split["table"] == str(table.url)
    assert set(rows) == {P(i) for i in FOUND_IN}
    for i, found in FOUND_IN.items():
        row = rows[P(i)]
        assert row["example_id"] == i
        assert [s == 1.0 for s in row["scores"]] == [e in found for e in range(EPOCHS)], P(i)
    assert rows[P(2)]["category"] == "never"
    assert rows[P(3)]["category"] == "forgotten"


def test_removing_an_image_moves_no_score_onto_another(trained):
    api, table, run, index = trained
    before, _ = learning(api, run)
    newer = remove_images(table, [P(1)], removed_set=None, reason="blurry")["version"]
    index.refresh()
    assert [r["image"] for r in newer] == [P(0), P(2), P(3), P(4)]  # positions shifted

    after, split = learning(api, run)
    assert split["table"] == str(table.url)  # still the version the metrics were collected on
    assert after == before

    # One image's history: example 2 must still be image 2, with image 2's box.
    rounds = api.get("/api/run/image-rounds", params={"url": str(run.url), "table": str(table.url), "example": 2}).json()
    assert rounds["image"] == P(2)
    assert [t["vertices"] for t in rounds["truth"]] == [box(2)]
    assert [r["f1"] for r in rounds["rounds"]] == [0.0] * EPOCHS

    # The row view refuses to show the shorter version beside these metrics.
    meta = api.get("/api/run", params={"url": str(run.url)}).json()
    assert meta["inputs"][0]["joined"] == str(table.url)
    joined = api.get("/api/run/joined", params={"url": str(run.url)}).json()["rows"]
    assert {r["example_id"]: r["image"] for r in joined} == {i: P(i) for i in FOUND_IN}


def test_a_label_edit_keeps_each_score_on_its_image(trained):
    api, table, run, index = trained
    before, _ = learning(api, run)
    moved = {"width": 100, "height": 100, "instances": [{"vertices": [60, 60, 70, 70], "label": 0}]}
    edited = api.post("/api/table/commit", json={"url": str(table.url), "values": {"bbs": {"3": moved}}})
    assert edited.status_code == 200, edited.text
    index.refresh()

    after, _ = learning(api, run)
    assert after == before
    # The history shows what the model was scored against then, not the edited box.
    rounds = api.get("/api/run/image-rounds", params={"url": str(run.url), "table": str(table.url), "example": 3}).json()
    assert rounds["image"] == P(3) and [t["vertices"] for t in rounds["truth"]] == [box(3)]


def test_findings_name_the_right_image_and_carry_the_decision(trained):
    api, table, run, index = trained
    report = api.get("/api/run/findings", params={"url": str(run.url)}).json()
    assert report["stores_boxes"] is True
    split = report["splits"][0]
    flagged = {item["image"]: item for item in split["images"]}
    # Image 2's box is never found; the always-found images raise nothing.
    assert P(2) in flagged and P(0) not in flagged and P(4) not in flagged
    missed = next(f for f in flagged[P(2)]["findings"] if f["rule"] == "missed")
    assert missed["box"] == box(2) and flagged[P(2)]["example_id"] == 2
    assert split["counts"]["missed"] >= 1 and flagged[P(2)]["review"] is None

    recorded = api.post("/api/reviews", json={"project": "golden", "dataset": "streets", "samples": [P(2)],
                                               "status": "correct", "reason": "findings-1: valid hard case"})
    assert recorded.status_code == 200, recorded.text
    remove_images(table, [P(1)], removed_set=None, reason="blurry")
    index.refresh()
    again = {i["image"]: i for i in api.get("/api/run/findings", params={"url": str(run.url)}).json()["splits"][0]["images"]}
    assert again[P(2)]["example_id"] == 2 and again[P(2)]["findings"][0]["box"] == box(2)
    assert again[P(2)]["review"]["status"] == "correct"
