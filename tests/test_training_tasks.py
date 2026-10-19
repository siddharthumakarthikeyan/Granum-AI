"""Task preflight and actual classification/semantic checkpoint-to-metrics behavior."""
import json

import numpy as np
import pytest
from PIL import Image

import granum
from granum.core.schemas import CategoricalLabelSchema, ImageSchema
from granum.core.schemas.geometry import BoundingBoxes2DSchema
from granum.errors import GranumError
from granum.formats.vision import encode_mask
from granum.training.data import validate_training


def tables(tmp_path, *, semantic=False):
    result = {}
    rng = np.random.default_rng(42)
    for split, count in [("train", 4), ("valid", 2), ("test", 2)]:
        images, labels, masks = [], [], []
        for i in range(count):
            path = tmp_path / f"{split}-{i}.png"
            Image.fromarray(rng.integers(0, 255, (40, 48, 3), dtype=np.uint8)).save(path)
            images.append(str(path))
            labels.append(3 if i % 2 else 7)
            mask = np.indices((40, 48))[1] < 24
            masks.append({"width": 48, "height": 40, "instances": [
                {"vertices": [0, 0, 24, 40], "label": 3, "segmentation": json.dumps(encode_mask(mask))},
                {"vertices": [24, 0, 48, 40], "label": 7, "segmentation": json.dumps(encode_mask(~mask))},
            ]})
        value_map = {3: "left", 7: "right"}
        data = {"image": images, **({"bbs": masks} if semantic else {"label": labels})}
        schema = {"image": ImageSchema(), **({"bbs": BoundingBoxes2DSchema(value_map=value_map, instance_properties={"segmentation": "string"})}
                  if semantic else {"label": CategoricalLabelSchema(value_map=value_map)})}
        result[split] = granum.Table.from_dict_data(data, schema=schema, project_name="tasks", dataset_name="data", table_name=split)
    return result


def test_preflight_rejects_copied_media_and_task_mismatch(isolated_project, tmp_path):
    import shutil

    source = tables(tmp_path)
    assert validate_training(source, "classify")["splits"] == {"train": 4, "valid": 2, "test": 2}
    shutil.copyfile(tmp_path / "train-0.png", tmp_path / "test-0.png")
    with pytest.raises(GranumError, match="byte-identical"):
        validate_training(source, "classify")
    with pytest.raises(GranumError):
        validate_training(source, "semantic", check_media=False)


def test_semantic_preflight_rejects_overlapping_ground_truth(isolated_project, tmp_path):
    source = tables(tmp_path, semantic=True)
    assert validate_training(source, "semantic")["task"] == "semantic"
    with pytest.raises(GranumError, match="whole-image"):
        validate_training(source, "classify", check_media=False)
    row = source["train"].to_arrow().to_pylist()[0]["bbs"]
    row["instances"][1]["segmentation"] = row["instances"][0]["segmentation"]
    changed = source["train"].set_values("bbs", {0: row})
    with pytest.raises(GranumError, match="overlap"):
        validate_training({**source, "train": changed}, "semantic")


def test_training_export_drops_excluded_training_rows_but_retains_all_validation(tmp_path):
    from granum import export_yolo

    source = tables(tmp_path, semantic=True)
    train = source["train"].set_weights({0: 0})
    valid = source["valid"].set_weights({0: 0})
    export_yolo({"train": train, "val": valid}, tmp_path / "export", split_weight_thresholds={"val": None})
    assert len(list((tmp_path / "export/images/train").glob("*.png"))) == 3
    assert len(list((tmp_path / "export/images/val").glob("*.png"))) == 2


@pytest.mark.parametrize("semantic", [False, True])
def test_real_training_preserves_ids_class_ids_and_test_separation(isolated_project, tmp_path, semantic):
    torch = pytest.importorskip("torch")
    pytest.importorskip("torchvision")
    torch.set_num_threads(2)
    from granum.training.train import main
    from granum.training.vision import score_checkpoint

    source = tables(tmp_path, semantic=semantic)
    source["train"] = source["train"].set_weights({0: 3.0})
    family, version = ("semantic", "lraspp-mobilenet-v3") if semantic else ("classifier", "resnet18")
    assert main(["--project-root", str(isolated_project), "--project", "tasks", "--run-name", family,
                 "--train-table", str(source["train"].url), "--valid-table", str(source["valid"].url),
                 "--test-table", str(source["test"].url), "--family", family, "--version", version,
                 "--epochs", "1", "--imgsz", "32", "--batch", "2", "--workers", "0", "--device", "cpu",
                 "--work-dir", str(tmp_path / "work"), "--no-pretrained", "--track-learning"]) == 0
    run = granum.Run.from_url(granum.ProjectLayout(isolated_project).run("tasks", family))
    assert run.status == "finished" and run.parameters["best_epoch"] == 1
    test_tables = [t for t in run.metrics_tables() if t.constants.get("split") == "test"]
    assert len(test_tables) == 1
    table = test_tables[0]
    assert str(table.foreign_table_url) == str(source["test"].url)
    assert table.to_arrow()["example_id"].to_pylist() == [0, 1]
    training_metrics = next(t for t in run.metrics_tables() if t.constants.get("split") == "train")
    assert training_metrics.to_arrow()["example_id"].to_pylist() == [0, 1, 2, 3]
    if semantic:
        assert {3, 7} == set(table.schema["bbs_predicted"].value_map)
        assert 0 <= run.parameters["test_mean_iou"] <= 1
        assert "score_map50" not in run.parameters
    else:
        assert set(table.to_arrow()["predicted"].to_pylist()) <= {3, 7}
        assert 0 <= run.parameters["test_accuracy"] <= 1
    repeated = score_checkpoint(run.parameters["weights"], source["test"], device="cpu")
    key = "mean_iou" if semantic else "accuracy"
    assert repeated[key] == pytest.approx(run.parameters[f"test_{key}"])
