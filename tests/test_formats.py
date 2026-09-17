import json
from pathlib import Path

import pytest
import yaml
from PIL import Image

from granum import Table, export_coco, export_yolo
from granum.errors import TableError


def write_image(path: Path, size=(64, 48), exif_rotate=False):
    path.parent.mkdir(parents=True, exist_ok=True)
    image = Image.new("RGB", size, (120, 40, 200))
    if exif_rotate:
        exif = Image.Exif()
        exif[274] = 6  # rotate 90: a model sees height x width
        image.save(path, exif=exif)
    else:
        image.save(path)


@pytest.fixture
def coco(tmp_path):
    for name in ("a.jpg", "b.jpg", "c.jpg"):
        write_image(tmp_path / "images" / name)
    document = {
        "info": {"description": "tiny", "year": 2026},
        "licenses": [{"id": 1, "name": "CC"}],
        "images": [
            {"id": 11, "file_name": "a.jpg", "width": 64, "height": 48, "license": 1, "coco_url": "http://x/a.jpg"},
            {"id": 12, "file_name": "b.jpg", "width": 64, "height": 48},
            {"id": 13, "file_name": "c.jpg", "width": 64, "height": 48},  # no annotations
        ],
        "annotations": [
            {"id": 101, "image_id": 11, "category_id": 3, "bbox": [4.5, 6.25, 20.07, 10.3], "area": 150.5,
             "iscrowd": 0, "segmentation": [[4.5, 6.25, 24.57, 6.25, 24.57, 16.55]]},
            {"id": 102, "image_id": 11, "category_id": 7, "bbox": [30, 5, 10, 12], "area": 120, "iscrowd": 1,
             "segmentation": {"counts": [1, 2, 3], "size": [48, 64]}, "attributes": {"occluded": True}},
            {"id": 103, "image_id": 12, "category_id": 3, "bbox": [0.1, 0.2, 63.8, 47.7], "area": 3043.26,
             "iscrowd": 0, "segmentation": []},
        ],
        "categories": [
            {"id": 3, "name": "car", "supercategory": "vehicle"},
            {"id": 7, "name": "truck", "supercategory": "vehicle"},
        ],
    }
    path = tmp_path / "annotations.json"
    path.write_text(json.dumps(document))
    return path, document


def normalise(document):
    """Order-insensitive view of a COCO document for comparison."""
    out = dict(document)
    out["images"] = sorted(document["images"], key=lambda i: i["id"])
    out["annotations"] = sorted(document["annotations"], key=lambda a: a["id"])
    out["categories"] = sorted(document["categories"], key=lambda c: c["id"])
    return out


def test_coco_import_uses_category_ids_and_keeps_extras(coco):
    path, _ = coco
    table = Table.from_coco(path, path.parent / "images", project_name="p")
    assert len(table) == 3
    assert table.schema["bbs"].classes == ["car", "truck"]
    assert sorted(table.schema["bbs"].value_map) == [3, 7]
    first = table[0]["bbs"]
    assert first["instances"][0]["vertices"] == pytest.approx([4.5, 6.25, 24.57, 16.55])
    assert first["instances"][1]["iscrowd"] is True
    assert table[2]["bbs"]["instances"] == []
    assert table.schema["coco_image"].default_visible is False


def test_coco_roundtrip_is_lossless(coco, tmp_path):
    path, document = coco
    table = Table.from_coco(path, path.parent / "images", project_name="p")
    out = export_coco(table, tmp_path / "out" / "annotations.json")
    assert normalise(json.loads(out.read_text())) == normalise(document)


def test_coco_roundtrip_survives_an_edit_revision(coco, tmp_path):
    path, document = coco
    table = Table.from_coco(path, path.parent / "images", project_name="p")
    value = table[1]["bbs"]
    value["instances"][0]["label"] = 7
    value["instances"].append({"vertices": [1.0, 1.0, 5.0, 9.0], "label": 3, "annotation_id": None,
                               "iscrowd": None, "area": None, "segmentation": None, "coco_extra": None})
    edited = table.apply_edits(values={"bbs": {1: value}})
    exported = json.loads(export_coco(edited, tmp_path / "e.json").read_text())
    assert exported["info"] == document["info"]  # from the lineage root
    ann = {a["id"]: a for a in exported["annotations"]}
    assert ann[103]["category_id"] == 7
    new = [a for a in exported["annotations"] if a["id"] not in (101, 102, 103)]
    assert len(new) == 1 and new[0]["id"] == 104 and new[0]["bbox"] == [1, 1, 4, 8] and new[0]["area"] == 32


def test_coco_export_honours_weights_and_copies_images(coco, tmp_path):
    path, _ = coco
    table = Table.from_coco(path, path.parent / "images", project_name="p").apply_edits(values={"weight": {0: 0.0}})
    out = export_coco(table, tmp_path / "x" / "ann.json", image_strategy="copy")
    exported = json.loads(out.read_text())
    assert [i["id"] for i in exported["images"]] == [12, 13]
    assert all(a["image_id"] != 11 for a in exported["annotations"])
    assert (tmp_path / "x" / "b.jpg").exists() and not (tmp_path / "x" / "a.jpg").exists()
    assert len(json.loads(export_coco(table, tmp_path / "all.json", weight_threshold=None).read_text())["images"]) == 3


def test_coco_rejects_annotations_for_missing_images(tmp_path):
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps({"images": [], "annotations": [{"id": 1, "image_id": 5, "category_id": 1, "bbox": [0, 0, 1, 1]}], "categories": [{"id": 1, "name": "x"}]}))
    with pytest.raises(TableError, match="refer to images"):
        Table.from_coco(bad)


# -- YOLO -----------------------------------------------------------------------


@pytest.fixture
def yolo(tmp_path):
    root = tmp_path / "ds"
    write_image(root / "images" / "train" / "one.jpg", (100, 50))
    write_image(root / "images" / "train" / "two.jpg", (40, 80), exif_rotate=True)
    write_image(root / "images" / "train" / "background.jpg", (10, 10))
    write_image(root / "images" / "val" / "three.jpg", (20, 20))
    (root / "labels" / "train").mkdir(parents=True)
    (root / "labels" / "val").mkdir(parents=True)
    (root / "labels" / "train" / "one.txt").write_text("0 0.5 0.5 0.2 0.4\n2 0.1 0.9 0.05 0.1\n")
    (root / "labels" / "train" / "two.txt").write_text("1 0.25 0.75 0.5 0.5\n")
    (root / "labels" / "val" / "three.txt").write_text("2 0.5 0.5 1 1\n")
    config = root / "data.yaml"
    config.write_text(yaml.safe_dump({"path": str(root), "train": "images/train", "val": "images/val",
                                      "names": {0: "cat", 1: "dog", 2: "bird"}}))
    return config


def test_yolo_import_converts_to_pixels(yolo):
    table = Table.from_yolo_url(yolo, "train", project_name="p")
    rows = {Path(r["image"]).name: r["bbs"] for r in table}
    assert rows["one.jpg"]["instances"][0]["vertices"] == pytest.approx([40, 15, 60, 35])
    assert rows["background.jpg"]["instances"] == []
    # EXIF-rotated: sized as the model sees it
    assert (rows["two.jpg"]["width"], rows["two.jpg"]["height"]) == (80, 40)
    assert table.schema["bbs"].classes == ["cat", "dog", "bird"]


def test_yolo_roundtrip_is_lossless(yolo, tmp_path):
    train = Table.from_yolo_url(yolo, "train", project_name="p")
    val = Table.from_yolo_url(yolo, "val", project_name="p", table_name="val")
    data = export_yolo({"train": train, "val": val}, tmp_path / "export", image_strategy="copy")
    exported = yaml.safe_load(data.read_text())
    assert exported["names"] == {0: "cat", 1: "dog", 2: "bird"}
    assert exported["train"] == "images/train" and exported["val"] == "images/val"
    source = yolo.parent
    for split, name in [("train", "one"), ("train", "two"), ("val", "three")]:
        original = [line.split() for line in (source / "labels" / split / f"{name}.txt").read_text().splitlines()]
        written = [line.split() for line in (tmp_path / "export" / "labels" / split / f"{name}.txt").read_text().splitlines()]
        assert len(original) == len(written)
        for a, b in zip(original, written):
            assert a[0] == b[0] and [float(x) for x in a[1:]] == pytest.approx([float(x) for x in b[1:]], abs=1e-6)
    assert (tmp_path / "export" / "labels" / "train" / "background.txt").read_text() == ""
    # and the export re-imports to the same boxes
    again = Table.from_yolo_url(data, "train", project_name="q")
    for a, b in zip(again, train):
        for ia, ib in zip(a["bbs"]["instances"], b["bbs"]["instances"]):
            assert ia["label"] == ib["label"] and ia["vertices"] == pytest.approx(ib["vertices"], abs=1e-3)


def test_yolo_export_renumbers_coco_ids_contiguously(coco, tmp_path):
    path, _ = coco
    table = Table.from_coco(path, path.parent / "images", project_name="p")
    data = export_yolo(table, tmp_path / "y", image_strategy="symlink", skip_ignored=False)
    assert yaml.safe_load(data.read_text())["names"] == {0: "car", 1: "truck"}
    lines = (tmp_path / "y" / "labels" / "train" / "a.txt").read_text().split("\n")
    assert [line.split()[0] for line in lines if line] == ["0", "1"]
    assert (tmp_path / "y" / "images" / "train" / "a.jpg").is_symlink()


def test_yolo_rejects_segmentation_labels(yolo):
    (yolo.parent / "labels" / "train" / "one.txt").write_text("0 0.1 0.1 0.2 0.1 0.2 0.2\n")
    with pytest.raises(TableError, match="expected 'class cx cy w h'"):
        Table.from_yolo_url(yolo, "train", project_name="p")


def test_unsupported_task_is_explicit(yolo):
    with pytest.raises(TableError, match="not supported yet"):
        Table.from_yolo_url(yolo, "train", task="segment")


def test_coco_empty_segmentation_is_stored_once_and_exported_back(tmp_path, isolated_project):
    import json

    from granum.formats.coco import export_coco, table_from_coco

    source = tmp_path / "boxes.json"
    source.write_text(json.dumps({
        "images": [{"id": 1, "file_name": "a.jpg", "width": 10, "height": 10}],
        "annotations": [{"id": 5, "image_id": 1, "category_id": 1, "bbox": [1, 1, 2, 2], "iscrowd": 0, "area": 4, "segmentation": []}],
        "categories": [{"id": 1, "name": "can"}],
    }))
    table = table_from_coco(source, project_name="p")
    assert "segmentation" not in table.schema["bbs"].instance_properties
    out = json.loads(export_coco(table, tmp_path / "out.json").read_text())
    assert out["annotations"][0]["segmentation"] == []
