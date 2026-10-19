"""SAM proposals with the same checked object access and worker lifecycle as training."""
from __future__ import annotations

import json
import sys
import uuid
from pathlib import Path
from typing import Any, Literal

from fastapi import HTTPException
from pydantic import BaseModel, Field

from granum.core.prelabel import box_column
from granum.errors import GranumError
from granum.formats._common import image_column
from granum.integration.sam import SAM_MODELS
from granum.service import trainers


class SegmentRequest(BaseModel):
    project: str
    dataset: str
    table: str
    image: str
    model: Literal["sam2.1_t.pt", "sam2.1_s.pt", "sam2.1_b.pt", "mobile_sam.pt"] = "sam2.1_t.pt"
    box: tuple[float, float, float, float] | None = None
    points: list[tuple[float, float]] = Field(default_factory=list, max_length=128)
    labels: list[Literal[0, 1]] = Field(default_factory=list, max_length=128)


def finish_segment(record: Any, cancelled: bool, code: int | None) -> dict[str, Any]:
    target = Path(record.log).with_suffix(".mask.json")
    try:
        if cancelled:
            return {"cancelled": True}
        if code not in (None, 0) or not target.exists() or target.stat().st_size > 128 * 1024 * 1024:
            raise GranumError("SAM could not finish; see the job log and check that training support is installed")
        return json.loads(target.read_text())
    finally:
        target.unlink(missing_ok=True)
        target.with_suffix(".tmp").unlink(missing_ok=True)


def sam_availability(installed: dict[str, Any]) -> dict[str, Any]:
    # An RF-DETR-only environment can train but cannot run Ultralytics SAM.
    available = bool(installed.get("available") and any(
        family.get("package") == "ultralytics" and family.get("installed")
        for family in installed.get("families", [])
    ))
    return {"available": available,
            "reason": None if available else installed.get("reason") or "SAM needs PyTorch and Ultralytics training support"}


def register_segmentation(app: Any, *, table_at: Any, jobs: Any, environment: Any, busy: Any, config: Any) -> None:
    @app.get("/api/annotations/segment/models")
    def models() -> dict[str, Any]:
        installed = sam_availability(environment())
        return {"available": installed["available"], "reason": installed.get("reason"),
                "models": [{"id": key, "name": name} for key, name in SAM_MODELS.items()]}

    @app.post("/api/annotations/segment")
    def segment(request: SegmentRequest) -> dict[str, Any]:
        source = table_at(request.table)
        if source.project_name != request.project or source.dataset_name != request.dataset:
            raise HTTPException(400, "choose an image in this dataset")
        paths = source.to_arrow().column(image_column(source)).to_pylist()
        if request.image not in paths:
            raise HTTPException(404, "the image is not in the selected table")
        if len(request.points) != len(request.labels) or (not request.box and not any(request.labels)):
            raise HTTPException(400, "provide a box or foreground point, with one label per point")
        row = paths.index(request.image)
        geometry = source.to_arrow().column(box_column(source))[row].as_py() or {}
        width, height = float(geometry.get("width") or 0), float(geometry.get("height") or 0)
        import math

        if width * height > 25_000_000 or min(width, height) <= 0:
            raise HTTPException(400, "interactive masks require known image dimensions up to 25 million pixels")
        if any(not math.isfinite(x) or not math.isfinite(y) or not 0 <= x <= width or not 0 <= y <= height for x, y in request.points):
            raise HTTPException(400, "prompt points must be inside the image")
        if request.box and (not all(math.isfinite(v) for v in request.box) or not 0 <= request.box[0] < request.box[2] <= width or not 0 <= request.box[1] < request.box[3] <= height):
            raise HTTPException(400, "prompt box must be inside the image")
        if not sam_availability(environment())["available"]:
            raise HTTPException(400, "install training support from the Training page to use SAM")
        if busy() is not None:
            raise HTTPException(409, "another model job is running; finish or cancel it first")
        from granum.cli.desktop import app_executable, running_appimage, training_dir
        from granum.processes import console_python

        name = "sam-" + uuid.uuid4().hex
        executable = [*app_executable(), "--python"] if running_appimage() else [console_python(sys.executable)]
        workdir = training_dir(Path(config.project_root.path))
        workdir.mkdir(parents=True, exist_ok=True)

        def work(job: Any) -> Any:
            # The log name is chosen by the worker supervisor; use its exact naming rule.
            import re

            root_key = re.sub(r"[^A-Za-z0-9]+", "_", str(config.project_root)).strip("_")[-60:]
            output = trainers.state_dir() / f"{root_key}-{name}.mask.json"
            command = [*trainers.trainer_prefix(executable, trainers.SEGMENT_MODULE), "--project-root", str(config.project_root),
                       "--table", str(source.url), "--row", str(row), "--model", request.model, "--output", str(output),
                       "--prompts", json.dumps({"box": request.box, "points": request.points, "labels": request.labels})]
            process, record = trainers.launch(command, cwd=workdir, project_root=str(config.project_root), project=request.project,
                                              run_name=name, rounds=1, module=trainers.SEGMENT_MODULE)
            return trainers.follow(job, record, process, finish_segment)

        job = jobs.start("segmentation", work)
        job.payload = request.project
        return job.to_dict()
