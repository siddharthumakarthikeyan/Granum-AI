"""Detectron2's real mapper, Instances, model and evaluator protocol."""
import json

import numpy as np
import pytest

torch = pytest.importorskip("torch")
pytest.importorskip("detectron2")

from detectron2 import model_zoo  # noqa: E402
from detectron2.config import get_cfg  # noqa: E402
from detectron2.data import DatasetCatalog, DatasetMapper, MetadataCatalog  # noqa: E402
from detectron2.evaluation import inference_on_dataset  # noqa: E402
from detectron2.modeling import build_model  # noqa: E402
from detectron2.structures import Boxes, Instances  # noqa: E402
from detectron2.utils.events import EventStorage  # noqa: E402
from PIL import Image  # noqa: E402

import granum  # noqa: E402
from granum.formats.coco import table_from_coco_data  # noqa: E402
from granum.formats.vision import encode_mask  # noqa: E402
from granum.integration.detectron2 import (  # noqa: E402
    GranumEvaluator,
    dataset_dicts,
    instance_predictions,
    register_dataset,
)
from granum.metrics.collect import CollectionError  # noqa: E402


def source_table(tmp_path):
    images, annotations = [], []
    mask = np.zeros((64, 64), dtype=np.uint8)
    mask[8:48, 8:48] = 1
    mask[16:24, 16:24] = 0
    for i in range(3):
        Image.new("RGB", (64, 64), (100 + i * 10, 20, 70)).save(tmp_path / f"{i}.png")
        images.append({"id": i + 20, "file_name": f"{i}.png", "width": 64, "height": 64})
        annotations.append({"id": i, "image_id": i + 20, "category_id": 7, "bbox": [8, 8, 40, 40],
                            "segmentation": encode_mask(mask), "keypoints": [16, 20, 2, 40, 30, 1]})
    return table_from_coco_data({"images": images, "annotations": annotations,
                                "categories": [{"id": 7, "name": "object", "keypoints": ["left", "right"]}],
                                "granum_yolo": {"kpt_shape": [2, 3], "flip_idx": [1, 0]}},
                               source=tmp_path / "coco.json", project_name="detectron", dataset_name="objects")


def test_detectron_registration_and_keypoint_coordinate_mapping(tmp_path):
    table = source_table(tmp_path).apply_edits(values={"weight": {1: 0.}})
    name = "granum-test-registration"
    try:
        metadata = register_dataset(name, table)
        assert metadata.thing_dataset_id_to_contiguous_id == {7: 0}
        assert metadata.keypoint_flip_map == [("left", "right")]
        records = DatasetCatalog.get(name)
        assert [row["image_id"] for row in records] == [0, 2]
        assert records[0]["annotations"][0]["keypoints"] == [16.5, 20.5, 2., 40.5, 30.5, 1.]
        assert isinstance(records[0]["annotations"][0]["segmentation"]["counts"], bytes)
        with pytest.raises(CollectionError, match="already registered"):
            register_dataset(name, table)
        prediction = Instances((64, 64))
        prediction.pred_boxes = Boxes(torch.tensor([[8., 8., 48., 48.]]))
        prediction.pred_classes = torch.tensor([0])
        prediction.scores = torch.tensor([.9])
        prediction.pred_keypoints = torch.tensor([[[16.5, 20.5, .99], [40.5, 30.5, .8]]])
        converted = instance_predictions(prediction, table, column="bbs", task="pose")
        assert converted["labels"].tolist() == [7]
        np.testing.assert_allclose(converted["keypoints"][0, :, :2], [[16, 20], [40, 30]])
    finally:
        if name in DatasetCatalog.list():
            DatasetCatalog.remove(name)
            MetadataCatalog.remove(name)


def test_detectron_real_model_training_step_and_inference_save_metrics(tmp_path):
    old_threads = torch.get_num_threads()
    torch.set_num_threads(2)
    try:
        table = source_table(tmp_path)
        cfg = get_cfg()
        cfg.merge_from_file(model_zoo.get_config_file("COCO-InstanceSegmentation/mask_rcnn_R_50_FPN_3x.yaml"))
        cfg.MODEL.DEVICE = "cpu"
        cfg.MODEL.ROI_HEADS.NUM_CLASSES = 1
        cfg.MODEL.ROI_HEADS.BATCH_SIZE_PER_IMAGE = 16
        cfg.MODEL.ROI_HEADS.SCORE_THRESH_TEST = 0.
        cfg.MODEL.RPN.PRE_NMS_TOPK_TRAIN = 32
        cfg.MODEL.RPN.POST_NMS_TOPK_TRAIN = 16
        cfg.MODEL.RPN.PRE_NMS_TOPK_TEST = 16
        cfg.MODEL.RPN.POST_NMS_TOPK_TEST = 8
        cfg.TEST.DETECTIONS_PER_IMAGE = 4
        cfg.INPUT.MIN_SIZE_TRAIN = (64,)
        cfg.INPUT.MAX_SIZE_TRAIN = 64
        cfg.INPUT.MIN_SIZE_TEST = 64
        cfg.INPUT.MAX_SIZE_TEST = 64
        cfg.INPUT.RANDOM_FLIP = "none"
        cfg.INPUT.MASK_FORMAT = "bitmask"
        records = dataset_dicts(table)
        model = build_model(cfg)
        mapper = DatasetMapper(cfg, is_train=True)
        model.train()
        with EventStorage():
            losses = model([mapper(records[0])])
        assert "loss_mask" in losses and all(torch.isfinite(value) for value in losses.values())
        optimizer = torch.optim.SGD(model.parameters(), lr=0.001)
        optimizer.zero_grad()
        sum(losses.values()).backward()
        optimizer.step()
        run = granum.init("detectron", "real-model")
        evaluator = GranumEvaluator(table, run=run, task="segment", epoch=0)
        eval_mapper = DatasetMapper(cfg, is_train=False)
        result = inference_on_dataset(model, [[eval_mapper(records[2])], [eval_mapper(records[0])]], evaluator)
        assert model.training  # framework restores the training mode
        assert result["granum"]["samples"] == 2
        metrics = evaluator.metrics_table
        assert [row["example_id"] for row in metrics] == [0, 2]
        for row in metrics:
            for instance in row["bbs_predicted"]["instances"]:
                assert instance["label"] == 7
                assert json.loads(instance["segmentation"])["size"] == [64, 64]
        with pytest.raises(CollectionError, match="Table identity"):
            evaluator.process([{"height": 64, "width": 64}], [{}])
    finally:
        torch.set_num_threads(old_threads)
