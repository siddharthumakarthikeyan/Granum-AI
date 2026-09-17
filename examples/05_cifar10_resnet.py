"""Real model, real images: ResNet-18 on CIFAR-10, with planted label errors.

Run it:  python examples/05_cifar10_resnet.py
         python examples/05_cifar10_resnet.py --samples 20000 --epochs 12

Everything before this used synthetic feature vectors, which is fine for testing the
plumbing and useless for judging whether the product works. This is the real thing: a
real convolutional network, real photographs written to disk as PNGs, a real training
loop on the GPU, and per-sample metrics collected every epoch.

3% of the labels are deliberately corrupted. The question the run answers is whether
sorting by per-sample loss finds them again -- and how much of the dataset a human would
have to review to catch them all.

Afterwards the project is browsable:

    granum --project-root-url <printed path> service
    cd web && npm run dev
"""

from __future__ import annotations

import argparse
import time
from pathlib import Path

import numpy as np
import torch
import torch.nn as nn
import torchvision
from PIL import Image
from torch.utils.data import DataLoader

import granum
from granum import Table
from granum.metrics import ClassificationMetricsCollector, Predictor, collect_metrics
from granum.schemas import CategoricalLabelSchema, ImageSchema
from granum.service import thumbnails as thumbs

CLASSES = [
    "airplane", "automobile", "bird", "cat", "deer",
    "dog", "frog", "horse", "ship", "truck",
]
MEAN = np.array([0.4914, 0.4822, 0.4465], dtype=np.float32)
STD = np.array([0.2470, 0.2435, 0.2616], dtype=np.float32)


# ---------------------------------------------------------------------------
# data
# ---------------------------------------------------------------------------


CIFAR_PARQUET_URL = (
    "https://huggingface.co/datasets/uoft-cs/cifar10/resolve/main/"
    "plain_text/train-00000-of-00001.parquet"
)


def export_cifar(data_dir: Path, image_dir: Path, samples: int) -> tuple[list[str], np.ndarray]:
    """Download CIFAR-10 and write the images to disk as individual PNGs.

    Writing real files matters: a Table stores *paths*, and the dashboard serves those
    paths as images. A dataset held in a tensor in memory cannot be looked at.

    The images come from the Hugging Face parquet copy rather than torchvision's
    download, whose Toronto mirror can crawl at tens of KB/s. Same images, same order,
    same class indices.
    """
    import urllib.request

    import pyarrow.parquet as pq

    data_dir.mkdir(parents=True, exist_ok=True)
    parquet = data_dir / "cifar10-train.parquet"
    if not parquet.exists():
        partial = parquet.with_suffix(".partial")
        urllib.request.urlretrieve(CIFAR_PARQUET_URL, partial)
        partial.rename(parquet)

    rows = pq.read_table(parquet).slice(0, samples).to_pylist()
    if len(rows) < samples:
        raise ValueError(f"CIFAR-10 train has {len(rows)} images, asked for {samples}")
    image_dir.mkdir(parents=True, exist_ok=True)

    paths: list[str] = []
    labels = np.zeros(samples, dtype=np.int64)
    for index, row in enumerate(rows):
        target = image_dir / f"{index:06d}.png"
        if not target.exists():
            target.write_bytes(row["img"]["bytes"])
        paths.append(str(target))
        labels[index] = row["label"]
    return paths, labels


def build_table(paths: list[str], labels: np.ndarray, corrupt_fraction: float, seed: int):
    """Create the Table, with a known fraction of labels flipped to a wrong class."""
    rng = np.random.default_rng(seed)
    corrupted_labels = labels.copy()
    count = int(len(labels) * corrupt_fraction)
    chosen = rng.choice(len(labels), size=count, replace=False)
    for index in chosen:
        options = [c for c in range(len(CLASSES)) if c != labels[index]]
        corrupted_labels[index] = rng.choice(options)

    table = Table.from_dict_data(
        {"image": paths, "label": corrupted_labels.tolist()},
        schema={
            "image": ImageSchema(sample_type="url"),
            "label": CategoricalLabelSchema(classes=CLASSES),
        },
        project_name="cifar10",
        dataset_name="train",
        table_name="initial",
        description=f"CIFAR-10 subset with {count} planted label errors",
    )
    return table, {int(i) for i in chosen}, labels


# Module-level so DataLoader workers can pickle them.


def load_image(path: str) -> np.ndarray:
    with Image.open(path) as handle:
        array = np.asarray(handle.convert("RGB"), dtype=np.float32) / 255.0
    return ((array - MEAN) / STD).transpose(2, 0, 1)


def train_sample(sample: dict):
    """Random horizontal flip, the one augmentation worth having here."""
    array = load_image(sample["image"])
    if np.random.rand() < 0.5:
        array = array[:, :, ::-1].copy()
    return torch.from_numpy(array), int(sample["label"])


def eval_batch(batch: dict) -> torch.Tensor:
    """Metrics collection is an eval pass: no flips, no shuffling, canonical order."""
    return torch.from_numpy(np.stack([load_image(p) for p in batch["image"]]))


def make_resnet18() -> nn.Module:
    """torchvision ResNet-18, adapted for 32x32 inputs the usual way."""
    model = torchvision.models.resnet18(num_classes=len(CLASSES))
    model.conv1 = nn.Conv2d(3, 64, kernel_size=3, stride=1, padding=1, bias=False)
    model.maxpool = nn.Identity()
    return model


# ---------------------------------------------------------------------------
# scoring
# ---------------------------------------------------------------------------


def report_detection(rows: list[dict], corrupted: set[int], clean: np.ndarray) -> None:
    ranked = [r["example_id"] for r in sorted(rows, key=lambda r: -r["loss"])]
    total = len(ranked)
    planted = len(corrupted)

    def hits(k: int) -> int:
        return sum(1 for i in ranked[:k] if i in corrupted)

    print("\n" + "=" * 66)
    print("Did per-sample loss find the planted label errors?")
    print("=" * 66)
    for k in (50, 100, 250, 500):
        if k <= total:
            found = hits(k)
            print(
                f"  top {k:>4}  ->  {found:>4} of {planted} planted errors "
                f"({100 * found / planted:>5.1f}% recall, {100 * found / k:>5.1f}% precision)"
            )
    expected = planted * 50 / total
    print(f"\n  random baseline for the top 50: {expected:.1f} errors")

    print("\n  10 highest-loss samples in the final epoch:")
    print("  " + "-" * 62)
    print(f"  {'rank':>4}  {'loss':>7}  {'given':<11} {'predicted':<11} {'true':<11} planted?")
    by_id = {r["example_id"]: r for r in rows}
    for rank, example_id in enumerate(ranked[:10], start=1):
        row = by_id[example_id]
        flag = "  <-- yes" if example_id in corrupted else ""
        print(
            f"  {rank:>4}  {row['loss']:>7.3f}  "
            f"{CLASSES[row['label']]:<11} {CLASSES[row['predicted']]:<11} "
            f"{CLASSES[clean[example_id]]:<11}{flag}"
        )


# ---------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--samples", type=int, default=10000)
    parser.add_argument("--epochs", type=int, default=8)
    parser.add_argument("--batch-size", type=int, default=256)
    parser.add_argument("--lr", type=float, default=0.01)
    parser.add_argument("--corrupt", type=float, default=0.03)
    parser.add_argument("--workers", type=int, default=6)
    parser.add_argument("--root", type=str, default="/tmp/granum-cifar")
    args = parser.parse_args()

    root = Path(args.root)
    granum.set_config(
        granum.Config.load(
            overrides={"project-root-url": str(root / "granum")},
            use_config_files=False,
            use_env=False,
        )
    )
    device = "cuda" if torch.cuda.is_available() else "cpu"
    print(f"device: {device}"
          f"{' (' + torch.cuda.get_device_name(0) + ')' if device == 'cuda' else ''}")

    print(f"\npreparing {args.samples:,} CIFAR-10 images as PNGs ...")
    started = time.time()
    paths, clean_labels = export_cifar(root / "data", root / "images", args.samples)
    table, corrupted, clean_labels = build_table(paths, clean_labels, args.corrupt, seed=0)
    print(f"  {len(table):,} rows, {len(corrupted)} labels corrupted "
          f"({100 * args.corrupt:.0f}%), {time.time() - started:.1f}s")

    model = make_resnet18().to(device)
    optimizer = torch.optim.SGD(model.parameters(), lr=args.lr, momentum=0.9,
                                weight_decay=5e-4, nesterov=True)
    scheduler = torch.optim.lr_scheduler.OneCycleLR(
        optimizer, max_lr=args.lr * 10, total_steps=args.epochs * (len(table) // args.batch_size + 1)
    )
    loss_fn = nn.CrossEntropyLoss()
    loader = DataLoader(
        table.with_transform(train_sample),
        batch_size=args.batch_size,
        shuffle=True,
        num_workers=args.workers,
        pin_memory=(device == "cuda"),
        persistent_workers=args.workers > 0,
    )

    run = granum.init(
        "cifar10", "resnet18",
        parameters={
            "model": "resnet18", "lr": args.lr, "epochs": args.epochs,
            "batch_size": args.batch_size, "optimizer": "sgd+onecycle",
            "corrupt_fraction": args.corrupt, "samples": args.samples,
        },
        description="ResNet-18 on CIFAR-10 with planted label errors",
    )

    print(f"\ntraining {args.epochs} epochs ...")
    for epoch in range(args.epochs):
        model.train()
        epoch_started = time.time()
        total, correct, seen = 0.0, 0, 0
        for images, targets in loader:
            images = images.to(device, non_blocking=True)
            targets = targets.to(device, non_blocking=True)
            optimizer.zero_grad(set_to_none=True)
            logits = model(images)
            loss = loss_fn(logits, targets)
            loss.backward()
            optimizer.step()
            scheduler.step()
            total += loss.detach().item() * targets.size(0)
            correct += (logits.argmax(1) == targets).sum().item()
            seen += targets.size(0)

        train_loss, train_acc = total / seen, correct / seen
        granum.log({"epoch": epoch, "train_loss": train_loss, "train_accuracy": train_acc,
                    "lr": scheduler.get_last_lr()[0]})

        collect_started = time.time()
        collect_metrics(
            table,
            [ClassificationMetricsCollector(classes=CLASSES)],
            predictor=Predictor(model, preprocess=eval_batch, device=device),
            constants={"epoch": epoch},
            split="train",
            batch_size=args.batch_size,
        )
        print(f"  epoch {epoch}  loss={train_loss:.4f}  acc={train_acc:.4f}  "
              f"[{time.time() - epoch_started - (time.time() - collect_started):.1f}s train, "
              f"{time.time() - collect_started:.1f}s collect]")

    final = run.metrics_tables()[-1]
    report_detection(final.join_input(), corrupted, clean_labels)

    print("\npublishing thumbnails ...")
    result = thumbs.create_for_table(table, sizes=(64, 128))
    print(f"  {result['written']:,} written for {result['images']:,} images")

    print("\n" + "=" * 66)
    print("Browse it:")
    print(f"  granum --project-root-url {root / 'granum'} service")
    print("  cd web && npm run dev        # then open http://localhost:5173")
    print("\nIn the dashboard: open the resnet18 run, filter epoch to the last one,")
    print("filter accuracy to 0, sort by loss descending, switch to grid view.")
    print("=" * 66)


if __name__ == "__main__":
    main()
