"""Stage 2 example: three lines added to an ordinary training loop.

Run it:  python examples/02_runs_and_metrics.py

This is the Stage 2 client test from the build plan. Note what is *not* here: the model,
the optimizer and the loop are ordinary PyTorch. Granum adds an init, a log and a
collect -- and in exchange every metric resolves back to the sample that produced it.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

import numpy as np
import torch
from torch import nn

import granum
from granum import Table
from granum.metrics import ClassificationMetricsCollector, Predictor, collect_metrics
from granum.schemas import CategoricalLabelSchema

CLASSES = ["low", "mid", "high"]


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


def build_table(n: int = 240) -> Table:
    rng = np.random.default_rng(0)
    features = rng.normal(size=(n, 4)).astype(np.float32)
    labels = (features[:, 0] > 0).astype(int) + (features[:, 1] > 0).astype(int)

    # Corrupt ten labels on purpose. Finding these again at the end is the whole point.
    corrupted = rng.choice(n, size=10, replace=False)
    labels[corrupted] = (labels[corrupted] + 1) % len(CLASSES)

    table = Table.from_dict_data(
        {"features": features.tolist(), "label": labels.tolist()},
        schema={"label": CategoricalLabelSchema(classes=CLASSES)},
        project_name="stage2-demo",
        dataset_name="synthetic",
        table_name="initial",
    )
    return table, set(int(i) for i in corrupted)


def main() -> None:
    workdir = Path(tempfile.mkdtemp(prefix="granum-stage2-"))
    granum.set_config(
        granum.Config.load(
            overrides={"project-root-url": str(workdir / "granum")},
            use_config_files=False,
            use_env=False,
        )
    )

    table, corrupted = build_table()
    print(f"== dataset ==\n   {len(table)} samples, {len(corrupted)} labels deliberately corrupted\n")

    model = TinyNet()
    optimizer = torch.optim.Adam(model.parameters(), lr=0.01)
    loss_fn = nn.CrossEntropyLoss()
    loader = torch.utils.data.DataLoader(
        table.with_transform(as_tensors), batch_size=16, shuffle=True
    )

    # ---- line 1 of 3 -----------------------------------------------------
    run = granum.init(
        "stage2-demo", "baseline", parameters={"lr": 0.01, "epochs": 8, "batch_size": 16}
    )

    print("== training ==")
    for epoch in range(8):
        model.train()
        total = 0.0
        for features, labels in loader:
            optimizer.zero_grad()
            loss = loss_fn(model(features), labels)
            loss.backward()
            optimizer.step()
            total += loss.detach().item()

        # ---- line 2 of 3 -------------------------------------------------
        granum.log({"epoch": epoch, "train_loss": total / len(loader)})

        # ---- line 3 of 3 -------------------------------------------------
        collect_metrics(
            table,
            [ClassificationMetricsCollector(classes=CLASSES)],
            predictor=Predictor(model, preprocess=to_tensor),
            constants={"epoch": epoch},
            split="train",
        )
        print(f"   epoch {epoch}  train_loss={total / len(loader):.4f}")

    print("\n== aggregate metrics ==")
    for row in run.aggregate_metrics():
        print(f"   epoch {row['epoch']}  train_loss={row['train_loss']:.4f}")

    print(f"\n== per-sample metrics ==\n   {len(run.metrics_tables())} metrics tables recorded")

    final = run.metrics_tables()[-1]
    joined = final.join_input()
    worst = sorted(joined, key=lambda r: -r["loss"])[:10]

    print("\n== the 10 highest-loss samples in the final epoch ==")
    print("   example_id   loss    label -> predicted   corrupted?")
    hits = 0
    for row in worst:
        flag = "  <-- yes" if row["example_id"] in corrupted else ""
        hits += 1 if row["example_id"] in corrupted else 0
        print(
            f"   {row['example_id']:>10}  {row['loss']:>6.3f}   "
            f"{CLASSES[row['label']]:>4} -> {CLASSES[row['predicted']]:<5}{flag}"
        )

    print(f"\n   {hits} of the 10 worst samples were the labels we corrupted.")
    print("   That is the product: a metric you don't like, resolved to the sample behind it.")
    print(f"\nproject root: {workdir / 'granum'}")


if __name__ == "__main__":
    main()
