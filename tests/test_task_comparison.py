"""Comparisons must join original rows and pool pixels, not image averages."""
import pytest
from test_training_tasks import tables

import granum
from granum.errors import GranumError
from granum.metrics.task_comparison import compare_vision
from granum.training.evaluate import evaluator_policy


def pair(source, task):
    parameters = {"task": task, "evaluator": evaluator_policy(task=task), "train_table": str(source["train"].url)}
    return (granum.init("tasks", "before", parameters=parameters),
            granum.init("tasks", "after", parameters=parameters))


def test_classification_comparison_joins_reordered_ids_and_rejects_changed_labels(tmp_path):
    source = tables(tmp_path)
    before, after = pair(source, "classify")
    before.add_metrics({"example_id": [0, 1], "accuracy": [0., 1.]}, foreign_table_url=source["test"].url, constants={"split": "test"})
    after.add_metrics({"example_id": [1, 0], "accuracy": [1., 1.]}, foreign_table_url=source["test"].url, constants={"split": "test"})
    report = compare_vision(before, after)
    assert report["delta"] == .5 and not report["held_out"]
    assert report["recipe_matches"] is None
    assert report["outcomes"] == {"improved": 1, "regressed": 0, "unchanged": 1}
    assert report["rows"][0]["row"] == 0 and report["rows"][0]["outcome"] == "improved"
    assert report["bootstrap_95"] == [0., 1.]
    for run in [before, after]:
        run.set_parameters({"test_table": str(source["test"].url),
                            "preflight": {"split_overlap": False, "media_sha256_checked": True, "splits": {"test": 2}}})
    assert compare_vision(before, after)["held_out"]
    after.set_parameters({"preflight": {"split_overlap": True, "media_sha256_checked": True, "splits": {"test": 2}}})
    assert not compare_vision(before, after)["held_out"]
    changed = source["test"].set_values("label", {0: 3})
    after.add_metrics({"example_id": [0, 1], "accuracy": [1., 1.]}, foreign_table_url=changed.url, constants={"split": "test", "epoch": 2})
    with pytest.raises(GranumError, match="same frozen"):
        compare_vision(before, after)


def test_semantic_comparison_pools_counts_and_rejects_duplicate_or_missing_observations(tmp_path):
    source = tables(tmp_path, semantic=True)
    before, after = pair(source, "semantic")
    before.add_metrics({"example_id": [0, 1], "mean_iou": [1., 0.],
        "class_3_intersection": [10, 0], "class_3_union": [10, 90],
        "class_7_intersection": [10, 0], "class_7_union": [10, 90]},
        foreign_table_url=source["test"].url, constants={"split": "test"})
    after.add_metrics({"example_id": [1, 0], "mean_iou": [.5, 1.],
        "class_3_intersection": [45, 10], "class_3_union": [90, 10],
        "class_7_intersection": [45, 10], "class_7_union": [90, 10]},
        foreign_table_url=source["test"].url, constants={"split": "test"})
    report = compare_vision(before, after)
    assert report["baseline"]["score"] == pytest.approx(.1)
    assert report["candidate"]["score"] == pytest.approx(.55)
    assert report["delta"] == pytest.approx(.45)
    after.add_metrics({"example_id": [0, 0], "mean_iou": [1., 1.]}, foreign_table_url=source["test"].url, constants={"split": "test", "epoch": 3})
    with pytest.raises(GranumError, match="exactly once"):
        compare_vision(before, after)


def test_comparison_requires_recorded_evaluation_policy(tmp_path):
    source = tables(tmp_path)
    before, after = pair(source, "classify")
    after.set_parameters({"evaluator": None})
    with pytest.raises(GranumError, match="record their evaluation rules"):
        compare_vision(before, after)


@pytest.mark.parametrize("semantic", [False, True])
def test_native_learning_history_preserves_epoch_predictions(tmp_path, isolated_project, semantic):
    from fastapi.testclient import TestClient

    from granum.core.index import Index
    from granum.service.app import create_app

    source = tables(tmp_path, semantic=semantic)
    task, metric = ("semantic", "mean_iou") if semantic else ("classify", "accuracy")
    run, _ = pair(source, task)
    for epoch in range(3):
        run.add_metrics({"example_id": [0, 1], metric: [1. if epoch else 0., 0.],
                         "predicted": [7, 3], "confidence": [.9, .6]},
                        foreign_table_url=source["test"].url, constants={"split": "test", "epoch": epoch})
    run.set_status("finished")
    index = Index([isolated_project])
    index.refresh()
    with TestClient(create_app(index=index, config=granum.get_config(), allowed_hosts=["testserver"], serve_dashboard=False)) as api:
        response = api.get("/api/run/learning", params={"url": str(run.url)})
        assert response.status_code == 200, response.text
        report = response.json()
        assert report["metric"] == metric
        assert len(report["splits"]) == 1
        assert len(report["splits"][0]["images"]) == 2
        assert all(row["category"] != "empty" for row in report["splits"][0]["images"])
        response = api.get("/api/run/image-rounds", params={"url": str(run.url), "table": str(source["test"].url), "example": 0})
        assert response.status_code == 200, response.text
        history = response.json()
        assert history["rounds"][0]["score"] == 0.
        assert history["rounds"][-1]["score"] == 1.
        if not semantic:
            assert history["label"] == 7
            assert history["rounds"][0]["predicted"] == 7
