"""One reading of whether a dataset is fit to train on, and what to do about it.

Granum already knows most of this: the import found broken files, the neighbour graph found
copies and leaks, a check found labels worth looking at, the review log knows what has been
verified. Each of those lives on the page where it was produced, which is the right place to
*work*, and the wrong place to answer "is this ready?".

So this module is a set of rules, not a new measurement. It takes what the other parts
already computed, judges each against a stated threshold, and returns one row per check with
a severity and a sentence that says what it means. The thresholds are here, in one place,
with the reasoning beside them, because that is the part a team will want to argue with.

Severity follows the import's vocabulary: ``block`` is a reason not to train yet, ``warn``
is a reason to look, ``ok`` is nothing to do.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from typing import Any

#: Severity order, worst first, for sorting a report.
ORDER = ("block", "warn", "ok")


@dataclass(frozen=True)
class HealthPolicy:
    #: A class with fewer labels than this has little for a model to learn from.
    min_class_labels: int = 50
    #: ...or fewer than this share of the largest class, which is the same problem told
    #: from the other end: an imbalance the loss will quietly ignore.
    rare_share: float = 0.02
    #: A held-out set smaller than this measures a model to roughly one percent, which is
    #: coarser than the differences teams try to read from it.
    min_holdout: int = 100
    #: Repeats above this share of a set are worth removing before training.
    duplicate_share: float = 0.01
    #: Images with nothing like them, above this share, mean the set is not one set.
    outlier_share: float = 0.05
    #: Drafted boxes nobody has checked, above this share of all boxes.
    drafted_share: float = 0.01
    #: Verified images below this share of the set: the review has barely started.
    verified_share: float = 0.5

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def check(code: str, severity: str, title: str, detail: str, **extra: Any) -> dict[str, Any]:
    """One row of the report: what was looked at, what was found, and how bad it is."""
    return {"code": code, "severity": severity, "title": title, "detail": detail, **extra}


def _plural(count: int, word: str, many: str | None = None) -> str:
    return f"{count:,} {word if count == 1 else (many or word + 's')}"


def class_balance(
    counts: Mapping[int, int],
    names: Mapping[int, str] | None = None,
    policy: HealthPolicy = HealthPolicy(),
) -> list[dict[str, Any]]:
    """Every class with how much of the set it is, and whether that is enough to learn.

    Two ways a class is too small, and they are not the same thing: too few labels in
    absolute terms (nothing to learn from), and too small a share of the largest class
    (something to learn from, but the loss is dominated by other classes). Either is worth
    saying before a run spends an afternoon proving it.
    """
    names = names or {}
    if not counts:
        return []
    largest = max(counts.values())
    rows = []
    for label, count in counts.items():
        share = count / largest if largest else 0.0
        if count < policy.min_class_labels:
            verdict = "too few"
        elif share < policy.rare_share:
            verdict = "rare"
        else:
            verdict = "ok"
        rows.append({
            "label": label,
            "name": names.get(label, str(label)),
            "labels": count,
            "share_of_largest": round(share, 4),
            "verdict": verdict,
        })
    rows.sort(key=lambda row: (-row["labels"], row["name"]))
    return rows


def report(summary: Mapping[str, Any], policy: HealthPolicy = HealthPolicy()) -> dict[str, Any]:
    """Judge one dataset from what the rest of Granum has already found.

    ``summary`` is what the service gathers: set sizes, class counts, the neighbour graph's
    numbers, the newest check's findings, review progress and drafted boxes. Anything
    missing is reported as *not looked at* rather than as passing, which is the difference
    between a report worth trusting and a green tick.
    """
    checks: list[dict[str, Any]] = []
    images = int(summary.get("images") or 0)
    sets: dict[str, int] = {str(k): int(v) for k, v in (summary.get("sets") or {}).items()}

    # -- is there a set to measure with at all --------------------------------------
    holdout = {name: n for name, n in sets.items() if name not in ("train", "removed", "isolated")}
    if not holdout:
        checks.append(check("holdout", "block", "Nothing to measure with",
                            "Every image is in the training set, so a score from it would only say how "
                            "well the model memorised. Split off a validation set before training.",
                            value=0))
    else:
        smallest = min(holdout.values())
        if smallest < policy.min_holdout:
            name = min(holdout, key=lambda key: holdout[key])
            checks.append(check("holdout", "warn", "The held-out set is small",
                                f"{name} holds {_plural(smallest, 'image')}. A set this size measures a "
                                f"model to about a percentage point, which is coarser than most of the "
                                f"differences teams read from it.", value=smallest))
        else:
            checks.append(check("holdout", "ok", "There is a set to measure with",
                                " · ".join(f"{name} {n:,}" for name, n in sorted(holdout.items())),
                                value=smallest))

    # -- class balance ---------------------------------------------------------------
    balance = class_balance({int(k): int(v) for k, v in (summary.get("class_counts") or {}).items()},
                            {int(k): v for k, v in (summary.get("class_names") or {}).items()}, policy)
    struggling = [row for row in balance if row["verdict"] != "ok"]
    if not balance:
        checks.append(check("classes", "warn", "No labels to weigh",
                            "Nothing in this dataset is labelled yet, so there is nothing to train on.",
                            value=0))
    elif struggling:
        worst = ", ".join(f"{row['name']} ({row['labels']:,})" for row in struggling[:4])
        checks.append(check("classes", "warn",
                            "A class is too small to learn" if len(struggling) == 1
                            else "Some classes are too small to learn",
                            f"{_plural(len(struggling), 'class', 'classes')} "
                            f"{'has' if len(struggling) == 1 else 'have'} fewer than "
                            f"{policy.min_class_labels} labels or under "
                            f"{round(policy.rare_share * 100)}% of the largest class: {worst}"
                            f"{' …' if len(struggling) > 4 else ''}.",
                            value=len(struggling), rows=struggling[:12]))
    else:
        checks.append(check("classes", "ok", "Every class has enough to learn from",
                            f"{_plural(len(balance), 'class', 'classes')}, the smallest with "
                            f"{min(row['labels'] for row in balance):,} labels.", value=len(balance)))

    # -- copies, leaks and outliers ----------------------------------------------------
    graph = summary.get("graph")
    if not graph:
        checks.append(check("copies", "warn", "Nobody has looked for copies",
                            "Reading the images once finds the same picture exported twice, and images "
                            "that sit in both the training set and a set you measure with.", value=None))
    else:
        leaks = int(graph.get("leaks") or 0)
        repeats = int(graph.get("redundant") or 0)
        outliers = int(graph.get("alone") or 0)
        if leaks:
            checks.append(check("leaks", "block", "Images are in two sets at once",
                                f"{_plural(leaks, 'pair')} straddle a split, so a score measured on those "
                                f"sets is partly a memory test.", value=leaks))
        else:
            checks.append(check("leaks", "ok", "No image is in two sets at once",
                                "Nothing in a set you measure with is a near copy of something trained on.",
                                value=0))
        share = repeats / images if images else 0.0
        if share > policy.duplicate_share:
            checks.append(check("copies", "warn", "The same picture is in here more than once",
                                f"{_plural(repeats, 'picture')} repeat another ({round(share * 100, 1)}% of "
                                f"the set). Exported copies of one picture are not counted.", value=repeats))
        else:
            checks.append(check("copies", "ok", "Few repeated pictures",
                                f"{_plural(repeats, 'picture')} repeat another.", value=repeats))
        if images and outliers / images > policy.outlier_share:
            checks.append(check("outliers", "warn", "A lot of images have nothing like them",
                                f"{_plural(outliers, 'image')} sit further from everything else than images "
                                f"of this set usually are from each other. That is often two datasets in one.",
                                value=outliers))

    # -- labels worth checking ----------------------------------------------------------
    findings = summary.get("findings")
    if findings and int(findings.get("images") or 0):
        checks.append(check("findings", "warn", "Labels are worth checking",
                            f"{_plural(int(findings['images']), 'image')} carry a finding from "
                            f"{findings.get('from') or 'a model'}: "
                            + ", ".join(f"{name.replace('_', ' ')} {count:,}"
                                        for name, count in (findings.get("counts") or {}).items() if count),
                            value=int(findings["images"])))
    elif findings is not None:
        checks.append(check("findings", "ok", "No label raised a finding",
                            "The model agrees with every label it can judge here.", value=0))
    else:
        checks.append(check("findings", "warn", "Nothing has read the labels",
                            "A check reads every image once with a model and lists the labels it "
                            "disagrees with. It needs no training.", value=None))

    # -- drafts nobody has checked -------------------------------------------------------
    drafted = int(summary.get("drafted_boxes") or 0)
    boxes = int(summary.get("boxes") or 0)
    if drafted:
        share = drafted / boxes if boxes else 1.0
        severity = "warn" if share > policy.drafted_share else "ok"
        checks.append(check("drafts", severity, "Boxes a model drew are still drafts",
                            f"{_plural(drafted, 'box', 'boxes')} of {boxes:,} were drawn by a model and "
                            f"nobody has checked them.", value=drafted))

    # -- review progress -------------------------------------------------------------------
    verified = int(summary.get("verified") or 0)
    if images:
        share = verified / images
        checks.append(check(
            "review", "ok" if share >= policy.verified_share else "warn",
            "Review" if share >= policy.verified_share else "Most images have not been looked at",
            f"{_plural(verified, 'image')} of {images:,} verified ({round(share * 100)}%).",
            value=verified))

    checks.sort(key=lambda row: (ORDER.index(row["severity"]), row["code"]))
    counts = {name: sum(1 for row in checks if row["severity"] == name) for name in ORDER}
    return {
        "checks": checks,
        "counts": counts,
        # One word for the whole dataset, which is what a reader wants before the detail.
        "verdict": "block" if counts["block"] else "warn" if counts["warn"] else "ok",
        "policy": policy.to_dict(),
        "balance": balance,
    }


def worst_first(checks: Sequence[Mapping[str, Any]]) -> list[Mapping[str, Any]]:
    return sorted(checks, key=lambda row: ORDER.index(str(row.get("severity", "ok"))))
