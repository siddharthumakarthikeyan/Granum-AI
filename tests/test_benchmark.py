"""The benchmark harness must keep scoring correctly as detectors are added."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "examples"))

import importlib.util  # noqa: E402

spec = importlib.util.spec_from_file_location(
    "label_error_ranking",
    Path(__file__).resolve().parents[1] / "examples" / "03_label_error_ranking.py",
)
lern = importlib.util.module_from_spec(spec)
pytest.importorskip("torch")
spec.loader.exec_module(lern)


CORRUPTED = {1, 3, 5}


def test_precision_at_counts_hits_in_the_prefix():
    ranking = [1, 9, 3, 8, 7]
    assert lern.precision_at(ranking, CORRUPTED, 2) == 0.5
    assert lern.precision_at(ranking, CORRUPTED, 4) == 0.5


def test_recall_at_is_over_all_planted_errors():
    ranking = [1, 3, 9, 8, 5]
    assert lern.recall_at(ranking, CORRUPTED, 2) == pytest.approx(2 / 3)
    assert lern.recall_at(ranking, CORRUPTED, 5) == 1.0


def test_average_precision_is_one_for_a_perfect_ranking():
    assert lern.average_precision([1, 3, 5, 2, 4], CORRUPTED) == pytest.approx(1.0)


def test_average_precision_penalises_a_bad_ranking():
    perfect = lern.average_precision([1, 3, 5, 2, 4], CORRUPTED)
    poor = lern.average_precision([2, 4, 1, 3, 5], CORRUPTED)
    assert poor < perfect


def test_review_effort_is_the_rank_of_the_last_error():
    assert lern.review_effort([1, 3, 9, 8, 5], CORRUPTED) == 5
    assert lern.review_effort([1, 3, 5, 9, 8], CORRUPTED) == 3


def test_review_effort_at_partial_recall():
    assert lern.review_effort([9, 1, 8, 3, 5], CORRUPTED, target_recall=2 / 3) == 4


def test_detectors_all_return_a_full_permutation():
    rows = [
        {"example_id": i, "loss": float(i), "confidence": 1.0 - i / 10, "predicted": i % 3,
         "label": (i + 1) % 3}
        for i in range(10)
    ]
    for name, detector in lern.DETECTORS.items():
        ranking = detector(rows)
        assert sorted(ranking) == list(range(10)), f"{name} dropped or duplicated ids"


def test_by_loss_ranks_highest_loss_first():
    rows = [{"example_id": 0, "loss": 0.1}, {"example_id": 1, "loss": 9.0},
            {"example_id": 2, "loss": 3.0}]
    assert lern.by_loss(rows) == [1, 2, 0]


def test_confident_disagreement_puts_agreements_last():
    rows = [
        {"example_id": 0, "predicted": 1, "label": 1, "confidence": 0.99},  # agrees
        {"example_id": 1, "predicted": 2, "label": 0, "confidence": 0.60},  # disagrees
        {"example_id": 2, "predicted": 2, "label": 0, "confidence": 0.95},  # disagrees, surer
    ]
    assert lern.by_confident_disagreement(rows) == [2, 1, 0]


def test_planted_errors_are_actually_planted():
    table, corrupted = lern.build_corrupted_table(seed=0, samples=60, corrupt=5)
    assert len(corrupted) == 5
    assert len(table) == 60
    assert all(0 <= i < 60 for i in corrupted)


@pytest.mark.parametrize("seed", [0])
def test_loss_beats_random_end_to_end(seed):
    """The whole harness, small enough to run in CI."""
    rows, corrupted = lern.run_trial(seed, samples=120, corrupt=8, epochs=6)
    by_loss = lern.average_precision(lern.by_loss(rows), corrupted)
    by_random = lern.average_precision(lern.random_order(rows), corrupted)
    assert by_loss > by_random * 2
    assert lern.review_effort(lern.by_loss(rows), corrupted) < 120
