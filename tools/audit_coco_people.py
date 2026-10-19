"""Audit completed COCO runs through immutable tables, exports and the dashboard API."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
from fastapi.testclient import TestClient
from qualify_coco_people import digest, write_json

import granum
from granum.core.index import Index
from granum.formats.coco import export_coco, table_from_coco
from granum.formats.semantic import (
    export_semantic_masks,
    semantic_pixels,
    table_from_semantic_masks,
)
from granum.licensing import Licensing, set_licensing
from granum.service.app import create_app


def client(root):
    config = granum.Config.load(overrides={"project-root-url": str(root)}, use_config_files=False, use_env=False)
    granum.set_config(config)
    index = Index([root])
    index.refresh()
    return TestClient(create_app(index=index, config=config, allowed_hosts=["testserver"], serve_dashboard=False))


def fetch(api, path, **params):
    response = api.get(path, params=params)
    assert response.status_code == 200, response.text
    return response.json()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path("data/qualification/coco-person"))
    args = parser.parse_args()
    root = args.root.resolve()
    output = root / "audit"
    output.mkdir(exist_ok=True)
    if (output / "report.json").exists():
        raise RuntimeError("Preserve the completed audit; choose another output directory")
    set_licensing(Licensing.open())
    benchmark = json.loads((root / "results/report.json").read_text())
    tasks = json.loads((root / "task-results/report.json").read_text())
    report = {"manifest_sha256": digest(root / "manifest.json"), "runs": [], "comparisons": [], "native": {}}
    with client(root / "granum") as api:
        for entry in benchmark["runs"]:
            run = granum.Run.from_url(entry["run_url"])
            selection = json.loads((root / "results" / f"{run.name}-selection.json").read_text())
            source, weighted = [granum.Table.from_url(selection[k]) for k in ["training_pool", "table"]]
            original, selected = source.to_arrow(), weighted.to_arrow()
            assert original.column("bbs").equals(selected.column("bbs"))
            assert original.column("image_id").equals(selected.column("image_id"))
            assert all(weight == 1 for weight in original.column("weight").to_pylist())
            kept = [row["image_id"] for row in selected.to_pylist() if row["weight"] > 0]
            assert kept == selection["image_ids"] and len(kept) == 500
            checked = 0
            for metrics in run.metrics_tables():
                if not metrics.foreign_table_url:
                    continue
                table = granum.Table.from_url(metrics.foreign_table_url)
                ids = metrics.to_arrow().column("example_id").to_pylist()
                assert len(ids) == len(table) and set(ids) == set(range(len(table)))
                checked += len(ids)
            learning = fetch(api, "/api/run/learning", url=str(run.url))
            assert all(len(split["epochs"]) == 3 for split in learning["splits"])
            assert {s["split"] for s in learning["splits"]} == {"train", "valid"}
            report["runs"].append({"name": run.name, "canonical_metric_rows_checked": checked,
                                   "selection_images": len(kept), "original_labels_and_weights_unchanged": True,
                                   "learning_splits": [{"split": s["split"], "images": len(s["images"]), "epochs": s["epochs"]} for s in learning["splits"]]})
        for seed in benchmark["recipe"]["seeds"]:
            before, after = [next(r for r in benchmark["runs"] if r["seed"] == seed and r["condition"] == condition) for condition in ["uniform", "review-selected"]]
            comparison = fetch(api, "/api/runs/compare", baseline=before["run_url"], candidate=after["run_url"], split="test", download=True)
            assert len(comparison["samples"]["images"]) == 500
            assert comparison["samples"]["counts"]["only_baseline"] == comparison["samples"]["counts"]["only_candidate"] == 0
            write_json(output / f"comparison-seed-{seed}.json", comparison)
            report["comparisons"].append({"seed": seed, "matched_images": 500, "outcomes": comparison["samples"]["counts"]})
        test = granum.Table.from_url(run.parameters["test_table"])
        exported = export_coco(test, output / "test-roundtrip.json", weight_threshold=None)
        original_document, roundtrip = json.loads((root / "test.json").read_text()), json.loads(exported.read_text())
        for key in ["images", "categories", "licenses"]:
            assert original_document[key] == roundtrip[key]
        before_annotations = {a["id"]: a for a in original_document["annotations"]}
        assert {a["id"] for a in roundtrip["annotations"]} == set(before_annotations)
        for annotation in roundtrip["annotations"]:
            original_annotation = before_annotations[annotation["id"]]
            np.testing.assert_allclose(annotation["bbox"], original_annotation["bbox"], atol=1e-5)
            np.testing.assert_allclose(annotation["area"], original_annotation["area"], atol=1e-7)
            assert {k: v for k, v in annotation.items() if k not in {"bbox", "area"}} == {k: v for k, v in original_annotation.items() if k not in {"bbox", "area"}}
        reread = table_from_coco(exported, root / "images/val2017", project_name="coco-people-audit", dataset_name="roundtrip")
        assert len(reread) == len(test)
        report["coco_roundtrip"] = {"images": len(reread), "annotations": len(roundtrip["annotations"]), "masks_crowds_ids_and_license_metadata_preserved": True}
    with client(root / "task-granum") as api:
        for task in ["classify", "semantic"]:
            run = granum.Run.from_url(tasks["tasks"][task]["run"])
            learning = fetch(api, "/api/run/learning", url=str(run.url))
            assert len(learning["splits"]) == 2
            assert all(s["epochs"] == [0, 1, 2] for s in learning["splits"])
            valid = next(s for s in learning["splits"] if s["split"] == "valid")
            history = fetch(api, "/api/run/image-rounds", url=str(run.url), table=valid["table"], example=0)
            assert len(history["rounds"]) == 3 and history["metric"] == learning["metric"]
            test_metrics = [m for m in run.metrics_tables() if m.constants.get("split") == "test"]
            assert len(test_metrics) == 1 and len(test_metrics[0]) == 80
            source = granum.Table.from_url(run.parameters["test_table"])
            report["native"][task] = {"three_epoch_history": True, "test_scored_once": True, "test_images": 80}
            if task == "classify":
                labels = source.to_arrow().column("label").to_pylist()
                report["native"][task]["test_class_counts"] = {str(label): labels.count(label) for label in sorted(set(labels))}
                report["native"][task]["majority_class_accuracy"] = max(labels.count(label) for label in set(labels)) / len(labels)
            else:
                exported = export_semantic_masks(source, output / "semantic-roundtrip", image_strategy=None, weight_threshold=None)
                reread = table_from_semantic_masks(exported, project_name="coco-task-audit", dataset_name="semantic")
                for before, after in zip(source.to_arrow().to_pylist(), reread.to_arrow().to_pylist()):
                    np.testing.assert_array_equal(semantic_pixels(before["bbs"], {0, 1}, 255), semantic_pixels(after["bbs"], {0, 1}, 255))
                report["native"][task]["lossless_png_roundtrip_images"] = len(reread)
    write_json(output / "report.json", report)
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
