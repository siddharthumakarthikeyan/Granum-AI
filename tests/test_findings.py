"""Findings rules on hand-made rounds: each rule fires where it should and nowhere else."""

from granum.metrics.findings import FindingPolicy, image_findings

TRUTH = [
    {"vertices": [10, 10, 30, 30], "label": 0, "annotation_id": 100},  # found every round
    {"vertices": [50, 50, 70, 70], "label": 1, "annotation_id": 101},  # the model calls it class 2
    {"vertices": [100, 100, 140, 140], "label": 0, "annotation_id": 102},  # the model's box is much smaller
    {"vertices": [200, 10, 220, 30], "label": 1, "annotation_id": 103},  # never found
    {"vertices": [0, 0, 300, 300], "label": 0, "iscrowd": True},  # area to skip
]


def prediction(box, label, confidence, matched=False):
    return {"vertices": box, "label": label, "confidence": confidence, "matched": matched, "ignored": False}


def round_record(extra=True, wrong=True):
    predicted = [prediction([10, 10, 30, 30], 0, 0.9, matched=True)]
    if wrong:
        predicted.append(prediction([50, 50, 70, 71], 2, 0.8))
    predicted.append(prediction([100, 100, 120, 120], 0, 0.7))  # IoU 0.25 with its label
    if extra:
        predicted.append(prediction([150, 150, 170, 170], 1, 0.6))  # nothing labelled there
    predicted.append(prediction([250, 250, 260, 260], 0, 0.3))  # not confident: never counts
    return {"bbs_predicted": {"instances": predicted}, "gt_match": [0, -1, -1, -1, -2]}


def test_each_rule_fires_on_its_case():
    rounds = {e: round_record() for e in range(8)}
    findings, info = image_findings(TRUTH, rounds)
    assert info == {"observed": 8, "window": 6, "from_epoch": 2}  # the first quarter is warm-up
    by_rule = {f["rule"]: f for f in findings}
    assert set(by_rule) == {"missing_label", "wrong_class", "loose_box", "missed"}

    missing = by_rule["missing_label"]
    assert missing["box"] == [150, 150, 170, 170] and missing["label"] is None and missing["predicted_label"] == 1
    assert missing["rounds"] == 6 and missing["confidence"] == [0.6, 0.6]

    wrong = by_rule["wrong_class"]
    assert wrong["truth_index"] == 1 and wrong["annotation_id"] == 101
    assert wrong["label"] == 1 and wrong["predicted_label"] == 2

    loose = by_rule["loose_box"]
    assert loose["truth_index"] == 2 and 0.2 < loose["iou"] < 0.3

    missed = by_rule["missed"]
    assert missed["truth_index"] == 3 and missed["confidence"] is None
    # Explained labels are not also reported as simply missed, and skip areas never are.
    assert [f["truth_index"] for f in findings if f["rule"] == "missed"] == [3]
    # Strongest first: a confident wrong class outranks a missed label seen as often.
    assert findings[0]["rule"] == "wrong_class" and findings[-1]["rule"] == "missed"


def test_a_finding_must_recur():
    # The unlabelled object shows up once in eight rounds: noise, not a finding.
    rounds = {e: round_record(extra=(e == 5)) for e in range(8)}
    rules = {f["rule"] for f in image_findings(TRUTH, rounds)[0]}
    assert "missing_label" not in rules


def test_a_learned_label_error_fades_but_is_still_reported():
    # The model disagrees with the class mid-run, then learns the label as it is.
    rounds = {e: round_record(wrong=e < 6) for e in range(12)}
    wrong = next(f for f in image_findings(TRUTH, rounds)[0] if f["rule"] == "wrong_class")
    assert wrong["rounds"] == 3 and wrong["in_last_round"] is False and wrong["last_epoch"] == 5


def test_rounds_without_stored_boxes_are_not_evidence():
    rounds = {e: {"bbs_predicted": None, "gt_match": None} for e in range(10)}
    findings, info = image_findings(TRUTH, rounds)
    assert findings == [] and info["observed"] == 0


def test_the_policy_is_honoured():
    rounds = {e: round_record() for e in range(8)}
    strict = FindingPolicy(confident=0.95)
    rules = {f["rule"] for f in image_findings(TRUTH, rounds, strict)[0]}
    assert rules == {"missed"}  # nothing is confident enough to explain anything


def test_judging_starts_when_the_set_is_learned():
    from granum.metrics.findings import competent_from

    # Recall climbs 0.1, 0.5, 0.92, 1.0, 0.95: competent (90% of best) from epoch 2.
    per_epoch = {0: (1, 9), 1: (5, 5), 2: (92, 8), 3: (100, 0), 4: (95, 5)}
    records = [{"epoch": e, "tp": tp, "fn": fn} for e, (tp, fn) in per_epoch.items()]
    assert competent_from(records) == 2
    assert competent_from([{"epoch": 0, "tp": 0, "fn": 3}]) is None

    rounds = {e: round_record() for e in range(8)}
    _, info = image_findings(TRUTH, rounds, from_epoch=5)
    assert info["window"] == 3 and info["from_epoch"] == 5


def test_a_merely_missed_label_needs_half_the_rounds():
    # The never-found label is found in 4 of 6 judged rounds: missed in only 2 (a third).
    rounds = {e: round_record() for e in range(8)}
    for e in (2, 3, 4, 5):
        rounds[e] = {**rounds[e], "gt_match": [0, -1, -1, 3, -2]}
    rules = [f["rule"] for f in image_findings(TRUTH, rounds)[0]]
    assert "missed" not in rules


# -- one pass: the same rules without rounds to lean on --------------------------


def test_one_pass_fires_the_same_rules_and_ranks_by_confidence():
    """A screening sees each case once, so its order is what the model is sure of."""
    from granum.metrics.findings import pass_findings

    findings = pass_findings(TRUTH, round_record())
    by_rule = {f["rule"]: f for f in findings}
    assert set(by_rule) == {"missing_label", "wrong_class", "loose_box", "missed"}
    # Evidence is one round, and says so rather than implying a run's worth.
    assert all(f["rounds"] == 1 and f["window"] == 1 and f["share"] == 1.0 for f in findings)

    # An invented box and a swapped class are worth the model's own confidence.
    assert by_rule["missing_label"]["score"] == 0.6
    assert by_rule["missing_label"]["box"] == [150, 150, 170, 170]
    assert by_rule["wrong_class"]["score"] == 0.8
    assert by_rule["wrong_class"]["predicted_label"] == 2 and by_rule["wrong_class"]["label"] == 1
    # A loose box at IoU 0.25 against a 0.5 match: half the fit missing, at 0.7 confidence.
    assert by_rule["loose_box"]["iou"] == 0.25
    assert by_rule["loose_box"]["score"] == 0.35
    # A label the model merely fails to find carries no confidence of its own.
    assert by_rule["missed"]["score"] == 0.25
    assert by_rule["missed"]["confidence"] is None
    assert [f["rule"] for f in findings] == ["wrong_class", "missing_label", "loose_box", "missed"]


def test_one_pass_leaves_a_well_labelled_image_alone():
    from granum.metrics.findings import pass_findings

    clean = {"bbs_predicted": {"instances": [prediction([10, 10, 30, 30], 0, 0.9, matched=True)]},
             "gt_match": [0, 0, 0, 0, -2]}
    assert pass_findings(TRUTH[:1], clean) == []


def test_one_pass_ignores_predictions_below_the_confidence_it_trusts():
    from granum.metrics.findings import FindingPolicy, pass_findings

    quiet = {"bbs_predicted": {"instances": [prediction([150, 150, 170, 170], 1, 0.4)]}, "gt_match": [0]}
    assert pass_findings([TRUTH[0]], {**quiet, "gt_match": [0]}) == []
    # ...unless the reader asks it to trust less confident ones.
    found = pass_findings([TRUTH[0]], {**quiet, "gt_match": [0]}, FindingPolicy(confident=0.3))
    assert [f["rule"] for f in found] == ["missing_label"]


def test_trust_is_decided_by_the_worst_box_not_the_average():
    """Forty right boxes do not make one badly wrong box acceptable."""
    from granum.metrics.findings import image_trust

    bad = [{"rule": "wrong_class", "truth_index": 0, "score": 0.9}]
    assert image_trust([], 40) == 1.0
    assert image_trust(bad, 40) < 0.2           # the mean of 40 boxes would be 0.98
    assert image_trust(bad, 1) < image_trust([{**bad[0], "score": 0.5}], 1)
    # A box the model says is missing counts as a box, so an image with no labels can fall.
    assert image_trust([{"rule": "missing_label", "truth_index": None, "score": 0.8}], 0) < 0.3
    assert image_trust([], 0) == 1.0


def test_a_model_is_not_asked_about_classes_it_was_never_taught():
    """A pretrained model that knows four of eleven classes must not report the other seven
    as labels it failed to find: its silence there is ignorance, not evidence."""
    from granum.metrics.findings import pass_findings

    nothing_found = {"bbs_predicted": {"instances": []}, "gt_match": [-1, -1, -1, -1, -2]}
    assert len(pass_findings(TRUTH, nothing_found)) == 4          # every label, judged
    assert [f["label"] for f in pass_findings(TRUTH, nothing_found, known={0})] == [0, 0]

    # Nor is a label of an unknown class something it can have put the wrong class on.
    swapped = {"bbs_predicted": {"instances": [prediction([50, 50, 70, 71], 2, 0.8)]},
               "gt_match": [-1, -1, -1, -1, -2]}
    assert any(f["rule"] == "wrong_class" for f in pass_findings(TRUTH, swapped))
    assert not any(f["rule"] == "wrong_class" for f in pass_findings(TRUTH, swapped, known={0, 2}))


# -- a label check, read through the service -------------------------------------


def screened(tmp_path):
    """A project whose labels one model has read once: what a screening records."""
    from fastapi.testclient import TestClient

    import granum
    from granum import BoundingBoxes2D, Table
    from granum.core.index import Index
    from granum.core.url import Url
    from granum.metrics import DetectionMetricsCollector, collect_metrics
    from granum.service.app import create_app

    def path(name):
        return str(Url(f"/checked/{name}.png"))

    table = Table.from_dict_data(
        {"image": [path(i) for i in range(3)],
         "bbs": [
             # Right: the model finds it. Wrong class: the model says dog. Missed: nothing found.
             {"width": 100, "height": 100, "instances": [{"vertices": [10, 10, 30, 30], "label": 0}]},
             {"width": 100, "height": 100, "instances": [{"vertices": [40, 40, 60, 60], "label": 0}]},
             {"width": 100, "height": 100, "instances": [{"vertices": [70, 70, 90, 90], "label": 1}]},
         ]},
        schema={"bbs": BoundingBoxes2D.schema(["car", "dog"])},
        project_name="checked", dataset_name="streets", table_name="valid",
    )
    predictions = {
        path(0): {"boxes": [[10, 10, 30, 30]], "scores": [0.95], "labels": [0]},
        path(1): {"boxes": [[40, 40, 60, 60]], "scores": [0.8], "labels": [1]},
        path(2): {"boxes": [], "scores": [], "labels": []},
    }
    # A screening is a run with one round of predictions per set, and says which it is.
    run = granum.init("checked", "check-1", parameters={
        "kind": "screening", "framework": "yolo", "version": "yolo26m.pt",
        "screened_with": "trained", "screened_from_run": "run-1", "tracks_learning": True,
        "covers_all_classes": True,
    })
    collect_metrics(table, [DetectionMetricsCollector("bbs", value_map=table.schema["bbs"].value_map)],
                    predictor=lambda batch: [predictions[p] for p in batch["image"]],
                    constants={"epoch": 0, "split": "valid"}, batch_size=2)
    run.set_status("finished")
    index = Index([granum.get_config().project_root])
    index.refresh()
    api = TestClient(create_app(index=index, config=granum.get_config(),
                                allowed_hosts=["testserver"], serve_dashboard=False))
    return api, run, path


def test_one_pass_is_read_as_a_check_not_as_a_run(isolated_project, tmp_path):
    api, run, path = screened(tmp_path)
    report = api.get("/api/run/findings", params={"url": str(run.url)}).json()

    assert report["kind"] == "screening"
    assert report["model"]["with"] == "trained" and report["model"]["from_run"] == "run-1"
    split = report["splits"][0]
    # One round of boxes is one pass: no warm-up was skipped and no epoch is claimed.
    assert split["single_pass"] is True and split["observed"] == 1 and split["competent_from"] is None

    flagged = {item["image"]: item for item in split["images"]}
    assert path(0) not in flagged                      # labelled right, found right
    assert flagged[path(1)]["findings"][0]["rule"] == "wrong_class"
    assert flagged[path(2)]["findings"][0]["rule"] == "missed"
    # Trust is a number per image, and the confidently-swapped label is the worse of the two.
    assert flagged[path(1)]["trust"] < flagged[path(2)]["trust"] < 1.0
