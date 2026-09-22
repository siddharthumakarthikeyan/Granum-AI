"""Findings: which labels in a detection dataset are worth a person's time, and why.

The evidence is the model's own predictions, stored for every image in every observed
round of a training run. Four rules turn them into candidates, each tied to a place in the
image:

``missing_label``  a confident prediction with no label anywhere near it
``wrong_class``    a confident prediction of another class sitting on a label the model
                   does not otherwise find
``loose_box``      a confident prediction of the label's class that overlaps the label,
                   but not enough to count as a match
``missed``         a label the model does not find, with none of the above explaining why

A finding is a candidate, not a verdict: an unlabelled object the model sees may be out of
scope, a label it keeps missing may be a valid hard case. Each finding carries the rounds it
was seen in, so its strength is visible.

The same four rules read **one** pass of a model over a dataset (:func:`pass_findings`), which
is what a screening produces: a model the user already trained, or a pretrained one, run over
labels it was not trained on just now. There is no recurrence to lean on there, so strength is
the model's own confidence and how badly the geometry disagrees. One pass is weaker evidence
than a run's worth of rounds and is reported as what it is, but it needs no training at all,
which is the difference between checking a dataset today and checking it after an afternoon.

Rounds before the model is competent on the set are left out: while it is still learning it
misses and misplaces everything, which says nothing about the labels (:func:`competent_from`).
A finding needs to recur: one odd round is noise, and a label the model merely misses must be
missed in half the rounds, since a miss is weaker evidence than a confident prediction. On images the model trains on, evidence weakens as the
model learns the labels as they are; later rounds may stop showing a real label error.
Held-out sets (validation, test) do not have that problem.

Rules are versioned (:data:`RULES_VERSION`); decisions recorded against findings name it.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable
from dataclasses import asdict, dataclass
from typing import Any

import numpy as np

from granum.core.datatypes.bounding_boxes import box_iou

RULES_VERSION = "findings-1"
RULES = ("missing_label", "wrong_class", "loose_box", "missed")


@dataclass(frozen=True)
class FindingPolicy:
    #: A prediction counts as the model's opinion at or above this confidence.
    confident: float = 0.5
    #: IoU at which a prediction and a label are the same object (as in matching).
    match_iou: float = 0.5
    #: Below this IoU with every label a prediction has no label nearby; from it up to
    #: ``match_iou`` it overlaps a label: a loose fit (same class) or unclear (another class).
    nearby_iou: float = 0.1
    #: Without a competence start, this share of the observed rounds is left out as warm-up.
    warmup: float = 0.25
    #: The set counts as learned from the first round its recall reaches this share of its best.
    competent: float = 0.9
    #: A finding needs this share of the rounds judged...
    min_share: float = 0.2
    #: ...(a label the model only misses needs this share)...
    missed_share: float = 0.5
    #: ...and at least this many of them.
    min_rounds: int = 2
    #: One pass: a label the model simply does not find carries no confidence of its own, so
    #: it weighs this share of what a just-confident prediction would.
    missed_weight: float = 0.5
    #: One pass: a class the model finds less of this share of in the set is a class it
    #: cannot find here, and its silence about those labels is not evidence.
    pass_recall: float = 0.6
    #: One pass: a class this often wrong when it does predict is not worth accusing a
    #: label with. Deliberately low -- it removes the useless, not the merely imperfect.
    pass_precision: float = 0.3
    #: One pass: in an image where the model found less than this share of the labels it
    #: could be asked about, the model is out of its depth and its misses say nothing.
    image_recall: float = 0.6
    #: ...but only where there are this many labels to judge the image on. One label found
    #: or not found is not a measurement of anything.
    image_min_labels: int = 5
    #: How much of a class there must be before its recall or its precision is taken as a
    #: fact about the model. Below this the gates open: too little to say it cannot, and a
    #: small set is cheap to look through anyway.
    pass_min_labels: int = 30
    pass_min_predictions: int = 30
    #: One pass: how sharply the worst box pulls an image's trustworthiness down. Small
    #: means the worst box decides it; large averages the boxes together.
    temperature: float = 0.1

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _boxes(instances: list[dict[str, Any]]) -> np.ndarray:
    return np.array([i["vertices"][:4] for i in instances], dtype=np.float64).reshape(-1, 4)


def competent_from(records: list[dict[str, Any]], policy: FindingPolicy = FindingPolicy()) -> int | None:
    """The first epoch from which the model finds most of a set's labels.

    ``records`` are the set's per-image metrics rows (``epoch``, ``tp``, ``fn``). Recall per
    epoch is pooled over the set; the start is the first epoch reaching ``policy.competent``
    of the best recall. None when no epoch found anything.
    """
    found: dict[int, list[int]] = {}
    for record in records:
        if record.get("epoch") is None:
            continue
        pair = found.setdefault(int(record["epoch"]), [0, 0])
        pair[0] += int(record.get("tp") or 0)
        pair[1] += int(record.get("fn") or 0)
    recall = {e: tp / (tp + fn) for e, (tp, fn) in found.items() if tp + fn}
    best = max(recall.values(), default=0.0)
    if best <= 0:
        return None
    return min(e for e, r in recall.items() if r >= policy.competent * best)


@dataclass(frozen=True)
class _Labels:
    """An image's labels, prepared once: the rules read them a round at a time."""

    #: (index in ``truth``, the instance) for every label that is not an area to skip.
    listed: list[tuple[int, dict[str, Any]]]
    boxes: np.ndarray
    classes: list[int]
    #: Per listed label: whether the model can be asked about it at all. A model that does
    #: not know a class has no opinion on its labels, and its silence is not evidence.
    judged: list[bool]


def _labels_of(truth: list[dict[str, Any]], known: set[int] | None = None) -> _Labels:
    listed = [(i, t) for i, t in enumerate(truth) if not t.get("iscrowd")]
    classes = [int(t["label"]) for _, t in listed]
    return _Labels(
        listed=listed,
        boxes=_boxes([t for _, t in listed]),
        classes=classes,
        judged=[known is None or label in known for label in classes],
    )


def _candidates(
    labels: _Labels,
    record: dict[str, Any],
    clusters: list[np.ndarray],
    policy: FindingPolicy,
) -> list[tuple[tuple[str, Any], dict[str, Any]]]:
    """Which rules fire on one set of predictions for one image, and on what.

    The keys say what a finding is *about*: a label by its index in the image, or, for a
    prediction with no label near it, a place -- ``clusters`` collects those places so that
    the same invented box across rounds is one finding rather than one per round. A single
    pass passes a fresh list and gets one key per place.
    """
    predicted = [p for p in (record.get("bbs_predicted") or {}).get("instances", []) if not p.get("ignored")]
    matches = list(record.get("gt_match") or [])
    confident = [p for p in predicted if float(p.get("confidence", 0)) >= policy.confident]
    overlaps = (box_iou(_boxes(confident), labels.boxes) if confident and labels.listed
                else np.zeros((len(confident), len(labels.listed))))
    found: list[tuple[tuple[str, Any], dict[str, Any]]] = []
    explained: set[int] = set()
    for k, prediction in enumerate(confident):
        if prediction.get("matched"):
            continue
        box = np.array(prediction["vertices"][:4], dtype=np.float64)
        conf = float(prediction["confidence"])
        label = int(prediction["label"])
        best = int(np.argmax(overlaps[k])) if labels.listed else -1
        best_iou = float(overlaps[k, best]) if labels.listed else 0.0
        if best_iou < policy.nearby_iou:
            place = next((c for c, where in enumerate(clusters)
                          if float(box_iou(box[None], where[None])[0, 0]) >= policy.match_iou), None)
            if place is None:
                clusters.append(box)
                place = len(clusters) - 1
            found.append((("missing_label", place),
                          {"confidence": conf, "predicted_label": label, "box": box.tolist()}))
            continue
        index, _ = labels.listed[best]
        if index < len(matches) and matches[index] >= 0:
            continue  # that label was found by another prediction: a duplicate guess
        if not labels.judged[best]:
            continue  # a label of a class this model was never taught: not its to judge
        if label != labels.classes[best] and best_iou >= policy.match_iou:
            found.append((("wrong_class", index),
                          {"confidence": conf, "predicted_label": label, "iou": best_iou, "box": box.tolist()}))
            explained.add(index)
        elif label == labels.classes[best] and best_iou < policy.match_iou:
            found.append((("loose_box", index),
                          {"confidence": conf, "predicted_label": label, "iou": best_iou, "box": box.tolist()}))
            explained.add(index)
    for at, (index, _) in enumerate(labels.listed):
        if index in explained or not labels.judged[at]:
            continue
        if index >= len(matches) or matches[index] == -1:
            found.append((("missed", index), {}))
    return found


@dataclass(frozen=True)
class PassCompetence:
    """How well one pass did over a whole set, which is what its silence is worth.

    A training run earns the right to be believed by finding most of a set's labels after a
    few rounds (:func:`competent_from`). One pass has no rounds, so the same question is
    asked across the set instead: a class the model barely finds here is a class it cannot
    find here, and a label of it that it missed says nothing about the label. A class it
    predicts and is usually wrong about is not one to accuse a label with either.

    Both are measured against the labels being checked, which is circular in the small:
    if half the labels of a class are wrong, the model looks worse at it than it is. The
    thresholds are set low enough that this removes the useless rather than the imperfect.
    """

    #: Per class: the share of its labels the model found, and the share of its predictions
    #: that landed on a label of that class.
    recall: dict[int, float]
    precision: dict[int, float]
    labels: dict[int, int]
    predicted: dict[int, int]
    #: Classes whose missed labels count as evidence, and whose predictions do.
    judged: frozenset[int]
    trusted: frozenset[int]

    def to_dict(self) -> dict[str, Any]:
        return {
            "recall": {str(k): round(v, 4) for k, v in sorted(self.recall.items())},
            "precision": {str(k): round(v, 4) for k, v in sorted(self.precision.items())},
            "labels": {str(k): v for k, v in sorted(self.labels.items())},
            "predicted": {str(k): v for k, v in sorted(self.predicted.items())},
            "judged": sorted(self.judged),
            "trusted": sorted(self.trusted),
        }


def pass_competence(
    images: Iterable[tuple[list[dict[str, Any]], dict[str, Any]]],
    policy: FindingPolicy = FindingPolicy(),
) -> PassCompetence:
    """What one pass over a set is worth, per class.

    ``images`` yields ``(truth instances, metrics record)`` for every image of the set.
    """
    labels: Counter[int] = Counter()
    found: Counter[int] = Counter()
    predicted: Counter[int] = Counter()
    landed: Counter[int] = Counter()
    for truth, record in images:
        matches = list(record.get("gt_match") or [])
        for index, item in enumerate(truth):
            if item.get("iscrowd"):
                continue
            label = int(item["label"])
            labels[label] += 1
            if index < len(matches) and matches[index] >= 0:
                found[label] += 1
        for instance in (record.get("bbs_predicted") or {}).get("instances", []):
            if instance.get("ignored") or float(instance.get("confidence", 0)) < policy.confident:
                continue
            label = int(instance["label"])
            predicted[label] += 1
            landed[label] += int(bool(instance.get("matched")))
    recall = {c: found[c] / n for c, n in labels.items() if n}
    precision = {c: landed[c] / n for c, n in predicted.items() if n}
    return PassCompetence(
        recall=recall,
        precision=precision,
        labels=dict(labels),
        predicted=dict(predicted),
        # Too few of a class to say the model cannot find it: judge it and let the ranking
        # sort it out. A class the model never predicts at all has nothing to say either way.
        judged=frozenset(c for c, r in recall.items()
                         if r >= policy.pass_recall or labels[c] < policy.pass_min_labels),
        trusted=frozenset(c for c, p in precision.items()
                          if p >= policy.pass_precision or predicted[c] < policy.pass_min_predictions),
    )


def image_findings(
    truth: list[dict[str, Any]],
    rounds: dict[int, dict[str, Any]],
    policy: FindingPolicy = FindingPolicy(),
    *,
    from_epoch: int | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Findings for one image.

    ``truth`` is the image's labelled instances as collected (``vertices`` xyxy, ``label``,
    optional ``iscrowd``); ``rounds`` maps epoch to that round's metrics record with
    ``bbs_predicted`` and ``gt_match``. Rounds without stored boxes are skipped.

    ``from_epoch`` starts the judged rounds (see :func:`competent_from`); without it the first
    ``policy.warmup`` of the observed rounds are skipped.

    Returns the findings, strongest first, and the window of rounds they were judged on.
    """
    observed = sorted(e for e, r in rounds.items() if (r.get("bbs_predicted") or None) is not None)
    if from_epoch is None:
        window = observed[int(len(observed) * policy.warmup):]
    else:
        window = [e for e in observed if e >= from_epoch]
    info = {"observed": len(observed), "window": len(window), "from_epoch": window[0] if window else None}
    if len(window) < policy.min_rounds:
        return [], info

    labels = _labels_of(truth)

    # key -> the rounds it was seen in, with what was seen
    seen: dict[tuple[str, Any], list[dict[str, Any]]] = {}
    clusters: list[np.ndarray] = []  # places of predictions with no label nearby

    def note(key: tuple[str, Any], epoch: int, **what: Any) -> None:
        seen.setdefault(key, []).append({"epoch": epoch, **what})

    for epoch in window:
        for key, what in _candidates(labels, rounds[epoch], clusters, policy):
            note(key, epoch, **what)

    findings = []
    for (rule, key), hits in seen.items():
        count = len({h["epoch"] for h in hits})
        share = count / len(window)
        needed = policy.missed_share if rule == "missed" else policy.min_share
        if count < policy.min_rounds or share < needed:
            continue
        confidences = [h["confidence"] for h in hits if "confidence" in h]
        latest = max(hits, key=lambda h: h["epoch"])
        finding: dict[str, Any] = {
            "rule": rule,
            "rounds": count,
            "window": len(window),
            "share": round(share, 4),
            "first_epoch": min(h["epoch"] for h in hits),
            "last_epoch": latest["epoch"],
            "in_last_round": latest["epoch"] == window[-1],
            "confidence": [round(min(confidences), 4), round(max(confidences), 4)] if confidences else None,
        }
        if rule == "missing_label":
            finding["truth_index"] = None
            finding["box"] = [round(v, 2) for v in np.mean([h["box"] for h in hits], axis=0).tolist()]
            finding["label"] = None
        else:
            truth_item = truth[key]
            finding["truth_index"] = key
            finding["annotation_id"] = truth_item.get("annotation_id")
            finding["box"] = [round(float(v), 2) for v in truth_item["vertices"][:4]]
            finding["label"] = int(truth_item["label"])
            if rule in ("wrong_class", "loose_box"):
                finding["iou"] = round(float(np.mean([h["iou"] for h in hits])), 4)
                finding["predicted_box"] = [round(v, 2) for v in latest["box"]]
        if confidences:
            finding["predicted_label"] = Counter(h["predicted_label"] for h in hits).most_common(1)[0][0]
        # Strength: how often, and how sure. A label the model misses says less than a
        # confident prediction does: it weighs as the least confident prediction that counts,
        # and loses ties to one.
        finding["score"] = round(share * (float(np.mean(confidences)) if confidences else policy.confident), 4)
        findings.append(finding)
    findings.sort(key=lambda f: (-f["score"], RULES.index(f["rule"])))
    return findings, info


def pass_findings(
    truth: list[dict[str, Any]],
    record: dict[str, Any],
    policy: FindingPolicy = FindingPolicy(),
    *,
    known: set[int] | None = None,
    competence: PassCompetence | None = None,
) -> list[dict[str, Any]]:
    """Findings for one image from a single pass of a model over it.

    Same four rules and the same output shape as :func:`image_findings`, so everything
    downstream -- the review queue, the decisions, the dashboard -- does not know the
    difference. What changes is where strength comes from. With rounds, a finding earns its
    place by recurring; with one pass there is nothing to recur, so it is the model's own
    confidence, and for a loose box how far the fit falls short of a match.

    A label the model simply does not find carries no confidence at all: it weighs
    ``policy.missed_weight`` of what a just-confident prediction would, which keeps it below
    every real prediction in the ranking, as the ``missed_share`` rule does over rounds.

    ``record`` is one round's metrics: ``bbs_predicted`` and ``gt_match``, exactly as a
    collector writes them.

    ``known`` limits the judging to the classes the model can predict, which matters when the
    model is a pretrained one that knows some of a dataset's classes and not others: a label
    it was never taught is left alone rather than reported as one it failed to find.

    ``competence`` is what the pass was worth over the whole set (:func:`pass_competence`),
    and it is what keeps a dense set from reporting everything. A model that finds half the
    objects in a crowded aerial frame has not found half the labels to be wrong: without the
    gate, one pass over 547 such images called 17,686 labels missed. With it, a miss counts
    only where the model demonstrably finds that class, and in images where it found most of
    what it could be asked about.
    """
    labels = _labels_of(truth, known)
    matches = list(record.get("gt_match") or [])
    weak_image = False
    if competence is not None:
        askable = [(at, index) for at, (index, _) in enumerate(labels.listed)
                   if labels.judged[at] and labels.classes[at] in competence.judged]
        if len(askable) >= policy.image_min_labels:
            hit = sum(1 for _, index in askable if index < len(matches) and matches[index] >= 0)
            weak_image = hit / len(askable) < policy.image_recall
    findings = []
    for (rule, key), what in _candidates(labels, record, [], policy):
        if competence is not None:
            if rule == "missed":
                # Nothing to learn from a miss by a model that cannot find this class here,
                # or that has already shown it is out of its depth on this picture.
                if weak_image or int(truth[key]["label"]) not in competence.judged:
                    continue
            elif int(what["predicted_label"]) not in competence.trusted:
                continue
        confidence = what.get("confidence")
        if rule == "missed":
            score = policy.confident * policy.missed_weight
        elif rule == "loose_box":
            # A box that nearly matches is weak evidence of anything; one that overlaps by a
            # tenth while the model is sure of the class is the case worth a person's time.
            fit = min(float(what["iou"]) / policy.match_iou, 1.0)
            score = float(confidence) * (1.0 - fit)
        else:
            score = float(confidence)
        finding: dict[str, Any] = {
            "rule": rule,
            # One pass is one round of evidence, and says so rather than implying more.
            "rounds": 1,
            "window": 1,
            "share": 1.0,
            "first_epoch": None,
            "last_epoch": None,
            "in_last_round": True,
            "confidence": [round(float(confidence), 4)] * 2 if confidence is not None else None,
        }
        if rule == "missing_label":
            finding["truth_index"] = None
            finding["label"] = None
            finding["box"] = [round(float(v), 2) for v in what["box"]]
        else:
            item = truth[key]
            finding["truth_index"] = key
            finding["annotation_id"] = item.get("annotation_id")
            finding["box"] = [round(float(v), 2) for v in item["vertices"][:4]]
            finding["label"] = int(item["label"])
            if rule in ("wrong_class", "loose_box"):
                finding["iou"] = round(float(what["iou"]), 4)
                finding["predicted_box"] = [round(float(v), 2) for v in what["box"]]
        if confidence is not None:
            finding["predicted_label"] = int(what["predicted_label"])
        finding["score"] = round(score, 4)
        findings.append(finding)
    findings.sort(key=lambda f: (-f["score"], RULES.index(f["rule"])))
    return findings


def image_trust(findings: list[dict[str, Any]], labels: int, policy: FindingPolicy = FindingPolicy()) -> float:
    """One number for how much of an image's labelling to trust, from 0 to 1.

    Every label starts perfect and is pulled down by the worst finding against it; a
    prediction with no label near it counts as a box that should have been there and is
    judged the same way. The image's number is a *softmin* of those, not a mean: one badly
    wrong box in an image of forty right ones is what a reviewer needs to see, and a mean
    would bury it. ``policy.temperature`` sets how sharply the worst box dominates.

    An image with no labels and nothing found is fully trusted -- there is nothing there to
    be wrong -- which is also what makes this sortable across a whole set.
    """
    quality = [1.0] * max(labels, 0)
    for finding in findings:
        hurt = 1.0 - float(finding["score"])
        index = finding.get("truth_index")
        if index is None:
            quality.append(hurt)          # a box the model says is missing
        elif 0 <= index < len(quality):
            quality[index] = min(quality[index], hurt)
    if not quality:
        return 1.0
    values = np.asarray(quality, dtype=np.float64)
    weights = np.exp(-values / max(policy.temperature, 1e-6))
    return round(float(np.sum(values * weights) / np.sum(weights)), 4)
