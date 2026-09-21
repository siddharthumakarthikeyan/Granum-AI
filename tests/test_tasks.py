"""Suggesting the task a COCO dataset's labels are for."""

from types import SimpleNamespace

import pytest

from granum.importing.tasks import detect_task, normalize_tasks, task_warning, tasks_of


def _split(annotations, images=None):
    images = images or [{"id": i, "width": 100, "height": 80} for i in (1, 2, 3)]
    by_image = {}
    for a in annotations:
        by_image.setdefault(a["image_id"], []).append(a)
    return SimpleNamespace(coco={"categories": [{"id": 1}, {"id": 2}]}, image_by_id={i["id"]: i for i in images},
                           annotations_by_image=by_image)


def _ann(image, category=1, **extra):
    return {"image_id": image, "category_id": category, "bbox": [10, 10, 20, 20], **extra}


POLY = [[10, 10, 30, 10, 30, 30]]


def test_boxes_only_is_object_detection():
    assert detect_task([_split([_ann(1), _ann(1), _ann(2)])])["detected"] == "object_detection"
    # Box-only exports carry empty segmentation lists; they are still detection.
    assert detect_task([_split([_ann(1, segmentation=[]), _ann(2, segmentation=[])])])["detected"] == "object_detection"


def test_masks_are_instance_or_semantic_segmentation():
    instances = _split([_ann(1, segmentation=POLY), _ann(1, segmentation=POLY), _ann(2, segmentation=POLY)])
    assert detect_task([instances])["detected"] == "instance_segmentation"
    # One region per class per image reads as semantic segmentation.
    regions = _split([_ann(1, 1, segmentation=POLY), _ann(1, 2, segmentation=POLY), _ann(2, 1, segmentation={"counts": "abc", "size": [80, 100]})])
    assert detect_task([regions])["detected"] == "semantic_segmentation"


def test_keypoints_panoptic_and_classification():
    assert detect_task([_split([_ann(1, keypoints=[5, 5, 2, 0, 0, 0])])])["detected"] == "keypoint_detection"
    assert detect_task([_split([_ann(1, keypoints=[0, 0, 0])])])["detected"] == "object_detection"
    assert detect_task([_split([{"image_id": 1, "segments_info": []}])])["detected"] == "panoptic_segmentation"
    whole = [{"image_id": i, "category_id": 1, "bbox": [0, 0, 100, 80]} for i in (1, 2, 3)]
    assert detect_task([_split(whole)])["detected"] == "classification"


def test_warnings_when_the_labels_do_not_fit():
    counts = detect_task([_split([_ann(1)])])["counts"]
    assert task_warning("instance_segmentation", counts) and task_warning("keypoint_detection", counts)
    assert task_warning("panoptic_segmentation", counts) and task_warning("classification", counts)
    assert task_warning("object_detection", counts) is None
    assert task_warning("object_detection", detect_task([_split([])])["counts"])
    whole = detect_task([_split([{"image_id": i, "category_id": 1, "bbox": [0, 0, 100, 80]} for i in (1, 2, 3)])])["counts"]
    assert task_warning("classification", whole) is None


def test_tasks_are_normalized_and_read_from_old_imports():
    assert normalize_tasks(["instance_segmentation", "object_detection", "object_detection"]) == ["object_detection", "instance_segmentation"]
    assert normalize_tasks("classification") == ["classification"]
    with pytest.raises(ValueError):
        normalize_tasks(["painting"])
    assert tasks_of({"task": "keypoint_detection"}) == ["keypoint_detection"]
    assert tasks_of({"tasks": ["classification"], "task": "x"}) == ["classification"]
    assert tasks_of({}) == []
