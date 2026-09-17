"""Benchmark: how well does Granum surface corrupted labels?

Run it:  python examples/03_label_error_ranking.py
         python examples/03_label_error_ranking.py --seeds 10 --samples 500 --corrupt 25

This is a *repeatable measurement*, not a demo. It plants a known number of label errors,
trains a model, ranks every sample with each registered detector, and scores the ranking
against ground truth it alone knows.

Why it exists: "8 of the top 10 were corrupted" is precision@10, and the 10 is a choice
of how many rows to print -- not a property of the system. The numbers that matter are
recall at a review budget, and how much of the dataset a human must look at to find
essentially every bad label.

Add a detector here as the product grows. Stage 2 can only rank by what a single
inference pass reveals; the Stage 15 detectors (embedding-neighbourhood disagreement,
confident learning, ranked severity) plug into the same harness and are scored the same
way, so improvement is measurable rather than asserted.
"""

from __future__ import annotations

import argparse
import statistics
import tempfile
from pathlib import Path
from typing import Callable

import numpy as np
import torch
from torch import nn

import granum
from granum import Table
from granum.metrics import ClassificationMetricsCollector, Predictor, collect_metrics
from granum.schemas import CategoricalLabelSchema

CLASSES = ["low", "mid", "high"]

# A ranking: example_ids ordered most-suspicious first.
Detector = Callable[[list[dict]], list[int]]


# ---------------------------------------------------------------------------
# detectors
# ---------------------------------------------------------------------------


def by_loss(rows: list[dict]) -> list[int]:
    """Highest per-sample loss first. What Stage 2 makes possible."""
    return [r["example_id"] for r in sorted(rows, key=lambda r: -r["loss"])]


def by_low_confidence(rows: list[dict]) -> list[int]:
    """Least confident prediction first."""
    return [r["example_id"] for r in sorted(rows, key=lambda r: r["confidence"])]


def by_confident_disagreement(rows: list[dict]) -> list[int]:
    """Confidently wrong first: the model disagrees with the label *and* is sure.

    A cheap stand-in for what confident learning does properly in Stage 15. Correct
    predictions sort to the back regardless of confidence.
    """
    def key(row: dict) -> tuple[int, float]:
        disagrees = row["predicted"] != row["label"]
        return (0 if disagrees else 1, -row["confidence"])

    return [r["example_id"] for r in sorted(rows, key=key)]


def random_order(rows: list[dict]) -> list[int]:
    """The control. Any detector that cannot beat this is worthless."""
    rng = np.random.default_rng(0)
    ids = [r["example_id"] for r in rows]
    rng.shuffle(ids)
    return ids


DETECTORS: dict[str, Detector] = {
    "random (control)": random_order,
    "low confidence": by_low_confidence,
    "highest loss": by_loss,
    "confident disagreement": by_confident_disagreement,
}


# ---------------------------------------------------------------------------
# scoring
# ---------------------------------------------------------------------------


def precision_at(ranking: list[int], corrupted: set[int], k: int) -> float:
    return sum(1 for i in ranking[:k] if i in corrupted) / k


def recall_at(ranking: list[int], corrupted: set[int], k: int) -> float:
    return sum(1 for i in ranking[:k] if i in corrupted) / len(corrupted)


def average_precision(ranking: list[int], corrupted: set[int]) -> float:
    hits = 0
    total = 0.0
    for position, example_id in enumerate(ranking, start=1):
        if example_id in corrupted:
            hits += 1
            total += hits / position
    return total / len(corrupted)


def review_effort(ranking: list[int], corrupted: set[int], target_recall: float = 1.0) -> int:
    """How many samples a human must review to reach ``target_recall``."""
    needed = int(round(len(corrupted) * target_recall))
    hits = 0
    for position, example_id in enumerate(ranking, start=1):
        if example_id in corrupted:
            hits += 1
            if hits >= needed:
                return position
    return len(ranking)


# ---------------------------------------------------------------------------
# the experiment
# ---------------------------------------------------------------------------


class TinyNet(nn.Module):
    def __init__(self) -> None:
        super().__init__()
        self.hidden = nn.Linear(4, 16)
        self.relu = nn.ReLU()
        self.head = nn.Linear(16, len(CLASSES))

    def forward(self, x):
        return self.head(self.relu(self.hidden(x)))


def as_tensors(sample: dict):
    return torch.tensor(sample["features"], dtype=torch.float32), int(sample["label"])


def to_tensor(batch: dict):
    return torch.tensor(np.asarray(batch["features"], dtype=np.float32))


def build_corrupted_table(seed: int, samples: int, corrupt: int) -> tuple[Table, set[int]]:
    """A separable 3-class problem with a known set of labels flipped.

    Labels come from thresholds at exactly zero on two features, so samples near the
    boundary are genuinely ambiguous. A detector that surfaces those is not making a
    mistake -- they are worth a human's attention too.
    """
    rng = np.random.default_rng(seed)
    features = rng.normal(size=(samples, 4)).astype(np.float32)
    labels = (features[:, 0] > 0).astype(int) + (features[:, 1] > 0).astype(int)

    corrupted = rng.choice(samples, size=corrupt, replace=False)
    labels[corrupted] = (labels[corrupted] + 1) % len(CLASSES)

    table = Table.from_dict_data(
        {"features": features.tolist(), "label": labels.tolist()},
        schema={"label": CategoricalLabelSchema(classes=CLASSES)},
        project_name="label-error-benchmark",
        dataset_name="synthetic",
        table_name=f"seed-{seed}",
    )
    return table, {int(i) for i in corrupted}


def run_trial(seed: int, samples: int, corrupt: int, epochs: int) -> tuple[list[dict], set[int]]:
    """Train once and return the joined metrics rows plus the planted errors."""
    table, corrupted = build_corrupted_table(seed, samples, corrupt)

    torch.manual_seed(seed)
    model = TinyNet()
    optimizer = torch.optim.Adam(model.parameters(), lr=0.01)
    loss_fn = nn.CrossEntropyLoss()
    loader = torch.utils.data.DataLoader(
        table.with_transform(as_tensors), batch_size=16, shuffle=True
    )

    run = granum.init("label-error-benchmark", f"seed-{seed}", parameters={"seed": seed})
    for epoch in range(epochs):
        model.train()
        total = 0.0
        for features, labels in loader:
            optimizer.zero_grad()
            loss = loss_fn(model(features), labels)
            loss.backward()
            optimizer.step()
            total += loss.detach().item()
        granum.log({"epoch": epoch, "train_loss": total / len(loader)})

    metrics = collect_metrics(
        table,
        [ClassificationMetricsCollector(classes=CLASSES)],
        predictor=Predictor(model, preprocess=to_tensor),
        split="train",
    )
    del run
    return metrics.join_input(), corrupted


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seeds", type=int, default=5)
    parser.add_argument("--samples", type=int, default=240)
    parser.add_argument("--corrupt", type=int, default=10)
    parser.add_argument("--epochs", type=int, default=8)
    args = parser.parse_args()

    workdir = Path(tempfile.mkdtemp(prefix="granum-benchmark-"))
    granum.set_config(
        granum.Config.load(
            overrides={"project-root-url": str(workdir / "granum")},
            use_config_files=False,
            use_env=False,
        )
    )

    print(
        f"Label-error ranking benchmark\n"
        f"  {args.seeds} seeds x {args.samples} samples, "
        f"{args.corrupt} planted label errors ({100 * args.corrupt / args.samples:.1f}%), "
        f"{args.epochs} epochs\n"
    )

    scores: dict[str, dict[str, list[float]]] = {
        name: {"p10": [], "r20": [], "ap": [], "effort": [], "ranks": []}
        for name in DETECTORS
    }

    for seed in range(args.seeds):
        rows, corrupted = run_trial(seed, args.samples, args.corrupt, args.epochs)
        for name, detector in DETECTORS.items():
            ranking = detector(rows)
            scores[name]["p10"].append(precision_at(ranking, corrupted, 10))
            scores[name]["r20"].append(recall_at(ranking, corrupted, 20))
            scores[name]["ap"].append(average_precision(ranking, corrupted))
            scores[name]["effort"].append(review_effort(ranking, corrupted))
            scores[name]["ranks"].extend(
                ranking.index(i) + 1 for i in corrupted
            )
        print(f"  seed {seed} done")

    header = f"\n{'detector':<24}{'P@10':>7}{'R@20':>8}{'AP':>7}{'med rank':>10}{'review effort':>16}"
    print(header)
    print("-" * len(header.strip()))

    for name in DETECTORS:
        s = scores[name]
        effort = statistics.mean(s["effort"])
        print(
            f"{name:<24}"
            f"{statistics.mean(s['p10']):>7.2f}"
            f"{statistics.mean(s['r20']):>8.2f}"
            f"{statistics.mean(s['ap']):>7.3f}"
            f"{int(statistics.median(s['ranks'])):>10}"
            f"{effort:>10.0f} of {args.samples}"
        )

    best = max(DETECTORS, key=lambda n: statistics.mean(scores[n]["ap"]))
    best_effort = statistics.mean(scores[best]["effort"])
    saved = 100 * (1 - best_effort / args.samples)

    print("\n  P@10   share of the top 10 that were planted errors")
    print("  R@20   share of all planted errors found in the top 20")
    print("  AP     average precision over the whole ranking")
    print("  review effort  samples a human must check to find every planted error")
    print(
        f"\n  Best detector: {best!r}.\n"
        f"  Reviewing {best_effort:.0f} of {args.samples} samples "
        f"({best_effort / args.samples * 100:.0f}%) finds every planted error "
        f"-- {saved:.0f}% less review than checking the whole dataset."
    )
    print(
        "\n  Caveat: synthetic data, and these detectors only see one inference pass.\n"
        "  Re-run on a real dataset before quoting any of this externally."
    )


if __name__ == "__main__":
    main()
