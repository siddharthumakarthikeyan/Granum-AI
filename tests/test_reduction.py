import importlib.util
import time

import numpy as np
import pytest
from fastapi.testclient import TestClient

from granum import Table
from granum.core.config import get_config
from granum.core.index import Index
from granum.core.objects.run import get_active_run, init, set_active_run
from granum.core.schemas import EmbeddingSchema
from granum.metrics import EmbeddingsMetricsCollector, Prediction
from granum.metrics.collectors import CollectorError
from granum.reduction import Reducer, ReductionError, reduce_run, reduce_table
from granum.service.app import create_app


@pytest.fixture(autouse=True)
def active_run():
    set_active_run(None)
    yield
    set_active_run(None)


def embedding_table():
    return Table.from_dict_data({"embedding": [[1, 2, 0], [2, 0, 3], [4, 5, 6]], "label": [0, 1, 0]},
                                schema={"embedding": EmbeddingSchema(shape=(3,))},
                                project_name="projection", dataset_name="images")


def test_pca_reuses_reference_coordinates_and_pads_small_inputs():
    data = np.asarray([[1, 2, 3], [2, 4, 5], [8, 3, 2]], dtype=np.float32)
    reducer = Reducer(dimensions=3)
    points = reducer.fit_transform(data)
    np.testing.assert_allclose(points, reducer.transform(data))
    np.testing.assert_allclose(points[[2, 0]], reducer.transform(data[[2, 0]]), atol=1e-5)
    assert reducer.manifest()["reference_sha256"]
    assert Reducer(dimensions=3).fit_transform([[4]]).shape == (1, 3)


@pytest.mark.parametrize("bad", [[[1, 2], [3]], [[np.nan, 1]], [], [[1, np.inf]]])
def test_invalid_vectors_are_rejected(bad):
    with pytest.raises(ReductionError):
        Reducer().fit_transform(bad)


@pytest.mark.parametrize("method", ["umap", "pacmap"])
def test_optional_reducers_fit_and_transform_real_data(method, tmp_path):
    if importlib.util.find_spec(method) is None:
        pytest.skip(f"{method} optional dependency is absent")
    data = np.random.default_rng(4).normal(size=(40, 8)).astype(np.float32)
    reducer = Reducer(method, dimensions=3, neighbours=5, seed=7)
    points = reducer.fit_transform(data)
    projected = reducer.transform(data[:5] + 0.05)
    assert points.shape == (40, 3) and projected.shape == (5, 3)
    assert np.isfinite(projected).all()
    np.testing.assert_array_equal(points, reducer.transform(data))
    saved = reducer.save(tmp_path / method)
    with pytest.raises(ReductionError, match="trusted=True"):
        Reducer.load(saved)
    restored = Reducer.load(saved, trusted=True)
    np.testing.assert_array_equal(points, restored.transform(data))
    np.testing.assert_allclose(projected, restored.transform(data[:5] + .05), atol=1e-5)


def test_pca_save_is_reusable_without_pickle_and_detects_corruption(tmp_path):
    values = np.array([[1, 2, 3], [4, 5, 2], [0, 1, 4]], dtype=np.float32)
    reducer = Reducer(dimensions=3)
    reducer.fit_transform(values)
    saved = reducer.save(tmp_path / "projection")
    restored = Reducer.load(saved)
    np.testing.assert_array_equal(reducer.transform(values + .5), restored.transform(values + .5))
    assert not list(saved.glob("*.pkl"))
    with pytest.raises(ReductionError, match="already exists"):
        reducer.save(saved)
    with (saved / "arrays.npz").open("ab") as handle:
        handle.write(b"damaged")
    with pytest.raises(ReductionError, match="damaged"):
        Reducer.load(saved)


def test_projection_writes_an_immutable_version_with_provenance(isolated_project):
    source = embedding_table()
    projected = reduce_table(source, "embedding")
    assert "projection_x" in projected.schema
    assert "projection_x" not in Table.from_url(source.url).schema
    assert projected.producer["op"] == "reduce_embeddings"
    assert projected.producer["args"]["reference_sha256"]
    with pytest.raises(ReductionError, match="already exist"):
        reduce_table(projected, "embedding")


def test_run_projection_retains_sample_joins_epoch_constants_and_active_run(isolated_project):
    source = embedding_table()
    run = init("projection", "training")
    for epoch in (1, 2):
        run.add_metrics({"example_id": [2, 0, 1], "embedding": [[1 * epoch, 2, 0], [2, 3, 4], [5, 6, 7]]},
                        foreign_table_url=source.url, schema={"embedding": EmbeddingSchema(shape=(3,))}, constants={"epoch": epoch})
    projected = reduce_run(run, "embedding")
    assert get_active_run() is run
    assert projected.status == "finished"
    assert projected.parameters["source_run"] == str(run.url)
    assert len(projected.metrics_tables()) == 2
    assert "projection_x" not in run.metrics_tables()[0].schema
    table = projected.metrics_tables()[0]
    assert table.constants["epoch"] == 1
    assert [row["label"] for row in table.join_input()] == [0, 0, 1]


def test_run_reuses_a_previously_fitted_coordinate_system(tmp_path):
    source = embedding_table()
    reference = np.asarray(source.to_pydict()["embedding"], dtype=np.float32)
    reducer = Reducer(dimensions=3)
    reducer.fit_transform(reference)
    reducer = Reducer.load(reducer.save(tmp_path / "saved"))
    fingerprint = reducer.manifest()["reference_sha256"]
    run = init("projection", "new-data")
    for epoch in (1, 2):
        run.add_metrics({"example_id": [0, 1, 2], "embedding": (reference + 100 * epoch).tolist()},
                        foreign_table_url=source.url, schema={"embedding": EmbeddingSchema(shape=(3,))},
                        constants={"epoch": epoch})
    projected = reduce_run(run, "embedding", reducer=reducer)
    assert projected.parameters["reference_sha256"] == fingerprint
    assert projected.parameters["reused_reducer"] is True
    assert projected.parameters["reference_table"] is None
    for epoch, table in enumerate(projected.metrics_tables(), 1):
        data = table.to_pydict()
        points = np.column_stack([data[f"projection_{axis}"] for axis in "xyz"])
        np.testing.assert_allclose(points, reducer.transform(reference + 100 * epoch), atol=1e-5)
        assert np.linalg.norm(points.mean(axis=0)) > 100  # a refit would recenter the new data


def test_collector_pools_features_and_checks_batch_identity():
    collector = EmbeddingsMetricsCollector(3)
    prediction = Prediction(outputs=np.zeros((2, 1)), activations={3: np.ones((2, 4, 3, 3))})
    assert collector.collect({"image": ["a", "b"]}, prediction) == {"embedding": [[1.0] * 4] * 2}
    assert collector.column_schemas()["embedding"].shape == (4,)
    with pytest.raises(CollectorError, match="batch size"):
        collector.collect({"image": ["a"]}, prediction)
    with pytest.raises(CollectorError, match="not captured"):
        collector.collect({}, Prediction(outputs=[]))


def test_projection_api_works_with_dashboard_and_checks_paths(isolated_project):
    table = embedding_table()
    with TestClient(create_app(config=get_config(), allowed_hosts=["testserver"], serve_dashboard=True)) as client:
        assert client.get("/api/analysis/methods").status_code == 200
        bad = client.post("/api/analysis/project", json={"url": "/etc", "column": "embedding"})
        assert bad.status_code == 403
        response = client.post("/api/analysis/project", json={"url": str(table.url), "column": "embedding", "dimensions": 3})
        assert response.status_code == 200
        job = response.json()
        for _ in range(100):
            job = client.get(f"/api/jobs/{job['id']}").json()
            if job["status"] != "running":
                break
            time.sleep(0.01)
        assert job["status"] == "done", job
        assert job["result"]["axes"] == ["projection_x", "projection_y", "projection_z"]


def test_dashboard_saved_projection_survives_restart_and_is_project_scoped(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    table = embedding_table()

    def complete(client, response):
        assert response.status_code == 200, response.text
        job = response.json()
        for _ in range(200):
            job = client.get(f"/api/jobs/{job['id']}").json()
            if job["status"] != "running":
                return job
            time.sleep(.01)
        pytest.fail("projection did not finish")

    with TestClient(create_app(config=get_config(), index=Index([get_config().project_root]), allowed_hosts=["testserver"])) as client:
        job = complete(client, client.post("/api/analysis/project", json={
            "url": str(table.url), "column": "embedding", "dimensions": 3, "save_reducer_as": "Reference space",
        }))
        assert job["status"] == "done", job
        identifier = job["result"]["reducer_id"]
        reference_hash = job["result"]["projection"]["reference_sha256"]

    reference = np.asarray(table.to_pydict()["embedding"], dtype=np.float32)
    target = Table.from_dict_data({"embedding": (reference + 100).tolist()},
                                 schema={"embedding": EmbeddingSchema(shape=(3,))},
                                 project_name="projection", dataset_name="shifted")
    foreign = Table.from_dict_data({"embedding": reference.tolist()},
                                  schema={"embedding": EmbeddingSchema(shape=(3,))},
                                  project_name="another-project", dataset_name="foreign")
    with TestClient(create_app(config=get_config(), index=Index([get_config().project_root]), allowed_hosts=["testserver"])) as client:
        listing = client.get("/api/analysis/reducers", params={"url": str(target.url)}).json()
        assert len(listing) == 1 and listing[0]["id"] == identifier
        assert listing[0]["features"] == 3 and listing[0]["name"] == "Reference space"
        assert client.get("/api/analysis/reducers", params={"url": "/etc"}).status_code == 403
        assert client.get("/api/analysis/reducers", params={"url": str(foreign.url)}).json() == []
        projected = complete(client, client.post("/api/analysis/project", json={
            "url": str(target.url), "column": "embedding", "reducer_id": identifier, "prefix": "aligned",
        }))
        assert projected["status"] == "done", projected
        assert projected["result"]["axes"] == ["aligned_x", "aligned_y", "aligned_z"]
        assert projected["result"]["projection"]["reference_sha256"] == reference_hash
        result = Table.from_url(projected["result"]["url"]).to_pydict()
        expected = Reducer(dimensions=3)
        expected.fit_transform(reference)
        np.testing.assert_allclose(np.column_stack([result[f"aligned_{axis}"] for axis in "xyz"]),
                                   expected.transform(reference + 100), atol=1e-5)
        wrong_project = complete(client, client.post("/api/analysis/project", json={
            "url": str(foreign.url), "column": "embedding", "reducer_id": identifier,
        }))
        assert wrong_project["status"] == "failed" and "not found" in wrong_project["error"]
        assert client.post("/api/analysis/project", json={
            "url": str(target.url), "column": "embedding", "reducer_id": "../../model.pkl",
        }).status_code == 422
