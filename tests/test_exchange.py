"""The formats a dataset arrives in and leaves in, and what survives the trip."""

import csv as csv_module
import json
import xml.etree.ElementTree as ET

import pytest
from PIL import Image

from granum import BoundingBoxes2D, Table
from granum.core.prelabel import CONFIDENCE, MODEL, SOURCE
from granum.formats.exchange import (
    csv_to_coco,
    export_csv,
    export_cvat,
    export_folders,
    export_kitti,
    export_label_studio,
    export_voc,
    folders_to_coco,
    kitti_to_coco,
    voc_to_coco,
    yolo_to_coco,
)


def picture(path, size=(60, 40), colour=(30, 90, 160)):
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", size, colour).save(path)
    return str(path)


@pytest.fixture
def labelled(isolated_project, tmp_path):
    """Two images: one labelled by a person and one a model drafted, plus an empty one."""
    images = [picture(tmp_path / "pics" / f"{i}.png") for i in range(3)]
    boxes = [
        {"width": 60.0, "height": 40.0, "instances": [
            {"vertices": [5.0, 5.0, 25.0, 25.0], "label": 0, SOURCE: "manual", CONFIDENCE: None},
            {"vertices": [30.0, 10.0, 50.0, 30.0], "label": 1, SOURCE: "manual", CONFIDENCE: None},
        ]},
        {"width": 60.0, "height": 40.0, "instances": [
            {"vertices": [10.0, 10.0, 20.0, 20.0], "label": 1, SOURCE: MODEL, CONFIDENCE: 0.77},
        ]},
        {"width": 60.0, "height": 40.0, "instances": []},
    ]
    return Table.from_dict_data(
        {"image": images, "bbs": boxes},
        schema={"bbs": BoundingBoxes2D.schema(["car", "van"],
                                              instance_properties={SOURCE: "string", CONFIDENCE: "float32"})},
        project_name="moving", dataset_name="street", table_name="train",
    )


def test_voc_writes_one_file_per_image_and_reads_back(labelled, tmp_path):
    out = export_voc(labelled, tmp_path / "voc", image_strategy="copy")
    files = sorted((out / "Annotations").glob("*.xml"))
    assert [f.stem for f in files] == ["0", "1", "2"]
    first = ET.parse(files[0]).getroot()
    assert [o.findtext("name") for o in first.findall("object")] == ["car", "van"]
    assert first.findtext("size/width") == "60"
    assert ET.parse(files[1]).getroot().findtext("object/source") == MODEL

    # ...and back: the boxes and the classes survive the round trip.
    coco = voc_to_coco(out, images_dir=out / "JPEGImages")
    assert sorted(c["name"] for c in coco["categories"]) == ["car", "van"]
    assert len(coco["images"]) == 3 and len(coco["annotations"]) == 3
    box = next(a for a in coco["annotations"] if a["image_id"] == 1)
    assert box["bbox"] == [5.0, 5.0, 20.0, 20.0]


def test_kitti_round_trips_through_its_own_columns(labelled, tmp_path):
    out = export_kitti(labelled, tmp_path / "kitti", image_strategy="copy")
    lines = (out / "label_2" / "0.txt").read_text().splitlines()
    assert lines[0].split()[0] == "car"
    assert [float(v) for v in lines[0].split()[4:8]] == [5.0, 5.0, 25.0, 25.0]

    coco = kitti_to_coco(out, images_dir=out / "image_2")
    assert len(coco["images"]) == 3
    assert {c["name"] for c in coco["categories"]} == {"car", "van"}
    assert coco["images"][0]["width"] == 60


def test_csv_lists_every_image_including_the_empty_one(labelled, tmp_path):
    out = export_csv(labelled, tmp_path / "boxes.csv")
    rows = list(csv_module.DictReader(out.open(encoding="utf-8")))
    assert len(rows) == 4                      # three boxes and one image with none
    assert rows[0]["class"] == "car" and rows[0]["x_min"] == "5"
    assert rows[2]["source"] == MODEL and rows[2]["confidence"] == "0.77"
    assert rows[3]["class"] == ""              # the empty image is still listed

    coco = csv_to_coco(out)
    assert len(coco["images"]) == 3 and len(coco["annotations"]) == 3


def test_a_csv_of_one_class_per_image_reads_as_classification(tmp_path):
    a, b = picture(tmp_path / "a.png"), picture(tmp_path / "b.png")
    path = tmp_path / "labels.csv"
    with path.open("w", newline="") as handle:
        writer = csv_module.writer(handle)
        writer.writerow(["filename", "label"])
        writer.writerow([a, "cat"])
        writer.writerow([b, "dog"])
    coco = csv_to_coco(path)
    assert [c["name"] for c in coco["categories"]] == ["cat", "dog"]
    # Each class is about the whole picture, so its box is the picture.
    assert coco["annotations"][0]["bbox"] == [0.0, 0.0, 60.0, 40.0]


def test_cvat_names_the_classes_and_says_which_boxes_a_model_drew(labelled, tmp_path):
    out = export_cvat(labelled, tmp_path / "cvat.xml")
    root = ET.parse(out).getroot()
    assert [n.text for n in root.findall("meta/task/labels/label/name")] == ["car", "van"]
    images = root.findall("image")
    assert len(images) == 3 and images[0].get("width") == "60"
    drafted = images[1].find("box")
    assert drafted.get("source") == MODEL and drafted.get("label") == "van"
    assert drafted.findtext("attribute") == "0.7700"


def test_label_studio_puts_a_models_boxes_under_predictions(labelled, tmp_path):
    out = export_label_studio(labelled, tmp_path / "tasks.json")
    tasks = json.loads(out.read_text())
    assert len(tasks) == 3
    assert "annotations" in tasks[0] and "predictions" in tasks[1]
    result = tasks[0]["annotations"][0]["result"][0]
    assert result["value"]["rectanglelabels"] == ["car"]
    # Percent of the image, which is what Label Studio stores.
    assert result["value"]["x"] == pytest.approx(5 / 60 * 100, abs=0.01)
    assert result["value"]["width"] == pytest.approx(20 / 60 * 100, abs=0.01)
    assert tasks[1]["predictions"][0]["result"][0]["score"] == pytest.approx(0.77)


def test_folders_file_each_image_under_a_class_and_read_back(labelled, tmp_path):
    out = export_folders(labelled, tmp_path / "tree", image_strategy="copy")
    assert sorted(p.name for p in out.iterdir()) == ["car", "unlabelled", "van"]
    coco = folders_to_coco(out)
    assert [c["name"] for c in coco["categories"]] == ["car", "unlabelled", "van"]
    assert len(coco["images"]) == 3


def test_yolo_converts_to_coco_with_its_own_class_order(labelled, tmp_path):
    from granum import export_yolo

    data_yaml = export_yolo({"train": labelled}, tmp_path / "yolo", image_strategy="copy")
    coco = yolo_to_coco(data_yaml, "train")
    assert [c["name"] for c in coco["categories"]] == ["car", "van"]
    assert len(coco["images"]) == 3 and len(coco["annotations"]) == 3
    box = next(a for a in coco["annotations"] if a["image_id"] == 1)
    assert box["bbox"][0] == pytest.approx(5.0, abs=0.05)


def test_a_folder_with_nothing_in_it_says_so(tmp_path):
    from granum.errors import TableError

    (tmp_path / "empty").mkdir()
    for reader in (voc_to_coco, kitti_to_coco, folders_to_coco):
        with pytest.raises(TableError):
            reader(tmp_path / "empty")


# -- through the service: a VOC folder imports like a COCO one --------------------


def api_client(data_root=None):
    from fastapi.testclient import TestClient

    import granum
    from granum.core.index import Index
    from granum.service.app import create_app

    index = Index([granum.get_config().project_root])
    index.refresh()
    return TestClient(create_app(index=index, config=granum.get_config(),
                                 allowed_hosts=["testserver"], serve_dashboard=False,
                                 data_roots=[str(data_root)] if data_root else None)), index


def test_the_wizard_finds_a_voc_folder_and_imports_it(isolated_project, tmp_path):
    folder = tmp_path / "voc-set"
    (folder / "Annotations").mkdir(parents=True)
    for i in range(2):
        picture(folder / f"{i}.png")
        root = ET.Element("annotation")
        ET.SubElement(root, "filename").text = f"{i}.png"
        size = ET.SubElement(root, "size")
        ET.SubElement(size, "width").text = "60"
        ET.SubElement(size, "height").text = "40"
        item = ET.SubElement(root, "object")
        ET.SubElement(item, "name").text = "cat"
        box = ET.SubElement(item, "bndbox")
        for tag, value in (("xmin", 5), ("ymin", 5), ("xmax", 25), ("ymax", 25)):
            ET.SubElement(box, tag).text = str(value)
        ET.ElementTree(root).write(folder / "Annotations" / f"{i}.xml")

    client, _index = api_client(tmp_path)
    browsed = client.get("/api/import/browse", params={"path": str(folder)}).json()
    found = browsed["detected"]
    assert found and found[0]["format"] == "voc"

    started = client.post("/api/import/preflight", json={
        "sources": [{"split": "train", "annotations": found[0]["annotations"],
                     "images": found[0]["images"], "format": "voc"}],
        "media": "full",
    })
    assert started.status_code == 200, started.text
    # The converted COCO file is left beside the data rather than in a temporary folder.
    assert (folder / "Annotations" / "granum-voc-train.coco.json").exists()
