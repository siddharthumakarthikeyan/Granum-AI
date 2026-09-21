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

    labelled = [(i, t) for i, t in enumerate(truth) if not t.get("iscrowd")]
    truth_boxes = _boxes([t for _, t in labelled])
    truth_labels = [int(t["label"]) for _, t in labelled]

    # key -> the rounds it was seen in, with what was seen
    seen: dict[tuple[str, Any], list[dict[str, Any]]] = {}
    clusters: list[np.ndarray] = []  # places of predictions with no label nearby

    def note(key: tuple[str, Any], epoch: int, **what: Any) -> None:
        seen.setdefault(key, []).append({"epoch": epoch, **what})

    for epoch in window:
        record = rounds[epoch]
        predicted = [p for p in (record.get("bbs_predicted") or {}).get("instances", []) if not p.get("ignored")]
        matches = list(record.get("gt_match") or [])
        confident = [p for p in predicted if float(p.get("confidence", 0)) >= policy.confident]
        overlaps = box_iou(_boxes(confident), truth_boxes) if confident and labelled else np.zeros((len(confident), len(labelled)))
        explained: set[int] = set()
        for k, prediction in enumerate(confident):
            if prediction.get("matched"):
                continue
            box = np.array(prediction["vertices"][:4], dtype=np.float64)
            conf = float(prediction["confidence"])
            label = int(prediction["label"])
            best = int(np.argmax(overlaps[k])) if labelled else -1
            best_iou = float(overlaps[k, best]) if labelled else 0.0
            if best_iou < policy.nearby_iou:
                place = next((c for c, where in enumerate(clusters)
                              if float(box_iou(box[None], where[None])[0, 0]) >= policy.match_iou), None)
                if place is None:
                    clusters.append(box)
                    place = len(clusters) - 1
                note(("missing_label", place), epoch, confidence=conf, predicted_label=label, box=box.tolist())
                continue
            index, _ = labelled[best]
            if index < len(matches) and matches[index] >= 0:
                continue  # that label was found by another prediction: a duplicate guess
            if label != truth_labels[best] and best_iou >= policy.match_iou:
                note(("wrong_class", index), epoch, confidence=conf, predicted_label=label, iou=best_iou, box=box.tolist())
                explained.add(index)
            elif label == truth_labels[best] and best_iou < policy.match_iou:
                note(("loose_box", index), epoch, confidence=conf, predicted_label=label, iou=best_iou, box=box.tolist())
                explained.add(index)
        for index, _ in labelled:
            if index in explained:
                continue
            if index >= len(matches) or matches[index] == -1:
                note(("missed", index), epoch)

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
