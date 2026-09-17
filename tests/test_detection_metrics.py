import pytest

import granum
from granum import BoundingBoxes2D, Table
from granum.core.objects.run import set_active_run
from granum.metrics import DetectionMetricsCollector, collect_metrics


@pytest.fixture(autouse=True)
def clear_active_run():
    set_active_run(None)
    yield
    set_active_run(None)


def boxes(*instances, width=100, height=100):
    return {"width": width, "height": height, "instances": [{"vertices": v, "label": label} for v, label in instances]}


def test_detection_metrics_end_to_end():
    table = Table.from_dict_data(
        {"image": ["a.png", "b.png", "c.png"],
         "bbs": [boxes(([0, 0, 10, 10], 0), ([50, 50, 70, 70], 1)), boxes(([5, 5, 25, 25], 1)), boxes()]},
        schema={"bbs": BoundingBoxes2D.schema(["cat", "dog"])},
        project_name="p", dataset_name="d",
    )
    predictions = {
        "a.png": {"boxes": [[0, 0, 10, 10], [80, 80, 90, 90]], "scores": [0.4, 0.9], "labels": [0, 0]},
        "b.png": {"boxes": [[5, 5, 25, 26]], "scores": [0.7], "labels": [0]},  # right place, wrong class
        "c.png": {"boxes": [], "scores": [], "labels": []},
    }

    def predictor(batch):
        return [predictions[path.rsplit("/", 1)[-1]] for path in batch["image"]]

    granum.init("p", "det")
    metrics = collect_metrics(
        table,
        [DetectionMetricsCollector("bbs", value_map=table.schema["bbs"].value_map)],
        predictor=predictor, constants={"epoch": 0}, batch_size=2,
    )
    rows = metrics.join_input()
    a, b, c = rows
    # predictions stored highest confidence first
    assert [i["confidence"] for i in a["bbs_predicted"]["instances"]] == pytest.approx([0.9, 0.4])
    assert [i["matched"] for i in a["bbs_predicted"]["instances"]] == [False, True]
    assert a["gt_match"] == [1, -1]  # gt 0 matched by stored prediction 1; gt 1 missed
    assert (a["tp"], a["fp"], a["fn"]) == (1, 1, 1)
    assert b["bbs_predicted"]["instances"][0]["iou"] == 0.0  # class-aware: no same-class overlap
    assert (b["tp"], b["fp"], b["fn"]) == (0, 1, 1)
    assert (c["precision"], c["recall"]) == (1.0, 1.0)
    schema = metrics.schema["bbs_predicted"]
    assert schema.instance_properties == {"confidence": "float32", "iou": "float32", "matched": "bool", "ignored": "bool"}
    assert schema.classes == ["cat", "dog"] and schema.writable is False


def test_areas_to_skip_are_neither_missed_nor_false_positives():
    from granum.metrics.detection import DetectionMetricsCollector

    truth = {"width": 100, "height": 100, "instances": [
        {"vertices": [0, 0, 10, 10], "label": 0},
        {"vertices": [50, 50, 90, 90], "label": 1, "iscrowd": True},   # area to skip
        {"vertices": [20, 20, 30, 30], "label": 0},                    # missed
    ]}
    prediction = {
        "boxes": [[0, 0, 10, 10], [55, 55, 65, 65], [70, 0, 80, 10]],
        "scores": [0.9, 0.8, 0.7],
        "labels": [0, 0, 0],
    }
    out = DetectionMetricsCollector("bbs").collect({"bbs": [truth]}, [prediction])
    instances = out["bbs_predicted"][0]["instances"]
    assert [i["matched"] for i in instances] == [True, False, False]
    assert [i["ignored"] for i in instances] == [False, True, False]
    assert out["tp"] == [1] and out["fp"] == [1] and out["fn"] == [1]
    assert out["gt_match"][0] == [0, -2, -1]


def test_yolo_export_leaves_out_areas_to_skip(tmp_path, isolated_project):
    from granum import BoundingBoxes2D, Table, export_yolo

    table = Table.from_dict_data(
        {"image": [str(tmp_path / "a.jpg")], "bbs": [{"width": 10, "height": 10, "instances": [
            {"vertices": [0, 0, 5, 5], "label": 0, "iscrowd": False},
            {"vertices": [5, 5, 10, 10], "label": 0, "iscrowd": True},
        ]}]},
        schema={"bbs": BoundingBoxes2D.schema(["car"], instance_properties={"iscrowd": "bool"})},
        project_name="p", dataset_name="d",
    )
    (tmp_path / "a.jpg").write_bytes(b"x")
    export_yolo(table, tmp_path / "out", image_strategy="copy")
    assert len((tmp_path / "out" / "labels" / "train" / "a.txt").read_text().splitlines()) == 1


def test_average_precision_matches_hand_computed_cases():
    from granum.training.evaluate import average_precision

    assert average_precision([0.9, 0.8], [True, True], 2) == pytest.approx(1.0)
    assert average_precision([0.9, 0.8], [False, False], 2) == 0.0
    # one hit ranked after a miss: precision 0.5 up to recall 0.5, nothing beyond
    assert average_precision([0.9, 0.8], [False, True], 2) == pytest.approx(0.5 * 51 / 101)


def test_summary_only_collection_has_no_boxes():
    from granum.metrics.detection import DetectionMetricsCollector

    collector = DetectionMetricsCollector("bbs", store_boxes=False)
    truth = {"width": 10, "height": 10, "instances": [{"vertices": [0, 0, 5, 5], "label": 0}]}
    out = collector.collect({"bbs": [truth]}, [{"boxes": [[0, 0, 5, 5]], "scores": [0.9], "labels": [0]}])
    assert set(out) == {"tp", "fp", "fn", "precision", "recall", "f1"} == set(collector.column_schemas())
    assert out["tp"] == [1] and out["f1"] == [1.0]


def test_crossed_predicted_corners_are_ordered():
    from granum.metrics.detection import DetectionMetricsCollector

    truth = {"width": 100.0, "height": 100.0, "instances": [{"vertices": [10.0, 10.0, 20.0, 20.0], "label": 0}]}
    predicted = {"boxes": [[10.0, 20.0, 20.0, 10.0]], "scores": [0.9], "labels": [0]}
    out = DetectionMetricsCollector("bbs").collect({"bbs": [truth]}, [predicted])
    assert out["bbs_predicted"][0]["instances"][0]["vertices"] == [10.0, 10.0, 20.0, 20.0]
    assert out["tp"] == [1]
