import json
from types import SimpleNamespace

import numpy as np
import pytest

from granum.core.schemas import ValueMapEntry
from granum.errors import GranumError
from granum.formats.vision import encode_mask, oriented_corners, polygon_bounds
from granum.integration.ultralytics import YOLOPredictor
from granum.metrics.detection import DetectionMetricsCollector
from granum.metrics.vision import keypoint_oks, mask_scores, oriented_iou, semantic_scores


def collect(task, truth, prediction):
    collector = DetectionMetricsCollector(task=task, value_map={0: ValueMapEntry("object")})
    result = collector.collect({"bbs": [{"width": 10, "height": 10, "instances": truth}]}, [prediction])
    for name, schema in collector.column_schemas().items():
        schema.to_storage(result[name][0])
    return result


def test_oriented_matching_does_not_use_axis_aligned_bounds():
    target = oriented_corners(5, 5, 4, 1, np.pi / 4)
    prediction = oriented_corners(5, 5, 4, 1, -np.pi / 4)
    assert polygon_bounds(target) == pytest.approx(polygon_bounds(prediction))
    assert oriented_iou(target, prediction) == pytest.approx(1 / 7)
    assert oriented_iou(target, np.asarray(target).reshape(-1, 2)[::-1]) == pytest.approx(1)
    truth = [{"vertices": polygon_bounds(target), "label": 0, "coco_extra": json.dumps({"obb": target})}]
    result = collect("obb", truth, {"boxes": [polygon_bounds(prediction)], "scores": [.9], "labels": [0], "obb": [prediction]})
    assert (result["tp"], result["fp"], result["fn"]) == ([0], [1], [1])
    assert json.loads(result["bbs_predicted"][0]["instances"][0]["coco_extra"])["obb"] == prediction


def test_mask_matching_and_crowd_regions_use_pixels():
    target, pred = np.eye(10, dtype=np.uint8), np.fliplr(np.eye(10, dtype=np.uint8))
    truth = [{"vertices": [0, 0, 10, 10], "label": 0, "segmentation": json.dumps(encode_mask(target))}]
    output = {"boxes": [[0, 0, 10, 10]], "scores": [.9], "labels": [0], "segmentations": [encode_mask(pred)]}
    result = collect("segment", truth, output)
    assert result["tp"] == [0] and result["fp"] == [1]
    truth[0]["iscrowd"] = True
    result = collect("segment", truth, output)
    assert result["fp"] == [1]  # same enclosing box, but no pixels in the crowd region
    output["segmentations"] = [encode_mask(target)]
    result = collect("segment", truth, output)
    assert result["fp"] == [0] and result["fn"] == [0]
    assert result["bbs_predicted"][0]["instances"][0]["ignored"]


@pytest.mark.parametrize("segmentation", [None, [], {"size": [10, 10], "counts": [100]}])
def test_segmentation_rejects_missing_and_empty_ground_truth(segmentation):
    truth = [{"vertices": [0, 0, 10, 10], "label": 0, "segmentation": segmentation}]
    prediction = {"boxes": [[0, 0, 10, 10]], "scores": [.9], "labels": [0],
                  "segmentations": [encode_mask(np.zeros((10, 10)))]}
    with pytest.raises(GranumError, match="nonempty mask"):
        collect("segment", truth, prediction)


def test_keypoint_scoring_honours_visibility_area_and_sigmas():
    score, points = keypoint_oks([[1, 0, .9], [100, 100, .2]], [0, 0, 2, 0, 0, 0], 100, [0.1, 0.1])
    assert score == pytest.approx(np.exp(-1 / 8))
    assert points[1] is None
    assert keypoint_oks([[0, 0], [0, 0]], [0, 0, 0, 0, 0, 0], 100)[0] is None
    with pytest.raises(Exception, match="sigma"):
        keypoint_oks([[0, 0]], [0, 0, 2], 100, [0])
    truth = [{"vertices": [0, 0, 10, 10], "label": 0, "coco_extra": json.dumps({"keypoints": [2, 3, 2, 7, 8, 1]})}]
    result = collect("pose", truth, {"boxes": [[0, 0, 10, 10]], "scores": [.9], "labels": [0], "keypoints": [[[2, 3, .99], [7, 8, .3]]]})
    assert result["tp"] == [1]
    instance = result["bbs_predicted"][0]["instances"][0]
    assert instance["oks"] == 1 and instance["iou"] is None
    assert json.loads(instance["coco_extra"])["keypoint_oks"] == [1, 1]
    assert instance["keypoint_0_oks"] == 1
    assert instance["keypoint_1_confidence"] == .3


def test_keypoint_scores_persist_as_filterable_numeric_properties():
    import granum
    from granum import Table
    from granum.core.schemas.geometry import BoundingBoxes2DSchema
    from granum.metrics import collect_metrics

    table = Table.from_dict_data({"bbs": [{"width": 10, "height": 10, "instances": [{
        "vertices": [0, 0, 10, 10], "label": 0,
        "coco_extra": json.dumps({"keypoints": [2, 3, 2, 0, 0, 0]}),
    }]}]}, schema={"bbs": BoundingBoxes2DSchema(classes=["person"], instance_properties={"coco_extra": "string"})},
        project_name="pose", dataset_name="people")
    run = granum.init("pose", "keypoints")
    output = {"boxes": [[0, 0, 10, 10]], "labels": [0], "scores": [.9], "keypoints": [[[2, 3, .9], [5, 6, .2]]]}
    result = collect_metrics(table, [DetectionMetricsCollector(task="pose", value_map=table.schema["bbs"].value_map)],
                             predictor=lambda _: [output], run=run)
    properties = result.schema["bbs_predicted"].instance_properties
    assert properties["keypoint_0_oks"] == "float32"
    instance = result[0]["bbs_predicted"]["instances"][0]
    assert instance["keypoint_0_oks"] == 1
    assert instance["keypoint_1_oks"] is None  # unlabelled ground truth is never a zero score


def test_pixel_metrics_exclude_void_and_absent_classes():
    truth = np.array([[0, 1], [255, 1]])
    pred = np.array([[0, 0], [2, 1]])
    result = semantic_scores(pred, truth, [0, 1, 2], ignore_index=255)
    assert result["pixel_accuracy"] == pytest.approx(2 / 3)
    assert result["mean_iou"] == .5
    assert 2 not in result["classes"]
    assert mask_scores(pred == 1, truth == 1)["dice"] == pytest.approx(2 / 3)


class Tensor:
    def __init__(self, value):
        self.value = np.asarray(value)

    def cpu(self):
        return self

    def numpy(self):
        return self.value


@pytest.mark.parametrize("task", ["segment", "pose", "obb"])
def test_yolo_results_keep_task_geometry_and_class_mapping(task):
    boxes = SimpleNamespace(xyxy=Tensor([[1, 1, 4, 4], [2, 2, 3, 3]]), cls=Tensor([1, 0]), conf=Tensor([.8, .9]),
                            xyxyxyxy=Tensor(np.arange(16).reshape(2, 4, 2)))
    result = SimpleNamespace(boxes=boxes, obb=boxes, masks=SimpleNamespace(data=Tensor(np.ones((2, 10, 10)))),
                             keypoints=SimpleNamespace(data=Tensor([[[1, 2, .8]], [[3, 4, .9]]])))
    options = {}

    def predict(paths, **kwargs):
        options.update(kwargs)
        return [result]

    model = SimpleNamespace(task=task, names={0: "unknown", 1: "object"}, predict=predict)
    predictor = YOLOPredictor(model, {7: ValueMapEntry("object")}, on_unknown="drop")
    [output] = predictor({"image": ["image.png"]})
    assert output["labels"].tolist() == [7]
    assert output["boxes"].tolist() == [[1, 1, 4, 4]]
    assert len(output[{"segment": "segmentations", "pose": "keypoints", "obb": "obb"}[task]]) == 1
    if task == "segment":
        assert options["retina_masks"] and output["segmentations"][0]["size"] == [10, 10]
