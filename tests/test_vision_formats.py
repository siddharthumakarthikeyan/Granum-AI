import json
from pathlib import Path

import numpy as np
import pytest
import yaml
from PIL import Image

from granum import Table, export_coco, export_yolo
from granum.errors import TableError
from granum.formats.exchange import yolo_to_coco
from granum.formats.vision import encode_mask, mask_array, yolo_polygon


def dataset(tmp_path, task, line, **metadata):
    root = tmp_path / task
    (root / "images" / "train").mkdir(parents=True)
    (root / "labels" / "train").mkdir(parents=True)
    Image.new("RGB", (100, 50)).save(root / "images" / "train" / "image.png")
    (root / "labels" / "train" / "image.txt").write_text(line + "\n")
    path = root / "data.yaml"
    path.write_text(yaml.safe_dump({"names": {0: "object"}, "train": "images/train", "task": task, **metadata}))
    return path


@pytest.mark.parametrize("task,line,metadata", [
    ("segment", "0 0.1 0.1 0.8 0.1 0.5 0.9", {}),
    ("obb", "0 0.4 0.1 0.8 0.5 0.6 0.9 0.2 0.5", {}),
    ("pose", "0 0.5 0.5 0.8 0.8 0.2 0.3 2 0.7 0.8 1 0 0 0", {
        "kpt_shape": [3, 3], "flip_idx": [1, 0, 2], "kpt_names": {0: ["left", "right", "centre"]},
        "skeleton": [[1, 3], [2, 3]], "kpt_oks_sigmas": [0.1, 0.1, 0.2],
    }),
    ("pose", "0 0.5 0.5 0.8 0.8 0.2 0.3 0.7 0.8", {"kpt_shape": [2, 2]}),
])
def test_yolo_task_roundtrip_preserves_geometry_and_metadata(tmp_path, isolated_project, task, line, metadata):
    source = dataset(tmp_path, task, line, **metadata)
    original = Table.from_yolo_url(source, project_name="vision")
    assert Path(original[0]["image"]).is_file()
    # One immutable edit version must retain import provenance and pose metadata.
    table = original.apply_edits(values={"weight": {0: 2.0}})
    out = export_yolo(table, tmp_path / "out", task=task, image_strategy="copy")
    emitted = (out.parent / "labels" / "train" / "image.txt").read_text().split()
    assert list(map(float, emitted)) == pytest.approx(list(map(float, line.split())), abs=1e-6)
    config = yaml.safe_load(out.read_text())
    for key, value in metadata.items():
        assert config[key] == value
    reread = Table.from_yolo_url(out, project_name="again")
    before = json.loads(export_coco(table, tmp_path / "before.json").read_text())["annotations"][0]
    after = json.loads(export_coco(reread, tmp_path / "after.json").read_text())["annotations"][0]
    assert after == before


def test_dashboard_converter_uses_the_same_task_parser(tmp_path):
    source = dataset(tmp_path, "segment", "0 0.1 0.1 0.8 0.1 0.5 0.9")
    coco = yolo_to_coco(source)
    assert coco["annotations"][0]["segmentation"] == [[10, 5, 80, 5, 50, 45]]
    assert (source.parent / coco["images"][0]["file_name"]).is_file()
    with pytest.raises(TableError, match="matching YOLO task"):
        yolo_to_coco(source, task="detect")
    (source.parent / "labels" / "train" / "image.txt").write_text("5 0.5 0.5 0.1 0.1")
    with pytest.raises(TableError, match="class 5"):
        yolo_to_coco(source, task="detect")


def test_export_does_not_overwrite_labels_for_different_image_extensions(tmp_path):
    path = dataset(tmp_path, "detect", "0 0.5 0.5 0.2 0.2")
    Image.new("RGB", (100, 50)).save(path.parent / "images/train/image.jpg")
    table = Table.from_yolo_url(path)
    output = export_yolo(table, tmp_path / "export")
    assert len(list((output.parent / "labels/train").glob("*.txt"))) == 2
    reread = Table.from_yolo_url(output, dataset_name="again")
    assert len(reread) == 2 and all(len(row["bbs"]["instances"]) == 1 for row in reread)


def test_oriented_export_rejects_outside_image_corners(tmp_path):
    path = dataset(tmp_path, "obb", "0 0.4 0.1 0.8 0.5 0.6 0.9 0.2 0.5")
    table = Table.from_yolo_url(path)
    value = table[0]["bbs"]
    extra = json.loads(value["instances"][0]["coco_extra"])
    extra["obb"][0] = -4
    value["instances"][0]["coco_extra"] = json.dumps(extra)
    edited = table.apply_edits(values={"bbs": {0: value}})
    with pytest.raises(TableError, match="outside the image"):
        export_yolo(edited, tmp_path / "bad-export", task="obb")


@pytest.mark.parametrize("metadata", [
    {"flip_idx": [0, 0]}, {"flip_idx": [1]}, {"kpt_names": {0: ["same", "same"]}},
    {"kpt_oks_sigmas": [0.1, 0]}, {"kpt_shape": [True, 3]},
])
def test_pose_metadata_is_validated_before_import(tmp_path, metadata):
    path = dataset(tmp_path, "pose", "0 0.5 0.5 0.8 0.8 0.2 0.3 2 0.7 0.8 2",
                   **{"kpt_shape": [2, 3], **metadata})
    with pytest.raises(TableError):
        Table.from_yolo_url(path)


@pytest.mark.parametrize("mask", [np.zeros((8, 9)), np.ones((8, 9)), np.eye(8), np.array([[0, 1], [1, 0]])])
def test_masks_roundtrip_with_coco_reference_decoder(mask):
    pytest.importorskip("pycocotools")
    height, width = mask.shape
    assert np.array_equal(mask_array(encode_mask(mask), width, height), mask)


def test_rle_retains_holes_and_yolo_exports_contours():
    pytest.importorskip("pycocotools")
    pytest.importorskip("cv2")
    mask = np.zeros((30, 40), dtype=np.uint8)
    mask[2:20, 2:20] = 1
    mask[6:10, 6:10] = 0
    mask[22:28, 30:38] = 1
    rle = encode_mask(mask)
    assert np.array_equal(mask_array(rle, 40, 30), mask)
    assert len(yolo_polygon(rle, 40, 30)) >= 24
    with pytest.raises(TableError, match="counts"):
        mask_array({"size": [30, 40], "counts": [10, 5000]}, 40, 30)
