"""Summarize a completed qualification without changing models, selections or test results."""
from __future__ import annotations

import argparse
import json
from datetime import date
from pathlib import Path

import numpy as np
from qualify_coco_people import digest, write_json


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path("data/qualification/coco-person"))
    parser.add_argument("--date", default=date.today().isoformat())
    args = parser.parse_args()
    root = args.root
    manifest, detection, tasks, audit = [json.loads((root / name).read_text()) for name in
                                        ["manifest.json", "results/report.json", "task-results/report.json", "audit/report.json"]]
    task = tasks["tasks"]
    conditions = {}
    for condition in ["uniform", "review-selected"]:
        runs = [run for run in detection["runs"] if run["condition"] == condition]
        conditions[condition] = {"mean_ap_points": float(np.mean([run["official_coco"]["AP"] for run in runs]) * 100),
                                 "mean_ap50_points": float(np.mean([run["official_coco"]["AP50"] for run in runs]) * 100),
                                 "per_seed": [{"seed": run["seed"], "ap_points": run["official_coco"]["AP"] * 100,
                                               "ap50_points": run["official_coco"]["AP50"] * 100} for run in runs]}
    reference = task["pretrained-detection"]["official_coco"]["AP"] * 100
    delta = detection["selection_effect"]["mean_ap_delta"] * 100
    report = {
        "recorded_on": args.date,
        "decision": "Core image pilot workflows exercised on real data. Accuracy improvement and superiority over 3LC are not established.",
        "dataset": {"name": "Official COCO 2017 person, image-license-filtered CC BY 2.0 subset", "images": len(manifest["images"]),
                    "splits": manifest["splits"], "manifest": str(root / "manifest.json"), "manifest_sha256": digest(root / "manifest.json"),
                    "license_selection": "Only COCO image license id 4 (CC BY 2.0); all original image source, Flickr, license and file SHA256 records retained.",
                    "rights_limit": "COCO metadata was checked; original image rights were not independently reverified. COCO annotation licensing does not license every COCO photograph.",
                    "excluded_alternative": "CrowdHuman: its official terms restrict use to non-commercial research and education.",
                    "split_policy": manifest["split_policy"], "duplicate_bytes_across_splits": manifest["split_hash_overlap"],
                    "complexity": "Dense groups, small people, crowd regions, overlapping boxes and border-touching people. Overlap and border contact are geometric proxies, not ground-truth occlusion/truncation labels."},
        "detection_experiment": {"metric": "Official pycocotools COCO bbox AP at IoU .50:.05:.95, in points (0–100)",
                                 "recipe": detection["recipe"], "test_images": 500, "test_individual_people": 1441,
                                 "selection": "Same 400 person/100 negative training counts. Uniform SHA256 order versus half highest training-pool error scores plus half hashed samples; no human label corrections.",
                                 "crowd_policy": detection["training_eligibility"], "conditions": conditions,
                                 "mean_selection_delta_ap_points": delta,
                                 "per_seed_delta_ap_points": [value * 100 for value in detection["selection_effect"]["paired_seed_ap_deltas"]],
                                 "pretrained_reference_ap_points": reference,
                                 "conclusion": "Error-guided selection regressed on average (two seeds worse, one better). Both three-epoch fine-tuning conditions scored below the untouched pretrained detector. Do not promote this recipe as an accuracy improvement.",
                                 "architecture_note": "Ultralytics changes nc=80 to nc=1 for person-only fine-tuning. The untouched reference retains the 80-class head; only person predictions are evaluated.",
                                 "pretraining_note": "YOLO weights were pretrained on full COCO train2017, which includes this qualification's training and validation pools. This is a workflow/fine-tuning qualification, not evaluation in a new domain.",
                                 "test_use": "Training-pool predictions determine selection; validation chooses checkpoints. The six recipes were held fixed and test results were not used to tune them. The untouched reference was evaluated afterward for context."},
        "additional_gpu_qualification": {
            "classify": {"model": "ResNet18", "derived_task": "Any annotated person, including a crowd region, versus no person", "train_valid_test_images": [200, 40, 80],
                         "epochs": 3, "accuracy_percent": task["classify"]["parameters"]["test_accuracy"] * 100,
                         "macro_f1": task["classify"]["parameters"]["test_macro_f1"],
                         "majority_class_accuracy_percent": audit["native"]["classify"]["majority_class_accuracy"] * 100},
            "semantic": {"model": "LR-ASPP MobileNetV3", "derived_task": "Union of individual-person masks versus background; crowd pixels ignored", "train_valid_test_images": [200, 40, 80],
                         "epochs": 3, "dataset_mean_iou_percent": task["semantic"]["parameters"]["test_mean_iou"] * 100,
                         "person_iou_percent": task["semantic"]["parameters"]["test_class_1_iou"] * 100,
                         "pixel_accuracy_percent": task["semantic"]["parameters"]["test_pixel_accuracy"] * 100,
                         "aggregation": "Pooled class intersections/unions at original image resolution"},
            "instance_masks": {"model": "YOLO11n-seg pretrained", "test_images": 80, "official_coco_mask_ap_points": task["segment"]["official_coco"]["AP"] * 100},
            "pose": {"model": "YOLO11n-pose pretrained", "test_images": 80, "official_coco_keypoint_ap_points": task["pose"]["official_coco"]["AP"] * 100},
            "sam": {name: {"oracle_box_prompts": len(task[name]["observations"]), "mean_mask_iou_percent": task[name]["mean_iou"] * 100,
                            "all_nonempty": all(row["nonempty"] for row in task[name]["observations"])} for name in ["mobile_sam.pt", "sam2.1_t.pt"]},
            "sam_limit": "Ten largest-person ground-truth box prompts; selected examples, direct model adapter on GPU. This is not automatic detection or a general SAM quality benchmark.",
            "embeddings": tasks["embeddings"],
            "limit": "Classification and semantic tasks are derived engineering checks, not official COCO benchmark tasks. Single training seed. Mask and pose checks are pretrained inference only."},
        "integrity_audit": {"source": str(root / "audit/report.json"), "canonical_detection_metric_rows": sum(run["canonical_metric_rows_checked"] for run in audit["runs"]),
                            "selection_versions_preserve_originals": True, "matched_test_images_per_comparison": 500,
                            "coco_roundtrip": audit["coco_roundtrip"], "native": audit["native"]},
        "claims": [
            {"claim": "Per-sample metrics and epoch histories", "result": "verified in this scope", "evidence": "6 detection runs with 3 epochs, plus native classification and semantic API histories."},
            {"claim": "Immutable selection, retraining and comparison", "result": "verified in this scope", "evidence": "Six frozen 500-image selections; original 1000-image labels/weights unchanged; 500 matched test images in every comparison."},
            {"claim": "Mask/pose analysis and SAM proposals", "result": "bounded verification", "evidence": "Real GPU inference and stored task metrics; editor and proposal recovery tested in a browser with deterministic model responses."},
            {"claim": "Embeddings and reusable 3D projections", "result": "bounded verification", "evidence": "512-dimensional learned ResNet features, 200-image PCA reference reused on 80 test images; saved coordinates and identity preserved. Interactive rendering separately tested."},
            {"claim": "Better accuracy after this selection recipe", "result": "not supported", "evidence": f"Mean delta {delta:.4f} AP points across three paired seeds."},
            {"claim": "Faster annotation, reduced human effort, better than 3LC", "result": "not measured", "evidence": "No timed human study and no matched 3LC execution."},
            {"claim": "Full platform parity or production scale", "result": "not established", "evidence": "Plugin SDK/managed environments, SAML, point clouds, retrieval operators, broad GPU/distributed frameworks and large-scale qualification remain."},
        ],
        "environment": {"gpu": detection["hardware"], "torch": detection["torch"], "cuda": detection["cuda"], "packages": str(root / "environment.txt"),
                        "timing_limit": "Shared development laptop with concurrent workloads. Timing and memory observations are descriptive, not isolated performance or competitor benchmarks."},
        "raw_artifacts": {name: {"path": str(root / name), "sha256": digest(root / name)} for name in
                          ["manifest.json", "results/report.json", "task-results/report.json", "audit/report.json"]},
        "reproduce": ["Use an empty --root for a new experiment; completed artifacts are preserved.",
                      ".venv/bin/python tools/qualify_coco_people.py prepare --root <new-root>",
                      ".venv/bin/python tools/run_coco_people.py --root <new-root>",
                      ".venv/bin/python tools/qualify_coco_tasks.py --root <new-root>",
                      ".venv/bin/python tools/audit_coco_people.py --root <new-root>",
                      ".venv/bin/python tools/report_coco_people.py --root <new-root>"],
        "sources": {"official_dataset": "https://cocodataset.org/#download", "dataset_terms": "https://github.com/cocodataset/cocodataset.github.io/blob/master/dataset/termsofuse.htm",
                    "image_license": "https://creativecommons.org/licenses/by/2.0/", "crowdhuman_terms": "https://www.crowdhuman.org/download.html",
                    "evaluation": "https://cocodataset.org/dataset/detection-eval.htm", "3lc_platform": "https://3lc.ai/platform/", "3lc_docs": "https://docs.3lc.ai/3lc/latest/introduction.html"},
    }
    report["model_weights_sha256"] = {name: digest(Path(name)) for name in ["yolo11n.pt", "yolo11n-seg.pt", "yolo11n-pose.pt", "mobile_sam.pt", "sam2.1_t.pt"]}
    import matplotlib

    matplotlib.use("Agg")
    from matplotlib import pyplot as plt

    fig, ax = plt.subplots(figsize=(8.5, 5.5), layout="constrained")
    colors = ["#2563eb", "#d97706"]
    for index, condition in enumerate(conditions):
        values = [row["ap_points"] for row in conditions[condition]["per_seed"]]
        ax.bar(index, np.mean(values), color=colors[index], alpha=.18, width=.55)
        ax.scatter([index] * len(values), values, color=colors[index], s=60, zorder=3)
        ax.text(index, np.mean(values) + 8, f"Mean {np.mean(values):.2f}", ha="center", color=colors[index], weight="bold")
    for seed in detection["recipe"]["seeds"]:
        pair = [next(row["ap_points"] for row in conditions[condition]["per_seed"] if row["seed"] == seed) for condition in conditions]
        ax.plot([0, 1], pair, color="#94a3b8", alpha=.7, linewidth=1, zorder=1)
        ax.annotate(f"seed {seed}", (0, pair[0]), xytext=(-8, -4), textcoords="offset points", ha="right", fontsize=9)
    ax.axhline(reference, color="#334155", linestyle="--", linewidth=1.2)
    ax.text(.5, reference + 1.2, f"Untouched pretrained detector: {reference:.2f} AP", ha="center", color="#334155")
    ax.set(xticks=[0, 1], xticklabels=["Uniform selection", "Error-guided selection"], ylim=(0, 62), xlim=(-.6, 1.6), ylabel="COCO person AP (.50:.95), points")
    ax.spines[["top", "right"]].set_visible(False)
    ax.grid(axis="y", alpha=.15)
    ax.set_title("COCO person · 500 test images · three paired seeds\n3 epochs and 500 training images per fine-tuned run", loc="left", pad=14)
    fig.supxlabel("CC BY image subset; not full COCO or a 3LC head-to-head.\nPretrained reference has 80 classes; fine-tuned heads have 1 class.", fontsize=9)
    figure = root / "results/detection-comparison.png"
    fig.savefig(figure, dpi=160)
    plt.close(fig)
    report["figure"] = str(figure)
    output = Path("docs") / f"coco-people-validation-{args.date}.json"
    write_json(output, report)
    print(output)


if __name__ == "__main__":
    main()
