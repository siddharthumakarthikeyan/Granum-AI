"""Close the loop: retrain on the revision you committed in the dashboard.

Run 05 first, fix labels in the dashboard, commit. Then:

    python examples/06_retrain_on_latest.py
    python examples/06_retrain_on_latest.py --seeds 5 --epochs 12

The training code never mentions a revision. It asks for ``table.latest()`` and wraps it in
a weighted sampler, so corrected labels and zeroed weights flow in without code changes.

To tell whether the edits helped, the same model is trained on the original Table and on
the latest revision with identical settings and seeds, and both are scored on the CIFAR-10
*test* set, whose labels were never corrupted. One run each would prove nothing -- two
trainings differ by a point or more from seed alone -- so the comparison is paired by seed
and reported with its spread.

Every training is logged as a Run, so the retrained models sit beside the original run
in the dashboard with per-sample metrics of their own.
"""

from __future__ import annotations

import argparse
import importlib.util
import time
import urllib.request
from pathlib import Path

import numpy as np
import pyarrow.parquet as pq
import torch
import torch.nn as nn
from PIL import Image
from torch.utils.data import DataLoader

import granum
from granum import Table, create_weighted_sampler
from granum.metrics import ClassificationMetricsCollector, Predictor, collect_metrics

# Reuse 05's data and model code so the two scripts cannot drift apart.
_spec = importlib.util.spec_from_file_location("cifar05", Path(__file__).with_name("05_cifar10_resnet.py"))
cifar05 = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(cifar05)  # type: ignore[union-attr]

#: Two-sided 95% critical values of Student's t, by degrees of freedom.
T_CRITICAL_95 = {
    1: 12.706, 2: 4.303, 3: 3.182, 4: 2.776, 5: 2.571, 6: 2.447, 7: 2.365, 8: 2.306,
    9: 2.262, 10: 2.228, 11: 2.201, 12: 2.179, 14: 2.145, 19: 2.093, 29: 2.045,
}

TEST_URL = (
    "https://huggingface.co/datasets/uoft-cs/cifar10/resolve/main/"
    "plain_text/test-00000-of-00001.parquet"
)


def load_test_set(data_dir: Path) -> tuple[torch.Tensor, torch.Tensor]:
    """The 10,000 CIFAR-10 test images, normalised, with their (clean) labels."""
    import io

    path = data_dir / "cifar10-test.parquet"
    if not path.exists():
        partial = path.with_suffix(".partial")
        urllib.request.urlretrieve(TEST_URL, partial)
        partial.rename(path)
    table = pq.read_table(path)
    images = np.stack([
        ((np.asarray(Image.open(io.BytesIO(item["bytes"])).convert("RGB"), dtype=np.float32) / 255.0
          - cifar05.MEAN) / cifar05.STD).transpose(2, 0, 1)
        for item in table.column("img").to_pylist()
    ])
    labels = np.asarray(table.column("label").to_pylist(), dtype=np.int64)
    return torch.from_numpy(images), torch.from_numpy(labels)


def label_errors(table: Table, clean: np.ndarray) -> tuple[int, int]:
    """(wrong labels among weighted-in samples, samples weighted out)."""
    data = table.to_arrow()
    labels = np.asarray(data.column("label").to_pylist())
    weights = np.asarray(data.column("weight").to_pylist())
    return int(((labels != clean) & (weights > 0)).sum()), int((weights == 0).sum())


def train_and_score(
    table: Table, arm: str, seed: int, args: argparse.Namespace,
    test_images: torch.Tensor, test_labels: torch.Tensor, device: str,
) -> float:
    torch.manual_seed(seed)
    np.random.seed(seed)
    model = cifar05.make_resnet18().to(device)
    sampler = create_weighted_sampler(table, seed=seed)
    loader = DataLoader(
        table.with_transform(cifar05.train_sample),
        batch_size=args.batch_size,
        sampler=sampler,
        num_workers=args.workers,
        pin_memory=device == "cuda",
        persistent_workers=args.workers > 0,
        generator=torch.Generator().manual_seed(seed),
    )
    optimizer = torch.optim.SGD(model.parameters(), lr=args.lr, momentum=0.9, weight_decay=5e-4, nesterov=True)
    scheduler = torch.optim.lr_scheduler.OneCycleLR(
        optimizer, max_lr=args.lr * 10, total_steps=args.epochs * len(loader)
    )
    loss_fn = nn.CrossEntropyLoss()

    run = granum.init(
        "cifar10", f"retrain-{arm}-seed{seed}",
        parameters={
            "table": table.name, "seed": seed, "epochs": args.epochs, "lr": args.lr,
            "sampler": "weighted", "model": "resnet18",
        },
        description=f"ResNet-18 retrained on {table.name!r} (seed {seed})",
    )
    for epoch in range(args.epochs):
        model.train()
        for images, targets in loader:
            images = images.to(device, non_blocking=True)
            targets = targets.to(device, non_blocking=True)
            optimizer.zero_grad(set_to_none=True)
            loss = loss_fn(model(images), targets)
            loss.backward()
            optimizer.step()
            scheduler.step()

    model.eval()
    correct = 0
    with torch.no_grad():
        for start in range(0, len(test_images), 1000):
            batch = test_images[start:start + 1000].to(device)
            correct += (model(batch).argmax(1).cpu() == test_labels[start:start + 1000]).sum().item()
    accuracy = correct / len(test_images)
    granum.log({"epoch": args.epochs - 1, "test_accuracy": accuracy})

    # Per-sample metrics on the training table, so this run is inspectable like the first.
    collect_metrics(
        table,
        [ClassificationMetricsCollector(classes=cifar05.CLASSES)],
        predictor=Predictor(model, preprocess=cifar05.eval_batch, device=device),
        constants={"epoch": args.epochs - 1},
        split="train",
        batch_size=args.batch_size,
    )
    run.set_status("finished")
    return accuracy


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--root", default="/tmp/granum-cifar")
    parser.add_argument("--seeds", type=int, default=3)
    parser.add_argument("--epochs", type=int, default=10)
    parser.add_argument("--batch-size", type=int, default=256)
    parser.add_argument("--lr", type=float, default=0.01)
    parser.add_argument("--workers", type=int, default=6)
    args = parser.parse_args()

    root = Path(args.root)
    granum.set_config(granum.Config.load(
        overrides={"project-root-url": str(root / "granum")}, use_config_files=False, use_env=False,
    ))
    device = "cuda" if torch.cuda.is_available() else "cpu"

    original = Table.from_names("cifar10", "train", "initial")
    latest = original.latest()
    if latest.url == original.url:
        raise SystemExit(
            "No revision of cifar10/train/initial exists yet.\n"
            "Open the run in the dashboard, correct some labels, press commit, then rerun this."
        )

    clean = np.asarray(
        pq.read_table(root / "data" / "cifar10-train.parquet", columns=["label"])
        .column("label").to_pylist()[: len(original)]
    )
    print(f"original: {original.name}")
    print(f"latest:   {latest.name}  ({latest.depth()} revision(s) later: "
          f"{' -> '.join(t.name for t in latest.lineage())})")
    for table in (original, latest):
        wrong, excluded = label_errors(table, clean)
        print(f"  {table.name:<14} wrong labels in training: {wrong:>4}   weighted out: {excluded:>4}")

    print("\nloading the CIFAR-10 test set (clean labels) ...")
    test_images, test_labels = load_test_set(root / "data")

    scores: dict[str, list[float]] = {"original": [], "latest": []}
    for seed in range(args.seeds):
        for arm, table in (("original", original), ("latest", latest)):
            started = time.time()
            accuracy = train_and_score(table, arm, seed, args, test_images, test_labels, device)
            scores[arm].append(accuracy)
            print(f"  seed {seed}  {arm:<8}  test accuracy {100 * accuracy:6.2f}%   [{time.time() - started:.0f}s]")

    deltas = np.array(scores["latest"]) - np.array(scores["original"])
    print("\n" + "=" * 66)
    for arm in ("original", "latest"):
        values = 100 * np.array(scores[arm])
        print(f"  {arm:<8}  {values.mean():6.2f}% ± {values.std(ddof=1) if len(values) > 1 else 0:.2f}"
              f"   per seed: {', '.join(f'{v:.2f}' for v in values)}")
    mean = 100 * deltas.mean()
    spread = 100 * deltas.std(ddof=1) if len(deltas) > 1 else float("nan")
    print(f"\n  paired difference (latest - original): {mean:+.2f} points"
          f"   per seed: {', '.join(f'{100 * d:+.2f}' for d in deltas)}")
    if len(deltas) > 1:
        stderr = spread / np.sqrt(len(deltas))
        # Paired t-test at 95%. With few seeds the t critical value is much larger than 2:
        # three seeds need the mean to exceed 4.3 standard errors, not 2.
        degrees = len(deltas) - 1
        critical = T_CRITICAL_95[max(k for k in T_CRITICAL_95 if k <= degrees)]  # conservative
        low, high = mean - critical * stderr, mean + critical * stderr
        verdict = (
            "improved beyond seed noise" if low > 0
            else "worse beyond seed noise" if high < 0
            else "not distinguishable from seed noise at 95% -- run more seeds"
        )
        print(f"  95% interval [{low:+.2f}, {high:+.2f}] ({len(deltas)} seeds) -> {verdict}")
    print("=" * 66)
    print("\nThe retrained runs are in the dashboard under cifar10 -> runs.")


if __name__ == "__main__":
    main()
