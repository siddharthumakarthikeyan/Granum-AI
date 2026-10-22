"""Exercise classification, semantic, pose, masks and SAM on licensed COCO photos.

Classification labels are person presence, semantic labels are the union of individual
person masks versus background; COCO crowd pixels are ignored. These derived tasks are
explicit engineering qualifications, not official COCO classification/semantic tasks.
"""
from __future__ import annotations

import argparse
import gc
import json
import time
from pathlib import Path

import numpy as np
from qualify_coco_people import digest, write_json
from run_coco_people import collect


def qualify_embeddings(sources, weights, output):
    import torch

    import granum
    from granum.core.schemas import EmbeddingSchema, ImageSchema
    from granum.reduction import Reducer, reduce_table
    from granum.training.vision import build_model, image_tensor

    checkpoint = torch.load(weights, map_location="cpu", weights_only=True)
    model = build_model("resnet18", len(checkpoint["classes"]), pretrained=False)
    model.load_state_dict(checkpoint["state_dict"])
    model.fc = torch.nn.Identity()
    model.to("cuda:0").eval()
    reducer = Reducer("pca", dimensions=3, seed=0)
    report = {"model_weights_sha256": digest(Path(weights)), "preprocessing": "ImageNet normalization, RGB resize to 224 square",
              "reference_split": "train", "feature_dimensions": 512, "splits": {}}
    for split in ["train", "test"]:
        rows = sources[split].to_arrow().to_pylist()
        features = []
        with torch.inference_mode():
            for start in range(0, len(rows), 16):
                batch = torch.stack([image_tensor(row["image"], 224) for row in rows[start:start + 16]]).to("cuda:0")
                features.extend(model(batch).cpu().numpy().tolist())
        table = granum.Table.from_dict_data({"image": [row["image"] for row in rows], "image_id": [row["image_id"] for row in rows], "embedding": features},
            schema={"image": ImageSchema(), "embedding": EmbeddingSchema(shape=(512,))},
            project_name="coco-task-qualification", dataset_name="person-embeddings", table_name=split)
        projected = reduce_table(table, "embedding", reducer=reducer)
        assert "projection_x" not in granum.Table.from_url(table.url).columns
        assert projected.to_arrow().column("image_id").to_pylist() == [row["image_id"] for row in rows]
        if split == "train" and not (output / "pca-reference").exists():
            reducer.save(output / "pca-reference")
        restored = Reducer.load(output / "pca-reference")
        np.testing.assert_allclose(restored.transform(features), reducer.transform(features), atol=1e-5)
        report["splits"][split] = {"images": len(rows), "source": str(table.url), "projection": str(projected.url),
                                   "saved_projection_matches": True, "source_unchanged": True, "identity_preserved": True}
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path("data/qualification/coco-person"))
    args = parser.parse_args()
    root = args.root.resolve()
    import torch
    from ultralytics import YOLO

    import granum
    from granum.core.schemas import CategoricalLabelSchema, ImageSchema
    from granum.formats.coco import table_from_coco_data
    from granum.formats.vision import encode_mask, mask_array
    from granum.licensing import Licensing, set_licensing
    from granum.training.train import main as train

    if not torch.cuda.is_available():
        raise RuntimeError("CUDA is required for this qualification")
    set_licensing(Licensing.open())
    project_root = root / "task-granum"
    granum.set_config(granum.Config.load(overrides={"project-root-url": str(project_root)}, use_config_files=False, use_env=False))
    output = root / "task-results"
    output.mkdir(exist_ok=True)
    if (output / "report.json").exists():
        raise RuntimeError("A completed qualification already exists; preserve it and use a new output directory")
    report = {"manifest_sha256": digest(root / "manifest.json"), "hardware": torch.cuda.get_device_name(), "torch": str(torch.__version__),
              "scope": "Derived person-presence and binary-person semantic tasks; official COCO mask/keypoint inference on a subset; SAM prompt smoke.",
              "tasks": {}}
    if (output / "progress.json").exists():
        previous = json.loads((output / "progress.json").read_text())
        if previous["manifest_sha256"] != report["manifest_sha256"]:
            raise RuntimeError("The dataset manifest changed; do not combine qualification runs")
        report = previous
    sources, original = {}, {}
    for split, limit in [("train", 200), ("valid", 40), ("test", 80)]:
        document = json.loads((root / f"{split}.json").read_text())
        chosen = document["images"][:limit]
        ids = {image["id"] for image in chosen}
        document = {**document, "images": chosen, "annotations": [a for a in document["annotations"] if a["image_id"] in ids]}
        original[split] = document
        folder = root / "images" / ("val2017" if split == "test" else "train2017")
        existing = granum.ProjectLayout(project_root).table("coco-task-qualification", "people", split)
        source = (granum.Table.from_url(existing) if (Path(str(existing)) / "object.granum.json").exists() else
                  table_from_coco_data(document, source=root / f"{split}.json", image_folder=folder, project_name="coco-task-qualification", dataset_name="people", table_name=split))
        sources[split] = source
    for task, family, version, size in [("classify", "classifier", "resnet18", 224), ("semantic", "semantic", "lraspp-mobilenet-v3", 320)]:
        if task in report["tasks"]:
            saved = report["tasks"][task]
            if digest(Path(saved["parameters"]["weights"])) != saved["weights_sha256"]:
                raise RuntimeError("A completed checkpoint changed")
            continue
        tables = {}
        for split, source in sources.items():
            rows = source.to_arrow().to_pylist()
            if task == "classify":
                labels = [int(bool(row["bbs"]["instances"])) for row in rows]
                tables[split] = granum.Table.from_dict_data({"image": [row["image"] for row in rows], "label": labels},
                    schema={"image": ImageSchema(), "label": CategoricalLabelSchema(value_map={0: "no person", 1: "person"})},
                    project_name="coco-task-qualification", dataset_name="person-presence", table_name=split)
            else:
                annotations = []
                for row in rows:
                    geometry = row["bbs"]
                    width, height = int(geometry["width"]), int(geometry["height"])
                    foreground, ignored = np.zeros((height, width), dtype=bool), np.zeros((height, width), dtype=bool)
                    for obj in geometry["instances"]:
                        pixels = mask_array(obj.get("segmentation"), width, height).astype(bool)
                        if obj.get("iscrowd"):
                            ignored |= pixels
                        else:
                            foreground |= pixels
                    for label, mask in [(0, ~foreground & ~ignored), (1, foreground & ~ignored)]:
                        if not mask.any():
                            continue
                        ys, xs = np.nonzero(mask)
                        annotations.append({"id": len(annotations) + 1, "image_id": row["image_id"], "category_id": label,
                            "bbox": [int(xs.min()), int(ys.min()), int(xs.max() - xs.min() + 1), int(ys.max() - ys.min() + 1)],
                            "segmentation": encode_mask(mask), "area": int(mask.sum()), "iscrowd": 0})
                document = {**original[split], "annotations": annotations, "categories": [{"id": 0, "name": "background"}, {"id": 1, "name": "person"}],
                            "granum_semantic": {"ignore_index": 255}}
                tables[split] = table_from_coco_data(document, source=root / f"{split}.json", image_folder=root / "images" / ("val2017" if split == "test" else "train2017"),
                    project_name="coco-task-qualification", dataset_name="person-semantic", table_name=split)
        started = time.monotonic()
        train(["--project-root", str(project_root), "--project", "coco-task-qualification", "--run-name", task,
               "--train-table", str(tables["train"].url), "--valid-table", str(tables["valid"].url), "--test-table", str(tables["test"].url),
               "--family", family, "--version", version, "--imgsz", str(size), "--epochs", "3", "--batch", "8", "--workers", "2",
               "--device", "cuda:0", "--work-dir", str(root / "task-training"), "--track-learning"])
        run = granum.Run.from_url(granum.ProjectLayout(project_root).run("coco-task-qualification", task))
        report["tasks"][task] = {"run": str(run.url), "status": run.status, "wall_seconds": time.monotonic() - started,
                                 "parameters": run.parameters, "weights_sha256": digest(Path(run.parameters["weights"])),
                                 "metrics_tables": len(run.metrics_tables()), "real_images": {key: len(value) for key, value in tables.items()}}
        write_json(output / "progress.json", report)
        gc.collect()
        torch.cuda.empty_cache()
    for task, weights in [("segment", "yolo11n-seg.pt"), ("pose", "yolo11n-pose.pt")]:
        if task in report["tasks"]:
            continue
        document = original["test"]
        if task == "pose":
            pose = json.loads((root / "test-pose.json").read_text())
            ids = {image["id"] for image in document["images"]}
            document = {**document, "categories": pose["categories"], "annotations": [a for a in pose["annotations"] if a["image_id"] in ids]}
        source_file = output / f"{task}-test.json"
        write_json(source_file, document)
        source = table_from_coco_data(document, source=source_file, image_folder=root / "images/val2017",
                                     project_name="coco-task-qualification", dataset_name=task, table_name="test")
        run = granum.init("coco-task-qualification", f"{task}-inference", parameters={"task": task, "weights": weights})
        model = YOLO(weights)
        measured, _ = collect(model, source, run, "test", "cuda:0", official=source_file)
        run.set_status("finished")
        report["tasks"][task] = {"scope": "Pretrained inference; no fine-tuning", "run": str(run.url),
                                 "weights_sha256": digest(Path(weights)), **measured}
        write_json(output / "progress.json", report)
        del model
        gc.collect()
        torch.cuda.empty_cache()
    if "embeddings" not in report:
        report["embeddings"] = qualify_embeddings(sources, report["tasks"]["classify"]["parameters"]["weights"], output)
    write_json(output / "progress.json", report)
    gc.collect()
    torch.cuda.empty_cache()
    # An untouched starting-model reference on the exact 500-image detection test set.
    # It is measured after all six fine-tuning runs and never changes their recipes.
    if "pretrained-detection" not in report["tasks"]:
        full_test = json.loads((root / "test.json").read_text())
        reference = table_from_coco_data(full_test, source=root / "test.json", image_folder=root / "images/val2017",
                                        project_name="coco-task-qualification", dataset_name="pretrained-detection", table_name="test")
        reference_run = granum.init("coco-task-qualification", "pretrained-detection", parameters={"task": "detect", "weights": "yolo11n.pt"})
        model = YOLO("yolo11n.pt")
        measured, _ = collect(model, reference, reference_run, "test", "cuda:0", official=root / "test.json")
        reference_run.set_status("finished")
        report["tasks"]["pretrained-detection"] = {"scope": "Untouched pretrained reference; same 500 test images as the six fine-tuned runs",
                                                  "run": str(reference_run.url), "weights_sha256": digest(Path("yolo11n.pt")), **measured}
        write_json(output / "progress.json", report)
        del model
    gc.collect()
    torch.cuda.empty_cache()
    from PIL import Image
    from ultralytics import SAM

    from granum.integration.sam import propose_mask

    examples = []
    for row in sources["test"].to_arrow().to_pylist():
        instances = [obj for obj in row["bbs"]["instances"] if not obj.get("iscrowd")]
        if instances:
            examples.append((row, max(instances, key=lambda obj: obj.get("area") or 0)))
        if len(examples) == 10:
            break
    for weights in ["mobile_sam.pt", "sam2.1_t.pt"]:
        if weights in report["tasks"]:
            continue
        model = SAM(weights)
        model.overrides["device"] = "cuda:0"
        measurements = []
        torch.cuda.reset_peak_memory_stats()
        for row, instance in examples:
            with Image.open(row["image"]) as image:
                began = time.monotonic()
                proposal = propose_mask(image.convert("RGB"), model=model, box=instance["vertices"])
                torch.cuda.synchronize()
                seconds = time.monotonic() - began
                prediction = mask_array(proposal["candidates"][0]["mask"], *image.size)
                truth = mask_array(instance["segmentation"], *image.size)
                intersection, union = (prediction & truth).sum(), (prediction | truth).sum()
                measurements.append({"image_id": row["image_id"], "annotation_id": instance["annotation_id"],
                                     "seconds": seconds, "iou": float(intersection / union), "nonempty": bool(prediction.any())})
        report["tasks"][weights] = {"scope": "Ten largest-person oracle-box prompts; no manual correction and no automatic detection claim.",
                                    "weights_sha256": digest(Path(weights)),
                                    "observations": measurements, "mean_iou": float(np.mean([m["iou"] for m in measurements])),
                                    "peak_cuda_bytes": torch.cuda.max_memory_allocated()}
        write_json(output / "progress.json", report)
        del model
        gc.collect()
        torch.cuda.empty_cache()
    write_json(output / "report.json", report)
    print(f"Qualification complete: {output / 'report.json'}", flush=True)


if __name__ == "__main__":
    try:
        main()
    except BaseException:
        from granum.core.objects.run import get_active_run

        active = get_active_run()
        if active is not None and active.status == "running":
            active.set_status("failed")
        raise
