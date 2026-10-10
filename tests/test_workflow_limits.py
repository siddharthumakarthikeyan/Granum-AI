import pytest
from fastapi.testclient import TestClient

import granum
from granum import Table
from granum.core.index import Index
from granum.core.schemas import ImageSchema
from granum.service.app import create_app
from granum.service.limits import WorkflowLimits


@pytest.mark.parametrize("limits", [WorkflowLimits(images=1, rows=1), WorkflowLimits(uncompressed_bytes=1)])
def test_oversized_workflows_fail_instead_of_returning_partial_results(isolated_project, limits):
    table = Table.from_dict_data({"image": ["a.png", "b.png"]}, schema={"image": ImageSchema(sample_type="url")}, project_name="p", dataset_name="d")
    run = granum.init("p", "r")
    run.add_metrics({"example_id": [0, 1], "loss": [0.1, 0.2]}, foreign_table_url=table.url)
    index = Index([isolated_project])
    index.refresh()
    api = TestClient(create_app(index=index, config=granum.get_config(), limits=limits, allowed_hosts=["testserver"], serve_dashboard=False))
    for endpoint, params in [
        ("/api/table/rows", {"url": str(table.url)}),
        ("/api/table/arrow", {"url": str(table.url)}),
        ("/api/images", {"project": "p", "dataset": "d"}),
        ("/api/run/joined", {"url": str(run.url)}),
    ]:
        response = api.get(endpoint, params=params)
        assert response.status_code == 413, response.text
        assert "No partial result" in response.json()["detail"]