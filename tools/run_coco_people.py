"""Run Granum's actual import/collect/curate/train/evaluate loop on prepared COCO data.

The official COCO evaluator scores untouched annotations. Granum's own operating-point
metrics are recorded separately. Data selection uses only training-pool predictions.
Run ``tools/qualify_coco_people.py prepare`` first. GPU execution is explicit.
"""
from __future__ import annotations

import argparse
import contextlib
import copy
import gc
import hashlib
import io
import json
import os
import subprocess
import sys
import time
from pathlib import Path

import numpy as np
from qualify_coco_people import digest, write_json


def official_scores(document, predictions, image_ids, task="bbox"):
    from pycocotools.coco import COCO
    from pycocotools.cocoeval import COCOeval

    with contextlib.redirect_stdout(io.StringIO()):
        truth = COCO()
        truth.dataset = document
        truth.createIndex()
        if predictions:
            detected = truth.loadRes(copy.deepcopy(predictions))
        else:
            detected = COCO()
            detected.dataset = {"images": document["images"], "categories": document["categories"], "annotations": []}
            detected.createIndex()
        evaluator = COCOeval(truth, detected, task)
        evaluator.params.imgIds = image_ids
        evaluator.params.catIds = [1]
        evaluator.evaluate()
        evaluator.accumulate()
        evaluator.summarize()
    names = (["AP", "AP50", "AP75", "AP_medium", "AP_large", "AR", "AR50", "AR75", "AR_medium", "AR_large"]
             if task == "keypoints" else ["AP", "AP50", "AP75", "AP_small", "AP_medium", "AP_large", "AR1", "AR10", "AR100", "AR_small", "AR_medium", "AR_large"])
    return {name: (float(value) if value >= 0 else None) for name, value in zip(names, evaluator.stats)}


def collect(model, table, run, split, device, size=640, *, official=None, manifest=None):
    import torch

    from granum.integration.ultralytics import YOLOPredictor, collector_for

    predictor = YOLOPredictor(model, table.schema["bbs"].value_map, conf=.001, imgsz=size, device=device, on_unknown="drop")
    collector = collector_for(predictor, table, "bbs", value_map=table.schema["bbs"].value_map)
    rows = table.to_arrow().to_pylist()
    values = {"example_id": [], **{key: [] for key in collector.column_schemas()}}
    predictions, latencies = [], []
    # Warmup is excluded from measured throughput; synchronized timing includes IO and preprocessing.
    predictor({"image": [rows[0]["image"]]})
    torch.cuda.synchronize()
    torch.cuda.reset_peak_memory_stats()
    for start in range(0, len(rows), 8):
        batch = rows[start:start + 8]
        began = time.perf_counter()
        outputs = predictor({"image": [row["image"] for row in batch]})
        torch.cuda.synchronize()
        latencies.append((time.perf_counter() - began) / len(batch))
        operating = []
        for row, output in zip(batch, outputs):
            for at, (box, score, label) in enumerate(zip(output["boxes"], output["scores"], output["labels"])):
                x, y, right, bottom = map(float, box)
                item = {"image_id": row["image_id"], "category_id": int(label), "bbox": [x, y, right - x, bottom - y], "score": float(score)}
                if predictor.task == "pose":
                    item["keypoints"] = np.asarray(output["keypoints"][at]).reshape(-1).tolist()
                if predictor.task == "segment":
                    from pycocotools import mask as masks

                    from granum.formats.vision import mask_array

                    mask = output["segmentations"][at]
                    encoded = masks.encode(np.asfortranarray(mask_array(mask, int(row["bbs"]["width"]), int(row["bbs"]["height"])), dtype=np.uint8))
                    item["segmentation"] = {"size": encoded["size"], "counts": encoded["counts"].decode()}
                    item.pop("bbox")  # COCO mask AP must use mask area, not box area.
                predictions.append(item)
            keep = np.asarray(output["scores"]) >= .25
            operating.append({key: ([v for v, selected in zip(value, keep) if selected] if key == "segmentations" else np.asarray(value)[keep]) for key, value in output.items()})
        measured = collector.collect({"bbs": [row["bbs"] for row in batch]}, operating)
        values["example_id"].extend(range(start, start + len(batch)))
        for key, entries in measured.items():
            values[key].extend(entries)
    run.add_metrics(values, schema=collector.column_schemas(), foreign_table_url=table.url, constants={"split": split})
    result = {"images": len(rows), "predict_seconds": sum(latency * min(8, len(rows) - 8 * i) for i, latency in enumerate(latencies)),
              "batch_size": 8, "median_ms_per_image": float(np.median(latencies) * 1000),
              "p95_ms_per_image": float(np.quantile(latencies, .95) * 1000), "peak_cuda_bytes": torch.cuda.max_memory_allocated(),
              "operating_confidence": .25, "tp": sum(values["tp"]), "fp": sum(values["fp"]), "fn": sum(values["fn"])}
    if official is not None:
        document = json.loads(official.read_text())
        task = {"pose": "keypoints", "segment": "segm"}.get(predictor.task, "bbox")
        result["official_coco"] = official_scores(document, predictions, [row["image_id"] for row in rows], task)
        if manifest:
            result["slices"] = {}
            entries = [entry for entry in manifest["images"] if entry["split"] == split]
            for name in sorted({name for entry in entries for name in entry["slices"]}):
                ids = [entry["id"] for entry in entries if name in entry["slices"]]
                result["slices"][name] = {"images": len(ids), **official_scores(document, predictions, ids, task)}
        write_json(official.parent / "results" / f"{run.name}-{split}-predictions.json", predictions)
    return result, values


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path("data/qualification/coco-person"))
    parser.add_argument("--epochs", type=int, default=3)
    parser.add_argument("--seeds", default="0,1,2")
    parser.add_argument("--device", default="cuda:0")
    args = parser.parse_args()
    root = args.root.resolve()
    manifest = json.loads((root / "manifest.json").read_text())
    import torch
    from ultralytics import YOLO

    import granum
    from granum.formats.coco import table_from_coco
    from granum.licensing import Licensing, set_licensing
    from granum.training.data import validate_training
    from granum.training.evaluate import evaluator_policy

    if not torch.cuda.is_available() or not args.device.startswith("cuda"):
        raise RuntimeError("This qualification requires an available CUDA GPU")
    torch.set_num_threads(4)
    torch.cuda.set_device(args.device)
    set_licensing(Licensing.open())  # This local engineering benchmark is not a customer license test.
    project_root = root / "granum"
    granum.set_config(granum.Config.load(overrides={"project-root-url": str(project_root)}, use_config_files=False, use_env=False))
    output = root / "results"
    output.mkdir(exist_ok=True)
    if (output / "report.json").exists():
        raise RuntimeError("A completed report already exists; preserve it and use a new output directory")
    tables = {split: table_from_coco(root / f"{split}.json", root / "images" / ("val2017" if split == "test" else "train2017"),
        project_name="coco-people", dataset_name="people", table_name=split) for split in ["train", "valid", "test"]}
    preflight = validate_training(tables, "detect")
    report = {"dataset": manifest["dataset"], "manifest_sha256": digest(root / "manifest.json"), "preflight": preflight,
              "hardware": torch.cuda.get_device_name(), "torch": str(torch.__version__), "cuda": torch.version.cuda,
              "recipe": {"epochs": args.epochs, "seeds": [int(s) for s in args.seeds.split(",")], "image_size": 640, "batch": 8,
                         "model": "yolo11n.pt", "training_images_each": 500},
              "training_eligibility": "Both selection policies exclude training images containing crowd regions because YOLO training cannot mask ignored regions. Validation and test retain all official crowd annotations.",
              "evaluation": {"implementation": "pycocotools COCOeval", "task": "bbox", "category": "person", "minimum_confidence": .001,
                             "iou": "0.50:0.05:0.95", "max_detections": 100, "held_out": "official val2017 licensed subset"},
              "limits": ["Subset benchmark; not full COCO or a 3LC head-to-head.", "Starting weights were pretrained on COCO; this tests workflow and fine-tuning, not learning a new domain from scratch.",
                         "Selection uses training-pool errors only. Validation chooses checkpoints. Test images do not influence selection or training.",
                         "Occlusion and truncation slices use geometric proxies, not dedicated annotations.",
                         "All downloaded images have CC BY licenses in COCO metadata; original rights were not independently reverified."], "runs": []}
    pretrained = YOLO("yolo11n.pt")
    scouting = granum.init("coco-people", "training-pool-review", parameters={"task": "detect", "evaluator": evaluator_policy(), "weights_source": "COCO pretrained"})
    review, metrics = collect(pretrained, tables["train"], scouting, "train", args.device)
    scouting.set_status("finished")
    report["training_pool_review"] = review
    write_json(output / "progress.json", report)
    del pretrained
    gc.collect()
    torch.cuda.empty_cache()
    records = tables["train"].to_arrow().to_pylist()
    strata = {"negative": [], "person": []}
    for i, row in enumerate(records):
        if any(box.get("iscrowd") for box in row["bbs"]["instances"]):
            continue
        strata["person" if any(not box.get("iscrowd") for box in row["bbs"]["instances"]) else "negative"].append(i)
    for seed in report["recipe"]["seeds"]:
        for condition in ["uniform", "review-selected"]:
            selected = []
            for group, count in [("negative", 100), ("person", 400)]:
                order = sorted(strata[group], key=lambda i: hashlib.sha256(f"selection:{seed}:{records[i]['image_id']}".encode()).hexdigest())
                if condition == "uniform":
                    chosen = order[:count]
                else:
                    def hardness(i):
                        return (-(metrics["fn"][i] + metrics["fp"][i]) / max(1, metrics["tp"][i] + metrics["fn"][i]), records[i]["image_id"])
                    chosen = sorted(order, key=hardness)[:count // 2]
                    chosen += [i for i in order if i not in set(chosen)][:count - len(chosen)]
                if len(chosen) != count:
                    raise RuntimeError("Training pool has too few images in a selection stratum")
                selected.extend(chosen)
            keep = set(selected)
            train = tables["train"].set_weights({i: float(i in keep) for i in range(len(records))})
            name = f"{condition}-seed-{seed}"
            selected_ids = [records[i]["image_id"] for i in sorted(selected)]
            write_json(output / f"{name}-selection.json", {"table": str(train.url), "image_ids": selected_ids, "training_pool": str(tables["train"].url)})
            command = [sys.executable, "-m", "granum.training.train", "--project-root", str(project_root), "--project", "coco-people", "--run-name", name,
                       "--train-table", str(train.url), "--valid-table", str(tables["valid"].url), "--family", "yolo", "--version", "yolo11n.pt",
                       "--epochs", str(args.epochs), "--imgsz", "640", "--batch", "8", "--workers", "2", "--seed", str(seed), "--device", args.device,
                       "--work-dir", str(root / "training"), "--track-learning"]
            print(f"Training {name}, {len(selected)} images, {args.epochs} epochs", flush=True)
            began = time.monotonic()
            with (output / f"{name}.log").open("w") as log:
                subprocess.run(command, stdout=log, stderr=subprocess.STDOUT, check=True,
                               env={**os.environ, "OMP_NUM_THREADS": "4", "OPENBLAS_NUM_THREADS": "4"})
            elapsed = time.monotonic() - began
            run = granum.Run.from_url(granum.ProjectLayout(project_root).run("coco-people", name))
            model = YOLO(run.parameters["weights"])
            result, values = collect(model, tables["test"], run, "test", args.device, official=root / "test.json", manifest=manifest)
            run.set_parameters({"test_table": str(tables["test"].url), "test_coco_ap": result["official_coco"]["AP"], "selection": condition})
            report["runs"].append({"name": name, "seed": seed, "condition": condition, "training_wall_seconds": elapsed,
                                   "weights_sha256": digest(Path(run.parameters["weights"])), "run_url": str(run.url), **result})
            write_json(output / f"{name}-image-errors.json", {"image_ids": [row["image_id"] for row in tables["test"].to_arrow().to_pylist()],
                                                           **{key: values[key] for key in ["tp", "fp", "fn"]}})
            write_json(output / "progress.json", report)
            del model
            gc.collect()
            torch.cuda.empty_cache()
    deltas = []
    for seed in report["recipe"]["seeds"]:
        before = next(r for r in report["runs"] if r["seed"] == seed and r["condition"] == "uniform")
        after = next(r for r in report["runs"] if r["seed"] == seed and r["condition"] == "review-selected")
        deltas.append(after["official_coco"]["AP"] - before["official_coco"]["AP"])
    report["selection_effect"] = {"paired_seed_ap_deltas": deltas, "mean_ap_delta": float(np.mean(deltas)),
                                  "training_seeds": len(deltas), "superiority_over_3lc_established": False}
    write_json(output / "report.json", report)
    print(json.dumps(report["selection_effect"]), flush=True)


if __name__ == "__main__":
    main()
