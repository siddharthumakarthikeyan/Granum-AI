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
