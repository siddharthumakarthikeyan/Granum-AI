"""Reproducible synthetic CV workload; never touches an existing project.

Measures collection and API work, or serves the fixture for browser qualification.
Reported timings are not GPU-training overhead or a universal capacity certification.
"""
from __future__ import annotations

import argparse
import io
import json
import os
import platform
import resource
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import granum  # noqa: E402
from granum import BoundingBoxes2D, Table  # noqa: E402
from granum.core.index import Index  # noqa: E402
from granum.core.schemas import ImageSchema  # noqa: E402
from granum.service.app import create_app  # noqa: E402


def fixture(root: Path, images: int, epochs: int, boxes: int):
    from PIL import Image

    granum.set_config(granum.Config.load(overrides={"project-root-url": str(root)}, use_env=False, use_config_files=False))
    media = root / "media"
    media.mkdir()
    buffer = io.BytesIO()
    Image.new("RGB", (128, 128), (72, 101, 73)).save(buffer, format="PNG")
    paths = []
    for i in range(images):
        path = media / f"sample-{i:06d}.png"
        path.write_bytes(buffer.getvalue())
        paths.append(str(path))
    truth = {"width": 128, "height": 128, "instances": [
        {"vertices": [float(3 + i % 80), 4.0, float(20 + i % 80), 40.0], "label": i % 2} for i in range(boxes)
    ]}
    table = Table.from_dict_data({"image": paths, "bbs": [truth] * images},
                                schema={"image": ImageSchema(sample_type="url"), "bbs": BoundingBoxes2D.schema(["object", "other"])},
                                project_name="qualification", dataset_name="synthetic", table_name="train")
    predicted = {**truth, "instances": [{**instance, "confidence": 0.8} for instance in truth["instances"]]}
    timings = {}
    run = None
    for geometry in (False, True):
        name = "predictions" if geometry else "scores-only"
        run = granum.init("qualification", name, parameters={"tracks_learning": True})
        started = time.perf_counter()
        for epoch in range(epochs):
            data = {"example_id": list(range(images)), "epoch": [epoch] * images, "loss": [0.25] * images,
                    "tp": [boxes] * images, "fp": [0] * images, "fn": [0] * images, "f1": [1.0] * images}
            schema = {}
            if geometry:
                data["bbs_predicted"] = [predicted] * images
                data["gt_match"] = [list(range(boxes))] * images
                schema["bbs_predicted"] = BoundingBoxes2D.schema(["object", "other"], instance_properties={"confidence": "float32"})
            run.add_metrics(data, schema=schema, foreign_table_url=table.url, constants={"split": "train"})
        run.set_status("completed")
        timings[name] = {"seconds": round(time.perf_counter() - started, 4),
                         "bytes": sum(p.stat().st_size for p in Path(run.url.path).rglob("*.parquet"))}
    index = Index([root])
    start = time.perf_counter()
    index.refresh(force=True)
    timings["index_seconds"] = round(time.perf_counter() - start, 4)
    return create_app(index=index, config=granum.get_config(), allowed_hosts=["testserver"]), table, run, timings


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--images", type=int, default=1000)
    parser.add_argument("--epochs", type=int, default=6)
    parser.add_argument("--boxes", type=int, default=8)
    parser.add_argument("--serve", action="store_true")
    parser.add_argument("--port", type=int, default=18860)
    args = parser.parse_args()
    if not (1 <= args.images <= 100000 and 1 <= args.epochs <= 300 and 1 <= args.boxes <= 500):
        parser.error("images 1–100000, epochs 1–300, boxes 1–500")
    with tempfile.TemporaryDirectory(prefix="granum-qualification-") as temporary:
        app, table, run, timings = fixture(Path(temporary), args.images, args.epochs, args.boxes)
        if args.serve:
            import uvicorn

            uvicorn.run(app, host="127.0.0.1", port=args.port, log_level="warning")
            return
        from fastapi.testclient import TestClient

        api = TestClient(app)
        results = {}
        for name, endpoint, params in [
            ("images", "/api/images", {"project": "qualification", "dataset": "synthetic"}),
            ("table_page", "/api/table/rows", {"url": str(table.url), "limit": 5000}),
            ("joined_cold", "/api/run/joined", {"url": str(run.url), "limit": 5000}),
            ("joined_warm", "/api/run/joined", {"url": str(run.url), "limit": 5000}),
        ]:
            started = time.perf_counter()
            response = api.get(endpoint, params=params)
            results[name] = {"seconds": round(time.perf_counter() - started, 4), "status": response.status_code,
                             "json_bytes": len(response.content)}
        report = {"workload": {"images": args.images, "epochs": args.epochs, "boxes_per_image": args.boxes,
                               "metric_rows": args.images * args.epochs},
                  "environment": {"platform": platform.platform(), "python": platform.python_version(), "cpus": os.cpu_count(),
                                  "granum": granum.__version__}, "collection": timings, "api": results,
                  "process_peak_rss_mib": round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024, 2),
                  "scope": "synthetic, local filesystem; collection timings exclude model inference; RSS includes fixture construction"}
        print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()