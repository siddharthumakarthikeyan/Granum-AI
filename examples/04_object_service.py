"""Stage 3 example: the Object Service, end to end.

Run it:  python examples/04_object_service.py

This is the Stage 3 client test from the build plan. It builds a project, starts the
service in-process, and exercises the API the dashboard will use -- including the two
things that decide whether Stage 4 is viable: does a write show up in the index without
a restart, and is an unchanged project actually free to poll.
"""

from __future__ import annotations

import io
import json
import tempfile
from pathlib import Path

import pyarrow as pa
from fastapi.testclient import TestClient
from PIL import Image

import granum
from granum import Table
from granum.core.index import Index
from granum.schemas import CategoricalLabelSchema, ImageSchema
from granum.service import thumbnails as thumbs
from granum.service.app import create_app

CLASSES = ["cat", "dog"]


def show(title: str, payload: object) -> None:
    text = json.dumps(payload, indent=2, default=str)
    if len(text) > 620:
        text = text[:620] + "\n  ... (truncated)"
    print(f"\n== {title} ==\n{text}")


def main() -> None:
    workdir = Path(tempfile.mkdtemp(prefix="granum-stage3-"))
    granum.set_config(
        granum.Config.load(
            overrides={"project-root-url": str(workdir / "granum")},
            use_config_files=False,
            use_env=False,
        )
    )

    # -- a small project with images, a revision, and a Run --------------
    images = workdir / "photos"
    images.mkdir()
    paths = []
    for i in range(6):
        target = images / f"{i}.png"
        Image.new("RGB", (640, 480), (30 + i * 30, 90, 160)).save(target)
        paths.append(str(target))

    table = Table.from_dict_data(
        {"image": paths, "label": [i % 2 for i in range(6)]},
        schema={"image": ImageSchema(sample_type="url"),
                "label": CategoricalLabelSchema(classes=CLASSES)},
        project_name="stage3-demo", dataset_name="photos", table_name="initial",
    )
    cleaned = table.delete_rows([5])

    run = granum.init("stage3-demo", "baseline", parameters={"lr": 0.01})
    run.add_metrics(
        {"example_id": list(range(6)), "loss": [0.2, 1.9, 0.3, 0.1, 2.6, 0.4]},
        foreign_table_url=table.url,
    )
    granum.log({"epoch": 0, "train_loss": 0.91})

    print(f"project root: {workdir / 'granum'}")
    print(f"  {len(table)} images, 1 revision, 1 run")

    # -- publish thumbnails ----------------------------------------------
    result = thumbs.create_for_table(table, sizes=(64, 128))
    print(f"\nthumbnails: {result['written']} written for {result['images']} images")

    # -- start the service -----------------------------------------------
    index = Index([granum.get_config().project_root])
    index.refresh()
    client = TestClient(create_app(index=index, config=granum.get_config(), allowed_hosts=["testserver"]))

    show("GET /api/health", client.get("/api/health").json())
    show("GET /api/projects", client.get("/api/projects").json())

    show(
        "GET /api/projects/stage3-demo/lineage",
        client.get("/api/projects/stage3-demo/lineage").json()["edges"],
    )

    show(
        "GET /api/table  (metadata + schema)",
        {
            k: v
            for k, v in client.get("/api/table", params={"url": str(table.url)}).json().items()
            if k in {"name", "row_count", "columns", "latest_revision"}
        },
    )

    show(
        "GET /api/table/rows?offset=1&limit=2",
        client.get("/api/table/rows",
                   params={"url": str(table.url), "offset": 1, "limit": 2}).json()["rows"],
    )

    # -- columnar rows, no JSON parse on the client -----------------------
    arrow_response = client.get("/api/table/arrow", params={"url": str(table.url)})
    with pa.ipc.open_stream(io.BytesIO(arrow_response.content)) as reader:
        arrow = reader.read_all()
    print(
        f"\n== GET /api/table/arrow ==\n  {arrow.num_rows} rows x {arrow.num_columns} columns "
        f"as Arrow IPC, {len(arrow_response.content)} bytes, columns {arrow.column_names}"
    )

    # -- the join, over HTTP ----------------------------------------------
    joined = client.get("/api/run/joined", params={"url": str(run.url)}).json()["rows"]
    worst = sorted(joined, key=lambda r: -r["loss"])[:3]
    print("\n== GET /api/run/joined  (worst 3 by loss) ==")
    for row in worst:
        print(f"  loss={row['loss']:.2f}  example_id={row['example_id']}  {row['image']}")

    # -- media, full and thumbnailed --------------------------------------
    full = client.get("/api/media", params={"url": paths[0]})
    small = client.get(
        "/api/media",
        params={"url": paths[0], "size": 64, "project": "stage3-demo", "dataset": "photos"},
    )
    print(
        f"\n== GET /api/media ==\n"
        f"  full size : {len(full.content):>7,} bytes\n"
        f"  thumbnail : {len(small.content):>7,} bytes  "
        f"({100 * len(small.content) / len(full.content):.1f}% of the original)"
    )

    # -- the guard ---------------------------------------------------------
    denied = client.get("/api/media", params={"url": "/etc/passwd"})
    print(f"\n== security ==\n  GET /api/media?url=/etc/passwd -> {denied.status_code} "
          f"{denied.json()['detail'][:60]}")

    # -- the two questions Stage 4 depends on ------------------------------
    print("\n== indexing behaviour ==")
    before = index.stats.locations_visited
    index.refresh()
    print(f"  unchanged project re-scan: {index.stats.locations_visited - before} "
          f"locations walked (skipped via change marker)")

    Table.from_dict_data({"image": paths[:2], "label": [0, 1]},
                         schema={"image": ImageSchema(sample_type="url"),
                                 "label": CategoricalLabelSchema(classes=CLASSES)},
                         project_name="stage3-demo", dataset_name="photos",
                         table_name="added-while-running")
    index.refresh()
    tables = client.get("/api/projects/stage3-demo/tables").json()["tables"]
    print(f"  after a write with the service live: {len(tables)} tables visible "
          f"-> {[t['name'] for t in tables]}")

    print(f"\nTo drive this from a browser or curl:\n"
          f"  granum --project-root-url {workdir / 'granum'} service\n")
    del cleaned


if __name__ == "__main__":
    main()
