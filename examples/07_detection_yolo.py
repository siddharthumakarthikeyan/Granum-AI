"""Object detection end to end: YOLO dataset in, per-box metrics out.

Run it:  python examples/07_detection_yolo.py
         python examples/07_detection_yolo.py --epochs 10 --model yolov8s.pt

Uses COCO128 -- 128 real COCO images with YOLO labels -- downloaded on first run. The
dataset is imported as Tables (train / val split), exported back to a YOLO dataset for
Ultralytics to train on, and the Granum callback logs every epoch and writes per-box
metrics: which predictions matched a ground-truth box, which did not, and which
labelled objects the model missed.

Afterwards:

    granum --project-root-url <printed path> service
    cd web && npm run dev

In the dashboard, open the run and filter predicted boxes to unmatched, high-confidence
ones: most are objects the annotators did not label. Accept the real ones, fix labels in
the patch view, commit -- then close the loop:

    python examples/07_detection_yolo.py --retrain-latest

which exports the latest revision of each split, trains the same model again, and scores
the original and the retrained weights on the *same* (revised) validation labels.
"""

from __future__ import annotations

import argparse
import shutil
import urllib.request
import zipfile
from pathlib import Path

import granum
from granum import Table, export_yolo

COCO128_URL = "https://github.com/ultralytics/assets/releases/download/v0.0.0/coco128.zip"
NAMES = [
    "person", "bicycle", "car", "motorcycle", "airplane", "bus", "train", "truck", "boat", "traffic light",
    "fire hydrant", "stop sign", "parking meter", "bench", "bird", "cat", "dog", "horse", "sheep", "cow",
    "elephant", "bear", "zebra", "giraffe", "backpack", "umbrella", "handbag", "tie", "suitcase", "frisbee",
    "skis", "snowboard", "sports ball", "kite", "baseball bat", "baseball glove", "skateboard", "surfboard",
    "tennis racket", "bottle", "wine glass", "cup", "fork", "knife", "spoon", "bowl", "banana", "apple",
    "sandwich", "orange", "broccoli", "carrot", "hot dog", "pizza", "donut", "cake", "chair", "couch",
    "potted plant", "bed", "dining table", "toilet", "tv", "laptop", "mouse", "remote", "keyboard",
    "cell phone", "microwave", "oven", "toaster", "sink", "refrigerator", "book", "clock", "vase",
    "scissors", "teddy bear", "hair drier", "toothbrush",
]


def fetch_coco128(data_dir: Path) -> Path:
    """Download COCO128 and write a dataset YAML for it. Returns the YAML path."""
    root = data_dir / "coco128"
    if not (root / "images").exists():
        data_dir.mkdir(parents=True, exist_ok=True)
        archive = data_dir / "coco128.zip"
        urllib.request.urlretrieve(COCO128_URL, archive)
        with zipfile.ZipFile(archive) as zipped:
            zipped.extractall(data_dir)
    config = root / "coco128.yaml"
    lines = [f"path: {root}", "train: images/train2017", "names:"]
    lines += [f"  {i}: {name}" for i, name in enumerate(NAMES)]
    config.write_text("\n".join(lines) + "\n")
    return config


def retrain_latest(args: argparse.Namespace, root: Path) -> None:
    from ultralytics import YOLO

    from granum.core.layout import ProjectLayout
    from granum.integration.ultralytics import add_granum_callback

    run_name = f"{Path(args.model).stem}-coco128"
    run = granum.Run.from_url(ProjectLayout(granum.get_config().project_root).runs_dir("coco128") / run_name)
    splits: dict[str, Table] = {}
    for metrics in run.metrics_tables():
        split = metrics.constants.get("split")
        if split and metrics.foreign_table_url is not None:
            splits[split] = Table.from_url(metrics.foreign_table_url)
    latest = {split: table.latest() for split, table in splits.items()}
    for split in splits:
        chain = " -> ".join(t.name for t in latest[split].lineage())
        print(f"{split}: {chain}")
    if all(latest[s].url == splits[s].url for s in splits):
        raise SystemExit("No committed revisions yet: edit boxes in the dashboard and commit first.")
    if "train" in splits and latest["train"].url == splits["train"].url:
        print("note: only validation labels changed. Training data is identical, so with a fixed seed the\n"
              "      retrained model reproduces the original; the comparison below isolates the label change.")

    export_dir = root / "yolo-export-latest"
    shutil.rmtree(export_dir, ignore_errors=True)
    data_yaml = export_yolo(latest, export_dir, image_strategy="symlink")

    model = YOLO(args.model)
    add_granum_callback(model, latest, project_name="coco128", run_name=f"{run_name}-latest")
    model.train(
        data=str(data_yaml), epochs=args.epochs, imgsz=args.imgsz, batch=args.batch, seed=0, deterministic=True,
        project=str(root / "ultralytics"), name="train-latest", exist_ok=True, verbose=False, plots=False,
    )

    # Score both models against the same, revised validation labels -- comparing mAP
    # computed on two different label sets would measure the labels, not the model.
    scores = {}
    for label, weights in (("original", root / "ultralytics" / "train" / "weights" / "best.pt"),
                           ("retrained", root / "ultralytics" / "train-latest" / "weights" / "best.pt")):
        metrics = YOLO(str(weights)).val(data=str(data_yaml), split="val", imgsz=args.imgsz, verbose=False, plots=False)
        scores[label] = (metrics.box.map50, metrics.box.map)
    print("\nOn the revised validation labels:")
    for label, (map50, map5095) in scores.items():
        print(f"  {label:<10} mAP50 {map50:.4f}   mAP50-95 {map5095:.4f}")
    print("\nOne training per side: differences below a point or two are within seed noise.")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--root", default="/tmp/granum-det")
    parser.add_argument("--model", default="yolov8n.pt")
    parser.add_argument("--epochs", type=int, default=5)
    parser.add_argument("--imgsz", type=int, default=640)
    parser.add_argument("--batch", type=int, default=16)
    parser.add_argument("--retrain-latest", action="store_true", help="retrain on the latest committed revisions")
    args = parser.parse_args()

    from ultralytics import YOLO

    from granum.integration.ultralytics import add_granum_callback

    root = Path(args.root)
    granum.set_config(granum.Config.load(
        overrides={"project-root-url": str(root / "granum")}, use_config_files=False, use_env=False,
    ))

    if args.retrain_latest:
        retrain_latest(args, root)
        return

    config = fetch_coco128(root / "data")
    full = Table.from_yolo_url(config, "train", project_name="coco128", dataset_name="coco128", table_name="all")
    train = full.subset(range_factor_max=0.8)
    val = full.subset(range_factor_min=0.8)
    boxes = lambda t: sum(len(r["bbs"]["instances"]) for r in t)  # noqa: E731
    print(f"imported {len(full)} images: train {len(train)} ({boxes(train)} boxes), val {len(val)} ({boxes(val)} boxes)")

    export_dir = root / "yolo-export"
    shutil.rmtree(export_dir, ignore_errors=True)
    data_yaml = export_yolo({"train": train, "val": val}, export_dir, image_strategy="symlink")
    print(f"exported YOLO dataset: {data_yaml}")

    model = YOLO(args.model)
    add_granum_callback(model, {"train": train, "val": val}, project_name="coco128", run_name=f"{Path(args.model).stem}-coco128")
    model.train(
        data=str(data_yaml), epochs=args.epochs, imgsz=args.imgsz, batch=args.batch,
        project=str(root / "ultralytics"), name="train", exist_ok=True, verbose=False, plots=False,
    )

    run = granum.get_active_run()
    last = run.aggregate_metrics()[-1]
    print("\nfinal epoch:", {k: round(v, 4) for k, v in last.items() if isinstance(v, float)})
    val_metrics = [t for t in run.metrics_tables() if t.constants.get("split") == "val"][-1]
    rows = val_metrics.join_input()
    predicted = [i for r in rows for i in r["bbs_predicted"]["instances"]]
    unmatched_confident = [i for i in predicted if not i["matched"] and i["confidence"] >= 0.5]
    missed = sum(r["fn"] for r in rows)
    print(f"val: {len(predicted)} predicted boxes, {sum(i['matched'] for i in predicted)} matched, "
          f"{len(unmatched_confident)} unmatched with confidence >= 0.5, {missed} labelled boxes missed")
    print(f"\nBrowse it:  granum --project-root-url {root / 'granum'} service")


if __name__ == "__main__":
    main()
