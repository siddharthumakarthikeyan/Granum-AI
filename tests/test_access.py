import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import granum
from granum import Table
from granum.core.index import Index
from granum.core.qa import QaLog
from granum.core.schemas import ImageSchema
from granum.licensing import Licensing
from granum.service.app import create_app
from granum.service.auth import SharedAccess, password_hash

PASSWORD = "test-only-long-password"


@pytest.fixture
def shared(isolated_project):
    table = Table.from_dict_data({"image": ["a.png"]}, schema={"image": ImageSchema(sample_type="url")}, project_name="p", dataset_name="d")
    hashed = password_hash(PASSWORD)
    access = SharedAccess({name: {"role": name, "password_hash": hashed} for name in ("admin", "reviewer", "annotator", "viewer")})
    index = Index([isolated_project])
    index.refresh()
    app = create_app(index=index, config=granum.get_config(), access=access, licensing=Licensing.open(), allowed_hosts=["testserver"], serve_dashboard=False)
    return TestClient(app, base_url="https://testserver"), table


def test_all_routes_require_authentication_including_media_docs_and_jobs(shared):
    api, _ = shared
    for path in ("/api/health", "/api/media?url=/etc/passwd", "/api/projects", "/api/jobs/example", "/docs", "/"):
        response = api.get(path)
        assert response.status_code == 401
        assert response.headers["www-authenticate"].startswith("Basic")


def test_cleartext_and_wrong_password_are_rejected(shared):
    api, _ = shared
    assert api.get("http://testserver/api/health", auth=("admin", PASSWORD)).status_code == 403
    assert api.get("/api/health", auth=("admin", "wrong")).status_code == 401
    for _ in range(20):
        last = api.get("/api/health", auth=("no-such-user", "wrong"))
    assert last.status_code == 429


def test_viewer_reads_but_cannot_mutate_or_launch_jobs(shared):
    api, _ = shared
    assert api.get("/api/projects", auth=("viewer", PASSWORD)).status_code == 200
    for path in ("/api/table/commit", "/api/qa/status", "/api/qa/approve", "/api/service/quit", "/api/training", "/api/embeddings", "/api/jobs/x/cancel"):
        assert api.post(path, json={}, auth=("viewer", PASSWORD)).status_code == 403


def test_authenticated_attribution_overrides_spoofed_author(shared):
    api, table = shared
    result = api.post("/api/qa/status", auth=("reviewer", PASSWORD), json={
        "project": "p", "dataset": "d", "table": str(table.url), "samples": [table[0]["image"]], "status": "reviewed", "author": "pretend-admin",
    })
    assert result.status_code == 200, result.text
    assert QaLog("p", "d").events()[0]["author"] == "reviewer"
    assert api.post("/api/qa/approve", auth=("annotator", PASSWORD), json={}).status_code == 403
    assert api.post("/api/training/install", auth=("reviewer", PASSWORD), json={}).status_code == 403
    events = [json.loads(s) for s in (granum.get_config().project_root / "access-audit.jsonl").read_text().splitlines()]
    assert [e["phase"] for e in events] == ["requested", "responded"]
    assert all(e["author"] == "reviewer" and "password" not in str(e).lower() for e in events)


def test_annotator_commit_resets_review_with_authenticated_identity(shared):
    api, table = shared
    response = api.post("/api/table/commit", auth=("annotator", PASSWORD), json={"url": str(table.url), "expected_head": str(table.url), "values": {"weight": {"0": 0.5}}})
    assert response.status_code == 200, response.text
    assert QaLog("p", "d").current()[table[0]["image"]]["author"] == "annotator"
    assert api.get("/api/access", auth=("annotator", PASSWORD)).json()["attribution"] == "authenticated"


def test_bad_registry_rejected(tmp_path):
    path = Path(tmp_path) / "users.json"
    path.write_text(json.dumps({"version": 999, "users": {}}))
    path.chmod(0o600)
    with pytest.raises(ValueError, match="version"):
        SharedAccess.from_file(path)
    with pytest.raises(ValueError, match="administrator"):
        SharedAccess({"viewer": {"role": "viewer", "password_hash": password_hash(PASSWORD)}})


def test_parallel_authenticated_reads_keep_identity_isolated(shared):
    api, _ = shared
    roles = ["viewer", "annotator", "reviewer", "admin"] * 4

    def read(role):
        response = api.get("/api/access", auth=(role, PASSWORD))
        assert response.status_code == 200
        return response.json()["name"]

    with ThreadPoolExecutor(max_workers=8) as pool:
        assert list(pool.map(read, roles)) == roles


def test_legacy_reviews_are_attributed_to_authenticated_user(shared):
    from granum.core.reviews import ReviewLog

    api, table = shared
    response = api.post("/api/reviews", auth=("reviewer", PASSWORD), json={
        "project": "p", "dataset": "d", "table": str(table.url), "samples": [table[0]["image"]], "status": "correct",
    })
    assert response.status_code == 200, response.text
    assert ReviewLog("p", "d").events()[0]["reviewer"] == "reviewer"


def test_audit_completion_failure_preserves_result_and_blocks_further_writes(shared, monkeypatch):
    import granum.core.qa as qa

    api, table = shared
    append = qa._append

    def interrupted(url, events):
        if str(url).endswith("access-audit.jsonl") and events[0]["phase"] == "responded":
            raise OSError("simulated full disk")
        return append(url, events)

    monkeypatch.setattr(qa, "_append", interrupted)
    response = api.post("/api/table/commit", auth=("annotator", PASSWORD), json={
        "url": str(table.url), "expected_head": str(table.url), "values": {"weight": {"0": 0.25}},
    })
    assert response.status_code == 200, response.text
    assert response.headers["x-granum-audit-warning"]
    assert Table.from_url(response.json()["url"])[0]["weight"] == 0.25
    assert api.get("/api/access", auth=("annotator", PASSWORD)).json()["audit_available"] is False
    assert api.post("/api/qa/comment", auth=("annotator", PASSWORD), json={}).status_code == 503