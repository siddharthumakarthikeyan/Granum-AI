"""Runs in a separate environment because SG 3.7 pins NumPy and torchmetrics."""
import numpy as np
import pytest

torch = pytest.importorskip("torch")
pytest.importorskip("super_gradients")

from PIL import Image  # noqa: E402
from super_gradients import Trainer, setup_device  # noqa: E402
from super_gradients.training import models  # noqa: E402
from super_gradients.training.metrics import Accuracy  # noqa: E402
from super_gradients.training.utils.callbacks import PhaseContext  # noqa: E402
from super_gradients.training.utils.collate_fn import DetectionCollateFN  # noqa: E402
from torch.utils.data import DataLoader, Subset  # noqa: E402

import granum  # noqa: E402
from granum.core.schemas import CategoricalLabelSchema  # noqa: E402
from granum.formats.coco import table_from_coco_data  # noqa: E402
from granum.integration._metrics import SAMPLE_ID, SOURCE_URL  # noqa: E402
from granum.integration.super_gradients import (  # noqa: E402
    Evaluation,
    GranumCallback,
    IdentityCollate,
    IndexedDataset,
    SuperGradientsPredictor,
    identity_collate,
)
from granum.metrics import ClassificationMetricsCollector, EmbeddingsMetricsCollector  # noqa: E402
from granum.metrics.collect import CollectionError  # noqa: E402
from granum.metrics.detection import DetectionMetricsCollector  # noqa: E402
from granum.metrics.predictor import Prediction  # noqa: E402


def feature_table():
    return granum.Table.from_dict_data(
        {"features": [[3., 0.], [0., 4.], [2., 0.], [0., 1.], [5., 0.]], "label": [0, 1, 0, 1, 0]},
        schema={"label": CategoricalLabelSchema(classes=["a", "b"])},
        project_name="sg", dataset_name="features",
    )


def test_super_gradients_fit_and_test_collect_shuffled_samples(tmp_path):
    table = feature_table()
    dataset = IndexedDataset(table.with_transform(lambda row: (
        torch.tensor(row["features"], dtype=torch.float32), row["label"],
    )))
    loader = DataLoader(dataset, batch_size=2, collate_fn=identity_collate)
    validation = DataLoader(Subset(dataset, [4, 1, 3]), batch_size=2, collate_fn=identity_collate)
    run = granum.init("sg", "classification")
    callback = GranumCallback(
        run, validation=[Evaluation(table, [ClassificationMetricsCollector()], "val")],
        test=[Evaluation(table, [ClassificationMetricsCollector(), EmbeddingsMetricsCollector(0)], "test",
                         output_transform=lambda ctx: Prediction(ctx.preds, {0: ctx.inputs * 2}))],
    )
    setup_device(device="cpu")
    trainer = Trainer("granum-sg", ckpt_root_dir=str(tmp_path))
    trainer.train(
        model=torch.nn.Linear(2, 2), train_loader=loader, valid_loader=validation,
        training_params={"max_epochs": 2, "initial_lr": 0.01, "optimizer": "SGD",
                         "loss": torch.nn.CrossEntropyLoss(), "metric_to_watch": "Accuracy",
                         "greater_metric_to_watch_is_better": True, "valid_metrics_list": [Accuracy()],
                         "train_metrics_list": [], "phase_callbacks": [callback],
                         "save_model": False, "average_best_models": False,
                         "mixed_precision": False, "ema": False,
                         "sg_logger_params": {"launch_tensorboard": False}},
    )
    assert len(run.metrics_tables()) == 2
    trainer.test(model=torch.nn.Identity(), test_loader=validation, test_metrics_list=[Accuracy()],
                 test_phase_callbacks=[callback])
    results = run.metrics_tables()
    assert len(results) == 3
    for result in results:
        assert [row["example_id"] for row in result] == [1, 3, 4]
        assert all(np.isfinite(row["loss"]) for row in result)
    assert [row["accuracy"] for row in results[-1]] == [1., 1., 1.]
    np.testing.assert_allclose([row["embedding"] for row in results[-1]], [[0, 8], [0, 2], [10, 0]])
    assert results[-1].schema["embedding"].shape == (2,)
    assert run.aggregate_metrics()


def test_identity_collator_preserves_variable_targets_and_rejects_wrong_version():
    table = feature_table()
    dataset = IndexedDataset(table.with_transform(lambda row: (
        torch.zeros(3, 16, 16), np.zeros((int(row["features"][0]), 5), dtype=np.float32),
    )))
    collate = IdentityCollate(DetectionCollateFN())
    inputs, targets, extras = collate([dataset[4], dataset[1]])
    assert inputs.shape == (2, 3, 16, 16)
    assert targets.shape == (5, 6)
    assert extras[SAMPLE_ID].tolist() == [4, 1]
    assert extras[SOURCE_URL] == [table.url.resolved] * 2
    callback = GranumCallback(granum.init("sg", "invalid"), validation=[
        Evaluation(table, [ClassificationMetricsCollector()], "val"),
    ])
    context = PhaseContext(epoch=0, net=torch.nn.Identity(), preds=torch.ones(2, 2),
                           additional_batch_items={**extras, SOURCE_URL: ["wrong"] * 2})
    callback.on_validation_loader_start(context)
    with pytest.raises(CollectionError, match="Table version"):
        callback.on_validation_batch_end(context)


def vision_table(tmp_path):
    image = np.zeros((64, 96, 3), dtype=np.uint8)
    image[10:45, 20:60] = 220
    for i in range(2):
        Image.fromarray(image).save(tmp_path / f"{i}.png")
    return table_from_coco_data({
        "images": [{"id": i, "file_name": f"{i}.png", "width": 96, "height": 64} for i in range(2)],
        "annotations": [{"id": i, "image_id": i, "category_id": 7, "bbox": [20, 10, 40, 35],
                         "keypoints": [30, 20, 2, 50, 35, 2]} for i in range(2)],
        "categories": [{"id": 7, "name": "object", "keypoints": ["left", "right"]}],
    }, source=tmp_path / "data.json", project_name="sg", dataset_name="vision")


@pytest.mark.parametrize("task,architecture", [("detect", "yolo_nas_s"), ("pose", "yolo_nas_pose_n")])
def test_real_yolo_nas_pipeline_restores_geometry_and_training_modes(tmp_path, task, architecture):
    table = vision_table(tmp_path)
    old_threads = torch.get_num_threads()
    torch.set_num_threads(2)
    try:
        # No pretrained weights or accuracy assertion; execute the actual inference stack.
        model = models.get(architecture, num_classes=1 if task == "detect" else 2)
        processing = {"ComposeProcessing": {"processings": [
            {"DetectionLongestMaxSizeRescale": {"output_shape": [128, 192]}},
            {"DetectionBottomRightPadding": {"output_shape": [128, 192], "pad_value": 114}},
            {"ImagePermute": {"permutation": [2, 0, 1]}},
        ]}}
        if task == "detect":
            model.set_dataset_processing_params(class_names=["object"], image_processor=processing, iou=0.5, conf=0.0)
        else:
            processing = {"ComposeProcessing": {"processings": [
                {"KeypointsRescale": {"output_shape": [128, 192]}},
                {"ImagePermute": {"permutation": [2, 0, 1]}},
            ]}}
            model.set_dataset_processing_params(image_processor=processing, conf=1e-8, iou=0.5,
                                                edge_links=[(0, 1)], edge_colors=[(255, 0, 0)],
                                                keypoint_colors=[(255, 0, 0), (0, 255, 0)])
        model.train()
        next(child for child in model.modules() if isinstance(child, torch.nn.BatchNorm2d)).eval()
        modes = [module.training for module in model.modules()]
        options = {"nms_top_k": 10, "max_predictions": 3} if task == "detect" else {
            "pre_nms_max_predictions": 10, "post_nms_max_predictions": 3,
        }
        predictor = SuperGradientsPredictor(model, table.schema["bbs"].value_map, task=task,
                                            conf=0., **options)
        result = predictor({"image": [table[1]["image"], table[0]["image"]]})
        assert [module.training for module in model.modules()] == modes
        assert len(result) == 2 and all(0 < len(row["labels"]) <= 3 for row in result)
        assert all(set(row["labels"]) == {7} for row in result)
        if task == "pose":
            assert all(row["keypoints"].shape[1:] == (2, 3) for row in result)
        run = granum.init("sg", f"nas-{task}")
        callback = GranumCallback(run, validation=[Evaluation(
            table, [DetectionMetricsCollector("bbs", task=task, value_map=table.schema["bbs"].value_map)], "val",
            predictor_factory=lambda net: SuperGradientsPredictor(net, table.schema["bbs"].value_map, task=task,
                                                                 conf=0., **options),
        )])
        context = PhaseContext(net=model, epoch=0, metrics_dict={"score": 0.})
        callback.on_validation_loader_start(context)
        callback.on_validation_batch_end(context)
        callback.on_validation_loader_end(context)
        metrics = run.metrics_tables()
        assert len(metrics) == 1
        assert [row["example_id"] for row in metrics[0]] == [0, 1]
        assert [row["bbs_predicted"]["width"] for row in metrics[0]] == [96, 96]
    finally:
        torch.set_num_threads(old_threads)
