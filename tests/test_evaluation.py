"""Reading a run's predictions: what it confuses, class by class, threshold by threshold."""

import pytest

from granum.metrics.evaluation import (
    EvalPolicy,
    best_threshold,
    confusion,
    examples,
    match_any_class,
    per_class,
    sweep,
)


def box(x, y, size=10):
    return [float(x), float(y), float(x + size), float(y + size)]


def image(truth, predicted, name="/d/a.png"):
    """One image as the collectors write it: labels, predictions, and the size of the picture."""
    return {
        "image": name,
        "truth": {"width": 100.0, "height": 100.0,
                  "instances": [{"vertices": b, "label": label} for b, label in truth]},
        "predicted": {"instances": [
            {"vertices": b, "label": label, "confidence": c, "matched": m, "ignored": False}
            for b, label, c, m in predicted]},
    }


# A van called a car, a car found, a pedestrian nothing predicted, and a box over nothing.
VAN, CAR, PERSON = 0, 1, 2
RECORDS = [
    image(
        [(box(10, 10), VAN), (box(40, 40), CAR), (box(70, 70), PERSON)],
        [(box(10, 10), CAR, 0.9, False), (box(40, 40), CAR, 0.8, True), (box(0, 80), CAR, 0.6, False)],
    ),
]
NAMES = {VAN: "van", CAR: "car", PERSON: "pedestrian"}


def test_a_box_in_the_right_place_with_the_wrong_class_lands_in_a_cell():
    """Class-aware matching hides a swap as a miss plus a false positive; this is why the
    matrix matches without looking at the class first."""
    found = confusion(RECORDS)
    assert found["cells"] == {f"{VAN}:{CAR}": 1, f"{CAR}:{CAR}": 1}
    assert found["missed"] == {str(PERSON): 1}
    assert found["background"] == {str(CAR): 1}


def test_the_strongest_prediction_takes_the_label_it_overlaps():
    truth = [{"vertices": box(10, 10), "label": VAN}]
    predicted = [{"vertices": box(11, 11), "label": CAR, "confidence": 0.9},
                 {"vertices": box(10, 10), "label": VAN, "confidence": 0.4}]
    took, taken = match_any_class(truth, predicted, 0.5)
    assert took == [0, -1] and taken == [0]      # the confident one wins, right or wrong


def test_predictions_below_the_operating_point_are_not_counted():
    quiet = [image([(box(10, 10), CAR)], [(box(10, 10), CAR, 0.1, True)])]
    assert confusion(quiet)["missed"] == {str(CAR): 1}
    assert confusion(quiet, EvalPolicy(operating_confidence=0.05))["cells"] == {f"{CAR}:{CAR}": 1}


def test_per_class_counts_each_class_as_the_score_does():
    rows = {row["name"]: row for row in per_class(RECORDS, names=NAMES)}
    # car: one found, two boxes that are not cars where cars were claimed.
    assert (rows["car"]["tp"], rows["car"]["fp"], rows["car"]["fn"]) == (1, 2, 0)
    assert rows["van"]["support"] == 1 and rows["van"]["recall"] == 0.0
    assert rows["pedestrian"]["fn"] == 1 and rows["pedestrian"]["predictions"] == 0
    assert rows["car"]["precision"] == round(1 / 3, 4)


def test_the_sweep_walks_the_threshold_and_finds_where_f1_peaks():
    # One right box at 0.9 and one wrong box at 0.3: above 0.3 precision is perfect.
    records = [image([(box(10, 10), CAR)],
                     [(box(10, 10), CAR, 0.9, True), (box(50, 50), CAR, 0.3, False)])]
    curve = sweep(records)
    low = next(row for row in curve if row["confidence"] == 0.25)
    high = next(row for row in curve if row["confidence"] == 0.5)
    assert low["fp"] == 1 and high["fp"] == 0
    assert best_threshold(curve) is not None and best_threshold(curve) > 0.3
    assert [row["confidence"] for row in curve] == sorted(row["confidence"] for row in curve)


def test_examples_are_the_objects_behind_a_cell():
    swapped = examples(RECORDS, truth_label=VAN, predicted_label=CAR)
    assert len(swapped) == 1
    assert swapped[0]["box"] == box(10, 10) and swapped[0]["predicted_box"] == box(10, 10)
    assert swapped[0]["confidence"] == 0.9 and swapped[0]["image"] == "/d/a.png"
    assert (swapped[0]["width"], swapped[0]["height"]) == (100.0, 100.0)

    assert [e["label"] for e in examples(RECORDS, truth_label=PERSON, predicted_label=None)] == [PERSON]
    invented = examples(RECORDS, truth_label=None, predicted_label=CAR)
    assert len(invented) == 1 and invented[0]["label"] is None
    assert examples(RECORDS, truth_label=VAN, predicted_label=CAR, limit=0) == []


def test_an_empty_set_does_not_raise():
    assert confusion([])["cells"] == {}
    assert per_class([]) == []
    assert best_threshold([]) is None


# -- through the service ---------------------------------------------------------


def evaluated(tmp_path):
    """A run that stored its boxes on one set, served by the API."""
    from fastapi.testclient import TestClient

    import granum
    from granum import BoundingBoxes2D, Table
    from granum.core.index import Index
    from granum.core.url import Url
    from granum.metrics import DetectionMetricsCollector, collect_metrics
    from granum.service.app import create_app

    def path(name):
        return str(Url(f"/eval/{name}.png"))

    table = Table.from_dict_data(
        {"image": [path(i) for i in range(3)],
         "bbs": [
             {"width": 100.0, "height": 100.0, "instances": [{"vertices": box(10, 10), "label": 0}]},
             {"width": 100.0, "height": 100.0, "instances": [{"vertices": box(40, 40), "label": 1}]},
             {"width": 100.0, "height": 100.0, "instances": [{"vertices": box(70, 70), "label": 1}]},
         ]},
        schema={"bbs": BoundingBoxes2D.schema(["van", "car"])},
        project_name="reading", dataset_name="streets", table_name="valid",
    )
    predictions = {
        # The van is called a car, the car is found, the last label is missed.
        path(0): {"boxes": [box(10, 10)], "scores": [0.9], "labels": [1]},
        path(1): {"boxes": [box(40, 40)], "scores": [0.8], "labels": [1]},
        path(2): {"boxes": [], "scores": [], "labels": []},
    }
    run = granum.init("reading", "run-1", parameters={"tracks_learning": True})
    collect_metrics(table, [DetectionMetricsCollector("bbs", value_map=table.schema["bbs"].value_map)],
                    predictor=lambda batch: [predictions[p] for p in batch["image"]],
                    split="valid", constants={"epoch": 0}, batch_size=2)
    run.set_status("finished")
    index = Index([granum.get_config().project_root])
    index.refresh()
    api = TestClient(create_app(index=index, config=granum.get_config(),
                                allowed_hosts=["testserver"], serve_dashboard=False))
    return api, run


def test_the_service_reads_a_run_class_by_class(isolated_project, tmp_path):
    api, run = evaluated(tmp_path)
    report = api.get("/api/run/evaluation", params={"url": str(run.url)}).json()

    assert report["stores_boxes"] is True and report["split"] == "valid" and report["images"] == 3
    assert report["confusion"]["cells"] == {"0:1": 1, "1:1": 1}
    assert report["confusion"]["missed"] == {"1": 1}
    rows = {row["name"]: row for row in report["per_class"]}
    assert rows["van"]["support"] == 1 and rows["van"]["tp"] == 0
    assert rows["car"]["tp"] == 1 and rows["car"]["fp"] == 1 and rows["car"]["fn"] == 1
    assert report["headline"]["labels"] == 3
    assert report["curve"] and report["best_confidence"] is not None

    # The cell behind the swap names the image, so a reader can go and look at it.
    cell = api.get("/api/run/evaluation/examples",
                   params={"url": str(run.url), "truth": 0, "predicted": 1}).json()
    assert [e["image"] for e in cell["examples"]] == ["/eval/0.png"]
    assert cell["examples"][0]["confidence"] == pytest.approx(0.9)  # float32, as stored

    missed = api.get("/api/run/evaluation/examples",
                     params={"url": str(run.url), "truth": 1}).json()
    assert [e["image"] for e in missed["examples"]] == ["/eval/2.png"]

    empty = api.get("/api/run/evaluation/examples", params={"url": str(run.url)})
    assert empty.status_code == 400
