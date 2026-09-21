import io
import json
from pathlib import Path

import pyarrow as pa
import pytest
from fastapi.testclient import TestClient

import granum
from granum import Table
from granum.core.index import Index
from granum.core.objects.run import set_active_run
from granum.core.schemas import CategoricalLabelSchema, ImageSchema
from granum.core.url import Url
from granum.service.app import create_app
from granum.service.cache import ByteCache


@pytest.fixture(autouse=True)
def clear_active_run():
    set_active_run(None)
    yield
    set_active_run(None)


@pytest.fixture
def client(isolated_project, tmp_path):
    images = tmp_path / "imgs"
    images.mkdir()
    paths = []
    for i in range(3):
        target = images / f"{i}.png"
        # a real 1x1 PNG so thumbnailing has something to decode
        target.write_bytes(bytes.fromhex(
            "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c4"
            "890000000a49444154789c6360000002000100fdff03fa0000000049454e44ae426082"
        ))
        paths.append(str(Url(target)))  # as the table stores it

    table = Table.from_dict_data(
        {"image": paths, "label": [0, 1, 0]},
        schema={"image": ImageSchema(sample_type="url"),
                "label": CategoricalLabelSchema(classes=["cat", "dog"])},
        project_name="demo", dataset_name="train", table_name="initial",
    )
    child = table.delete_rows([2])
    run = granum.init("demo", "exp", parameters={"lr": 0.1})
    run.add_metrics({"example_id": [0, 1, 2], "loss": [0.5, 2.0, 0.1]},
                    foreign_table_url=table.url)
    granum.log({"epoch": 0, "train_loss": 1.0})

    index = Index([isolated_project])
    index.refresh()
    app = create_app(index=index, config=granum.get_config(), cache=ByteCache(), allowed_hosts=["testserver"], data_roots=[str(tmp_path)], serve_dashboard=False)
    return TestClient(app), table, child, run, paths


# -- meta -------------------------------------------------------------------


def test_health(client):
    body = client[0].get("/api/health").json()
    assert body["status"] == "ok"
    assert body["objects"] >= 3


def test_stats_reports_index_and_cache(client):
    body = client[0].get("/api/stats").json()
    assert "index" in body and "cache" in body
    assert body["index"]["objects_found"] >= 3


def test_reindex(client):
    assert client[0].post("/api/reindex").json()["objects"] >= 3


# -- navigation -------------------------------------------------------------


def test_projects(client):
    projects = client[0].get("/api/projects").json()["projects"]
    assert [p["name"] for p in projects] == ["demo"]
    assert projects[0]["tables"] == 2
    assert projects[0]["runs"] == 1


def test_project_tables_and_runs(client):
    api = client[0]
    assert len(api.get("/api/projects/demo/tables").json()["tables"]) == 2
    runs = api.get("/api/projects/demo/runs").json()["runs"]
    assert len(runs) == 1
    assert runs[0]["parameters"] == {"lr": 0.1}
    assert runs[0]["last_metrics"] == {"epoch": 0, "train_loss": 1.0}


def test_lineage_graph(client):
    api, table, child, *_ = client
    body = api.get("/api/projects/demo/lineage").json()
    assert len(body["nodes"]) == 2
    assert {"from": str(table.url), "to": str(child.url)} in body["edges"]


# -- tables -----------------------------------------------------------------


def test_table_metadata(client):
    api, table, child, *_ = client
    body = api.get("/api/table", params={"url": str(table.url)}).json()
    assert body["row_count"] == 3
    assert [c["name"] for c in body["columns"]] == ["image", "label", "weight"]
    assert body["latest_revision"] == str(child.url)
    label = next(c for c in body["columns"] if c["name"] == "label")
    assert label["kind"] == "categorical_label" and label["writable"] is True


def test_table_rows_paginate(client):
    api, table, *_ = client
    body = api.get("/api/table/rows", params={"url": str(table.url), "offset": 1,
                                              "limit": 1}).json()
    assert body["total"] == 3
    assert len(body["rows"]) == 1
    assert body["rows"][0]["_row"] == 1
    assert body["rows"][0]["label"] == 1


def test_table_rows_rejects_oversized_page(client):
    api, table, *_ = client
    assert api.get("/api/table/rows",
                   params={"url": str(table.url), "limit": 99999}).status_code == 422


def test_table_arrow_stream(client):
    api, table, *_ = client
    response = api.get("/api/table/arrow", params={"url": str(table.url)})
    assert response.status_code == 200
    assert response.headers["content-type"] == "application/vnd.apache.arrow.stream"
    with pa.ipc.open_stream(io.BytesIO(response.content)) as reader:
        arrow = reader.read_all()
    assert arrow.num_rows == 3
    assert arrow.column_names == ["image", "label", "weight"]


def test_missing_table_is_404(client, isolated_project):
    api = client[0]
    missing = isolated_project / "projects" / "demo" / "datasets" / "train" / "tables" / "nope"
    assert api.get("/api/table", params={"url": str(missing)}).status_code == 404


# -- runs -------------------------------------------------------------------


def test_run_metadata(client):
    api, table, _, run, _ = client
    body = api.get("/api/run", params={"url": str(run.url)}).json()
    assert body["name"] == "exp"
    assert body["parameters"] == {"lr": 0.1}
    assert len(body["metrics_tables"]) == 1
    assert body["metrics_tables"][0]["foreign_table_url"] == str(table.url)
    assert body["aggregate_metrics"][0]["train_loss"] == 1.0


def test_run_joined_resolves_metrics_to_samples(client):
    api, _, _, run, paths = client
    body = api.get("/api/run/joined", params={"url": str(run.url)}).json()
    assert body["total"] == 3
    worst = max(body["rows"], key=lambda r: r["loss"])
    assert worst["example_id"] == 1
    assert worst["image"] == paths[1]


def test_run_joined_sees_metrics_added_after_first_read(client):
    """The join is cached; a new epoch's metrics table must still show up."""
    api, table, _, run, _ = client
    params = {"url": str(run.url)}
    assert api.get("/api/run/joined", params=params).json()["total"] == 3
    run.add_metrics({"example_id": [0, 1], "loss": [0.2, 0.3]}, foreign_table_url=table.url)
    assert api.get("/api/run/joined", params=params).json()["total"] == 5


# -- security ---------------------------------------------------------------


def test_table_outside_scan_roots_is_forbidden(client, tmp_path):
    api = client[0]
    outside = tmp_path / "elsewhere"
    outside.mkdir()
    response = api.get("/api/table", params={"url": str(outside)})
    assert response.status_code == 403
    assert "scan roots" in response.json()["detail"]


def test_media_refuses_unreferenced_files(client, tmp_path):
    """The endpoint must not become a file-read primitive."""
    api = client[0]
    secret = tmp_path / "secret.png"
    secret.write_bytes(b"not referenced by any table")
    response = api.get("/api/media", params={"url": str(secret)})
    assert response.status_code == 403


def test_media_refuses_etc_passwd(client):
    response = client[0].get("/api/media", params={"url": "/etc/passwd"})
    assert response.status_code == 403


# -- media ------------------------------------------------------------------


def test_media_serves_a_referenced_image(client):
    api, _, _, _, paths = client
    response = api.get("/api/media", params={"url": paths[0]})
    assert response.status_code == 200
    assert response.headers["content-type"] == "image/png"
    assert response.content.startswith(b"\x89PNG")


def test_media_is_cached(client):
    api, _, _, _, paths = client
    api.get("/api/media", params={"url": paths[0]})
    api.get("/api/media", params={"url": paths[0]})
    assert api.get("/api/stats").json()["cache"]["hits"] >= 1


# -- editing ----------------------------------------------------------------


def test_table_columns_describe_editability_and_classes(client):
    api, table, *_ = client
    columns = {c["name"]: c for c in api.get("/api/table", params={"url": str(table.url)}).json()["columns"]}
    assert columns["label"]["writable"] is True
    assert columns["label"]["value_map"]["1"]["internal_name"] == "dog"
    assert columns["image"]["writable"] is False
    assert columns["weight"]["writable"] is True


def test_commit_writes_one_revision_and_indexes_it(client):
    api, table, _, run, _ = client
    response = api.post("/api/table/commit", json={
        "url": str(table.url),
        "values": {"label": {"0": 1}, "weight": {"2": 0}, "note": {"1": "blurry"}},
        "new_columns": {"note": ["string", ""]},
        "value_maps": {"label": {"0": "cat", "1": "dog", "2": {"internal_name": "fox"}}},
        "name": "cleaned-v1",
        "description": "first pass",
    })
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["name"] == "cleaned-v1"
    assert body["parents"] == [str(table.url)]
    assert body["summary"]["cells"] == {"label": 1, "weight": 1, "note": 1}

    revision = Table.from_url(body["url"])
    assert revision[0]["label"] == 1 and revision[2]["weight"] == 0.0 and revision[1]["note"] == "blurry"
    assert table[0]["label"] == 0

    meta = api.get("/api/table", params={"url": str(table.url)}).json()
    assert meta["latest_revision"] == body["url"]
    nodes = api.get("/api/projects/demo/lineage").json()["edges"]
    assert {"from": str(table.url), "to": body["url"]} in [{"from": e["from"], "to": e["to"]} for e in nodes]


def test_run_view_joins_the_latest_revision_after_a_commit(client):
    api, table, _, run, _ = client
    before = api.get("/api/run/joined", params={"url": str(run.url)}).json()
    assert before["sources"] == [str(table.url)]
    assert [r["label"] for r in sorted(before["rows"], key=lambda r: r["example_id"])] == [0, 1, 0]

    committed = api.post("/api/table/commit", json={"url": str(table.url), "values": {"label": {"2": 1}}}).json()

    after = api.get("/api/run/joined", params={"url": str(run.url)}).json()
    assert after["sources"] == [committed["url"]]
    assert all(r["_src"] == 0 for r in after["rows"])
    assert [r["label"] for r in sorted(after["rows"], key=lambda r: r["example_id"])] == [0, 1, 1]
    # metrics are unchanged: they describe the model, not the labels
    assert sorted(r["loss"] for r in after["rows"]) == sorted(r["loss"] for r in before["rows"])

    meta = api.get("/api/run", params={"url": str(run.url)}).json()
    assert meta["inputs"][0]["collected_on"] == str(table.url)
    assert meta["inputs"][0]["joined"] == committed["url"]
    columns = {c["name"]: c for c in meta["columns"]}
    assert columns["label"]["writable"] and columns["label"]["source"] == "table"
    assert not columns["loss"]["writable"] and columns["loss"]["source"] == "metrics"


def test_commit_refuses_invalid_edits_with_a_reason(client):
    api, table, *_ = client
    response = api.post("/api/table/commit", json={"url": str(table.url), "values": {"label": {"0": 9}}})
    assert response.status_code == 400
    assert "not a class" in response.json()["detail"]
    response = api.post("/api/table/commit", json={"url": str(table.url), "values": {"image": {"0": "x"}}})
    assert response.status_code == 400 and "read-only" in response.json()["detail"]


def test_commit_refuses_metrics_tables_and_outside_roots(client, tmp_path):
    api, _, _, run, _ = client
    metrics_url = str(run.metrics_tables()[0].url)
    assert api.post("/api/table/commit", json={"url": metrics_url, "values": {"loss": {"0": 1}}}).status_code == 400
    assert api.post("/api/table/commit", json={"url": str(tmp_path), "values": {}}).status_code == 403


def test_box_columns_describe_classes_and_instance_properties(isolated_project):
    from granum import BoundingBoxes2D

    table = Table.from_dict_data(
        {"image": ["/x/a.png"], "bbs": [{"width": 10, "height": 10, "instances": [{"vertices": [0, 0, 1, 1], "label": 0, "confidence": 0.5}]}]},
        schema={"bbs": BoundingBoxes2D.schema(["cat"], instance_properties={"confidence": "float32"})},
        project_name="demo", dataset_name="det",
    )
    index = Index([isolated_project])
    index.refresh()
    api = TestClient(create_app(index=index, config=granum.get_config(), cache=ByteCache(), allowed_hosts=["testserver"]))
    columns = {c["name"]: c for c in api.get("/api/table", params={"url": str(table.url)}).json()["columns"]}
    assert columns["bbs"]["kind"] == "bounding_boxes_2d"
    assert columns["bbs"]["writable"] is True
    assert columns["bbs"]["value_map"]["0"]["internal_name"] == "cat"
    assert columns["bbs"]["instance_properties"] == {"confidence": "float32"}
    row = api.get("/api/table/rows", params={"url": str(table.url)}).json()["rows"][0]
    assert row["bbs"]["instances"][0]["vertices"] == [0, 0, 1, 1]


# -- provenance: collected versus displayed revision ----------------------------


def test_run_view_shows_the_label_metrics_were_collected_with(client):
    api, table, _, run, _ = client
    api.post("/api/table/commit", json={"url": str(table.url), "values": {"label": {"2": 1}}})
    meta = api.get("/api/run", params={"url": str(run.url)}).json()
    assert meta["inputs"][0]["changed_columns"] == ["label"]
    collected = {c["name"]: c for c in meta["columns"]}["label@collected"]
    assert collected["writable"] is False and collected["collected_of"] == "label"
    rows = sorted(api.get("/api/run/joined", params={"url": str(run.url)}).json()["rows"], key=lambda r: r["example_id"])
    assert [r["label"] for r in rows] == [0, 1, 1]
    assert [r["label@collected"] for r in rows] == [0, 1, 0]


def test_run_view_never_joins_through_a_row_changing_revision(client):
    """Golden identity check: equal length is not proof that rows line up."""
    api, table, _, run, _ = client
    # Same length, but produced by an operation that is allowed to drop and reorder rows.
    refiltered = table.filter(lambda row: True)
    refiltered.set_values("label", {0: 1})  # a newer, deeper descendant
    api.post("/api/reindex")
    meta = api.get("/api/run", params={"url": str(run.url)}).json()
    assert meta["inputs"][0]["joined"] == str(table.url)
    assert "filter" in (meta["inputs"][0]["newer_revision_skipped"] or "")
    rows = api.get("/api/run/joined", params={"url": str(run.url)}).json()["rows"]
    assert sorted(r["label"] for r in rows) == [0, 0, 1]
    assert all("label@collected" not in r for r in rows)


def test_metrics_rows_resolve_to_the_same_images_after_edits(client):
    """Golden identity check: an edit must not move any metric onto another image."""
    api, table, _, run, paths = client
    before = {r["example_id"]: r["image"] for r in api.get("/api/run/joined", params={"url": str(run.url)}).json()["rows"]}
    api.post("/api/table/commit", json={"url": str(table.url), "values": {"label": {"0": 1, "1": 0}}, "new_columns": {"note": ["string", ""]}})
    after = {r["example_id"]: r["image"] for r in api.get("/api/run/joined", params={"url": str(run.url)}).json()["rows"]}
    assert before == after == {0: paths[0], 1: paths[1], 2: paths[2]}


# -- local access ---------------------------------------------------------------


def test_unknown_host_is_refused(client):
    """DNS rebinding: a page on evil.example resolving to 127.0.0.1 sends its own Host."""
    response = client[0].get("/api/projects", headers={"host": "evil.example:8000"})
    assert response.status_code == 403


def test_cross_origin_requests_are_refused(client):
    api, table, *_ = client
    response = api.get("/api/projects", headers={"origin": "https://evil.example"})
    assert response.status_code == 403
    assert "access-control-allow-origin" not in response.headers
    response = api.post("/api/table/commit", json={"url": str(table.url), "values": {}},
                        headers={"origin": "https://evil.example"})
    assert response.status_code == 403
    assert api.get("/api/projects", headers={"origin": "null"}).status_code == 403


def test_same_origin_requests_are_allowed(client):
    api = client[0]
    assert api.get("/api/projects", headers={"origin": "http://testserver"}).status_code == 200


def test_writes_must_be_json(client):
    """A cross-site form post uses text/plain or form encoding and never triggers CORS."""
    api, table, *_ = client
    response = api.post("/api/table/commit", content=json.dumps({"url": str(table.url)}),
                        headers={"content-type": "text/plain"})
    assert response.status_code == 415


def test_allowed_origin_gets_cors_headers(isolated_project):
    index = Index([isolated_project])
    api = TestClient(create_app(index=index, config=granum.get_config(), allowed_hosts=["testserver"],
                                allowed_origins=["http://localhost:5173"], serve_dashboard=False))
    response = api.get("/api/health", headers={"origin": "http://localhost:5173"})
    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "http://localhost:5173"


# -- import ---------------------------------------------------------------------


def _wait(api, job):
    import time

    for _ in range(200):
        body = api.get(f"/api/jobs/{job['id']}").json()
        if body["status"] != "running":
            return body
        time.sleep(0.02)
    raise AssertionError("job did not finish")


def _dataset(tmp_path):
    from PIL import Image

    folder = tmp_path / "shop" / "train"
    folder.mkdir(parents=True)
    Image.new("RGB", (40, 30)).save(folder / "a.jpg")
    Image.new("RGB", (40, 30), (9, 9, 9)).save(folder / "b.jpg")
    (folder / "_annotations.coco.json").write_text(json.dumps({
        "images": [{"id": 1, "file_name": "a.jpg", "width": 40, "height": 30},
                   {"id": 2, "file_name": "b.jpg", "width": 40, "height": 30}],
        "annotations": [{"id": 1, "image_id": 1, "category_id": 1, "bbox": [1, 1, 10, 10]},
                        {"id": 2, "image_id": 1, "category_id": 1, "bbox": [1, 1, 0, 10]}],
        "categories": [{"id": 1, "name": "can"}],
    }))
    return folder


def test_import_flow_browse_preflight_commit(client, tmp_path):
    api = client[0]
    folder = _dataset(tmp_path)

    browsed = api.get("/api/import/browse", params={"path": str(folder.parent)}).json()
    assert browsed["detected"] == [{"split": "train", "annotations": str(Url(folder / "_annotations.coco.json")), "images": str(Url(folder))}]

    # Opening one split folder still finds every split of the dataset beside it.
    valid = folder.parent / "valid"
    valid.mkdir()
    (valid / "_annotations.coco.json").write_text((folder / "_annotations.coco.json").read_text())
    inside = api.get("/api/import/browse", params={"path": str(folder)}).json()
    assert [d["split"] for d in inside["detected"]] == ["train", "valid"]

    job = api.post("/api/import/preflight", json={"sources": browsed["detected"], "media": "full"}).json()
    done = _wait(api, job)
    assert done["status"] == "done", done
    codes = {f["code"]: f for f in done["result"]["findings"]}
    assert codes["annotations.zero_area"]["default"] == "drop"

    # The report's example images can be previewed before anything is imported.
    example = codes["annotations.zero_area"]["examples"][0]["image"]
    assert api.get("/api/media", params={"url": example, "size": 64}).status_code == 200

    commit = api.post("/api/import/commit", json={"preflight_job": job["id"], "project_name": "shop",
                                                   "resolutions": {"images.unannotated": "exclude"}}).json()
    finished = _wait(api, commit)
    assert finished["status"] == "done", finished
    table_url = finished["result"]["tables"][0]["url"]
    assert finished["result"]["effects"]["boxes_dropped_zero_area"] == 1

    tables = api.get("/api/projects/shop/tables").json()["tables"]
    assert tables[0]["url"] == table_url and tables[0]["preflight"]["verdict"] == "warn"
    imports = api.get("/api/projects/shop/imports").json()["imports"]
    assert imports[0]["resolutions"]["images.unannotated"] == "exclude"
    again = api.post("/api/import/commit", json={"preflight_job": job["id"], "project_name": "shop"})
    assert again.status_code == 409


def test_import_is_confined_to_data_roots(client, tmp_path):
    api = client[0]
    assert api.get("/api/import/browse", params={"path": "/etc"}).status_code == 403
    response = api.post("/api/import/preflight", json={"sources": [{"split": "train", "annotations": "/etc/passwd"}]})
    assert response.status_code == 403
    assert api.get("/api/import/browse", params={"path": str(tmp_path / ".." )}).status_code == 403


def test_import_rejects_bad_choices_before_starting(client, tmp_path):
    api = client[0]
    folder = _dataset(tmp_path)
    job = api.post("/api/import/preflight", json={"sources": [{"split": "train", "annotations": str(folder / "_annotations.coco.json")}]}).json()
    _wait(api, job)
    response = api.post("/api/import/commit", json={"preflight_job": job["id"], "project_name": "shop",
                                                     "resolutions": {"annotations.zero_area": "maybe"}})
    assert response.status_code == 400 and "choose one of" in response.json()["detail"]


# -- deleting projects --------------------------------------------------------------


def test_delete_project_removes_its_data_and_training_output(client, isolated_project):
    api, table, _, run, paths = client
    work = isolated_project.parent / "granum-training"
    weights = work / "runs" / run.name / "weights" / "best.pt"
    weights.parent.mkdir(parents=True)
    weights.write_bytes(b"weights")
    (work / "exports" / run.name).mkdir(parents=True)
    run.set_parameters({"weights": str(weights)})
    other = work / "runs" / "someone-elses-run"
    other.mkdir(parents=True)

    assert api.post("/api/projects/demo/delete", json={"confirm": "Demo"}).status_code == 400
    assert api.post("/api/projects/nope/delete", json={"confirm": "nope"}).status_code == 404
    assert any(p["name"] == "demo" for p in api.get("/api/projects").json()["projects"])

    done = api.post("/api/projects/demo/delete", json={"confirm": "demo"})
    assert done.status_code == 200, done.text
    assert done.json()["tables"] >= 2 and done.json()["runs"] == 1
    assert not (isolated_project / "projects" / "demo").exists()
    assert all(p["name"] != "demo" for p in api.get("/api/projects").json()["projects"])
    assert api.get("/api/projects/demo/tables").json()["tables"] == []
    assert not (work / "runs" / run.name).exists() and not (work / "exports" / run.name).exists()
    # Other runs' output and the original images are untouched.
    assert other.is_dir() and all(Path(p).exists() for p in paths)


def test_rename_project_through_the_service(client, isolated_project):
    api, table, child, run, _ = client
    assert api.post("/api/projects/demo/rename", json={"new_name": "../x"}).status_code == 400
    assert api.post("/api/projects/nope/rename", json={"new_name": "x"}).status_code == 404
    done = api.post("/api/projects/demo/rename", json={"new_name": "demo renamed"})
    assert done.status_code == 200, done.text
    names = [p["name"] for p in api.get("/api/projects").json()["projects"]]
    assert "demo renamed" in names and "demo" not in names
    tables = api.get("/api/projects/demo renamed/tables").json()["tables"]
    assert len(tables) >= 2 and all("/projects/demo renamed/" in t["url"] for t in tables)
    runs = api.get("/api/projects/demo renamed/runs").json()["runs"]
    joined = api.get("/api/run/joined", params={"url": runs[0]["url"]})
    assert joined.status_code == 200, joined.text


# -- annotation review and shipping ------------------------------------------------


def test_review_statuses_comments_and_shipping(client):
    api, table, child, _, paths = client
    base = {"project": "demo", "dataset": "train"}

    overview = api.get("/api/qa", params=base).json()
    [only] = overview["sets"]
    assert only["url"] == str(child.url) and [i["image"] for i in only["images"]] == paths[:2]
    assert only["counts"] == {"unreviewed": 2, "reviewed": 0, "rework": 0}
    assert overview["ready"] is False and overview["shipments"] == []

    # Rework needs a reason; with one, it starts the image's thread.
    assert api.post("/api/qa/status", json={**base, "samples": [paths[0]], "status": "rework"}).status_code == 400
    sent = api.post("/api/qa/status", json={**base, "samples": [paths[0]], "status": "rework", "comment": "box too loose", "author": "ana"}).json()
    assert sent["statuses"][paths[0]]["status"] == "rework"
    api.post("/api/qa/comment", json={**base, "sample": paths[0], "comment": "fixed", "author": "raj"})
    image = api.get("/api/qa/image", params={**base, "table": str(child.url), "image": paths[0]}).json()
    assert [(e["author"], e["status"], e["comment"]) for e in image["thread"]] == [("ana", "rework", "box too loose"), ("raj", None, "fixed")]

    # Nothing ships, and nothing trains, until every image is reviewed.
    assert api.post("/api/qa/ship", json=base).status_code == 409
    api.post("/api/qa/status", json={**base, "samples": paths[:2], "status": "reviewed", "author": "ana"})
    overview = api.get("/api/qa", params=base).json()
    assert overview["ready"] and overview["statuses"][paths[0]]["comments"] == 2
    shipment = api.post("/api/qa/ship", json={**base, "author": "ana", "note": "v1"}).json()["shipment"]
    assert shipment["sets"]["initial"] == {"url": str(child.url), "name": child.name, "images": 2}
    overview = api.get("/api/qa", params=base).json()
    assert overview["up_to_date"] and overview["shipments"][0]["id"] == shipment["id"]
    assert api.get("/api/training/status", params={"project": "demo"}).json()["shipped"] == [str(child.url)]

    assert api.post("/api/qa/status", json={**base, "samples": [paths[0]], "status": "done"}).status_code == 400
    assert api.get("/api/qa", params={**base, "dataset": "nope"}).status_code == 404


def test_ship_any_version_of_any_set(client):
    api, table, child, _, paths = client
    base = {"project": "demo", "dataset": "train"}
    overview = api.get("/api/qa", params=base).json()
    [initial] = overview["sets"]
    assert [v["url"] for v in initial["versions"]] == [str(child.url), str(table.url)]
    assert initial["ready"] is False and initial["shipped"] is False

    # The earlier, three-image version can ship on its own once its images are reviewed.
    older = api.get("/api/qa/version", params={**base, "table": str(table.url)}).json()
    assert older["images"] == 3 and older["ready"] is False
    api.post("/api/qa/status", json={**base, "samples": paths, "status": "reviewed"})
    assert api.get("/api/qa/version", params={**base, "table": str(table.url)}).json()["ready"] is True
    shipped = api.post("/api/qa/ship", json={**base, "sets": {"initial": str(table.url)}, "note": "full"})
    assert shipped.status_code == 200, shipped.text
    overview = api.get("/api/qa", params=base).json()
    assert overview["up_to_date"] is False and overview["sets"][0]["shipped"] is False
    assert [v["shipped"] for v in overview["sets"][0]["versions"]] == [False, True]

    # Then the newest version too; both stay available for training.
    assert api.post("/api/qa/ship", json={**base, "sets": {"initial": str(child.url)}}).status_code == 200
    assert api.get("/api/qa", params=base).json()["up_to_date"] is True
    assert set(api.get("/api/training/status", params={"project": "demo"}).json()["shipped"]) == {str(table.url), str(child.url)}

    assert api.post("/api/qa/ship", json={**base, "sets": {"initial": str(child.url)}}).status_code == 409
    assert api.post("/api/qa/ship", json={**base, "sets": {}}).status_code == 400
    assert api.post("/api/qa/ship", json={**base, "sets": {"nope": str(child.url)}}).status_code == 400


def test_ship_one_set_while_another_is_still_in_review(client, tmp_path):
    api = client[0]
    folder = _dataset(tmp_path)
    valid = folder.parent / "valid"
    valid.mkdir()
    for f in folder.iterdir():
        (valid / f.name).write_bytes(f.read_bytes())
    sources = [{"split": "train", "annotations": str(folder / "_annotations.coco.json")},
               {"split": "valid", "annotations": str(valid / "_annotations.coco.json")}]
    job = api.post("/api/import/preflight", json={"sources": sources, "media": "none"}).json()
    _wait(api, job)
    _wait(api, api.post("/api/import/commit", json={"preflight_job": job["id"], "project_name": "shop"}).json())
    [dataset] = {t["dataset_name"] for t in api.get("/api/projects/shop/tables").json()["tables"]}
    base = {"project": "shop", "dataset": dataset}
    sets = {s["set"]: s for s in api.get("/api/qa", params=base).json()["sets"]}
    train_images = [i["image"] for i in sets["train"]["images"]]
    api.post("/api/qa/status", json={**base, "samples": train_images, "status": "reviewed"})
    # valid shares file names but not paths, so it is still unreviewed.
    assert api.post("/api/qa/ship", json=base).status_code == 409
    done = api.post("/api/qa/ship", json={**base, "sets": {"train": sets["train"]["url"]}})
    assert done.status_code == 200, done.text
    after = {s["set"]: s for s in api.get("/api/qa", params=base).json()["sets"]}
    assert after["train"]["shipped"] and not after["valid"]["shipped"]


def test_import_records_the_tasks(client, tmp_path):
    api = client[0]
    folder = _dataset(tmp_path)
    job = api.post("/api/import/preflight", json={"sources": [{"split": "train", "annotations": str(folder / "_annotations.coco.json")}], "media": "none"}).json()
    report = _wait(api, job)["result"]
    assert report["summary"]["task"]["detected"] == "object_detection"
    bad = api.post("/api/import/commit", json={"preflight_job": job["id"], "project_name": "shop", "tasks": ["painting"]})
    assert bad.status_code == 400
    chosen = ["instance_segmentation", "object_detection"]
    done = _wait(api, api.post("/api/import/commit", json={"preflight_job": job["id"], "project_name": "shop", "tasks": chosen}).json())
    assert done["result"]["tasks"] == ["object_detection", "instance_segmentation"]
    tables = api.get("/api/projects/shop/tables").json()["tables"]
    assert tables and all(t["tasks"] == ["object_detection", "instance_segmentation"] for t in tables)


def test_create_dataset_versions_all_or_verified_only(client, tmp_path):
    api = client[0]
    folder = _dataset(tmp_path)
    job = api.post("/api/import/preflight", json={"sources": [{"split": "train", "annotations": str(folder / "_annotations.coco.json")}], "media": "none"}).json()
    _wait(api, job)
    _wait(api, api.post("/api/import/commit", json={"preflight_job": job["id"], "project_name": "shop"}).json())
    [dataset] = {t["dataset_name"] for t in api.get("/api/projects/shop/tables").json()["tables"]}
    base = {"project": "shop", "dataset": dataset}
    [train] = api.get("/api/qa", params=base).json()["sets"]
    images = [i["image"] for i in train["images"]]

    # Nothing verified: only the whole dataset can be taken.
    assert api.post("/api/qa/release", json={**base, "name": "v0", "mode": "verified"}).status_code == 409
    assert api.post("/api/qa/release", json={**base, "name": " ", "mode": "all"}).status_code == 400
    whole = api.post("/api/qa/release", json={**base, "name": "Everything", "description": "first cut", "mode": "all"})
    assert whole.status_code == 200, whole.text
    assert whole.json()["release"]["sets"]["train"] == {"url": train["url"], "name": train["name"], "images": 2, "verified": 0}
    assert api.post("/api/qa/release", json={**base, "name": "everything", "mode": "all"}).status_code == 409

    # Verified only freezes a copy of the verified images; the working set is untouched.
    api.post("/api/qa/status", json={**base, "samples": [images[0]], "status": "reviewed"})
    done = api.post("/api/qa/release", json={**base, "name": "Clean", "mode": "verified"}).json()["release"]
    frozen = done["sets"]["train"]
    assert frozen["images"] == 1 and frozen["url"] != train["url"] and done["version"] == 2
    [still] = api.get("/api/qa", params=base).json()["sets"]
    assert still["url"] == train["url"] and len(still["images"]) == 2
    listed = api.get("/api/releases", params={"project": "shop"}).json()["releases"]
    assert [r["name"] for r in listed] == ["Clean", "Everything"] and listed[0]["dataset"] == dataset
    assert set(api.get("/api/training/status", params={"project": "shop"}).json()["shipped"]) == {train["url"], frozen["url"]}


def test_review_isolate_return_delete_and_edit_boxes(client, tmp_path):
    api = client[0]
    folder = _dataset(tmp_path)
    job = api.post("/api/import/preflight", json={"sources": [{"split": "train", "annotations": str(folder / "_annotations.coco.json")}], "media": "none"}).json()
    _wait(api, job)
    _wait(api, api.post("/api/import/commit", json={"preflight_job": job["id"], "project_name": "shop"}).json())
    [dataset] = {t["dataset_name"] for t in api.get("/api/projects/shop/tables").json()["tables"]}
    base = {"project": "shop", "dataset": dataset}
    overview = api.get("/api/qa", params=base).json()
    [train] = overview["sets"]
    images = [i["image"] for i in train["images"]]
    assert overview["isolated"] is None and len(images) == 2

    # Isolating sets an image aside: the set and shipping no longer include it.
    moved = api.post("/api/qa/isolate", json={**base, "table": train["url"], "samples": [images[1]], "reason": "unclear", "author": "ana"})
    assert moved.status_code == 200, moved.text
    stale = api.post("/api/qa/isolate", json={**base, "table": train["url"], "samples": [images[0]]})
    assert stale.status_code == 409
    overview = api.get("/api/qa", params=base).json()
    [train] = overview["sets"]
    assert [i["image"] for i in train["images"]] == images[:1]
    assert [(i["image"], i["from"], i["reason"]) for i in overview["isolated"]["images"]] == [(images[1], "train", "unclear")]
    api.post("/api/qa/status", json={**base, "samples": images[:1], "status": "reviewed"})
    assert api.get("/api/qa", params=base).json()["ready"] is True

    # Boxes are edited through a commit of the box column, one version per save.
    detail = api.get("/api/qa/image", params={**base, "table": train["url"], "image": images[0]}).json()
    assert detail["editable"] and detail["box_column"]
    value = {"width": detail["width"], "height": detail["height"],
             "instances": detail["boxes"] + [{"vertices": [2, 2, 20, 20], "label": detail["boxes"][0]["label"], "iscrowd": False}]}
    saved = api.post("/api/table/commit", json={"url": train["url"], "values": {detail["box_column"]: {str(detail["row"]): value}}})
    assert saved.status_code == 200, saved.text
    edited = api.get("/api/qa/image", params={**base, "table": saved.json()["url"], "image": images[0]}).json()
    assert len(edited["boxes"]) == len(detail["boxes"]) + 1

    # Returning puts the image back into the newest version of its set.
    back = api.post("/api/qa/return", json={**base, "samples": [images[1]], "author": "ana"})
    assert back.status_code == 200, back.text
    overview = api.get("/api/qa", params=base).json()
    [train] = overview["sets"]
    assert sorted(i["image"] for i in train["images"]) == sorted(images) and overview["isolated"] is None
    thread = api.get("/api/qa/image", params={**base, "table": train["url"], "image": images[1]}).json()["thread"]
    assert [e["comment"] for e in thread] == ["Isolated from train: unclear", "Returned from isolation"]

    # Deleting moves it to the removed set, out of review.
    gone = api.post("/api/qa/delete", json={**base, "table": train["url"], "samples": [images[1]]})
    assert gone.status_code == 200, gone.text
    overview = api.get("/api/qa", params=base).json()
    assert [i["image"] for i in overview["sets"][0]["images"]] == images[:1]
    assert [i["image"] for i in api.get("/api/datasets/removed", params=base).json()["images"]] == [images[1]]


# -- training -------------------------------------------------------------------


def test_training_refuses_bad_requests_before_starting(client, monkeypatch):
    api, table, child, run, _ = client
    status = api.get("/api/training/status", params={"project": "demo"}).json()
    assert "available" in status and status["running_job"] is None
    assert status["installable"] is (not status["available"]) and status["install_size"] and status["install_job"] is None
    if status["available"]:
        assert api.post("/api/training/install", json={}).status_code == 409
    if not status["available"]:
        response = api.post("/api/training", json={"project": "demo", "train_table": str(table.url), "valid_table": str(child.url)})
        assert response.status_code == 400
        return
    base = {"project": "demo", "train_table": str(table.url), "valid_table": str(child.url)}
    assert api.post("/api/training", json={**base, "valid_table": str(table.url)}).status_code == 400
    assert api.post("/api/training", json={**base, "train_table": "/etc"}).status_code == 403
    assert api.post("/api/training", json={**base, "family": "huge"}).status_code == 400
    assert api.post("/api/training", json={**base, "version": "yolo99z.pt"}).status_code == 400
    assert api.post("/api/training", json={**base, "rounds": 0}).status_code == 422
    assert api.post("/api/training", json={**base, "compare_with": "nope"}).status_code == 404
    assert api.post("/api/training", json={**base, "run_name": "../../x"}).status_code == 400
    assert api.post("/api/training", json={**base, "test_table": str(child.url)}).status_code == 400
    assert api.post("/api/training", json={**base, "test_table": "/etc"}).status_code == 403


def test_pull_images_from_existing_projects_by_class(client, tmp_path):
    import json as _json

    from PIL import Image

    api = client[0]
    folder = tmp_path / "zoo" / "train"
    folder.mkdir(parents=True)
    for name in ("a.jpg", "b.jpg", "c.jpg"):
        Image.new("RGB", (40, 30)).save(folder / name)
    (folder / "_annotations.coco.json").write_text(_json.dumps({
        "images": [{"id": i, "file_name": n, "width": 40, "height": 30} for i, n in enumerate(("a.jpg", "b.jpg", "c.jpg"), 1)],
        "annotations": [{"id": 1, "image_id": 1, "category_id": 1, "bbox": [1, 1, 10, 10]},
                        {"id": 2, "image_id": 1, "category_id": 2, "bbox": [5, 5, 10, 10]},
                        {"id": 3, "image_id": 2, "category_id": 2, "bbox": [2, 2, 8, 8]}],
        "categories": [{"id": 1, "name": "Cat"}, {"id": 2, "name": "dog"}],
    }))
    job = api.post("/api/import/preflight", json={"sources": [{"split": "train", "annotations": str(folder / "_annotations.coco.json")}], "media": "none"}).json()
    _wait(api, job)
    _wait(api, api.post("/api/import/commit", json={"preflight_job": job["id"], "project_name": "zoo"}).json())

    library = api.get("/api/library").json()
    zoo = next(p for p in library["projects"] if p["name"] == "zoo")
    assert {c["key"]: c["images"] for c in zoo["classes"]} == {"cat": 1, "dog": 2}
    assert any(c["key"] == "cat" and "zoo" in c["projects"] for c in library["classes"])

    # Only images with a cat, and only their cat boxes.
    pulled = api.post("/api/library/pull", json={"selection": {"zoo": ["cat"]}})
    assert pulled.status_code == 200, pulled.text
    body = pulled.json()
    assert body["images"] == 1 and body["boxes"] == 1
    [source] = body["sources"]
    coco = _json.loads(open(source["annotations"]).read())
    assert [c["name"] for c in coco["categories"]] == ["Cat"] and coco["images"][0]["file_name"] == "a.jpg"

    # The pulled files go through preflight like any other source.
    job = api.post("/api/import/preflight", json={"sources": [{"split": s["split"], "annotations": s["annotations"], "images": s["images"]} for s in body["sources"]], "media": "full"}).json()
    report = _wait(api, job)
    assert report["status"] == "done" and report["result"]["summary"]["images"] == 1

    everything = api.post("/api/library/pull", json={"selection": {"zoo": ["dog"]}, "keep_other_labels": True}).json()
    assert everything["images"] == 2 and everything["boxes"] == 3
    assert api.post("/api/library/pull", json={"selection": {"zoo": ["zebra"]}}).status_code == 409
    assert api.post("/api/library/pull", json={"selection": {"nope": []}}).status_code == 404
    assert api.post("/api/library/pull", json={"selection": {}}).status_code == 422
    # An empty class list takes every image of the project, unlabelled ones too.
    assert api.post("/api/library/pull", json={"selection": {"zoo": []}}).json()["images"] == 3


def test_editor_saves_masks_keypoints_and_new_classes_on_a_box_dataset(client, tmp_path):
    import json as _json

    api = client[0]
    folder = _dataset(tmp_path)
    job = api.post("/api/import/preflight", json={"sources": [{"split": "train", "annotations": str(folder / "_annotations.coco.json")}], "media": "none"}).json()
    _wait(api, job)
    _wait(api, api.post("/api/import/commit", json={"preflight_job": job["id"], "project_name": "shop"}).json())
    [dataset] = {t["dataset_name"] for t in api.get("/api/projects/shop/tables").json()["tables"]}
    [train] = api.get("/api/qa", params={"project": "shop", "dataset": dataset}).json()["sets"]
    image = train["images"][0]["image"]
    detail = api.get("/api/qa/image", params={"project": "shop", "dataset": dataset, "table": train["url"], "image": image}).json()
    column = detail["box_column"]

    # A mask and keypoints on a box-only dataset, drawn with a class that did not exist.
    labels = {**detail["labels"], "9": "bottle"}
    instance = {"vertices": [2, 2, 12, 12], "label": 9, "iscrowd": False, "area": 50.0,
                "segmentation": _json.dumps([[2, 2, 12, 2, 12, 12]]),
                "coco_extra": _json.dumps({"keypoints": [5, 5, 2], "num_keypoints": 1})}
    value = {"width": detail["width"], "height": detail["height"], "instances": [*detail["boxes"], instance]}
    refused = api.post("/api/table/commit", json={"url": detail["table"], "values": {column: {str(detail["row"]): value}}})
    assert refused.status_code == 400 and "undeclared" in refused.text
    saved = api.post("/api/table/commit", json={
        "url": detail["table"], "values": {column: {str(detail["row"]): value}},
        "value_maps": {column: labels}, "instance_properties": {column: {"segmentation": "string", "coco_extra": "string"}},
    })
    assert saved.status_code == 200, saved.text
    after = api.get("/api/qa/image", params={"project": "shop", "dataset": dataset, "table": saved.json()["url"], "image": image}).json()
    assert after["labels"]["9"] == "bottle"
    drawn = after["boxes"][-1]
    assert _json.loads(drawn["segmentation"]) == [[2, 2, 12, 2, 12, 12]] and _json.loads(drawn["coco_extra"])["keypoints"] == [5, 5, 2]
    # Other instances gain the new properties, empty; a class in use cannot be removed.
    assert after["boxes"][0]["segmentation"] is None
    gone = api.post("/api/table/commit", json={"url": saved.json()["url"], "value_maps": {column: detail["labels"]}})
    assert gone.status_code == 400 and "removed class" in gone.text


def test_projects_summary_for_the_projects_page(client, tmp_path):
    api = client[0]
    folder = _dataset(tmp_path)
    job = api.post("/api/import/preflight", json={"sources": [{"split": "train", "annotations": str(folder / "_annotations.coco.json")}], "media": "none"}).json()
    _wait(api, job)
    _wait(api, api.post("/api/import/commit", json={"preflight_job": job["id"], "project_name": "shop", "tasks": ["object_detection"]}).json())
    [dataset] = {t["dataset_name"] for t in api.get("/api/projects/shop/tables").json()["tables"]}
    [train] = api.get("/api/qa", params={"project": "shop", "dataset": dataset}).json()["sets"]
    api.post("/api/qa/status", json={"project": "shop", "dataset": dataset, "samples": [train["images"][0]["image"]], "status": "reviewed"})
    api.post("/api/qa/release", json={"project": "shop", "dataset": dataset, "name": "v1", "mode": "all"})
    projects = {p["name"]: p for p in api.get("/api/projects/summary").json()["projects"]}
    shop = projects["shop"]
    assert shop["tasks"] == ["object_detection"] and shop["images"] == 2 and shop["verified"] == 1
    assert shop["versions"] == 1 and shop["classes"] == 1 and shop["sets"] == ["train"]
    assert len(shop["covers"]) == 2 and shop["updated"]


def test_dataset_version_with_augmented_train_copies(client, tmp_path):
    import json as _json
    from pathlib import Path as _Path

    api = client[0]
    folder = _dataset(tmp_path)
    job = api.post("/api/import/preflight", json={"sources": [{"split": "train", "annotations": str(folder / "_annotations.coco.json")}], "media": "none"}).json()
    _wait(api, job)
    _wait(api, api.post("/api/import/commit", json={"preflight_job": job["id"], "project_name": "aug", "tasks": ["object_detection"]}).json())
    [dataset] = {t["dataset_name"] for t in api.get("/api/projects/aug/tables").json()["tables"]}
    recipe = {"copies": 3, "flip": {"horizontal": True}, "rotation": {"min": -10, "max": 10}, "brightness": {"min": -20, "max": 20}}

    shown = api.post("/api/augment/examples", json={"project": "aug", "dataset": dataset, "items": {
        "rotation:min": {"recipe": {"rotation": {"min": -10, "max": 10}}, "at": "min"},
        "flip": {"recipe": {"flip": {"horizontal": True}}},
    }})
    assert shown.status_code == 200, shown.text
    shown = shown.json()
    assert set(shown["items"]) == {"rotation:min", "flip"} and shown["original"]["boxes"]
    assert shown["set"] == "train" and shown["bytes_per_image"] > 0
    assert shown["items"]["flip"]["image"].startswith("data:image/jpeg;base64,")
    # The flip is certain at a fixed end: the kept box mirrors across the 40 px wide image.
    [box] = [b["box"] for b in shown["original"]["boxes"] if b["box"][2] - b["box"][0] >= 1]
    assert [b["box"] for b in shown["items"]["flip"]["boxes"]] == [[40 - box[2], box[1], 40 - box[0], box[3]]]
    again = api.post("/api/augment/examples", json={"project": "aug", "dataset": dataset, "row": shown["row"], "items": {}}).json()
    assert again["row"] == shown["row"] and again["items"] == {}

    bad = api.post("/api/qa/release", json={"project": "aug", "dataset": dataset, "name": "bad", "augmentation": {"copies": 3, "rotation": {"min": 9, "max": 1}}})
    assert bad.status_code == 400 and "min" in bad.text

    started = api.post("/api/qa/release", json={"project": "aug", "dataset": dataset, "name": "augmented", "mode": "all", "augmentation": recipe})
    assert started.status_code == 200, started.text
    done = _wait(api, started.json()["job"])
    assert done["status"] == "done", done
    release = done["result"]["release"]
    assert release["augmentation"] == {"copies": 3, "flip": {"horizontal": True}, "rotation": {"min": -10.0, "max": 10.0}, "brightness": {"min": -20.0, "max": 20.0}}
    train = release["sets"]["train"]
    assert train["originals"] == 2 and train["augmented"] == 6 and train["images"] == 8

    rows = api.get("/api/table/rows", params={"url": train["url"], "limit": 20}).json()["rows"]
    new = [r for r in rows if "/releases/" in r["image"]]
    assert len(new) == 6 and all(_Path(r["image"]).is_file() for r in new)
    assert len({r["image_id"] for r in rows}) == 8
    assert {r["augmented_from"] for r in new} == {r["image"] for r in rows if r["augmented_from"] is None}
    # The version is listed for training; the augmented copy never becomes the working set.
    assert any(r["name"] == "augmented" for r in api.get("/api/releases", params={"project": "aug"}).json()["releases"])
    [working] = api.get("/api/qa", params={"project": "aug", "dataset": dataset}).json()["sets"]
    assert len(working["images"]) == 2
    assert _json.loads(_Path(train["url"], "object.granum.json").read_text())["producer"]["args"]["augmented"] == 6


def test_deleting_a_dataset_version_removes_only_its_own_files(client, tmp_path):
    from pathlib import Path as _Path

    api = client[0]
    folder = _dataset(tmp_path)
    job = api.post("/api/import/preflight", json={"sources": [{"split": "train", "annotations": str(folder / "_annotations.coco.json")}], "media": "none"}).json()
    _wait(api, job)
    _wait(api, api.post("/api/import/commit", json={"preflight_job": job["id"], "project_name": "del", "tasks": ["object_detection"]}).json())
    [dataset] = {t["dataset_name"] for t in api.get("/api/projects/del/tables").json()["tables"]}
    plain = api.post("/api/qa/release", json={"project": "del", "dataset": dataset, "name": "plain", "mode": "all"}).json()["release"]
    started = api.post("/api/qa/release", json={"project": "del", "dataset": dataset, "name": "augmented", "mode": "all",
                                                "augmentation": {"copies": 2, "flip": {"horizontal": True}}}).json()
    augmented = _wait(api, started["job"])["result"]["release"]
    augmented_dir = _Path(augmented["sets"]["train"]["url"]).parent
    assert augmented_dir.is_dir()

    usage = api.get("/api/releases/usage", params={"project": "del", "dataset": dataset, "release_id": augmented["id"]}).json()
    assert usage["files"] >= 4 and usage["bytes"] > 0 and usage["runs"] == []

    gone = api.post("/api/releases/delete", json={"project": "del", "dataset": dataset, "release_id": augmented["id"]})
    assert gone.status_code == 200, gone.text
    assert not augmented_dir.exists()
    names = [r["name"] for r in api.get("/api/releases", params={"project": "del"}).json()["releases"]]
    assert names == ["plain"]
    assert api.post("/api/releases/delete", json={"project": "del", "dataset": dataset, "release_id": augmented["id"]}).status_code == 404

    # A version that only pointed at the dataset's own sets leaves them in place.
    train_url = plain["sets"]["train"]["url"]
    assert api.post("/api/releases/delete", json={"project": "del", "dataset": dataset, "release_id": plain["id"]}).status_code == 200
    assert _Path(train_url).is_dir()
    assert len(api.get("/api/qa", params={"project": "del", "dataset": dataset}).json()["sets"][0]["images"]) == 2

    # Numbers are never reused, names are.
    again = api.post("/api/qa/release", json={"project": "del", "dataset": dataset, "name": "plain", "mode": "all"})
    assert again.status_code == 200 and again.json()["release"]["version"] == 3
    assert api.get("/api/releases/usage", params={"project": "del", "dataset": dataset, "release_id": "../x"}).status_code in (400, 404)
