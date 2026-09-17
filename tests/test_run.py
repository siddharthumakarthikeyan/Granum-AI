import pytest

import granum
from granum import Run, Table
from granum.core.objects.run import RunError, get_active_run, set_active_run


@pytest.fixture(autouse=True)
def clear_active_run():
    set_active_run(None)
    yield
    set_active_run(None)


def test_init_creates_and_activates():
    run = granum.init("demo", "exp-1", parameters={"lr": 1e-3}, description="first")
    assert run.name == "exp-1"
    assert run.parameters == {"lr": 1e-3}
    assert run.description == "first"
    assert get_active_run() is run
    assert run.url.exists()


def test_run_is_immutable():
    run = granum.init("demo", "exp-1")
    with pytest.raises(granum.ImmutableError):
        run.name = "renamed"


def test_set_parameters_merges_and_persists():
    run = granum.init("demo", "exp-1", parameters={"lr": 1e-3})
    run.set_parameters({"epochs": 10, "lr": 5e-4})
    assert run.parameters == {"lr": 5e-4, "epochs": 10}
    assert Run.from_url(run.url).parameters == {"lr": 5e-4, "epochs": 10}


def test_if_exists_rename_is_the_default():
    first = granum.init("demo", "exp")
    second = granum.init("demo", "exp")
    assert first.url != second.url
    assert second.name.startswith("exp")


def test_if_exists_reuse():
    first = granum.init("demo", "exp", parameters={"lr": 1.0})
    second = granum.init("demo", "exp", parameters={"bs": 32}, if_exists="reuse")
    assert first.url == second.url
    assert second.parameters == {"lr": 1.0, "bs": 32}


def test_if_exists_raise():
    granum.init("demo", "exp")
    with pytest.raises(RunError):
        granum.init("demo", "exp", if_exists="raise")


def test_if_exists_overwrite():
    first = granum.init("demo", "exp", parameters={"lr": 1.0})
    second = granum.init("demo", "exp", if_exists="overwrite")
    assert first.url == second.url
    assert second.parameters == {}


def test_if_exists_rejects_unknown_policy():
    with pytest.raises(RunError):
        granum.init("demo", "exp", if_exists="explode")


def test_run_reopens_from_url():
    run = granum.init("demo", "exp", parameters={"lr": 1e-3})
    reopened = Run.from_url(run.url)
    assert reopened.name == run.name
    assert reopened.parameters == run.parameters
    assert reopened.project_name == "demo"


def test_load_object_dispatches_on_type():
    run = granum.init("demo", "exp")
    table = Table.from_dict_data({"a": [1]}, project_name="demo", dataset_name="d")
    assert isinstance(granum.load_object(run.url), Run)
    assert isinstance(granum.load_object(table.url), Table)


# -- aggregate metrics ------------------------------------------------------


def test_log_appends_rows():
    run = granum.init("demo", "exp")
    granum.log({"epoch": 0, "train_loss": 1.2})
    granum.log({"epoch": 1, "train_loss": 0.8})
    rows = run.aggregate_metrics()
    assert [r["epoch"] for r in rows] == [0, 1]
    assert rows[1]["train_loss"] == 0.8


def test_log_persists_across_reload():
    run = granum.init("demo", "exp")
    granum.log({"epoch": 0, "acc": 0.5})
    assert Run.from_url(run.url).aggregate_metrics()[0]["acc"] == 0.5


def test_log_without_active_run_is_an_error():
    set_active_run(None)
    with pytest.raises(RunError):
        granum.log({"epoch": 0})


def test_log_to_explicit_run():
    run = granum.init("demo", "exp")
    set_active_run(None)
    granum.log({"epoch": 3}, run=run)
    assert run.aggregate_metrics()[0]["epoch"] == 3


def test_log_function_is_not_shadowed_by_a_module():
    """granum.log must stay callable.

    An internal module named `log` would silently replace this function the first time
    anything imported it -- the public API would vanish depending on import order.
    """
    import granum

    assert callable(granum.log)
    run = granum.init("demo", "shadow-check")
    granum.log({"epoch": 0})
    assert run.aggregate_metrics()[0]["epoch"] == 0
