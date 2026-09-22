"""Is this dataset fit to train on: the rules, and what they refuse to call fine."""

from granum.metrics.health import HealthPolicy, class_balance, report


def by_code(found):
    return {row["code"]: row for row in found["checks"]}


def healthy():
    return {
        "images": 1000,
        "sets": {"train": 800, "valid": 200},
        "class_counts": {0: 900, 1: 700},
        "class_names": {0: "car", 1: "van"},
        "graph": {"leaks": 0, "redundant": 2, "alone": 3},
        "findings": {"images": 0, "counts": {}, "from": "check-1"},
        "verified": 900,
        "boxes": 1600,
        "drafted_boxes": 0,
    }


def test_a_good_dataset_reads_as_ready():
    found = report(healthy())
    assert found["verdict"] == "ok"
    assert {row["severity"] for row in found["checks"]} == {"ok"}


def test_no_held_out_set_is_a_reason_not_to_train():
    found = report({**healthy(), "sets": {"train": 1000}})
    assert found["verdict"] == "block"
    assert by_code(found)["holdout"]["severity"] == "block"


def test_a_leak_blocks_and_a_few_repeats_do_not():
    found = by_code(report({**healthy(), "graph": {"leaks": 12, "redundant": 2, "alone": 0}}))
    assert found["leaks"]["severity"] == "block" and found["leaks"]["value"] == 12
    assert found["copies"]["severity"] == "ok"

    many = by_code(report({**healthy(), "graph": {"leaks": 0, "redundant": 300, "alone": 0}}))
    assert many["copies"]["severity"] == "warn"


def test_a_class_with_almost_nothing_in_it_is_named():
    found = report({**healthy(), "class_counts": {0: 900, 1: 12}, "class_names": {0: "car", 1: "bus"}})
    row = by_code(found)["classes"]
    assert row["severity"] == "warn" and "bus" in row["detail"]
    assert found["verdict"] == "warn"


def test_a_class_can_be_large_and_still_too_rare_beside_the_biggest():
    balance = class_balance({0: 100_000, 1: 800}, {0: "car", 1: "bus"})
    assert [row["verdict"] for row in balance] == ["ok", "rare"]
    # ...and not rare when the set is smaller, because the comparison is the point.
    assert [row["verdict"] for row in class_balance({0: 900, 1: 800})] == ["ok", "ok"]


def test_what_nobody_looked_at_is_not_reported_as_fine():
    found = by_code(report({**healthy(), "graph": None, "findings": None}))
    assert found["copies"]["severity"] == "warn" and found["copies"]["value"] is None
    assert found["findings"]["severity"] == "warn" and "needs no training" in found["findings"]["detail"]


def test_drafts_nobody_checked_are_flagged_in_proportion():
    lots = by_code(report({**healthy(), "drafted_boxes": 900}))
    assert lots["drafts"]["severity"] == "warn"
    few = by_code(report({**healthy(), "drafted_boxes": 5}))
    assert few["drafts"]["severity"] == "ok"


def test_the_thresholds_can_be_argued_with():
    strict = HealthPolicy(min_holdout=500)
    assert by_code(report(healthy(), strict))["holdout"]["severity"] == "warn"


def test_an_empty_dataset_does_not_raise():
    found = report({"images": 0, "sets": {}, "class_counts": {}})
    assert found["verdict"] == "block"
