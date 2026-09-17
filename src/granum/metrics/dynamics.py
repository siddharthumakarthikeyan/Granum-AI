"""Training dynamics: how each sample was learned across epochs.

A single epoch's metrics say which samples the model gets wrong *now*. Tracking the same
sample across epochs says much more: whether it was learned early or late, whether the
model kept changing its mind, whether it was ever confident at all.

Samples the model has not stably learned by the end of training are where mislabelled
data concentrates -- a model struggles to settle on a label that is wrong. On CIFAR-10
with 300 planted label errors and 8 epochs, 259 of the 300 were not stable by the end,
against 21% of all samples. That makes them candidates for review, not errors: rare
valid examples and ambiguous images land there too.

Learning speed is judged relative to the run, not by fixed epoch numbers: a sample learned
at epoch 5 is late in a run where most samples are learned by epoch 2, and early in one
where most take ten. Fixed cut-offs (such as the cartography paper's variability of 0.2)
put nearly everything in one bucket when a model is trained from scratch for a few epochs.

(After Swayamdipta et al., *Dataset Cartography*, 2020, and Toneva et al., *An Empirical
Study of Example Forgetting*, 2019.)

Per sample:

``observations``           distinct epochs observed (repeats of one epoch count once)
``first_epoch``, ``last_epoch``  the observed range; ``max_epoch_gap`` the widest gap in it
``mean_true_probability``  average probability given to the labelled class
``variability``            its standard deviation across observations
``correctness``            fraction of observations predicted correctly
``ever_correct``           predicted correctly at least once
``first_correct_epoch``    the first observation predicted correctly; None if never
``current_streak``         correct observations in a row, counted back from the last one
``stable_by_end``          correct at the last observation (``current_streak > 0``)
``forgetting_events``      correct -> wrong transitions between consecutive *observations*;
                           with gaps between observed epochs, real forgetting can be higher
``learned_epoch``          retrospective: the first epoch from which every later observation
                           was correct; None when not stable by the end. It depends on
                           observations after it, so a live run can still revise it
``uncertain_epochs``       epochs where the model was unsure of its top prediction
``learning_speed``         early / on time / late (quartiles of this run's learned epochs) /
                           not stable by end -- which includes samples learned and then forgotten
``unstable``               forgotten at least ``unstable_forgetting`` times
``probability_source``     ``recorded`` or ``loss`` (see below)

A prediction is *uncertain* when the gap between the two most probable classes is below
``uncertain_margin``; runs recorded before ``margin`` existed fall back to the top
probability being below ``uncertain_confidence``.

The probability of the true label is read from ``true_probability`` when recorded, and
otherwise recovered from the cross-entropy ``loss`` as ``exp(-loss)``, so runs collected
before this module existed can be analysed without retraining. That recovery is only valid
for unweighted, hard-label cross-entropy -- not label smoothing, focal, weighted, mixup or
detection losses -- so pass ``allow_loss_probability=False`` for those, and samples without
a recorded probability are skipped rather than given a wrong one.
"""

from __future__ import annotations

import math
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

import numpy as np

#: Bumped whenever a statistic's meaning changes, so saved results say which rules made them.
DYNAMICS_VERSION = 2
NOT_STABLE = "not stable by end"
SPEEDS = ("early", "on time", "late", NOT_STABLE)


@dataclass(frozen=True)
class DynamicsThresholds:
    #: Forgetting events at or above this mark a sample unstable.
    unstable_forgetting: int = 2
    #: Top-1 minus top-2 probability below this is uncertain.
    uncertain_margin: float = 0.25
    #: Used when margin was not recorded: top probability below this is uncertain.
    uncertain_confidence: float = 0.6


def true_probability(record: dict[str, Any], *, allow_loss: bool = True) -> float | None:
    value = record.get("true_probability")
    if isinstance(value, (int, float)) and math.isfinite(value):
        return float(value)
    loss = record.get("loss")
    if allow_loss and isinstance(loss, (int, float)) and math.isfinite(loss):
        return float(math.exp(-loss))
    return None


def is_uncertain(record: dict[str, Any], thresholds: DynamicsThresholds = DynamicsThresholds()) -> bool | None:
    margin = record.get("margin")
    if isinstance(margin, (int, float)) and math.isfinite(margin):
        return bool(margin < thresholds.uncertain_margin)
    confidence = record.get("confidence")
    if isinstance(confidence, (int, float)) and math.isfinite(confidence):
        return bool(confidence < thresholds.uncertain_confidence)
    return None


def _correct(record: dict[str, Any]) -> bool | None:
    accuracy = record.get("accuracy")
    if isinstance(accuracy, (int, float)) and math.isfinite(accuracy):
        return accuracy >= 0.5
    if "predicted" in record and "label" in record and record["label"] is not None:
        return record["predicted"] == record["label"]
    return None


def compute_dynamics(
    records: Iterable[dict[str, Any]],
    *,
    key: str = "_src",
    thresholds: DynamicsThresholds = DynamicsThresholds(),
    allow_loss_probability: bool = True,
) -> dict[tuple[Any, int], dict[str, Any]]:
    """Dynamics for every sample in a stream of per-epoch metric records.

    Each record needs ``example_id`` and ``epoch`` plus ``accuracy`` (or ``predicted`` and
    ``label``) and ``true_probability`` (or ``loss``). ``key`` names the field telling input
    Tables apart, so example 0 of train and example 0 of val stay distinct. Returns
    ``{(source, example_id): stats}``.
    """
    # One observation per (sample, epoch): a resumed run that re-evaluates an epoch must
    # not count as two observations, or a single disagreement becomes a forgetting event.
    series: dict[tuple[Any, int], dict[int, tuple[int, bool, float, bool | None]]] = {}
    sources: dict[tuple[Any, int], set[str]] = {}
    for record in records:
        epoch = record.get("epoch")
        example = record.get("example_id")
        if not isinstance(epoch, (int, float)) or not isinstance(example, (int, float)):
            continue
        correct = _correct(record)
        probability = true_probability(record, allow_loss=allow_loss_probability)
        if correct is None or probability is None:
            continue
        sample_key = (record.get(key), int(example))
        series.setdefault(sample_key, {})[int(epoch)] = (
            int(epoch), correct, probability, is_uncertain(record, thresholds)
        )
        recorded = isinstance(record.get("true_probability"), (int, float))
        sources.setdefault(sample_key, set()).add("recorded" if recorded else "loss")

    out: dict[tuple[Any, int], dict[str, Any]] = {}
    for sample, by_epoch in series.items():
        points = sorted(by_epoch.values(), key=lambda p: p[0])
        epochs = [p[0] for p in points]
        correct = np.array([p[1] for p in points], dtype=bool)
        probabilities = np.array([p[2] for p in points], dtype=np.float64)

        mean = float(probabilities.mean())
        variability = float(probabilities.std())  # population std, as in the cartography paper
        forgetting = int(np.count_nonzero(correct[:-1] & ~correct[1:]))
        wrong = np.flatnonzero(~correct)
        if len(wrong) == 0:
            learned: int | None = epochs[0]
        elif wrong[-1] == len(points) - 1:
            learned = None
        else:
            learned = epochs[int(wrong[-1]) + 1]

        streak = len(points) - (int(wrong[-1]) + 1) if len(wrong) else len(points)
        right = np.flatnonzero(correct)
        out[sample] = {
            "observations": len(points),
            "epochs_seen": len(points),  # kept for callers written before ``observations``
            "first_epoch": epochs[0],
            "last_epoch": epochs[-1],
            "max_epoch_gap": max((b - a for a, b in zip(epochs, epochs[1:])), default=0),
            "mean_true_probability": mean,
            "variability": variability,
            "correctness": float(correct.mean()),
            "ever_correct": bool(len(right)),
            "first_correct_epoch": epochs[int(right[0])] if len(right) else None,
            "current_streak": streak,
            "stable_by_end": streak > 0,
            "forgetting_events": forgetting,
            "learned_epoch": learned,
            "uncertain_epochs": [e for e, *_, uncertain in points if uncertain],
            "unstable": forgetting >= thresholds.unstable_forgetting,
            "probability_source": "recorded" if sources[sample] == {"recorded"} else "loss",
            "dynamics_version": DYNAMICS_VERSION,
        }

    learned = np.array([s["learned_epoch"] for s in out.values() if s["learned_epoch"] is not None], dtype=np.float64)
    early_cut, late_cut = (np.percentile(learned, [25, 75]) if len(learned) else (0.0, 0.0))
    for stats in out.values():
        epoch = stats["learned_epoch"]
        if epoch is None:
            stats["learning_speed"] = NOT_STABLE
        elif epoch < early_cut:
            stats["learning_speed"] = "early"
        elif epoch > late_cut:
            stats["learning_speed"] = "late"
        else:
            stats["learning_speed"] = "on time"
    return out


LEARNING_CATEGORIES = ("early", "steady", "late", "forgotten", "never", "empty")


def image_learning(
    records: Iterable[dict[str, Any]],
    *,
    key: str = "_src",
    score: str = "f1",
    good: float = 0.5,
    unstable_forgetting: int = 2,
) -> dict[tuple[Any, int], dict[str, Any]]:
    """How each image was learned over training, from a per-image score per epoch.

    For detection the score is the image's F1 (boxes found and guesses right at IoU 0.5).
    An observation is *good* when the score reaches ``good``. Categories:

    ``early`` / ``steady`` / ``late``  good from some epoch to the end; which third of this
                                      run's learned epochs (quartiles) that epoch falls in
    ``forgotten``  good at some point, but not at the end, or dropped back ``unstable_forgetting``
                   times or more
    ``never``      never good
    ``empty``      nothing labelled and nothing predicted in any observation

    Observations of one epoch recorded twice count once. ``learned_epoch`` is retrospective:
    later observations decide it.
    """
    series: dict[tuple[Any, int], dict[int, dict[str, Any]]] = {}
    for record in records:
        epoch, example, value = record.get("epoch"), record.get("example_id"), record.get(score)
        if not isinstance(epoch, (int, float)) or not isinstance(example, (int, float)):
            continue
        if not isinstance(value, (int, float)) or not math.isfinite(value):
            continue
        series.setdefault((record.get(key), int(example)), {})[int(epoch)] = record

    out: dict[tuple[Any, int], dict[str, Any]] = {}
    for sample, by_epoch in series.items():
        epochs = sorted(by_epoch)
        values = [float(by_epoch[e][score]) for e in epochs]
        good_flags = [v >= good for v in values]
        empty = all(
            int(by_epoch[e].get("tp") or 0) + int(by_epoch[e].get("fp") or 0) + int(by_epoch[e].get("fn") or 0) == 0
            for e in epochs
        )
        forgetting = sum(1 for a, b in zip(good_flags, good_flags[1:]) if a and not b)
        ever = any(good_flags)
        if ever and good_flags[-1]:
            last_bad = max((i for i, g in enumerate(good_flags) if not g), default=-1)
            learned = epochs[last_bad + 1]
        else:
            learned = None
        out[sample] = {
            "epochs": epochs,
            "scores": values,
            "first_good_epoch": epochs[good_flags.index(True)] if ever else None,
            "learned_epoch": learned,
            "forgetting_events": forgetting,
            "final_score": values[-1],
            "mean_score": sum(values) / len(values),
            "best_score": max(values),
            "category": "empty" if empty else None,
        }

    learned_epochs = sorted(
        s["learned_epoch"] for s in out.values()
        if s["learned_epoch"] is not None and s["category"] is None and s["forgetting_events"] < unstable_forgetting
    )
    early_cut, late_cut = (
        (float(np.percentile(learned_epochs, 25)), float(np.percentile(learned_epochs, 75))) if learned_epochs else (0.0, 0.0)
    )
    for stats in out.values():
        if stats["category"] == "empty":
            continue
        if stats["learned_epoch"] is None:
            stats["category"] = "forgotten" if stats["first_good_epoch"] is not None else "never"
        elif stats["forgetting_events"] >= unstable_forgetting:
            stats["category"] = "forgotten"
        elif stats["learned_epoch"] <= early_cut:
            stats["category"] = "early"
        elif stats["learned_epoch"] > late_cut or (
            late_cut > early_cut and late_cut == learned_epochs[-1] and stats["learned_epoch"] == late_cut
        ):
            # When the last quarter all falls on the final round, "after" it is empty; those
            # images still took the longest.
            stats["category"] = "late"
        else:
            stats["category"] = "steady"
        stats["early_before"], stats["late_after"] = early_cut, late_cut
    return out


def epoch_summary(
    records: Iterable[dict[str, Any]],
    *,
    key: str = "_src",
    thresholds: DynamicsThresholds = DynamicsThresholds(),
) -> list[dict[str, Any]]:
    """Per epoch: how many samples were confidently right, unsure, or confidently wrong,
    and how many were learned for good in that epoch."""
    records = list(records)
    dynamics = compute_dynamics(records, key=key, thresholds=thresholds)
    by_epoch: dict[int, dict[str, int]] = {}
    for record in records:
        epoch = record.get("epoch")
        example = record.get("example_id")
        correct = _correct(record)
        if not isinstance(epoch, (int, float)) or example is None or correct is None:
            continue
        bucket = by_epoch.setdefault(int(epoch), {"evaluated": 0, "confident_correct": 0, "uncertain": 0, "confident_wrong": 0, "newly_learned": 0})
        bucket["evaluated"] += 1
        if is_uncertain(record, thresholds):
            bucket["uncertain"] += 1
        elif correct:
            bucket["confident_correct"] += 1
        else:
            bucket["confident_wrong"] += 1
        stats = dynamics.get((record.get(key), int(example)))
        if stats and stats["learned_epoch"] == int(epoch):
            bucket["newly_learned"] += 1
    return [{"epoch": epoch, **counts} for epoch, counts in sorted(by_epoch.items())]


def training_dynamics(run: Any, *, thresholds: DynamicsThresholds = DynamicsThresholds()) -> list[dict[str, Any]]:
    """Dynamics for every sample of a Run, one dict per (input Table, example).

    Rows carry ``input_table`` and ``split`` so train and validation samples can be told
    apart. Filter ``stable_by_end == False`` or sort by ``learned_epoch`` to find
    candidates to review -- candidates, because valid hard examples land there too.
    """
    records: list[dict[str, Any]] = []
    tables: dict[str, str] = {}
    for metrics in run.metrics_tables():
        if metrics.foreign_table_url is None:
            continue
        source = str(metrics.foreign_table_url)
        split = metrics.constants.get("split")
        tables[source] = split
        data = metrics.to_arrow().to_pydict()
        count = len(data.get("example_id", []))
        for i in range(count):
            record = {name: values[i] for name, values in data.items()}
            record.update({k: v for k, v in metrics.constants.items() if k not in record})
            record["_source"] = source
            records.append(record)
    results = compute_dynamics(records, key="_source", thresholds=thresholds)
    return [
        {"input_table": source, "split": tables.get(source), "example_id": example, **stats}
        for (source, example), stats in sorted(results.items(), key=lambda item: (str(item[0][0]), item[0][1]))
    ]
