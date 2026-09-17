import math

import numpy as np
import pytest

import granum
from granum import Table
from granum.core.objects.run import set_active_run
from granum.metrics import (
    ClassificationMetricsCollector,
    collect_metrics,
    compute_dynamics,
    epoch_summary,
    training_dynamics,
)


def rec(example, epoch, correct, p, confidence=0.9, margin=None, src=0):
    record = {"example_id": example, "epoch": epoch, "accuracy": 1.0 if correct else 0.0,
              "loss": -math.log(p), "confidence": confidence, "_src": src}
    if margin is not None:
        record["margin"] = margin
    return record


def test_learned_epoch_forgetting_and_statistics():
    records = [
        # sample 0: right from the start
        rec(0, 0, True, 0.9), rec(0, 1, True, 0.9), rec(0, 2, True, 0.9),
        # sample 1: learned at epoch 2 after forgetting once
        rec(1, 0, True, 0.6), rec(1, 1, False, 0.3), rec(1, 2, True, 0.9),
        # sample 2: never learned
        rec(2, 0, False, 0.1), rec(2, 1, True, 0.5), rec(2, 2, False, 0.1),
    ]
    stats = compute_dynamics(records)
    assert stats[(0, 0)]["learned_epoch"] == 0 and stats[(0, 0)]["forgetting_events"] == 0
    assert stats[(0, 1)]["learned_epoch"] == 2 and stats[(0, 1)]["forgetting_events"] == 1
    assert stats[(0, 2)]["learned_epoch"] is None and stats[(0, 2)]["learning_speed"] == "not stable by end"
    assert stats[(0, 1)]["mean_true_probability"] == pytest.approx(0.6)
    assert stats[(0, 1)]["variability"] == pytest.approx(np.std([0.6, 0.3, 0.9]))
    assert stats[(0, 2)]["correctness"] == pytest.approx(1 / 3)


def test_learning_speed_is_relative_to_the_run():
    records = []
    for example, learned in enumerate([0, 1, 1, 1, 1, 3]):
        for epoch in range(4):
            records.append(rec(example, epoch, epoch >= learned, 0.9 if epoch >= learned else 0.2))
    speeds = {k[1]: v["learning_speed"] for k, v in compute_dynamics(records).items()}
    assert speeds[0] == "early" and speeds[5] == "late" and speeds[2] == "on time"


def test_unstable_needs_repeated_forgetting():
    records = [rec(0, e, c, 0.5) for e, c in enumerate([True, False, True, False, True])]
    assert compute_dynamics(records)[(0, 0)]["forgetting_events"] == 2
    assert compute_dynamics(records)[(0, 0)]["unstable"] is True


def test_uncertain_uses_margin_then_confidence():
    records = [
        rec(0, 0, True, 0.5, confidence=0.95, margin=0.1),   # margin small: unsure
        rec(0, 1, True, 0.5, confidence=0.40),               # no margin: low confidence
        rec(0, 2, True, 0.9, confidence=0.95, margin=0.9),
    ]
    assert compute_dynamics(records)[(0, 0)]["uncertain_epochs"] == [0, 1]


def test_sources_keep_train_and_val_apart():
    records = [rec(0, 0, True, 0.9, src="train"), rec(0, 0, False, 0.1, src="val")]
    stats = compute_dynamics(records)
    assert stats[("train", 0)]["correctness"] == 1.0 and stats[("val", 0)]["correctness"] == 0.0


def test_epoch_summary_counts():
    records = [
        rec(0, 0, False, 0.1, confidence=0.9), rec(0, 1, True, 0.9, confidence=0.9),
        rec(1, 0, True, 0.4, confidence=0.4), rec(1, 1, True, 0.9, confidence=0.9),
    ]
    summary = epoch_summary(records)
    assert summary[0] == {"epoch": 0, "evaluated": 2, "confident_correct": 0, "uncertain": 1, "confident_wrong": 1, "newly_learned": 1}
    assert summary[1]["newly_learned"] == 1 and summary[1]["confident_correct"] == 2


def test_training_dynamics_from_a_real_collection():
    set_active_run(None)
    table = Table.from_dict_data({"x": [0, 1, 2], "label": [0, 1, 1]}, project_name="p", dataset_name="d")
    run = granum.init("p", "dyn")
    # epoch 0 gets sample 2 wrong; epoch 1 gets everything right
    outputs = {0: [[5.0, 0.0], [0.0, 5.0], [5.0, 0.0]], 1: [[5.0, 0.0], [0.0, 5.0], [0.0, 5.0]]}
    for epoch in (0, 1):
        collect_metrics(
            table, [ClassificationMetricsCollector(classes=["a", "b"])],
            model=lambda batch, e=epoch: np.array([outputs[e][x] for x in batch["x"]]),
            constants={"epoch": epoch}, split="train",
        )
    rows = {r["example_id"]: r for r in training_dynamics(run)}
    assert rows[2]["learned_epoch"] == 1 and rows[0]["learned_epoch"] == 0
    assert rows[0]["split"] == "train"
    assert 0 <= rows[0]["mean_true_probability"] <= 1
    set_active_run(None)


def test_ever_correct_is_separate_from_stable_by_end():
    """A sample learned and then forgotten is not the same as one never learned."""
    forgotten = [rec(0, e, c, 0.5) for e, c in enumerate([False, True, True, False])]
    never = [rec(1, e, False, 0.1) for e in range(4)]
    stats = compute_dynamics(forgotten + never)
    assert stats[(0, 0)]["ever_correct"] is True and stats[(0, 0)]["first_correct_epoch"] == 1
    assert stats[(0, 0)]["stable_by_end"] is False and stats[(0, 0)]["current_streak"] == 0
    assert stats[(0, 1)]["ever_correct"] is False and stats[(0, 1)]["first_correct_epoch"] is None
    assert stats[(0, 0)]["learning_speed"] == stats[(0, 1)]["learning_speed"] == "not stable by end"


def test_current_streak_counts_back_from_the_last_observation():
    records = [rec(0, e, c, 0.5) for e, c in enumerate([True, False, True, True, True])]
    stats = compute_dynamics(records)[(0, 0)]
    assert stats["current_streak"] == 3 and stats["stable_by_end"] is True and stats["learned_epoch"] == 2


def test_repeated_epoch_observations_count_once():
    """A resumed run re-evaluating epoch 1 must not invent a forgetting event."""
    records = [rec(0, 0, True, 0.9), rec(0, 1, False, 0.2), rec(0, 1, True, 0.9), rec(0, 2, True, 0.9)]
    stats = compute_dynamics(records)[(0, 0)]
    assert stats["observations"] == 3
    assert stats["forgetting_events"] == 0


def test_sparse_observations_disclose_their_gaps():
    records = [rec(0, e, True, 0.9) for e in (0, 5, 10)]
    stats = compute_dynamics(records)[(0, 0)]
    assert stats["max_epoch_gap"] == 5 and stats["first_epoch"] == 0 and stats["last_epoch"] == 10


def test_probability_from_loss_can_be_refused():
    records = [rec(0, e, True, 0.9) for e in range(3)]
    assert compute_dynamics(records)[(0, 0)]["probability_source"] == "loss"
    assert compute_dynamics(records, allow_loss_probability=False) == {}
    recorded = [{**r, "true_probability": 0.8} for r in records]
    stats = compute_dynamics(recorded, allow_loss_probability=False)[(0, 0)]
    assert stats["probability_source"] == "recorded" and stats["mean_true_probability"] == pytest.approx(0.8)


def test_image_learning_categories():
    from granum.metrics.dynamics import image_learning

    def series(example, scores, counts=(1, 0, 0)):
        tp, fp, fn = counts
        return [{"example_id": example, "epoch": e, "f1": s, "tp": tp, "fp": fp, "fn": fn, "_src": 0} for e, s in enumerate(scores)]

    records = (
        series(0, [0.9, 0.9, 0.9, 0.9])            # learned at once
        + series(1, [0.1, 0.6, 0.7, 0.8])           # learned in round 1
        + series(2, [0.1, 0.2, 0.3, 0.9])           # learned at the very end
        + series(3, [0.1, 0.7, 0.2, 0.3])           # learned, then lost
        + series(4, [0.1, 0.1, 0.2, 0.2])           # never
        + series(5, [1.0, 1.0, 1.0, 1.0], (0, 0, 0))  # nothing to find
        + series(6, [0.9, 0.2, 0.9, 0.2, 0.9])      # flip-flops but ends good
    )
    stats = image_learning(records)
    category = {k[1]: v["category"] for k, v in stats.items()}
    assert category == {0: "early", 1: "steady", 2: "late", 3: "forgotten", 4: "never", 5: "empty", 6: "forgotten"}
    assert stats[(0, 2)]["learned_epoch"] == 3 and stats[(0, 3)]["first_good_epoch"] == 1
    assert stats[(0, 6)]["forgetting_events"] == 2


def test_image_learning_counts_final_round_learners_as_late():
    # A short run: most images are learned only in the last round, so the upper quartile
    # sits on that round and nothing is learned "after" it.
    records = []
    learned_at = {0: 0, 1: 1, 2: 3, 3: 3, 4: 3, 5: 3}
    for example, first in learned_at.items():
        for epoch in range(4):
            records.append({"_src": "t", "example_id": example, "epoch": epoch, "tp": 1, "fp": 0, "fn": 0,
                            "f1": 1.0 if epoch >= first else 0.0})
    from granum.metrics.dynamics import image_learning

    category = {k[1]: v["category"] for k, v in image_learning(records).items()}
    assert category[0] == "early"
    assert category[5] == "late"
