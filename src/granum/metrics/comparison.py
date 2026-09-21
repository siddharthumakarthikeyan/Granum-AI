"""Comparing two runs: what changed, on which images, and what the comparison is worth.

A number going up is not evidence. Two runs only compare when they were scored on the same
images with the same rules, and even then the interesting part is not the mean: it is which
images improved, which regressed, and which the runs do not share at all.

So a comparison here is three things, in this order:

1. **Compatibility** (:func:`compatibility_checks`). Same evaluation set, same version of it,
   same evaluator policy, per-image results on both sides. A missing answer is reported as
   unknown, never assumed. Anything that makes the two numbers different kinds of number
   blocks the comparison instead of quietly averaging over it.
2. **Per-image outcomes** (:func:`compare_samples`). Every image of the shared set is
   improved, regressed, unchanged, or unmatched -- in one run's set and not the other's.
   Unmatched images are counted and listed, not dropped: they are usually the whole story of
   what the dataset edit did.
3. **Slices** (:func:`class_slices`, :func:`size_slices`) and the data change
   (:func:`label_change`), each carrying its support, because a class with 4 labels in it
   moves for reasons that have nothing to do with the model.

What this module will not do is say one run is better *because* of an edit. When the
evaluation labels themselves changed between the runs, the per-image difference mixes a
model change with a label change and the report says so (:func:`interpretation`); with one
seed per run, a difference inside the declared tolerance is not called a win.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import asdict, dataclass
from typing import Any

import numpy as np

from granum.core.datatypes.bounding_boxes import box_iou

REPORT_VERSION = "comparison-1"

#: Per-image outcomes, plus the two unmatched sides.
OUTCOMES = ("improved", "regressed", "unchanged")
UNMATCHED = ("only_baseline", "only_candidate")

#: COCO object-size bands, as box area in pixels.
SIZE_BANDS = (("small", 0, 32 * 32), ("medium", 32 * 32, 96 * 96), ("large", 96 * 96, float("inf")))


@dataclass(frozen=True)
class ComparePolicy:
    #: A prediction counts at or above this confidence, on both sides of the comparison.
    operating_confidence: float = 0.25
    #: IoU at which a prediction and a label are the same object.
    match_iou: float = 0.5
    #: A declared tolerance, not a measured noise level: with one seed per run, a headline
    #: difference smaller than this is reported as not separable from run-to-run variation.
    tolerance: float = 0.02
    #: A slice with fewer labels than this is shown with its support and not called a change.
    min_support: int = 30
    #: Two boxes this close are the same box across dataset versions, so a class change on
    #: one of them reads as a relabel rather than a delete and an add.
    same_box_iou: float = 0.9

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


# ---------------------------------------------------------------------------
# scores
# ---------------------------------------------------------------------------


def scores_of(tp: int, fp: int, fn: int) -> dict[str, float]:
    """Precision, recall and F1 from counts, with empty denominators as 0."""
    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / (tp + fn) if tp + fn else 0.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    return {"precision": round(precision, 4), "recall": round(recall, 4), "f1": round(f1, 4)}


def pooled(rows: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    """Counts pooled over images, with the support they rest on.

    Pooled, not averaged over images: an image with 90 labels and one with 1 do not carry
    the same weight, and an average over images hides that.
    """
    tp = fp = fn = images = 0
    for row in rows:
        tp += int(row.get("tp") or 0)
        fp += int(row.get("fp") or 0)
        fn += int(row.get("fn") or 0)
        images += 1
    return {"tp": tp, "fp": fp, "fn": fn, "images": images, "labels": tp + fn, **scores_of(tp, fp, fn)}


# ---------------------------------------------------------------------------
# per-image outcomes
# ---------------------------------------------------------------------------


def image_outcome(before: Mapping[str, Any], after: Mapping[str, Any]) -> str:
    """How one image moved.

    Unchanged means the same counts, not a similar score: an image that trades a miss for a
    false positive keeps its F1 and has not stayed the same.
    """
    counts = [(int(r.get("tp") or 0), int(r.get("fp") or 0), int(r.get("fn") or 0)) for r in (before, after)]
    if counts[0] == counts[1]:
        return "unchanged"
    delta = scores_of(*counts[1])["f1"] - scores_of(*counts[0])["f1"]
    if delta > 0:
        return "improved"
    if delta < 0:
        return "regressed"
    # Same F1, different counts: a trade, not a stalemate. Fewer misses is the better trade.
    return "improved" if counts[1][2] < counts[0][2] else "regressed"


def compare_samples(
    baseline: Mapping[str, Mapping[str, Any]],
    candidate: Mapping[str, Mapping[str, Any]],
    policy: ComparePolicy = ComparePolicy(),
) -> dict[str, Any]:
    """Pair two runs' per-image results by image, and judge each pair.

    Both sides map an image key to its per-image record (``tp``, ``fp``, ``fn``, and
    whatever else the caller wants carried through, e.g. ``example_id``). Images are paired
    by their image reference, never by row position: a dataset version that removed rows
    moves every position after it.

    Returns the counts by outcome, the paired images (largest move first) and the unmatched
    ones from each side.
    """
    counts = dict.fromkeys(OUTCOMES + UNMATCHED, 0)
    paired: list[dict[str, Any]] = []
    for key, before in baseline.items():
        after = candidate.get(key)
        if after is None:
            counts["only_baseline"] += 1
            continue
        outcome = image_outcome(before, after)
        counts[outcome] += 1
        before_scores = scores_of(int(before.get("tp") or 0), int(before.get("fp") or 0), int(before.get("fn") or 0))
        after_scores = scores_of(int(after.get("tp") or 0), int(after.get("fp") or 0), int(after.get("fn") or 0))
        paired.append({
            "image": key,
            "outcome": outcome,
            "baseline": {**{k: int(before.get(k) or 0) for k in ("tp", "fp", "fn")},
                         "example_id": before.get("example_id"), **before_scores},
            "candidate": {**{k: int(after.get(k) or 0) for k in ("tp", "fp", "fn")},
                          "example_id": after.get("example_id"), **after_scores},
            "delta_f1": round(after_scores["f1"] - before_scores["f1"], 4),
        })
    only_candidate = [key for key in candidate if key not in baseline]
    counts["only_candidate"] = len(only_candidate)
    paired.sort(key=lambda item: (-abs(item["delta_f1"]), item["image"]))
    return {
        "counts": counts,
        "images": paired,
        "only_baseline": [key for key in baseline if key not in candidate],
        "only_candidate": only_candidate,
        "baseline": pooled(baseline.values()),
        "candidate": pooled(candidate.values()),
        "shared": {
            "baseline": pooled(b for k, b in baseline.items() if k in candidate),
            "candidate": pooled(c for k, c in candidate.items() if k in baseline),
        },
    }


# ---------------------------------------------------------------------------
# slices
# ---------------------------------------------------------------------------


def _instances(value: Any) -> list[dict[str, Any]]:
    return [i for i in (value or {}).get("instances", []) if not i.get("iscrowd")]


def _box_key(instance: Mapping[str, Any]) -> tuple[Any, ...]:
    """A box's identity for spotting one that did not change: its class and its place."""
    return (int(instance["label"]), *(round(float(v), 2) for v in instance["vertices"][:4]))


def _counted(truth: Sequence[Mapping[str, Any]], predicted: Any, matches: Sequence[int],
             policy: ComparePolicy, *, band_of: Any = None) -> dict[Any, list[int]]:
    """``key -> [tp, fp, fn]`` for one image, keyed by class or by size band.

    A label counts as found only when the prediction that matched it is confident at the
    comparison's operating point, so both runs are read at the same threshold whatever
    confidence their boxes were collected at.
    """
    instances = [p for p in (predicted or {}).get("instances", []) if not p.get("ignored")]
    confident = {i for i, p in enumerate(instances) if float(p.get("confidence", 0)) >= policy.operating_confidence}
    out: dict[Any, list[int]] = {}

    def bucket(key: Any) -> list[int]:
        return out.setdefault(key, [0, 0, 0])

    for index, label in enumerate(truth):
        key = band_of(label) if band_of is not None else int(label["label"])
        found = index < len(matches) and matches[index] >= 0 and matches[index] in confident
        bucket(key)[0 if found else 2] += 1
    if band_of is None:  # a false positive has no truth, so it has no size band
        for index, prediction in enumerate(instances):
            if index in confident and not prediction.get("matched"):
                bucket(int(prediction["label"]))[1] += 1
    return out


def _slice_rows(
    pairs: Iterable[tuple[Mapping[str, Any], Mapping[str, Any]]],
    policy: ComparePolicy,
    *,
    band_of: Any = None,
) -> dict[Any, dict[str, list[int]]]:
    totals: dict[Any, dict[str, list[int]]] = {}
    for before, after in pairs:
        for side, record in (("baseline", before), ("candidate", after)):
            truth = _instances(record.get("truth"))
            counted = _counted(truth, record.get("predicted"), record.get("gt_match") or [], policy, band_of=band_of)
            for key, (tp, fp, fn) in counted.items():
                entry = totals.setdefault(key, {"baseline": [0, 0, 0], "candidate": [0, 0, 0]})
                entry[side][0] += tp
                entry[side][1] += fp
                entry[side][2] += fn
    return totals


def _slice_payload(key: Any, name: str, counts: dict[str, list[int]], policy: ComparePolicy,
                   *, metric: str = "f1") -> dict[str, Any]:
    sides = {}
    for side in ("baseline", "candidate"):
        tp, fp, fn = counts[side]
        sides[side] = {"tp": tp, "fp": fp, "fn": fn, "labels": tp + fn, **scores_of(tp, fp, fn)}
    support = max(sides["baseline"]["labels"], sides["candidate"]["labels"])
    return {
        "key": key,
        "name": name,
        "metric": metric,
        "support": support,
        # Small slices are reported with their numbers and marked; they are not called moves.
        "conclusive": support >= policy.min_support,
        "baseline": sides["baseline"],
        "candidate": sides["candidate"],
        "delta": round(sides["candidate"][metric] - sides["baseline"][metric], 4),
    }


def class_slices(
    pairs: Iterable[tuple[Mapping[str, Any], Mapping[str, Any]]],
    policy: ComparePolicy = ComparePolicy(),
    names: Mapping[int, str] | None = None,
) -> list[dict[str, Any]]:
    """Per-class F1 on both sides, over the images both runs share.

    ``pairs`` are ``(baseline record, candidate record)`` for one image, each with ``truth``
    (the labelled boxes as collected), ``predicted`` and ``gt_match``. Runs that did not
    store their boxes have no slices; that is the caller's to disclose.
    """
    totals = _slice_rows(pairs, policy)
    names = names or {}
    rows = [_slice_payload(key, names.get(key, str(key)), counts, policy) for key, counts in totals.items()]
    rows.sort(key=lambda row: (-row["support"], str(row["name"])))
    return rows


def size_slices(
    pairs: Iterable[tuple[Mapping[str, Any], Mapping[str, Any]]],
    policy: ComparePolicy = ComparePolicy(),
) -> list[dict[str, Any]]:
    """Recall by object size. Precision has no size: a false positive has no label to measure."""

    def band_of(label: Mapping[str, Any]) -> str:
        x0, y0, x1, y1 = (float(v) for v in label["vertices"][:4])
        area = max(x1 - x0, 0.0) * max(y1 - y0, 0.0)
        return next(name for name, low, high in SIZE_BANDS if low <= area < high)

    totals = _slice_rows(pairs, policy, band_of=band_of)
    order = [name for name, _, _ in SIZE_BANDS]
    rows = [_slice_payload(key, key, counts, policy, metric="recall") for key, counts in totals.items()]
    rows.sort(key=lambda row: order.index(row["key"]) if row["key"] in order else len(order))
    return rows


# ---------------------------------------------------------------------------
# what changed in the data
# ---------------------------------------------------------------------------


def label_change(
    baseline: Mapping[str, Any],
    candidate: Mapping[str, Any],
    policy: ComparePolicy = ComparePolicy(),
) -> dict[str, Any]:
    """How the labels of one set differ between two versions of it.

    Both sides map an image key to that image's labelled instances. Boxes are matched
    between the versions by overlap: a box that stayed in place with another class is a
    relabel, not a deletion and an addition. Images only one version has are listed too --
    removing images is the most common edit there is.
    """
    added_images = [k for k in candidate if k not in baseline]
    removed_images = [k for k in baseline if k not in candidate]
    changed: list[dict[str, Any]] = []
    boxes_added = boxes_removed = boxes_relabelled = boxes_moved = 0
    for key, before_value in baseline.items():
        after_value = candidate.get(key)
        if after_value is None:
            continue
        before, after = _instances(before_value), _instances(after_value)
        if not before and not after:
            continue
        overlap = (box_iou(np.array([i["vertices"][:4] for i in before], dtype=np.float64).reshape(-1, 4),
                           np.array([i["vertices"][:4] for i in after], dtype=np.float64).reshape(-1, 4))
                   if before and after else np.zeros((len(before), len(after))))
        # An unchanged box pairs with its own copy first. Overlap alone cannot do that: a box
        # with no width or height has no area, so its IoU with itself is 0 and a dataset that
        # kept it untouched would read as one deletion and one addition.
        same: dict[tuple[Any, ...], list[int]] = {}
        for other, instance in enumerate(after):
            same.setdefault(_box_key(instance), []).append(other)
        taken: set[int] = set()
        pairs: dict[int, int] = {}
        for index, instance in enumerate(before):
            copies = same.get(_box_key(instance))
            if copies:
                pairs[index] = copies.pop(0)
                taken.add(pairs[index])
        counts = {"added": 0, "removed": 0, "relabelled": 0, "moved": 0}
        for index, instance in enumerate(before):
            if index in pairs:
                continue
            best = -1
            best_iou = 0.0
            for other in range(len(after)):
                if other in taken:
                    continue
                if overlap[index, other] > best_iou:
                    best, best_iou = other, float(overlap[index, other])
            if best < 0 or best_iou < policy.match_iou:
                counts["removed"] += 1
                continue
            taken.add(best)
            if int(after[best]["label"]) != int(instance["label"]):
                counts["relabelled"] += 1
            elif best_iou < policy.same_box_iou:
                counts["moved"] += 1
        counts["added"] += len(after) - len(taken)
        if any(counts.values()):
            changed.append({"image": key, **counts, "before": len(before), "after": len(after)})
        boxes_added += counts["added"]
        boxes_removed += counts["removed"]
        boxes_relabelled += counts["relabelled"]
        boxes_moved += counts["moved"]
    changed.sort(key=lambda row: (-(row["added"] + row["removed"] + row["relabelled"] + row["moved"]), row["image"]))
    return {
        "images_baseline": len(baseline),
        "images_candidate": len(candidate),
        "images_added": len(added_images),
        "images_removed": len(removed_images),
        "images_edited": len(changed),
        "added": added_images[:200],
        "removed": removed_images[:200],
        "boxes_baseline": sum(len(_instances(v)) for v in baseline.values()),
        "boxes_candidate": sum(len(_instances(v)) for v in candidate.values()),
        # Drawn or deleted on images both versions hold, and separately the boxes that came
        # or went with a whole image, so the two totals above add up.
        "boxes_added": boxes_added,
        "boxes_removed": boxes_removed,
        "boxes_with_added_images": sum(len(_instances(candidate[k])) for k in added_images),
        "boxes_with_removed_images": sum(len(_instances(baseline[k])) for k in removed_images),
        "boxes_relabelled": boxes_relabelled,
        "boxes_moved": boxes_moved,
        "edited": changed[:200],
        "truncated": len(changed) > 200,
    }


# ---------------------------------------------------------------------------
# compatibility
# ---------------------------------------------------------------------------


def _check(name: str, status: str, detail: str, **extra: Any) -> dict[str, Any]:
    return {"check": name, "status": status, "detail": detail, **extra}


def compatibility_checks(baseline: Mapping[str, Any], candidate: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Whether these two runs may be compared, and what has to be said if they are.

    Each side describes one run's evaluation: ``set`` (the set's identity, e.g.
    ``dataset/valid``), ``table`` (the exact version's url), ``images``, ``evaluator`` (the
    scoring policy the run recorded, or an empty mapping when it recorded none), ``classes``
    (index -> name), ``recipe`` and ``seed``.

    Statuses are ``blocked`` (the comparison would be meaningless), ``warn`` (it holds, with
    something the reader must know) and ``ok``. ``unknown`` is a warning, never an assumption.
    """
    checks: list[dict[str, Any]] = []

    if not baseline.get("set") or not candidate.get("set"):
        checks.append(_check("evaluation_set", "blocked", "one of the runs has no per-image results to compare"))
        return checks
    if baseline["set"] != candidate["set"]:
        checks.append(_check(
            "evaluation_set", "blocked",
            f"scored on different sets: {baseline['set']} and {candidate['set']}",
            baseline=baseline["set"], candidate=candidate["set"]))
        return checks
    checks.append(_check("evaluation_set", "ok", f"both scored on {baseline['set']}"))

    if baseline.get("table") == candidate.get("table"):
        checks.append(_check("evaluation_version", "ok", "the same version of that set, image for image"))
    else:
        checks.append(_check(
            "evaluation_version", "warn",
            "different versions of that set: the labels the runs were scored against are not "
            "the same, so a per-image difference mixes the model with the labels",
            baseline=baseline.get("table_name"), candidate=candidate.get("table_name")))

    baseline_eval, candidate_eval = dict(baseline.get("evaluator") or {}), dict(candidate.get("evaluator") or {})
    if not baseline_eval or not candidate_eval:
        checks.append(_check(
            "evaluator", "warn",
            "one of the runs did not record its scoring policy, so the two scores are only "
            "comparable if it used the current defaults"))
    elif baseline_eval != candidate_eval:
        differing = sorted(k for k in set(baseline_eval) | set(candidate_eval)
                           if baseline_eval.get(k) != candidate_eval.get(k))
        checks.append(_check(
            "evaluator", "blocked",
            "scored under different rules (" + ", ".join(
                f"{k}: {baseline_eval.get(k, '—')} vs {candidate_eval.get(k, '—')}" for k in differing) + ")",
            fields=differing))
    else:
        checks.append(_check("evaluator", "ok", "the same scoring rules on both sides"))

    baseline_classes, candidate_classes = baseline.get("classes") or {}, candidate.get("classes") or {}
    if baseline_classes and candidate_classes and baseline_classes != candidate_classes:
        shared = {k: v for k, v in baseline_classes.items() if candidate_classes.get(k) == v}
        status = "blocked" if not shared else "warn"
        checks.append(_check(
            "classes", status,
            "the class lists differ between the runs" + ("" if shared else ", with nothing in common"),
            baseline=baseline_classes, candidate=candidate_classes))
    elif baseline_classes:
        checks.append(_check("classes", "ok", f"{len(baseline_classes)} classes, the same on both sides"))

    recipe = {k: (baseline.get("recipe") or {}).get(k) for k in ("framework", "version", "epochs", "imgsz", "batch")}
    other = {k: (candidate.get("recipe") or {}).get(k) for k in recipe}
    differing = [k for k in recipe if recipe[k] != other[k]]
    if differing:
        checks.append(_check(
            "training_recipe", "warn",
            "the runs were trained differently (" + ", ".join(
                f"{k}: {recipe[k] or '—'} vs {other[k] or '—'}" for k in differing) + "), so the difference is not "
            "only the data",
            fields=differing))
    else:
        checks.append(_check("training_recipe", "ok", "the same model and training settings"))

    seeds = (baseline.get("seed"), candidate.get("seed"))
    if None in seeds:
        checks.append(_check("seeds", "warn", "at least one run did not record a seed"))
    else:
        checks.append(_check(
            "seeds", "warn" if seeds[0] == seeds[1] else "ok",
            "one run each, on one seed: a small difference cannot be separated from run-to-run "
            "variation" if seeds[0] == seeds[1] else f"different seeds ({seeds[0]} and {seeds[1]})"))
    return checks


def interpretation(checks: Sequence[Mapping[str, Any]], data_changed: bool) -> dict[str, Any]:
    """What may be read out of this comparison, in one sentence and one word.

    ``controlled`` is for a comparison where only the thing under test differs; ``observational``
    for one where the data changed too, which is the usual case here and the honest word for it.
    """
    blocked = [c for c in checks if c["status"] == "blocked"]
    warnings = [c for c in checks if c["status"] == "warn"]
    by_name = {c["check"]: c for c in checks}
    if blocked:
        return {"kind": "blocked", "blocked": [c["check"] for c in blocked],
                "summary": blocked[0]["detail"], "warnings": [c["check"] for c in warnings]}
    recipe_changed = by_name.get("training_recipe", {}).get("status") == "warn"
    labels_changed = by_name.get("evaluation_version", {}).get("status") == "warn"
    if data_changed and recipe_changed:
        summary = ("The data and the training settings both changed, so nothing here attributes a "
                   "difference to either one.")
    elif data_changed:
        summary = ("The training data changed between these runs. The comparison shows what happened "
                   "alongside that change, not what any single edit caused.")
    elif recipe_changed:
        summary = "The training settings changed; the data is the same on both sides."
    else:
        summary = "Same data, same settings: this is a repeat of the same run."
    if labels_changed:
        summary += (" The evaluation labels also changed, so part of every per-image difference is "
                    "the label, not the model.")
    return {
        "kind": "observational" if (data_changed or labels_changed) else "controlled",
        "blocked": [],
        "warnings": [c["check"] for c in warnings],
        "summary": summary,
    }


def headline(
    baseline: Mapping[str, Any],
    candidate: Mapping[str, Any],
    policy: ComparePolicy = ComparePolicy(),
    *,
    key: str = "map50",
) -> dict[str, Any]:
    """The run-level score each run recorded, and whether their difference is separable.

    ``tolerance`` is declared, not measured: without repeated seeds nobody here knows the
    run-to-run spread, and a number inside it is reported as too close to call.
    """
    values = [baseline.get(key), candidate.get(key)]
    if not all(isinstance(v, (int, float)) for v in values):
        return {"metric": key, "baseline": None, "candidate": None, "delta": None, "verdict": "not recorded"}
    delta = float(values[1]) - float(values[0])
    return {
        "metric": key,
        "baseline": round(float(values[0]), 4),
        "candidate": round(float(values[1]), 4),
        "delta": round(delta, 4),
        "tolerance": policy.tolerance,
        "verdict": ("too close to call" if abs(delta) < policy.tolerance
                    else "higher" if delta > 0 else "lower"),
    }


# ---------------------------------------------------------------------------
# cost
# ---------------------------------------------------------------------------


def review_cost(events: Iterable[Mapping[str, Any]], *, since: str | None, until: str | None) -> dict[str, Any]:
    """Review effort recorded between the two runs: decisions made, by whom, on how many images.

    Observed counts only. The estimate beside them is marked as an estimate and uses one
    declared rate; it is not a measurement of anyone's time.
    """
    counted = [e for e in events
               if (since is None or str(e.get("time", "")) >= since)
               and (until is None or str(e.get("time", "")) <= until)]
    statuses: dict[str, int] = {}
    for event in counted:
        statuses[str(event.get("status"))] = statuses.get(str(event.get("status")), 0) + 1
    return {
        "observed": {
            "decisions": len(counted),
            "images": len({str(e.get("sample")) for e in counted}),
            "reviewers": sorted({str(e.get("reviewer")) for e in counted if e.get("reviewer")}),
            "by_status": statuses,
            "from": since,
            "to": until,
        },
        "estimated": {
            "minutes": round(len(counted) * 20 / 60, 1),
            "basis": "20 seconds per decision; Granum does not time reviews",
        },
    }


def run_cost(created: str, aggregates: Sequence[Mapping[str, Any]], recipe: Mapping[str, Any]) -> dict[str, Any]:
    """What a run took: rounds, wall clock where the log supports it, and the settings.

    Wall clock comes from the logged rounds, so it covers training, not the whole job; when
    fewer than two rounds were logged there is nothing to measure and it stays None.
    """
    stamps = sorted(str(row["_logged"]) for row in aggregates if row.get("_logged"))
    seconds = None
    if len(stamps) >= 2:
        from datetime import datetime

        try:
            seconds = round((datetime.fromisoformat(stamps[-1]) - datetime.fromisoformat(stamps[0])).total_seconds(), 1)
        except ValueError:
            seconds = None
    return {
        "created": created,
        "rounds_logged": len(aggregates),
        "wall_clock_seconds": seconds,
        "wall_clock_covers": "the logged training rounds" if seconds is not None else None,
        "recipe": dict(recipe),
    }
