import json
import time

import numpy as np
import pytest
from fastapi.testclient import TestClient
from PIL import Image

from granum import Table, get_config
from granum.core.schemas import ValueMapEntry
from granum.errors import TableError
from granum.formats.semantic import export_semantic_masks, semantic_pixels, semantic_to_coco
from granum.formats.vision import encode_mask
from granum.metrics import Prediction, SemanticMetricsCollector
from granum.service.app import create_app


def dataset(folder, pixels, *, categories=None, ignore=255):
    folder.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (pixels.shape[1], pixels.shape[0])).save(folder / "image.png")
    Image.fromarray(pixels).save(folder / "mask.png")
    path = folder / "semantic.json"
    path.write_text(json.dumps({"format": "granum-semantic-masks", "version": 1, "ignore_index": ignore,
                                "categories": categories or [{"id": 0, "name": "background"}, {"id": 1, "name": "object"}],
                                "images": [{"file_name": "image.png", "mask": "mask.png"}]}))
    return path


@pytest.mark.parametrize("large", [False, True])
def test_semantic_png_roundtrip_preserves_holes_disjoint_regions_and_void(isolated_project, tmp_path, large):
    label, ignore = (300, 65535) if large else (1, 255)
    pixels = np.array([[ignore, 0, label, 0], [0, label, 0, label], [label, 0, label, ignore]], dtype=np.uint16 if large else np.uint8)
    manifest = dataset(tmp_path / "input", pixels, categories=[{"id": 0, "name": "background"}, {"id": label, "name": "object"}], ignore=ignore)
    source = Table.from_semantic_masks(str(manifest), project_name="semantic", dataset_name="train")
    assert source.producer["args"]["tasks"] == ["semantic_segmentation"]
    assert len(source[0]["bbs"]["instances"]) == 2
    assert source[0]["image"] == (tmp_path / "input" / "image.png").as_posix()
    output = export_semantic_masks(source, tmp_path / "output")
    exported = json.loads(output.read_text())
    assert exported["ignore_index"] == ignore
    np.testing.assert_array_equal(np.asarray(Image.open(output.parent / exported["images"][0]["mask"])), pixels)
    again = Table.from_semantic_masks(str(output), project_name="semantic", dataset_name="again")
    np.testing.assert_array_equal(semantic_pixels(again[0]["bbs"], {0, label}, ignore), pixels)


def test_rgb_and_palette_masks_use_explicit_class_ids(tmp_path):
    rgb = np.array([[[0, 0, 0], [240, 10, 30]], [[255, 255, 255], [0, 0, 0]]], dtype=np.uint8)
    path = dataset(tmp_path / "rgb", rgb, categories=[{"id": 0, "name": "background", "color": [0, 0, 0]}, {"id": 1, "name": "object", "color": [240, 10, 30]}])
    document = json.loads(path.read_text())
    document["ignore_color"] = [255, 255, 255]
    path.write_text(json.dumps(document))
    assert [a["area"] for a in semantic_to_coco(path)["annotations"]] == [2, 1]
    palette = Image.fromarray(np.array([[0, 1], [255, 0]], dtype=np.uint8)).convert("P")
    palette.save(path.parent / "mask.png")
    assert [a["area"] for a in semantic_to_coco(path)["annotations"]] == [2, 1]


def test_unknown_pixels_and_overlapping_classes_are_rejected(tmp_path):
    path = dataset(tmp_path / "unknown", np.array([[0, 2]], dtype=np.uint8))
    with pytest.raises(TableError, match="unknown class"):
        semantic_to_coco(path)
    value = {"width": 2, "height": 2, "instances": [{"label": label, "segmentation": encode_mask(np.ones((2, 2)))} for label in (0, 1)]}
    with pytest.raises(TableError, match="overlap"):
        semantic_pixels(value, {0, 1}, 255)
    value["instances"][1]["iscrowd"] = True
    np.testing.assert_array_equal(semantic_pixels(value, {0, 1}, 255), np.full((2, 2), 255))


def test_semantic_collector_keeps_sample_metrics_and_pixel_counts(isolated_project, tmp_path):
    path = dataset(tmp_path / "metrics", np.array([[0, 1], [1, 255]], dtype=np.uint8))
    table = Table.from_semantic_masks(str(path), project_name="semantic", dataset_name="metrics")
    collector = SemanticMetricsCollector({0: ValueMapEntry("background"), 1: ValueMapEntry("object"), 2: ValueMapEntry("absent")})
    values = collector.collect({"bbs": [table[0]["bbs"]]}, Prediction(np.array([[[0, 0], [1, 2]]])))
    assert values["pixel_count"] == [3] and values["pixel_correct"] == [2]
    assert values["pixel_accuracy"] == [pytest.approx(2 / 3)]
    assert values["class_1_intersection"] == [1] and values["class_1_union"] == [2]
    assert values["class_2_iou"] == [None]
    for name, schema in collector.column_schemas().items():
        schema.to_storage(values[name][0])


def test_service_imports_semantic_manifest_and_checks_mask_paths(isolated_project, tmp_path):
    path = dataset(tmp_path / "allowed", np.array([[0, 1], [1, 255]], dtype=np.uint8))
    with TestClient(create_app(config=get_config(), data_roots=[str(path.parent)], allowed_hosts=["testserver"])) as api:
        request = {"sources": [{"split": "train", "annotations": str(path), "format": "semantic"}], "media": "full"}
        response = api.post("/api/import/preflight", json=request)
        assert response.status_code == 200, response.text
        job = response.json()
        for _ in range(100):
            job = api.get(f"/api/jobs/{job['id']}").json()
            if job["status"] != "running":
                break
            time.sleep(.01)
        assert job["status"] == "done", job
        document = json.loads(path.read_text())
        document["images"][0]["mask"] = "../../not-allowed.png"
        path.write_text(json.dumps(document))
        assert api.post("/api/import/preflight", json=request).status_code == 403
