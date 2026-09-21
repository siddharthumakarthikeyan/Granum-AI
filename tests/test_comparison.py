"""Comparing two runs (EV06/EV11): pairing, refusals, slices, and the data change.

The rules under test are the ones that decide whether a difference may be shown at all,
and the ones that decide which images moved. Both are easy to get quietly wrong: pairing
by row position instead of by image, or averaging over a set the two runs do not share.
"""

import pytest
from fastapi.testclient import TestClient

import granum
from granum import BoundingBoxes2D, Table
from granum.core.index import Index
from granum.core.objects.run import set_active_run
from granum.core.url import Url
from granum.metrics import DetectionMetricsCollector, collect_metrics
from granum.metrics.comparison import (
    class_slices,
    compare_samples,
    compatibility_checks,
    headline,
    image_outcome,
    interpretation,
    label_change,
    review_cost,
    size_slices,
)
from granum.service.app import create_app


def counts(tp, fp, fn, example_id=0):
    return {"tp": tp, "fp": fp, "fn": fn, "example_id": example_id}


# -- per-image outcomes -----------------------------------------------------


def test_every_image_lands_in_exactly_one_outcome():
    baseline = {"a.png": counts(2, 0, 2), "b.png": counts(3, 1, 0), "c.png": counts(1, 0, 0), "gone.png": counts(0, 0, 1)}
    candidate = {"a.png": counts(4, 0, 0), "b.png": counts(1, 1, 2), "c.png": counts(1, 0, 0), "new.png": counts(2, 0, 0)}
    result = compare_samples(baseline, candidate)
    assert result["counts"] == {"improved": 1, "regressed": 1, "unchanged": 1,
                                "only_baseline": 1, "only_candidate": 1}
    assert result["only_baseline"] == ["gone.png"] and result["only_candidate"] == ["new.png"]
    # Pooled over the images each run was scored on, and over the shared ones separately:
    # the unmatched images are not silently folded into the comparison.
    assert result["baseline"]["images"] == 4 and result["shared"]["baseline"]["images"] == 3
    assert result["shared"]["baseline"]["labels"] == (2 + 2) + 3 + 1  # tp + fn, over the shared images
    # Biggest move first, whichever way it went: a regression is not sorted below a gain.
    assert result["images"][0]["image"] == "b.png" and result["images"][0]["delta_f1"] < 0


def test_images_pair_by_image_not_by_row():
    # The candidate's set dropped a row, so every position after it moved.
    baseline = {"a.png": counts(1, 0, 0, 0), "b.png": counts(0, 0, 1, 1), "c.png": counts(1, 0, 0, 2)}
    candidate = {"b.png": counts(1, 0, 0, 0), "c.png": counts(1, 0, 0, 1)}
    result = compare_samples(baseline, candidate)
    moved = next(row for row in result["images"] if row["image"] == "b.png")
    assert moved["outcome"] == "improved"
    assert moved["baseline"]["example_id"] == 1 and moved["candidate"]["example_id"] == 0
    assert result["counts"]["only_baseline"] == 1


def test_a_trade_is_not_unchanged():
    # Same F1, different mistakes: one miss traded for one false positive.
    assert image_outcome(counts(1, 0, 1), counts(1, 1, 0)) == "improved"
    assert image_outcome(counts(1, 1, 0), counts(1, 0, 1)) == "regressed"
    assert image_outcome(counts(2, 1, 1), counts(2, 1, 1)) == "unchanged"


# -- compatibility ----------------------------------------------------------


def side(**changes):
    base = {
        "set": "streets/valid",
        "table": "file:///p/valid/v2",
        "table_name": "v2",
        "evaluator": {"scorer": "granum-detection-1", "operating_confidence": 0.25, "match_iou": 0.5},
        "classes": {"0": "car"},
        "recipe": {"framework": "yolo", "version": "yolo26n.pt", "epochs": 12, "imgsz": 640, "batch": 16},
        "seed": 0,
    }
    return {**base, **changes}


def status_of(checks, name):
    return next(c["status"] for c in checks if c["check"] == name)


def test_different_evaluation_sets_are_refused():
    checks = compatibility_checks(side(), side(set="streets/test"))
    assert status_of(checks, "evaluation_set") == "blocked"
    assert interpretation(checks, data_changed=False)["kind"] == "blocked"
    # Nothing further is checked once the comparison is meaningless.
    assert [c["check"] for c in checks] == ["evaluation_set"]


def test_different_scoring_rules_are_refused():
    checks = compatibility_checks(side(), side(evaluator={"scorer": "granum-detection-1",
                                                         "operating_confidence": 0.5, "match_iou": 0.5}))
    blocked = next(c for c in checks if c["check"] == "evaluator")
    assert blocked["status"] == "blocked" and blocked["fields"] == ["operating_confidence"]
    assert interpretation(checks, data_changed=True)["kind"] == "blocked"


def test_an_unrecorded_policy_is_a_warning_not_an_assumption():
    checks = compatibility_checks(side(evaluator={}), side())
    assert status_of(checks, "evaluator") == "warn"
    assert interpretation(checks, data_changed=False)["kind"] == "controlled"


def test_a_new_version_of_the_set_is_disclosed():
    checks = compatibility_checks(side(), side(table="file:///p/valid/v3", table_name="v3"))
    assert status_of(checks, "evaluation_version") == "warn"
    reading = interpretation(checks, data_changed=True)
    assert reading["kind"] == "observational"
    assert "not what any single edit caused" in reading["summary"]
    assert "the label, not the model" in reading["summary"]


def test_a_changed_recipe_is_disclosed_but_does_not_block():
    checks = compatibility_checks(side(), side(recipe={**side()["recipe"], "epochs": 60}))
    recipe = next(c for c in checks if c["check"] == "training_recipe")
    assert recipe["status"] == "warn" and recipe["fields"] == ["epochs"]
    assert interpretation(checks, data_changed=False)["kind"] == "controlled"
    assert "settings changed" in interpretation(checks, data_changed=False)["summary"]


def test_one_seed_each_is_never_called_conclusive():
    checks = compatibility_checks(side(), side())
    assert status_of(checks, "seeds") == "warn"
    assert headline({"map50": 0.80}, {"map50": 0.815})["verdict"] == "too close to call"
    assert headline({"map50": 0.80}, {"map50": 0.86})["verdict"] == "higher"
    assert headline({"map50": None}, {"map50": 0.86})["verdict"] == "not recorded"


# -- slices -----------------------------------------------------------------


def record(truth, predicted, matches):
    return {
        "truth": {"instances": truth},
        "predicted": {"instances": predicted},
        "gt_match": matches,
    }


def label(x0, y0, x1, y1, klass=0):
    return {"vertices": [x0, y0, x1, y1], "label": klass}


def guess(x0, y0, x1, y1, klass=0, confidence=0.9, matched=True):
    return {"vertices": [x0, y0, x1, y1], "label": klass, "confidence": confidence,
            "matched": matched, "ignored": False}


def test_class_slices_carry_their_support():
    truth = [label(0, 0, 10, 10, 0), label(20, 20, 30, 30, 1)]
    before = record(truth, [guess(0, 0, 10, 10, 0)], [0, -1])
    after = record(truth, [guess(0, 0, 10, 10, 0), guess(20, 20, 30, 30, 1)], [0, 1])
    rows = {row["name"]: row for row in class_slices([(before, after)], names={0: "car", 1: "bus"})}
    assert rows["bus"]["baseline"]["recall"] == 0.0 and rows["bus"]["candidate"]["recall"] == 1.0
    assert rows["bus"]["support"] == 1 and rows["bus"]["conclusive"] is False
    assert rows["car"]["delta"] == 0.0


def test_a_label_found_only_below_the_operating_point_is_not_found():
    truth = [label(0, 0, 10, 10)]
    shy = record(truth, [guess(0, 0, 10, 10, confidence=0.1)], [0])
    sure = record(truth, [guess(0, 0, 10, 10, confidence=0.9)], [0])
    row = class_slices([(shy, sure)])[0]
    assert row["baseline"]["fn"] == 1 and row["candidate"]["tp"] == 1


def test_size_slices_split_by_object_area():
    truth = [label(0, 0, 10, 10), label(0, 0, 200, 200)]
    before = record(truth, [guess(0, 0, 10, 10)], [0, -1])
    after = record(truth, [guess(0, 0, 200, 200)], [-1, 0])
    rows = {row["key"]: row for row in size_slices([(before, after)])}
    assert set(rows) == {"small", "large"}
    assert rows["small"]["baseline"]["recall"] == 1.0 and rows["small"]["candidate"]["recall"] == 0.0
    assert rows["large"]["metric"] == "recall"


# -- what changed in the data -----------------------------------------------


def boxes(*instances):
    return {"width": 100, "height": 100, "instances": list(instances)}


def test_label_change_tells_a_relabel_from_a_delete_and_an_add():
    before = {
        "same.png": boxes(label(0, 0, 10, 10)),
        "relabelled.png": boxes(label(0, 0, 10, 10, 0)),
        "tightened.png": boxes(label(0, 0, 40, 40)),
        "dropped.png": boxes(label(0, 0, 10, 10)),
    }
    after = {
        "same.png": boxes(label(0, 0, 10, 10)),
        "relabelled.png": boxes(label(0, 0, 10, 10, 1)),
        "tightened.png": boxes(label(0, 0, 30, 30)),
        "added.png": boxes(label(5, 5, 15, 15)),
    }
    change = label_change(before, after)
    assert change["boxes_relabelled"] == 1 and change["boxes_moved"] == 1
    assert change["boxes_added"] == 0 and change["boxes_removed"] == 0
    assert change["images_added"] == 1 and change["images_removed"] == 1
    assert change["removed"] == ["dropped.png"] and change["added"] == ["added.png"]
    assert {row["image"] for row in change["edited"]} == {"relabelled.png", "tightened.png"}


def test_an_untouched_box_is_never_a_delete_and_an_add():
    # The example dataset plants a box with no width: it has no area, so overlap alone
    # cannot pair it with its own copy in the next version.
    flat = {"vertices": [10, 10, 10, 30], "label": 0}
    before = {"a.png": boxes(flat, label(0, 0, 10, 10)), "gone.png": boxes(label(0, 0, 10, 10), label(20, 20, 30, 30))}
    after = {"a.png": boxes(flat, label(0, 0, 10, 10))}
    change = label_change(before, after)
    assert change["images_edited"] == 0
    assert change["boxes_added"] == 0 and change["boxes_removed"] == 0
    # The boxes that left with a whole image are counted apart, so the totals add up.
    assert change["boxes_with_removed_images"] == 2
    assert change["boxes_baseline"] - change["boxes_with_removed_images"] == change["boxes_candidate"]


def test_a_box_that_moved_far_reads_as_one_removed_and_one_added():
    before = {"a.png": boxes(label(0, 0, 10, 10))}
    after = {"a.png": boxes(label(80, 80, 90, 90))}
    change = label_change(before, after)
    assert change["boxes_removed"] == 1 and change["boxes_added"] == 1 and change["boxes_moved"] == 0


# -- cost -------------------------------------------------------------------


def test_review_cost_counts_only_the_window_between_the_runs():
    events = [
        {"time": "2026-09-01T10:00:00+00:00", "sample": "a.png", "status": "corrected", "reviewer": "sid"},
        {"time": "2026-09-05T10:00:00+00:00", "sample": "a.png", "status": "correct", "reviewer": "sid"},
        {"time": "2026-09-05T11:00:00+00:00", "sample": "b.png", "status": "excluded", "reviewer": "mel"},
        {"time": "2026-09-09T10:00:00+00:00", "sample": "c.png", "status": "correct", "reviewer": "sid"},
    ]
    cost = review_cost(events, since="2026-09-02T00:00:00+00:00", until="2026-09-08T00:00:00+00:00")
    assert cost["observed"]["decisions"] == 2 and cost["observed"]["images"] == 2
    assert cost["observed"]["reviewers"] == ["mel", "sid"]
    assert cost["observed"]["by_status"] == {"correct": 1, "excluded": 1}
    assert "20 seconds per decision" in cost["estimated"]["basis"]


# -- end to end through the service -----------------------------------------


def P(name):
    return str(Url(f"/compare/{name}.png"))


IMAGES = ["a", "b", "c", "d"]


@pytest.fixture(autouse=True)
def clear_active_run():
    set_active_run(None)
    yield
    set_active_run(None)


def valid_table(name="valid", images=IMAGES):
    return Table.from_dict_data(
        {"image": [P(i) for i in images],
         "bbs": [{"width": 100, "height": 100, "instances": [{"vertices": [10, 10, 30, 30], "label": 0}]}
                 for _ in images]},
        schema={"bbs": BoundingBoxes2D.schema(["car"])},
        project_name="compare", dataset_name="streets", table_name=name,
    )


def trained_run(name, table, found, *, parameters=None, split="valid"):
    """A run that found the boxes of the images in ``found`` and missed the rest."""
    run = granum.init("compare", name, parameters={
        "framework": "yolo", "version": "yolo26n.pt", "epochs": 2, "imgsz": 640, "batch": 16, "seed": 0,
        "evaluator": {"scorer": "granum-detection-1", "operating_confidence": 0.25, "match_iou": 0.5},
        "train_table": str(table.url), "score_map50": 0.5,
        **(parameters or {}),
    })

    def predictor(batch):
        out = []
        for path in batch["image"]:
            hit = any(P(i) == path for i in found)
            out.append({"boxes": [[10, 10, 30, 30]] if hit else [], "scores": [0.9] if hit else [],
                        "labels": [0] if hit else []})
        return out

    collect_metrics(table, [DetectionMetricsCollector("bbs", value_map=table.schema["bbs"].value_map)],
                    predictor=predictor, constants={"epoch": 0}, split=split, batch_size=2, run=run)
    return run


@pytest.fixture
def two_runs():
    table = valid_table()
    baseline = trained_run("baseline", table, ["a", "b"])
    candidate = trained_run("candidate", table, ["a", "b", "c"])
    index = Index([granum.get_config().project_root])
    index.refresh()
    api = TestClient(create_app(index=index, config=granum.get_config(), allowed_hosts=["testserver"],
                                serve_dashboard=False))
    return api, table, baseline, candidate


def compare(api, baseline, candidate, **params):
    response = api.get("/api/runs/compare",
                       params={"baseline": str(baseline.url), "candidate": str(candidate.url), **params})
    assert response.status_code == 200, response.text
    return response.json()


def test_the_report_names_what_moved_and_on_which_images(two_runs):
    api, table, baseline, candidate = two_runs
    report = compare(api, baseline, candidate)
    assert report["split"] == "valid" and report["interpretation"]["kind"] == "controlled"
    assert report["samples"]["counts"] == {"improved": 1, "regressed": 0, "unchanged": 3,
                                            "only_baseline": 0, "only_candidate": 0}
    improved = next(row for row in report["samples"]["images"] if row["outcome"] == "improved")
    assert improved["image"] == P("c")
    assert report["samples"]["shared"]["candidate"]["tp"] == 3
    assert report["training_data"]["identical"] is True
    assert report["evaluation_data"]["identical"] is True
    assert report["slices"]["classes"][0]["name"] == "car"
    assert report["slices"]["classes"][0]["delta"] > 0
    assert report["cost"]["candidate"]["recipe"]["epochs"] == 2


def test_runs_scored_on_different_sets_are_refused(two_runs):
    api, table, baseline, _ = two_runs
    other = valid_table("holdout", images=["e", "f"])
    elsewhere = trained_run("elsewhere", other, ["e"], split="valid")
    Index([granum.get_config().project_root]).refresh()
    report = compare(api, baseline, elsewhere)
    assert report["interpretation"]["kind"] == "blocked"
    assert report["interpretation"]["blocked"] == ["evaluation_set"]
    assert "samples" not in report and "slices" not in report


def test_a_changed_evaluation_set_is_compared_and_disclosed(two_runs):
    api, table, baseline, _ = two_runs
    # The same set, one image's label corrected and one image removed.
    fixed = table.delete_rows([3]).apply_edits(values={"bbs": {0: {
        "width": 100, "height": 100, "instances": [{"vertices": [12, 12, 32, 32], "label": 0}]}}})
    later = trained_run("later", fixed, ["a", "b", "c"], parameters={"score_map50": 0.9})
    Index([granum.get_config().project_root]).refresh()
    report = compare(api, baseline, later)
    assert report["interpretation"]["kind"] == "observational"
    version = next(c for c in report["checks"] if c["check"] == "evaluation_version")
    assert version["status"] == "warn"
    assert report["samples"]["counts"]["only_baseline"] == 1  # the removed image, not averaged away
    assert report["evaluation_data"]["boxes_moved"] == 1
    assert report["evaluation_data"]["images_removed"] == 1
    assert report["headline"]["verdict"] == "higher"


def test_the_report_downloads_whole(two_runs):
    api, table, baseline, candidate = two_runs
    response = api.get("/api/runs/compare", params={"baseline": str(baseline.url), "candidate": str(candidate.url),
                                                    "download": True, "limit": 1})
    assert response.status_code == 200
    assert "attachment" in response.headers["content-disposition"]
    report = response.json()
    assert report["report_version"] and report["policy"]["operating_confidence"] == 0.25
    assert len(report["samples"]["images"]) == 4  # limit does not apply to the file


def test_a_run_cannot_be_compared_with_itself(two_runs):
    api, table, baseline, _ = two_runs
    response = api.get("/api/runs/compare", params={"baseline": str(baseline.url), "candidate": str(baseline.url)})
    assert response.status_code == 400
