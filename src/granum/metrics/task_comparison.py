"""Paired comparisons for classification and semantic runs on frozen evaluation data."""
from __future__ import annotations

from typing import Any

import numpy as np

from granum.core.objects.table import Table
from granum.errors import GranumError
from granum.training.data import contract


def vision_image_rounds(run: Any, source: Any, example: int) -> dict[str, Any]:
    from granum.training.data import classification_label

    task = run.parameters["task"]
    metric = "accuracy" if task == "classify" else "mean_iou"
    spec = contract(source, task)
    row = source.to_arrow().slice(example, 1).to_pylist()[0]
    geometry = row[spec["column"]] if task == "semantic" else {}
    rounds = {}
    for table in run.metrics_tables():
        if str(table.foreign_table_url) != str(source.url) or "epoch" not in table.constants or metric not in table.columns:
            continue
        record = next((r for r in table.to_arrow().to_pylist() if r["example_id"] == example), None)
        if record is not None:
            epoch = int(table.constants["epoch"])
            rounds[epoch] = {"epoch": epoch, "score": record[metric], "predicted": record.get("predicted"),
                             "confidence": record.get("confidence"), "masks": (record.get("bbs_predicted") or {}).get("instances", [])}
    if not rounds:
        raise GranumError("No recorded epochs for this image and table.")
    return {"task": task, "metric": metric, "image": row[spec["image"]], "width": geometry.get("width"), "height": geometry.get("height"),
            "labels": spec["names"], "label": classification_label(row, spec) if task == "classify" else None,
            "truth": geometry.get("instances", []), "rounds": [rounds[epoch] for epoch in sorted(rounds)]}


def _splits(run: Any) -> dict[str, Any]:
    found: dict[str, Any] = {}
    for table in run.metrics_tables():
        split = table.constants.get("split")
        if split and table.foreign_table_url:
            old = found.get(split)
            if old is None or int(table.constants.get("epoch", -1)) >= int(old.constants.get("epoch", -1)):
                found[split] = table
    return found


def compare_vision(baseline: Any, candidate: Any, split: str | None = None) -> dict[str, Any]:
    task = candidate.parameters.get("task")
    if task not in ("classify", "semantic") or baseline.parameters.get("task") != task:
        raise GranumError("Choose two runs with the same classification or semantic task.")
    if baseline.project_name != candidate.project_name or str(baseline.url) == str(candidate.url):
        raise GranumError("Choose two different runs in the same project.")
    if not baseline.parameters.get("evaluator") or not candidate.parameters.get("evaluator"):
        raise GranumError("Both runs must record their evaluation rules.")
    if baseline.parameters.get("evaluator") != candidate.parameters.get("evaluator"):
        raise GranumError("The runs used different evaluation rules.")
    left, right = _splits(baseline), _splits(candidate)
    shared = sorted(set(left) & set(right), key=lambda key: ({"test": 0, "valid_best": 1, "valid": 2, "train": 9}.get(key, 5), key))
    split = split or (shared[0] if shared else None)
    if split not in shared:
        raise GranumError("No shared evaluation split with per-image metrics is available.")
    before, after = left[split], right[split]
    if str(before.foreign_table_url) != str(after.foreign_table_url):
        raise GranumError("Comparison requires the same frozen evaluation table on both runs.")
    source = Table.from_url(before.foreign_table_url)
    spec = contract(source, task)
    a, b = before.to_arrow().to_pydict(), after.to_arrow().to_pydict()
    ids_a, ids_b = a["example_id"], b["example_id"]
    if not ids_a or len(set(ids_a)) != len(ids_a) or len(set(ids_b)) != len(ids_b) or set(ids_a) != set(ids_b) or set(ids_a) != set(range(len(source))):
        raise GranumError("Both runs must score every evaluation image exactly once.")
    positions = {value: i for i, value in enumerate(ids_b)}
    order = [positions[value] for value in ids_a]
    metric = "accuracy" if task == "classify" else "mean_iou"
    x, y = np.array(a[metric], dtype=float), np.array(b[metric], dtype=float)[order]
    if not np.isfinite(x).all() or not np.isfinite(y).all():
        raise GranumError("Evaluation contains unavailable or nonfinite image scores.")
    if task == "semantic":
        classes = spec["classes"]
        ai = np.array([a[f"class_{c}_intersection"] for c in classes], dtype=float).T
        au = np.array([a[f"class_{c}_union"] for c in classes], dtype=float).T
        bi = np.array([b[f"class_{c}_intersection"] for c in classes], dtype=float).T[order]
        bu = np.array([b[f"class_{c}_union"] for c in classes], dtype=float).T[order]

        def pooled(indices: Any, intersections: Any, unions: Any) -> float:
            i, u = intersections[indices].sum(0), unions[indices].sum(0)
            return float((i[u > 0] / u[u > 0]).mean())

        before_score, after_score = pooled(slice(None), ai, au), pooled(slice(None), bi, bu)
    else:
        before_score, after_score = float(x.mean()), float(y.mean())
    rng = np.random.default_rng(0)
    differences = []
    for _ in range(500):
        sample = rng.integers(0, len(x), size=len(x))
        differences.append(pooled(sample, bi, bu) - pooled(sample, ai, au) if task == "semantic" else float((y[sample] - x[sample]).mean()))
    images = source.to_arrow().column(spec["image"]).to_pylist()
    rows = [{"row": int(index), "image": images[index], "baseline": float(old), "candidate": float(new),
             "delta": float(new - old), "outcome": "improved" if new > old + 1e-12 else "regressed" if new < old - 1e-12 else "unchanged"}
            for index, old, new in zip(ids_a, x, y)]
    recipe_keys = ["framework", "version", "epochs", "imgsz", "batch", "seed", "learning_rate", "pretrained"]
    complete_recipes = all(run.parameters.get(key) is not None for run in [baseline, candidate] for key in recipe_keys)
    evaluated_split = "valid" if split == "valid_best" else split
    held_out = evaluated_split in {"test", "valid"} and all(
        run.parameters.get(f"{evaluated_split}_table") == str(source.url)
        and (run.parameters.get("preflight") or {}).get("split_overlap") is False
        and (run.parameters.get("preflight") or {}).get("media_sha256_checked") is True
        and (run.parameters.get("preflight") or {}).get("splits", {}).get(evaluated_split) == len(source)
        for run in [baseline, candidate]
    )
    return {"version": "vision-comparison-1", "task": task, "metric": metric, "split": split,
            "shared_splits": shared, "table": str(source.url), "images": len(rows),
            "baseline": {"name": baseline.name, "score": before_score},
            "candidate": {"name": candidate.name, "score": after_score},
            "delta": after_score - before_score, "bootstrap_95": np.quantile(differences, [.025, .975]).tolist(),
            "uncertainty": "Paired image bootstrap (500 resamples). This measures evaluation-sample uncertainty, not training-seed variation or a causal effect of editing.",
            "held_out": held_out,
            "recipe_matches": all(baseline.parameters[key] == candidate.parameters[key] for key in recipe_keys) if complete_recipes else None,
            "outcomes": {key: sum(r["outcome"] == key for r in rows) for key in ["improved", "regressed", "unchanged"]},
            "rows": rows}
