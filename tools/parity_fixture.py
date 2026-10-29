"""Small, isolated datasets for actual browser editing and analysis qualification."""
import json
import shutil
from pathlib import Path

import numpy as np
from PIL import Image

from granum import Table, init
from granum.core.objects.run import get_active_run, set_active_run
from granum.core.schemas import CategoricalLabelSchema, EmbeddingSchema, ImageSchema
from granum.formats.coco import table_from_coco_data
from granum.formats.vision import encode_mask
from granum.metrics.collect import collect_metrics
from granum.metrics.detection import DetectionMetricsCollector


def add_parity_fixtures(root: Path, image: str) -> None:
    native = root / "native-masks"
    native.mkdir()
    shutil.copyfile(image, native / "image.png")
    pixels = np.zeros((128, 128), dtype=np.uint8)
    pixels[24:96, 24:96] = 1
    pixels[40:60, 40:60] = 0
    pixels[:8] = 255
    Image.fromarray(pixels).save(native / "mask.png")
    (native / "semantic.json").write_text(json.dumps({
        "format": "granum-semantic-masks", "version": 1, "ignore_index": 255,
        "categories": [{"id": 0, "name": "background"}, {"id": 1, "name": "object"}],
        "images": [{"file_name": "image.png", "mask": "mask.png"}],
    }))
    for dataset, task in (("masks", "instance_segmentation"), ("semantic", "semantic_segmentation"),
                          ("sam-recovery", "instance_segmentation"), ("semantic-polygons", "semantic_segmentation"),
                          ("rotated", "oriented_object_detection"), ("pose", "keypoint_detection")):
        categories = [{"id": 0, "name": "object"}, {"id": 1, "name": "other"}]
        if dataset == "pose":
            categories[0].update(keypoints=["head", "tail"], skeleton=[[1, 2]])
        annotations = [] if not dataset.startswith("semantic") else [
            {"id": 1, "image_id": 0, "category_id": 1, "bbox": [16, 16, 80, 80],
             "segmentation": [[16, 16, 96, 16, 96, 96, 16, 96]], "area": 6400}
        ]
        imported = table_from_coco_data(
            {"images": [{"id": 0, "file_name": Path(image).name, "width": 128, "height": 128}],
             "categories": categories, "annotations": annotations},
            source=root / f"{dataset}.json", image_folder=Path(image).parent,
            project_name="parity", dataset_name=dataset, producer_args={"tasks": [task]},
        )
        if dataset == "semantic-polygons":
            semantic_history = imported
    Table.from_dict_data(
        {"loss": [float(i + 1) for i in range(12)], "count": [float(i % 3 + 1) for i in range(12)],
         "embedding": [[float(i), float(i % 3), float(i % 5)] for i in range(12)]},
        schema={"embedding": EmbeddingSchema(shape=(3,))},
        project_name="parity", dataset_name="analysis", table_name="initial",
    )
    pose_folder = root / "landmark-images"
    pose_folder.mkdir()
    for i in range(3):
        shutil.copyfile(image, pose_folder / f"{i}.png")
    pose_table = table_from_coco_data({
        "images": [{"id": i, "file_name": f"{i}.png", "width": 128, "height": 128} for i in range(3)],
        "categories": [{"id": 0, "name": "object", "keypoints": ["head", "tail"], "skeleton": [[1, 2]]}],
        "annotations": [{"id": i, "image_id": i, "category_id": 0, "bbox": [16, 16, 64, 64],
                         "keypoints": [24, 24, 0 if i == 2 else 2, 64, 64, 2]} for i in range(3)],
    }, source=root / "landmarks.json", image_folder=pose_folder,
       project_name="parity", dataset_name="landmarks", producer_args={"tasks": ["keypoint_detection"]})
    active = get_active_run()
    run = init("parity", "pose-analysis")
    set_active_run(active)
    collect_metrics(pose_table, [DetectionMetricsCollector("bbs", task="pose", value_map=pose_table.schema["bbs"].value_map,
                                                          keypoint_sigmas=[.025, .025], iou_threshold=.4)],
                    predictor=lambda batch: [{"boxes": [[16, 16, 80, 80]], "labels": [0], "scores": [.9],
                                              "keypoints": [[[48 if Path(path).stem == "1" else 24, 24, .2 if Path(path).stem == "1" else .9], [64, 64, .8]]]}
                                             for path in batch["image"]], run=run, split="val")
    run.set_status("finished")
    from granum.training.evaluate import evaluator_policy

    classification = Table.from_dict_data({"image": [str(pose_folder / f"{i}.png") for i in range(3)], "label": [3, 7, 3]},
        schema={"image": ImageSchema(), "label": CategoricalLabelSchema(value_map={3: "cat", 7: "dog"})},
        project_name="parity", dataset_name="classification-comparison", table_name="test")
    for name, scores in [("classification-before", [0., 1., 1.]), ("classification-after", [1., 1., 1.])]:
        native = init("parity", name, parameters={"task": "classify", "evaluator": evaluator_policy(task="classify"),
                                                "qualification_fixture": True})
        native.add_metrics({"example_id": [0, 1, 2], "accuracy": scores}, foreign_table_url=classification.url, constants={"split": "test"})
        for epoch in range(3):
            native.add_metrics({"example_id": [0, 1, 2], "accuracy": scores, "predicted": [3 if scores[0] else 7, 7, 3], "confidence": [.8, .9, .7]},
                               foreign_table_url=classification.url, constants={"split": "valid", "epoch": epoch})
        native.set_status("finished")
    semantic_run = init("parity", "semantic-learning", parameters={"task": "semantic", "qualification_fixture": True})
    for epoch in range(3):
        predicted = {"width": 128, "height": 128, "instances": [{"vertices": [24, 24, 96, 96], "label": 1,
                     "segmentation": json.dumps(encode_mask(pixels == 1))}]}
        semantic_run.add_metrics({"example_id": [0], "mean_iou": [.25 * (epoch + 1)], "bbs_predicted": [predicted]},
                                 schema={"bbs_predicted": semantic_history.schema["bbs"]}, foreign_table_url=semantic_history.url,
                                 constants={"split": "valid", "epoch": epoch})
    semantic_run.set_status("finished")
    set_active_run(active)
