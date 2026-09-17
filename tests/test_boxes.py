import numpy as np
import pyarrow as pa
import pytest

from granum import BoundingBoxes2D, Table, box_iou, match_boxes, nms
from granum.core.schemas import BoundingBoxes2DSchema, schema_from_dict
from granum.errors import SchemaError, TableError

# -- schema -----------------------------------------------------------------


def test_schema_roundtrips_and_stores_in_arrow():
    schema = BoundingBoxes2D.schema(["cat", "dog"], instance_properties={"confidence": "float32"})
    restored = schema_from_dict(schema.to_dict())
    assert isinstance(restored, BoundingBoxes2DSchema)
    assert restored.classes == ["cat", "dog"]
    assert restored.instance_properties == {"confidence": "float32"}
    value = schema.to_storage({"width": 10, "height": 8, "instances": [
        {"vertices": [1, 2, 3, 4], "label": 1, "confidence": 0.5}]})
    assert pa.array([value], type=schema.arrow_type()).to_pylist()[0] == value


@pytest.mark.parametrize("instance,match", [
    ({"vertices": [1, 2, 3], "label": 0}, "expected 4"),
    ({"vertices": [5, 2, 3, 4], "label": 0}, "max below min"),
    ({"vertices": [1, 2, 3, 4], "label": 7}, "not one of"),
    ({"vertices": [1, 2, 3, 4], "label": 0, "score": 1.0}, "undeclared"),
    ({"vertices": [1, 2, 3, 4], "label": 0, "confidence": "high"}, "must be a number"),
])
def test_schema_refuses_malformed_instances(instance, match):
    schema = BoundingBoxes2D.schema(["cat"], instance_properties={"confidence": "float32"})
    with pytest.raises(SchemaError, match=match):
        schema.to_storage({"width": 1, "height": 1, "instances": [instance]})


def test_box_table_edits_through_apply_edits():
    table = Table.from_dict_data(
        {"image": ["a.png"], "bbs": [{"width": 100, "height": 100, "instances": [{"vertices": [0, 0, 10, 10], "label": 0}]}]},
        schema={"bbs": BoundingBoxes2D.schema(["cat", "dog"])},
        project_name="p", dataset_name="d",
    )
    edited = table.apply_edits(values={"bbs": {0: {"width": 100, "height": 100, "instances": [
        {"vertices": [0, 0, 10, 10], "label": 1}, {"vertices": [20, 20, 40, 50], "label": 0}]}}})
    assert [i["label"] for i in edited[0]["bbs"]["instances"]] == [1, 0]
    with pytest.raises(TableError):
        table.apply_edits(values={"bbs": {0: {"width": 1, "height": 1, "instances": [{"vertices": [0, 0, 1, 1], "label": 5}]}}})


def test_value_helper_roundtrip():
    value = {"width": 64.0, "height": 48.0, "instances": [
        {"vertices": [1.0, 2.0, 3.0, 4.0], "label": 2, "confidence": 0.25}]}
    boxes = BoundingBoxes2D.from_value(value)
    assert boxes.boxes.shape == (1, 4) and boxes.labels.tolist() == [2]
    assert boxes.to_value() == value


# -- geometry -----------------------------------------------------------------


def test_iou_known_values():
    a = np.array([[0, 0, 10, 10]])
    b = np.array([[0, 0, 10, 10], [5, 0, 15, 10], [20, 20, 30, 30], [0, 0, 0, 0]])
    assert box_iou(a, b)[0].tolist() == pytest.approx([1.0, 50 / 150, 0.0, 0.0])
    assert box_iou(np.zeros((0, 4)), b).shape == (0, 4)


def test_matching_is_greedy_by_confidence_and_class_aware():
    gt = np.array([[0, 0, 10, 10], [50, 50, 60, 60]])
    gt_labels = np.array([0, 1])
    pred = np.array([[1, 1, 10, 10], [0, 0, 10, 10], [50, 50, 60, 60], [80, 80, 90, 90]])
    pred_labels = np.array([0, 0, 0, 1])  # third has the wrong class
    scores = np.array([0.6, 0.9, 0.8, 0.7])
    result = match_boxes(gt, gt_labels, pred, pred_labels, scores)
    # the higher-confidence exact box claims gt 0; the 0.6 duplicate is a false positive
    assert result.pred_match.tolist() == [-1, 0, -1, -1]
    assert result.gt_match.tolist() == [1, -1]
    assert (result.tp, result.fp, result.fn) == (1, 3, 1)
    assert result.precision == 0.25 and result.recall == 0.5
    assert result.pred_iou[0] == pytest.approx(81 / 100)

    agnostic = match_boxes(gt, gt_labels, pred, pred_labels, scores, class_aware=False)
    assert agnostic.gt_match.tolist() == [1, 2]


def test_empty_image_is_perfect():
    result = match_boxes(np.zeros((0, 4)), [], np.zeros((0, 4)), [])
    assert (result.precision, result.recall, result.f1) == (1.0, 1.0, 1.0)


def test_nms_keeps_best_and_respects_classes():
    boxes = np.array([[0, 0, 10, 10], [1, 1, 10, 10], [0, 0, 10, 10], [30, 30, 40, 40]])
    scores = np.array([0.5, 0.9, 0.8, 0.4])
    labels = np.array([0, 0, 1, 0])
    assert nms(boxes, scores, labels, iou_threshold=0.5).tolist() == [1, 2, 3]
    assert nms(boxes, scores, labels, iou_threshold=0.5, class_aware=False).tolist() == [1, 3]
