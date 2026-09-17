"""Train a detector on dataset versions, record everything in Granum, compare runs.

What the dashboard's *Train a model* button runs, as a separate process so a long GPU job
never blocks or crashes the service. Usable directly:

    python -m granum.training.train --project-root ROOT --project aerial \\
        --train-table URL --valid-table URL --run-name retrained \\
        --family yolo --version yolo26n.pt --epochs 12 --track-learning --compare-with baseline

Families: ``yolo`` and ``rtdetr`` (Ultralytics), ``rfdetr`` (Roboflow). All three record
the same things: per-epoch scores, per-image results with boxes at the middle and final
epochs, per-image scores every epoch with ``--track-learning``, and a final score from
:mod:`granum.training.evaluate`, which is computed the same way for every framework.

Progress is reported as ``GRANUM_PHASE <text>`` and ``GRANUM_PROGRESS <done> <total>``
lines on stdout.
"""

from __future__ import annotations

import argparse
import re
import shutil
import sys
from pathlib import Path
from typing import Any

from granum.training.models import version_ids


def phase(text: str) -> None:
    print(f"GRANUM_PHASE {text}", flush=True)


def progress(done: int, total: int) -> None:
    print(f"GRANUM_PROGRESS {min(done, total)} {total}", flush=True)


def step(done: int, total: int) -> None:
    """Progress within the current round, so a long round does not look stuck."""
    print(f"GRANUM_STEP {min(done, total)} {total}", flush=True)


# -- predictors for scoring ------------------------------------------------------


def predictor_for(framework: str, version: str, weights: Path, table: Any, *, imgsz: int, conf: float) -> Any:
    from granum.core.schemas.geometry import BoundingBoxes2DSchema

    column = next(n for n in table.columns if isinstance(table.schema[n], BoundingBoxes2DSchema))
    value_map = table.schema[column].value_map
    if framework == "rfdetr":
        from granum.integration.rfdetr import RFDETRPredictor, load_rfdetr

        return RFDETRPredictor(load_rfdetr(version, weights), value_map, conf=conf)
    from granum.integration.ultralytics import YOLOPredictor

    return YOLOPredictor(str(weights), value_map, conf=conf, imgsz=imgsz)


def weights_for(run: Any, root: Path, work: Path) -> Path | None:
    """Where a Run's best weights are: recorded on the Run, or where Granum's scripts put them."""
    candidates = [run.parameters.get("weights"), work / "runs" / run.name / "weights" / "best.pt",
                  root.parent / "ultralytics" / run.name / "weights" / "best.pt"]
    for candidate in candidates:
        if candidate and Path(candidate).exists():
            return Path(candidate)
    return None


# -- Ultralytics: YOLO and RT-DETR ----------------------------------------------------


def train_ultralytics(args: argparse.Namespace, train: Any, valid: Any, work: Path) -> tuple[Any, Path]:
    import granum
    from granum import export_yolo
    from granum.integration.ultralytics import add_granum_callback

    phase("Preparing the images")
    export_dir = work / "exports" / args.run_name
    shutil.rmtree(export_dir, ignore_errors=True)
    data_yaml = export_yolo({"train": train, "val": valid}, export_dir, image_strategy="symlink")

    phase("Loading the model")
    if args.family == "rtdetr":
        from ultralytics import RTDETR

        model = RTDETR(args.version)
    else:
        from ultralytics import YOLO

        model = YOLO(args.version)
    add_granum_callback(
        model, {"valid": valid, "train": train},
        project_name=args.project, run_name=args.run_name,
        collect_every=max(1, args.epochs // 2), final_only=("train",),
        track_learning=args.track_learning,
        parameters=run_parameters(args, train, valid),
    )

    def on_epoch_start(trainer: Any) -> None:
        phase(f"Training, round {int(trainer.epoch) + 1} of {int(trainer.epochs)}")
        progress(int(trainer.epoch), int(trainer.epochs))

    def on_epoch_end(trainer: Any) -> None:
        progress(int(trainer.epoch) + 1, int(trainer.epochs))

    batches = {"done": 0}

    def on_batch_start(trainer: Any) -> None:
        batches["done"] = 0 if batches.get("epoch") != trainer.epoch else batches["done"]
        batches["epoch"] = trainer.epoch

    def on_batch_end(trainer: Any) -> None:
        batches["done"] += 1
        total = len(getattr(trainer, "train_loader", None) or []) or 0
        if total and (batches["done"] % 10 == 0 or batches["done"] == total):
            step(batches["done"], total)

    model.add_callback("on_train_batch_start", on_batch_start)
    model.add_callback("on_train_batch_end", on_batch_end)
    model.add_callback("on_train_epoch_start", on_epoch_start)
    model.add_callback("on_fit_epoch_end", on_epoch_end)
    batch = args.batch or (8 if args.family == "rtdetr" else 16)
    model.train(
        data=str(data_yaml), epochs=args.epochs, imgsz=args.imgsz, batch=batch, seed=0, deterministic=True,
        project=str(work / "runs"), name=args.run_name, exist_ok=True, verbose=False, plots=False, workers=4,
    )
    run = granum.get_active_run()
    return run, work / "runs" / args.run_name / "weights" / "best.pt"


# -- RF-DETR -------------------------------------------------------------------------


_METRIC_KEYS = [
    (re.compile(r"map.?50.?95|map$|/map\b", re.I), "map50_95"),
    (re.compile(r"map.?50(?!.?95)", re.I), "map50"),
    (re.compile(r"recall", re.I), "recall"),
    (re.compile(r"precision", re.I), "precision"),
]


def _scalar_name(key: str) -> str:
    for pattern, name in _METRIC_KEYS:
        if pattern.search(key):
            return name
    return re.sub(r"[^0-9a-zA-Z]+", "_", key).strip("_").lower()


def train_rfdetr(args: argparse.Namespace, train: Any, valid: Any, work: Path) -> tuple[Any, Path]:
    import pytorch_lightning as pl
    import rfdetr.training as rf_training

    import granum
    from granum.integration.rfdetr import RFDETRPredictor, export_rfdetr_dataset, load_rfdetr
    from granum.integration.ultralytics import collect_detection_metrics

    phase("Preparing the images")
    dataset_dir = work / "exports" / args.run_name
    shutil.rmtree(dataset_dir, ignore_errors=True)
    export_rfdetr_dataset({"train": train, "valid": valid, "test": valid}, dataset_dir)
    output_dir = work / "runs" / args.run_name

    phase("Loading the model")
    model = load_rfdetr(args.version)
    run = granum.init(args.project, args.run_name, parameters={
        "model": f"rf-detr-{args.version}", "epochs": args.epochs, "seed": 0, **run_parameters(args, train, valid),
    }, description=f"RF-DETR training, {args.epochs} epochs")
    tables = {"valid": valid, "train": train}
    collect_every = max(1, args.epochs // 2)

    class GranumCallback(pl.Callback):
        def on_train_epoch_start(self, trainer: Any, module: Any) -> None:
            phase(f"Training, round {trainer.current_epoch + 1} of {args.epochs}")
            progress(trainer.current_epoch, args.epochs)

        def on_train_batch_end(self, trainer: Any, module: Any, outputs: Any, batch: Any, batch_idx: int) -> None:
            total = int(trainer.num_training_batches) if str(trainer.num_training_batches).isdigit() else 0
            if total and ((batch_idx + 1) % 20 == 0 or batch_idx + 1 == total):
                step(batch_idx + 1, total)

        def on_train_epoch_end(self, trainer: Any, module: Any) -> None:
            if trainer.sanity_checking:
                return
            epoch = int(trainer.current_epoch)
            scalars: dict[str, Any] = {"epoch": epoch}
            for key, value in trainer.callback_metrics.items():
                try:
                    scalars.setdefault(_scalar_name(key), float(value))
                except (TypeError, ValueError):
                    continue
            granum.log(scalars, run=run)
            phase(f"Recording per-image results, round {epoch + 1} of {args.epochs}")

            final = epoch + 1 >= args.epochs
            full = final or (epoch + 1) % collect_every == 0
            if full or args.track_learning:
                was_training = module.model.training
                model.model.model = module.model
                for split, table in tables.items():
                    # Tracking learning keeps each round's boxes, so every round can be looked at.
                    with_boxes = args.track_learning or (full and (split != "train" or final))
                    if not (with_boxes or args.track_learning):
                        continue
                    column = next(n for n in table.columns if n == "bbs")
                    predictor = RFDETRPredictor(model, table.schema[column].value_map, conf=0.25)
                    collect_detection_metrics(None, table, run=run, epoch=epoch, split=split,
                                              store_boxes=with_boxes, predictor=predictor)
                module.model.train(was_training)
            progress(epoch + 1, args.epochs)

    original = rf_training.build_trainer

    def build_trainer(*a: Any, **k: Any) -> Any:
        trainer = original(*a, **k)
        trainer.callbacks.append(GranumCallback())
        return trainer

    rf_training.build_trainer = build_trainer
    try:
        model.train(
            dataset_dir=str(dataset_dir), epochs=args.epochs, batch_size=args.batch or 4, grad_accum_steps=4,
            output_dir=str(output_dir), seed=0,
        )
    finally:
        rf_training.build_trainer = original
    run.set_status("finished")
    best = next((p for p in (output_dir / "checkpoint_best_total.pth", output_dir / "checkpoint_best_ema.pth",
                             output_dir / "checkpoint.pth") if p.exists()), output_dir / "checkpoint_best_total.pth")
    return run, best


def run_parameters(args: argparse.Namespace, train: Any, valid: Any) -> dict[str, Any]:
    return {
        "framework": args.family,
        "version": args.version,
        "train_version": f"{train.dataset_name}/{train.name}",
        "valid_version": f"{valid.dataset_name}/{valid.name}",
        "tracks_learning": bool(args.track_learning),
        **({"compared_with": args.compare_with} if args.compare_with else {}),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--project-root", required=True)
    parser.add_argument("--project", required=True)
    parser.add_argument("--train-table", required=True)
    parser.add_argument("--valid-table", required=True)
    parser.add_argument("--run-name", required=True)
    parser.add_argument("--family", choices=["yolo", "rtdetr", "rfdetr"], default="yolo")
    parser.add_argument("--version", default="yolo26n.pt")
    parser.add_argument("--epochs", type=int, default=12)
    parser.add_argument("--imgsz", type=int, default=640)
    parser.add_argument("--batch", type=int, default=0, help="0 picks a size suited to the family")
    parser.add_argument("--track-learning", action="store_true")
    parser.add_argument("--compare-with", default=None, help="name of an earlier Run to score on the same labels")
    parser.add_argument("--work-dir", default=None)
    args = parser.parse_args(argv)
    if args.version not in version_ids(args.family):
        parser.error(f"--version for {args.family} must be one of {version_ids(args.family)}")

    import granum
    from granum import Table
    from granum.training.evaluate import score_detector

    root = Path(args.project_root)
    granum.set_config(granum.Config.load(overrides={"project-root-url": str(root)}, use_config_files=False, use_env=False))
    work = Path(args.work_dir) if args.work_dir else root.parent / "granum-training"
    train = Table.from_url(args.train_table)
    valid = Table.from_url(args.valid_table)

    trainer = train_rfdetr if args.family == "rfdetr" else train_ultralytics
    run, best = trainer(args, train, valid, work)
    if run is None or not best.exists():
        print("training finished without a Granum run or saved weights", file=sys.stderr)
        return 1
    run.set_parameters({"weights": str(best)})

    phase("Scoring the model")
    scores = score_detector(predictor_for(args.family, args.version, best, valid, imgsz=args.imgsz, conf=0.01), valid)
    run.set_parameters({
        "score_labels": f"{valid.dataset_name}/{valid.name}",
        **{f"score_{k}": round(v, 4) for k, v in scores.items() if k != "images"},
    })
    print(f"score on {valid.name}: mAP50 {scores['map50']:.4f}  recall {scores['recall']:.3f}  precision {scores['precision']:.3f}", flush=True)

    if args.compare_with:
        phase("Scoring the earlier run the same way")
        earlier = granum.Run.from_url(granum.ProjectLayout(root).run(args.project, args.compare_with))
        earlier_weights = weights_for(earlier, root, work)
        if earlier_weights is None:
            print(f"cannot compare: {args.compare_with} has no saved model weights", flush=True)
        else:
            framework = earlier.parameters.get("framework", "rtdetr" if "rtdetr" in earlier_weights.name else "yolo")
            version = earlier.parameters.get("version", "")
            imgsz = int(earlier.parameters.get("imgsz", args.imgsz))
            theirs = score_detector(predictor_for(framework, version, earlier_weights, valid, imgsz=imgsz, conf=0.01), valid)
            run.set_parameters({
                "compare_labels": f"{valid.dataset_name}/{valid.name}",
                "compare_map50_this": round(scores["map50"], 4),
                "compare_map50_earlier": round(theirs["map50"], 4),
                "compare_recall_this": round(scores["recall"], 4),
                "compare_recall_earlier": round(theirs["recall"], 4),
            })
            print(f"{args.compare_with} on {valid.name}: mAP50 {theirs['map50']:.4f}", flush=True)

    phase("Finished")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
