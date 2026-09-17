"""The whole data-improvement loop on a real aerial dataset, watched live in the dashboard.

    # with the dashboard running on the same project root:
    granum --project-root-url ROOT service --data-root DATA
    python examples/08_aerial_pipeline.py --project-root ROOT --data DATA/human_aerial

Five steps, each printed as it happens:

1. Import  -- health-check train and valid together (so leakage between them is found),
              import whichever split the project does not have yet.
2. Select  -- a training subset with no capture sequence shared with validation, saved
              as a new version of the train dataset.
3. Train   -- YOLO on the GPU; every epoch's scores appear under Training runs, and the
              model's predictions on every image are recorded for review.
4. Review  -- in the dashboard: open the run, look at missed objects and confident
              predictions nobody labelled, fix labels, mark decisions, save changes.
5. Retrain -- run again with --retrain: trains on the newest versions and scores both
              models on the same, current validation labels.

The comparison is one training per side. Differences of a point or two are within the
noise of a single run; the script says so rather than declaring a winner.
"""

from __future__ import annotations

import argparse
import random
import re
import shutil
import time
from collections import defaultdict
from pathlib import Path

import granum
from granum import Table, export_yolo
from granum.core.index import Index
from granum.importing import Source, import_coco, run_preflight

SEQUENCE = re.compile(r"^(?P<sequence>[A-Za-z0-9]+)[_-]\d+")
BASELINE = "baseline"


def step(number: int, title: str) -> None:
    print(f"\n=== Step {number}/5  {title} " + "=" * max(0, 60 - len(title)), flush=True)


def sequence_of(path: str) -> str | None:
    match = SEQUENCE.match(Path(path).name)
    return match.group("sequence") if match else None


def project_tables(root: Path, project: str) -> dict[str, list[Table]]:
    index = Index([root])
    index.refresh(force=True)
    out: dict[str, list[Table]] = defaultdict(list)
    for entry in index.tables(project):
        out[entry.dataset_name].append(Table.from_url(entry.url))
    return out


def root_of(tables: list[Table]) -> Table:
    roots = [t for t in tables if not t.parents]
    return sorted(roots or tables, key=lambda t: t.created)[0]


def import_missing(args: argparse.Namespace, root: Path) -> dict[str, Table]:
    step(1, "Import with a health check")
    existing = project_tables(root, args.project)
    data = Path(args.data)
    sources = [Source("train", str(data / "train" / "_annotations.coco.json")),
               Source("valid", str(data / "valid" / "_annotations.coco.json"))]
    missing = [s.split for s in sources if s.split not in existing]
    if not missing:
        print("train and valid are already in the project; nothing to import.")
    else:
        print(f"checking {', '.join(s.split for s in sources)} together; importing {', '.join(missing)}")
        started = time.time()
        report = run_preflight(sources, media="full")
        print(f"health check: {report.summary['images']:,} images, {report.summary['boxes']:,} boxes, "
              f"{time.time() - started:.1f}s -> {report.verdict}")
        for finding in report.to_dict()["findings"]:
            if finding["severity"] != "info":
                print(f"  {finding['severity']:<5} {finding['count']:>7,} {finding['unit']:<10} {finding['title']}"
                      f"  -> {finding['default']}")
        result = import_coco(report, project_name=args.project, splits=missing)
        for table in result.tables:
            print(f"imported {table['split']}: {table['rows']:,} images, {table['boxes']:,} boxes")
        existing = project_tables(root, args.project)
    return {split: root_of(existing[split]) for split in ("train", "valid")}


def select_subset(args: argparse.Namespace, root: Path, splits: dict[str, Table]) -> Table:
    step(2, "Pick a leak-free training subset")
    name = f"pipeline-{args.train_images}"
    for table in project_tables(root, args.project)["train"]:
        if table.name == name:
            print(f"reusing version {name} ({len(table):,} images)")
            return table

    valid_sequences = {sequence_of(r) for r in splits["valid"].to_arrow().column("image").to_pylist()}
    train = splits["train"]
    paths = train.to_arrow().column("image").to_pylist()
    eligible = [i for i, p in enumerate(paths) if sequence_of(p) not in valid_sequences]
    rng = random.Random(0)
    chosen = set(rng.sample(eligible, min(args.train_images, len(eligible))))
    print(f"{len(paths) - len(eligible):,} training images share a capture sequence with validation and are left out")

    chosen_paths = {paths[i] for i in chosen}
    subset = train.filter(
        lambda row: row["image"] in chosen_paths,
        name=name,
        description=f"{len(chosen)} training images from sequences not used in validation, chosen at random (seed 0)",
    )
    print(f"saved as version {subset.name}: {len(subset):,} images")
    return subset


def train(args: argparse.Namespace, root: Path, tables: dict[str, Table], run_name: str, notes: dict) -> Path:
    from ultralytics import YOLO

    from granum.integration.ultralytics import add_granum_callback

    export_dir = root.parent / f"yolo-export-{run_name}"
    shutil.rmtree(export_dir, ignore_errors=True)
    data_yaml = export_yolo({"train": tables["train"], "val": tables["valid"]}, export_dir, image_strategy="symlink")
    print(f"exported for YOLO: {data_yaml}")

    model = YOLO(args.model)
    add_granum_callback(
        model, {"valid": tables["valid"], "train": tables["train"]},
        project_name=args.project, run_name=run_name,
        collect_every=max(1, args.epochs // 2), final_only=("train",),
        parameters={"train_version": tables["train"].name, "valid_version": tables["valid"].name, **notes},
    )
    print(f"training {args.model} for {args.epochs} epochs: watch Training runs in the dashboard")
    model.train(
        data=str(data_yaml), epochs=args.epochs, imgsz=args.imgsz, batch=args.batch, seed=0, deterministic=True,
        project=str(root.parent / "ultralytics"), name=run_name, exist_ok=True, verbose=False, plots=False,
        workers=4,
    )
    return root.parent / "ultralytics" / run_name / "weights" / "best.pt"


def summarize(run: granum.Run) -> None:
    last = run.aggregate_metrics()[-1]
    print(f"final epoch: mAP50 {last.get('map50', 0):.3f}  mAP50-95 {last.get('map50_95', 0):.3f}  "
          f"precision {last.get('precision', 0):.3f}  recall {last.get('recall', 0):.3f}")
    for split in ("valid", "train"):
        tables = [t for t in run.metrics_tables() if t.constants.get("split") == split]
        if not tables:
            continue
        rows = tables[-1].to_arrow().select(["fn", "bbs_predicted"]).to_pylist()
        predicted = [i for r in rows for i in (r["bbs_predicted"] or {}).get("instances", [])]
        confident = sum(1 for i in predicted if not i["matched"] and not i.get("ignored") and i["confidence"] >= 0.5)
        print(f"{split}: {sum(r['fn'] for r in rows):,} labelled objects missed, "
              f"{confident:,} confident predictions (>= 0.5) with no label")


def first_run(args: argparse.Namespace, root: Path) -> None:
    splits = import_missing(args, root)
    subset = select_subset(args, root, splits)

    step(3, "Train and record per-image results")
    train(args, root, {"train": subset, "valid": splits["valid"]}, BASELINE, {})
    run = granum.Run.from_url(granum.ProjectLayout(root).run(args.project, BASELINE))
    summarize(run)

    step(4, "Review in the dashboard")
    print(f"""Open the project '{args.project}', then Training runs -> {BASELINE}. Suggested:
  * Filter bbs 'Missed' = true: labelled objects the model never found -- wrong or unclear labels?
  * Filter predicted boxes to 'Matched' = false and confidence above 0.5: objects nobody labelled.
  * Fix labels, mark each image Looks right / Fixed / Unclear, and press Save changes.
Then close the loop:
  python examples/08_aerial_pipeline.py --project-root {root} --data {args.data} --retrain""")


def retrain(args: argparse.Namespace, root: Path) -> None:
    from ultralytics import YOLO

    base = granum.Run.from_url(granum.ProjectLayout(root).run(args.project, BASELINE))
    used: dict[str, Table] = {}
    for metrics in base.metrics_tables():
        split = metrics.constants.get("split")
        if split and metrics.foreign_table_url is not None:
            used[split] = Table.from_url(metrics.foreign_table_url)
    latest = {split: table.latest() for split, table in used.items()}

    step(5, "Retrain on the newest versions and compare")
    for split in ("train", "valid"):
        print(f"{split}: {' -> '.join(t.name for t in latest[split].lineage())}")
    if all(str(latest[s].url) == str(used[s].url) for s in used):
        raise SystemExit("No saved changes yet: fix labels in the dashboard and press Save changes first.")

    name = f"retrained-{time.strftime('%m%d-%H%M')}"
    weights = train(args, root, latest, name, {"retrained_from": BASELINE})

    # Both models against the same, current validation labels: comparing scores computed
    # on two different label sets would measure the labels, not the models.
    data_yaml = root.parent / f"yolo-export-{name}" / "data.yaml"
    baseline_weights = root.parent / "ultralytics" / BASELINE / "weights" / "best.pt"
    scores = {}
    for label, path in (("baseline", baseline_weights), ("retrained", weights)):
        result = YOLO(str(path)).val(data=str(data_yaml), split="val", imgsz=args.imgsz, verbose=False, plots=False)
        scores[label] = (float(result.box.map50), float(result.box.map))
    run = granum.Run.from_url(granum.ProjectLayout(root).run(args.project, name))
    run.set_parameters({**run.parameters,
                        "same_labels_map50_baseline": round(scores["baseline"][0], 4),
                        "same_labels_map50_retrained": round(scores["retrained"][0], 4)})
    print(f"\nOn the current validation labels ({latest['valid'].name}):")
    for label, (map50, map5095) in scores.items():
        print(f"  {label:<10} mAP50 {map50:.4f}   mAP50-95 {map5095:.4f}")
    difference = scores["retrained"][0] - scores["baseline"][0]
    print(f"  difference mAP50 {difference:+.4f}")
    print("One training per side: a difference under about 0.01-0.02 is within the noise of a single run.")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--project-root", required=True, help="the root the dashboard service uses")
    parser.add_argument("--data", default=str(Path(__file__).resolve().parents[2] / "dataset" / "human_aerial"))
    parser.add_argument("--project", default="human_aerial")
    parser.add_argument("--train-images", type=int, default=1500)
    parser.add_argument("--epochs", type=int, default=12)
    parser.add_argument("--imgsz", type=int, default=640)
    parser.add_argument("--batch", type=int, default=16)
    parser.add_argument("--model", default="yolo26n.pt")
    parser.add_argument("--retrain", action="store_true", help="retrain on the newest saved versions and compare")
    args = parser.parse_args()

    root = Path(args.project_root)
    granum.set_config(granum.Config.load(overrides={"project-root-url": str(root)}, use_config_files=False, use_env=False))
    if args.retrain:
        retrain(args, root)
    else:
        first_run(args, root)


if __name__ == "__main__":
    main()
