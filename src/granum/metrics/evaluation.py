"""What a run's predictions say about a set, class by class and threshold by threshold.

A single mAP number says a model is better or worse; it never says *what* it gets wrong.
Three readings of the same stored predictions do:

**Confusion.** Which class the model says when a label says something else, counted
class-agnostically -- a box is matched to the nearest label it overlaps whatever class it
claims, so "van called car" lands in a cell rather than vanishing into one miss and one
false positive, which is how class-aware matching (the right rule for scoring) hides it.

**Per class.** Precision, recall, F1, support and average precision for every class, so a
class the set barely holds is visible as that rather than as noise in the mean.

**Threshold.** Precision and recall as the operating confidence is swept, because the
number a team ships with is a choice, and it is usually made by guessing.

Everything here is pure: it reads records the collectors already wrote (``truth``,
``predicted``, ``gt_match``) and returns numbers, so the rules can be tested without a
model, a service or a browser.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import asdict, dataclass
from typing import Any

import numpy as np

from granum.core.datatypes.bounding_boxes import box_iou

#: Bumped when a change here would make new numbers incomparable with recorded ones.
EVALUATION_VERSION = "evaluation-1"

#: Where a label that nothing predicted, and a prediction with no label, are counted.
MISSED = "missed"
SPURIOUS = "background"


@dataclass(frozen=True)
class EvalPolicy:
    #: A prediction counts at or above this confidence.
    operating_confidence: float = 0.25
    #: IoU at which a prediction and a label are the same object.
    match_iou: float = 0.5
    #: Thresholds the sweep reports, from this up, in this step.
    sweep_from: float = 0.05
    sweep_step: float = 0.05

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _boxes(instances: Sequence[Mapping[str, Any]]) -> np.ndarray:
    return np.array([i["vertices"][:4] for i in instances], dtype=np.float64).reshape(-1, 4)


def labels_of(record: Mapping[str, Any]) -> list[dict[str, Any]]:
    """An image's labelled instances, areas to skip left out."""
    truth = record.get("truth")
    instances = (truth or {}).get("instances", []) if isinstance(truth, Mapping) else (truth or [])
    return [dict(i) for i in instances if not i.get("iscrowd")]


def predictions_of(record: Mapping[str, Any], policy: EvalPolicy) -> list[dict[str, Any]]:
    """An image's predictions at the operating point, strongest first."""
    predicted = (record.get("predicted") or {}).get("instances", [])
    kept = [dict(p) for p in predicted
            if not p.get("ignored") and float(p.get("confidence", 0)) >= policy.operating_confidence]
    kept.sort(key=lambda p: -float(p.get("confidence", 0)))
    return kept


def match_any_class(
    truth: Sequence[Mapping[str, Any]],
    predicted: Sequence[Mapping[str, Any]],
    iou: float,
) -> tuple[list[int], list[int]]:
    """Pair predictions with labels by overlap alone, strongest prediction first.

    Class-agnostic on purpose. The scorer matches within a class, which is right for
    counting whether a class was found; it also means a confident box drawn in exactly the
    right place with the wrong class is recorded as two separate mistakes. To say *which*
    class was confused with which, the box has to be paired with the label it covers first
    and judged afterwards.

    Returns, per prediction, the label it took (or -1), and per label, the prediction that
    took it (or -1).
    """
    took = [-1] * len(predicted)
    taken = [-1] * len(truth)
    if not truth or not predicted:
        return took, taken
    # A dense set is 70 labels against 50 boxes per image, over hundreds of images and
    # nineteen readings: the search for each prediction's best free label is left to numpy,
    # and a taken label is struck out of every row at once.
    overlaps = np.asarray(box_iou(_boxes(predicted), _boxes(truth)), dtype=np.float64).copy()
    overlaps[overlaps < iou] = -1.0
    for p in range(len(predicted)):  # predictions arrive strongest first
        row = overlaps[p]
        best = int(np.argmax(row))
        if row[best] < iou:
            continue
        took[p] = best
        taken[best] = p
        overlaps[:, best] = -1.0
    return took, taken


def confusion(
    records: Iterable[Mapping[str, Any]],
    policy: EvalPolicy = EvalPolicy(),
) -> dict[str, Any]:
    """How often each labelled class was predicted as each class, and what fell off the ends.

    ``records`` are per-image ``{"truth", "predicted"}`` as the collectors wrote them. The
    result counts pairs: ``cells[(labelled, predicted)]``, plus labels nothing covered
    (``missed``) and confident boxes covering nothing (``background``).
    """
    cells: dict[tuple[int, int], int] = {}
    missed: dict[int, int] = {}
    spurious: dict[int, int] = {}
    for record in records:
        truth = labels_of(record)
        predicted = predictions_of(record, policy)
        took, taken = match_any_class(truth, predicted, policy.match_iou)
        for p, t in enumerate(took):
            label = int(predicted[p]["label"])
            if t < 0:
                spurious[label] = spurious.get(label, 0) + 1
            else:
                key = (int(truth[t]["label"]), label)
                cells[key] = cells.get(key, 0) + 1
        for t, p in enumerate(taken):
            if p < 0:
                label = int(truth[t]["label"])
                missed[label] = missed.get(label, 0) + 1
    return {
        "cells": {f"{a}:{b}": n for (a, b), n in sorted(cells.items())},
        "missed": {str(k): v for k, v in sorted(missed.items())},
        "background": {str(k): v for k, v in sorted(spurious.items())},
    }


def class_matches(
    records: Iterable[Mapping[str, Any]],
    policy: EvalPolicy = EvalPolicy(),
) -> dict[int, dict[str, Any]]:
    """Per class: every prediction as (confidence, whether it took a label), and the labels.

    Matched once, at the lowest confidence any reading will ask about, and counted from
    there. That is exact rather than an approximation: matching takes the strongest
    prediction first, so raising the threshold only ever removes predictions that were
    already too weak to have taken a label from a stronger one. It is also the difference
    between reading a run in a second and in a minute -- the sweep asks nineteen times.
    """
    floor = EvalPolicy(operating_confidence=policy.sweep_from, match_iou=policy.match_iou)
    out: dict[int, dict[str, Any]] = {}

    def bucket(label: int) -> dict[str, Any]:
        return out.setdefault(label, {"scores": [], "labels": 0})

    for record in records:
        truth = labels_of(record)
        predicted = predictions_of(record, floor)
        # Within class: the same rule the score is computed under, so these numbers and the
        # headline cannot disagree.
        for label in {int(i["label"]) for i in truth} | {int(p["label"]) for p in predicted}:
            mine = [i for i in truth if int(i["label"]) == label]
            theirs = [p for p in predicted if int(p["label"]) == label]
            took, _taken = match_any_class(mine, theirs, policy.match_iou)
            entry = bucket(label)
            entry["labels"] += len(mine)
            for at, prediction in enumerate(theirs):
                entry["scores"].append((float(prediction.get("confidence", 0)), took[at] >= 0))
    return out


def counts_at(matches: Mapping[int, Mapping[str, Any]], confidence: float) -> dict[int, list[int]]:
    """``class -> [tp, fp, fn]`` from one matching pass, read at any operating point."""
    totals: dict[int, list[int]] = {}
    for label, entry in matches.items():
        tp = sum(1 for score, hit in entry["scores"] if hit and score >= confidence)
        fp = sum(1 for score, hit in entry["scores"] if not hit and score >= confidence)
        totals[label] = [tp, fp, int(entry["labels"]) - tp]
    return totals


def _counts(records: Iterable[Mapping[str, Any]], policy: EvalPolicy) -> dict[int, list[int]]:
    """``class -> [tp, fp, fn]`` at the operating point, matched within a class as scored."""
    return counts_at(class_matches(records, policy), policy.operating_confidence)


def scores(tp: int, fp: int, fn: int) -> dict[str, float]:
    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / (tp + fn) if tp + fn else 0.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    return {"precision": round(precision, 4), "recall": round(recall, 4), "f1": round(f1, 4)}


def per_class(
    records: Sequence[Mapping[str, Any]],
    policy: EvalPolicy = EvalPolicy(),
    names: Mapping[int, str] | None = None,
    matches: Mapping[int, Mapping[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """One row per class: what it costs the model, ordered by how much of it there is.

    ``matches`` reuses a pass already made (:func:`class_matches`); without it one is made.
    """
    totals = counts_at(matches if matches is not None else class_matches(records, policy),
                       policy.operating_confidence)
    average = average_precisions(records, policy)
    names = names or {}
    rows = []
    for label, (tp, fp, fn) in totals.items():
        rows.append({
            "label": label,
            "name": names.get(label, str(label)),
            "tp": tp, "fp": fp, "fn": fn,
            "support": tp + fn,
            "predictions": tp + fp,
            "ap": average.get(label),
            **scores(tp, fp, fn),
        })
    rows.sort(key=lambda row: (-row["support"], row["name"]))
    return rows


def average_precisions(
    records: Iterable[Mapping[str, Any]],
    policy: EvalPolicy = EvalPolicy(),
) -> dict[int, float]:
    """Average precision per class over every prediction, not only the confident ones.

    AP is a property of the whole ranking, so the operating point does not enter it; that
    is what makes it comparable between two models set to different thresholds.
    """
    from granum.training.evaluate import average_precision

    ranked: dict[int, list[tuple[float, bool]]] = {}
    positives: dict[int, int] = {}
    for record in records:
        truth = labels_of(record)
        for instance in truth:
            label = int(instance["label"])
            positives[label] = positives.get(label, 0) + 1
        every = [dict(p) for p in (record.get("predicted") or {}).get("instances", []) if not p.get("ignored")]
        for prediction in every:
            label = int(prediction["label"])
            ranked.setdefault(label, []).append(
                (float(prediction.get("confidence", 0)), bool(prediction.get("matched"))))
    out = {}
    for label, count in positives.items():
        hits = sorted(ranked.get(label, []), key=lambda item: -item[0])
        value = average_precision([c for c, _ in hits], [hit for _, hit in hits], count)
        out[label] = round(float(value), 4)
    return out


def sweep(
    records: Sequence[Mapping[str, Any]],
    policy: EvalPolicy = EvalPolicy(),
    matches: Mapping[int, Mapping[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """Precision and recall over every confidence the model could be run at.

    Pooled over classes, because the threshold is one setting for the whole model. The point
    with the best F1 is the one a team would usually ship with, and is marked by the caller.
    """
    steps = []
    value = policy.sweep_from
    while value < 1.0:
        steps.append(round(value, 4))
        value += policy.sweep_step
    found = matches if matches is not None else class_matches(records, policy)
    out = []
    for threshold in steps:
        tp = fp = fn = 0
        for label_counts in counts_at(found, threshold).values():
            tp += label_counts[0]
            fp += label_counts[1]
            fn += label_counts[2]
        out.append({"confidence": threshold, "tp": tp, "fp": fp, "fn": fn, **scores(tp, fp, fn)})
    return out


def best_threshold(curve: Sequence[Mapping[str, Any]]) -> float | None:
    """The confidence with the best pooled F1: the setting a sweep exists to find."""
    if not curve:
        return None
    best = max(curve, key=lambda row: (row["f1"], -row["confidence"]))
    return float(best["confidence"])


def examples(
    records: Iterable[Mapping[str, Any]],
    *,
    truth_label: int | None,
    predicted_label: int | None,
    policy: EvalPolicy = EvalPolicy(),
    limit: int = 60,
) -> list[dict[str, Any]]:
    """The objects behind one cell of the matrix, as crops a reader can judge.

    ``truth_label`` None means a confident box with no label under it; ``predicted_label``
    None means a label nothing predicted. Anything else is a pair: the label, the box the
    model drew over it, and how sure it was.
    """
    found: list[dict[str, Any]] = []
    for record in records:
        if len(found) >= limit:
            break
        truth = labels_of(record)
        predicted = predictions_of(record, policy)
        took, taken = match_any_class(truth, predicted, policy.match_iou)
        image = record.get("image")
        size = record.get("truth") if isinstance(record.get("truth"), Mapping) else {}
        width, height = float((size or {}).get("width") or 0), float((size or {}).get("height") or 0)
        rows: list[dict[str, Any]] = []
        if truth_label is None and predicted_label is not None:
            rows = [{"box": predicted[p]["vertices"][:4], "confidence": float(predicted[p].get("confidence", 0)),
                     "predicted_label": int(predicted[p]["label"]), "label": None}
                    for p, t in enumerate(took)
                    if t < 0 and int(predicted[p]["label"]) == predicted_label]
        elif predicted_label is None and truth_label is not None:
            rows = [{"box": truth[t]["vertices"][:4], "confidence": None,
                     "predicted_label": None, "label": int(truth[t]["label"])}
                    for t, p in enumerate(taken)
                    if p < 0 and int(truth[t]["label"]) == truth_label]
        elif truth_label is not None and predicted_label is not None:
            rows = [{"box": truth[t]["vertices"][:4],
                     "predicted_box": predicted[p]["vertices"][:4],
                     "confidence": float(predicted[p].get("confidence", 0)),
                     "predicted_label": int(predicted[p]["label"]), "label": int(truth[t]["label"])}
                    for p, t in enumerate(took)
                    if t >= 0 and int(truth[t]["label"]) == truth_label
                    and int(predicted[p]["label"]) == predicted_label]
        for row in rows[: max(0, limit - len(found))]:
            found.append({**row, "image": image, "width": width, "height": height,
                          "example_id": record.get("example_id")})
    return found
