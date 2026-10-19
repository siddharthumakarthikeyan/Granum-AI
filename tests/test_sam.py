import json
import time
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest
from fastapi.testclient import TestClient
from PIL import Image

from granum import Table, get_config
from granum.core.index import Index
from granum.core.schemas import ImageSchema
from granum.core.schemas.geometry import BoundingBoxes2DSchema
from granum.errors import GranumError
from granum.formats.vision import mask_array
from granum.integration.sam import propose_mask
from granum.service import trainers
from granum.service.app import create_app
from granum.service.segmentation import finish_segment, sam_availability


class Tensor:
    def __init__(self, value):
        self.value = np.asarray(value)

    def cpu(self):
        return self

    def numpy(self):
        return self.value


def test_sam_availability_requires_ultralytics_even_when_another_trainer_is_installed():
    assert not sam_availability({"available": True, "families": [{"package": "rfdetr", "installed": True}]})["available"]
    assert sam_availability({"available": True, "families": [{"package": "ultralytics", "installed": True}]})["available"]
    assert not sam_availability({"available": False, "families": [{"package": "ultralytics", "installed": True}]})["available"]


def test_sam_groups_positive_and_negative_prompts_for_one_object():
    seen = {}
    mask = np.zeros((10, 12), dtype=np.uint8)
    mask[2:8, 3:10] = 1
    mask[4:6, 5:7] = 0

    def model(image, **kwargs):
        seen.update(kwargs)
        return [SimpleNamespace(masks=SimpleNamespace(data=Tensor([mask, np.zeros_like(mask)])),
                                boxes=SimpleNamespace(conf=Tensor([.8, .3])))]

    result = propose_mask(Image.new("RGB", (12, 10)), model=model, box=[1, 1, 11, 9], points=[[4, 3], [6, 5]], labels=[1, 0])
    assert seen["points"] == [[[4, 3], [6, 5]]] and seen["labels"] == [[1, 0]]
    assert seen["bboxes"] == [[1, 1, 11, 9]]
    assert len(result["candidates"]) == 1
    assert np.array_equal(mask_array(result["candidates"][0]["mask"], 12, 10), mask)
    with pytest.raises(GranumError, match="foreground"):
        propose_mask(Image.new("RGB", (12, 10)), model=model, points=[[1, 1]], labels=[0])
    with pytest.raises(GranumError, match="inside"):
        propose_mask(Image.new("RGB", (12, 10)), model=model, box=[1, 1, 20, 20])


def test_proposals_are_read_once_and_cancelled_outputs_removed(tmp_path):
    record = SimpleNamespace(log=str(tmp_path / "sam.log"))
    output = Path(record.log).with_suffix(".mask.json")
    output.write_text(json.dumps({"candidates": [{"mask": {"size": [1, 1], "counts": [0, 1]}}]}))
    assert finish_segment(record, False, 0)["candidates"]
    assert not output.exists()
    output.write_text("{}")
    output.with_suffix(".tmp").write_text("partial")
    assert finish_segment(record, True, 1) == {"cancelled": True}
    assert not output.exists() and not output.with_suffix(".tmp").exists()


def test_sam_api_checks_source_and_prompts_before_loading_a_model(isolated_project, tmp_path):
    image = tmp_path / "sample.png"
    Image.new("RGB", (12, 10)).save(image)
    table = Table.from_dict_data({"image": [str(image)], "bbs": [{"width": 12, "height": 10, "instances": []}]},
                                schema={"image": ImageSchema(), "bbs": BoundingBoxes2DSchema(classes=["object"])},
                                project_name="sam", dataset_name="train")
    request = {"project": "sam", "dataset": "train", "table": str(table.url), "image": str(image), "points": [[5, 5]], "labels": [1]}
    with TestClient(create_app(config=get_config(), index=Index([isolated_project]), allowed_hosts=["testserver"], serve_dashboard=True)) as client:
        assert client.post("/api/annotations/segment", json={**request, "table": "/etc/passwd"}).status_code == 403
        assert client.post("/api/annotations/segment", json={**request, "image": "/etc/passwd"}).status_code == 404
        assert client.post("/api/annotations/segment", json={**request, "points": [[50, 5]]}).status_code == 400
        assert client.post("/api/annotations/segment", json={**request, "labels": []}).status_code == 400
        assert client.post("/api/annotations/segment", json={**request, "model": "https://unknown/model.pt"}).status_code == 422
    assert Table.from_url(table.url)[0]["bbs"]["instances"] == []


def test_restart_finalizes_a_completed_proposal_without_creating_a_run(isolated_project, tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    record = trainers.TrainerRecord(pid=2**22 + 7, project="sam", run_name="sam-finished", rounds=1,
                                    log=str(tmp_path / "sam.log"), project_root=str(isolated_project),
                                    started=time.time(), module=trainers.SEGMENT_MODULE)
    record.save()
    output = Path(record.log).with_suffix(".mask.json")
    output.write_text(json.dumps({"model": "sam2.1_t.pt", "candidates": [{"mask": {"size": [1, 1], "counts": [0, 1]}}]}))
    app = create_app(config=get_config(), allowed_hosts=["testserver"], serve_dashboard=False)
    jobs = [job for job in app.state.jobs.all() if job.kind == "segmentation"]
    assert len(jobs) == 1
    deadline = time.monotonic() + 5
    while jobs[0].status == "running" and time.monotonic() < deadline:
        time.sleep(.01)
    assert jobs[0].status == "done" and jobs[0].result["candidates"]
    assert not output.exists() and not record.path.exists()
    assert not (isolated_project / "projects" / "sam" / "runs").exists()
