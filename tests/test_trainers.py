"""Trainings outlive the service that started them."""

import sys
import time

import granum
from granum.core.index import Index
from granum.service import trainers
from granum.service.app import create_app
from granum.service.cache import ByteCache

# A stand-in trainer: its command line names the trainer module, so it is recognised as one.
FAKE = """
import sys, time
import granum
from granum.core.objects.run import Run
granum.set_config(granum.Config.load(overrides={"project-root-url": sys.argv[1]}, use_config_files=False, use_env=False))
print("GRANUM_PHASE Training, round 1 of 3", flush=True)
print("GRANUM_PROGRESS 1 3", flush=True)
print("some log line", flush=True)
time.sleep(float(sys.argv[3]))
Run.from_url(sys.argv[2]).set_status("finished")
print("GRANUM_PROGRESS 3 3", flush=True)
# granum.training.train
"""


def _run(project="demo", name="run-1", framework="yolo"):
    run = granum.init(project, name, parameters={"framework": framework})
    granum.set_active_run(None)
    return run


def _app(isolated_project):
    index = Index([isolated_project])
    index.refresh()
    return create_app(index=index, config=granum.get_config(), cache=ByteCache(), allowed_hosts=["testserver"], serve_dashboard=False)


def _wait_job(app, kind="training", timeout=20):
    from fastapi.testclient import TestClient

    api = TestClient(app)
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        status = api.get("/api/training/status", params={"project": "demo"}).json()
        job = status["running_job"]
        if job is None:
            return None
        time.sleep(0.2)
    raise AssertionError("training job did not finish")


def test_trainer_reports_progress_and_finishes(isolated_project, tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    run = _run()
    process, record = trainers.launch([sys.executable, "-c", FAKE, str(isolated_project), str(run.url), "0.5"], cwd=tmp_path,
                                      project_root=str(isolated_project), project="demo", run_name=run.name, rounds=3)
    assert record.path.exists()

    class Job:
        from collections import deque
        cancel = __import__("threading").Event()
        log = deque(maxlen=50)
        phase = ""
        done = 0
        total = 0

        def progress(self, phase, done, total):
            self.phase, self.done, self.total = phase, done, total

    job = Job()
    outcome = trainers.follow(job, record, process, lambda r, cancelled, code: (cancelled, code))
    assert outcome == (False, 0)
    assert job.phase == "Training, round 1 of 3" and (job.done, job.total) == (3, 3) and "some log line" in job.log
    assert not record.path.exists()
    assert granum.Run.from_url(run.url).status == "finished"


def test_restarted_service_reattaches_and_can_cancel(isolated_project, tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    run = _run()
    process, record = trainers.launch([sys.executable, "-c", FAKE, str(isolated_project), str(run.url), "60"], cwd=tmp_path,
                                      project_root=str(isolated_project), project="demo", run_name=run.name, rounds=3)
    try:
        # A "new" service: it finds the live trainer and follows it as a training job.
        from fastapi.testclient import TestClient

        app = _app(isolated_project)
        api = TestClient(app)
        for _ in range(50):
            job = api.get("/api/training/status", params={"project": "demo"}).json()["running_job"]
            if job and job["done"] == 1:
                break
            time.sleep(0.1)
        assert job and job["kind"] == "training" and job["phase"] == "Training, round 1 of 3"
        assert granum.Run.from_url(run.url).status == "running"

        api.post(f"/api/jobs/{job['id']}/cancel")
        assert _wait_job(app) is None
        assert process.wait(timeout=20) != 0
        assert granum.Run.from_url(run.url).status == "cancelled"
        assert not record.path.exists()
    finally:
        if process.poll() is None:
            process.kill()


def test_abandoned_dashboard_runs_are_marked_interrupted(isolated_project, tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    dead = _run(name="died-while-service-was-down")
    trainers.TrainerRecord(pid=2 ** 22 + 7, project="demo", run_name=dead.name, rounds=3, log=str(tmp_path / "x.log"),
                           project_root=str(isolated_project), started=time.time()).save()
    orphan = _run(name="from-before-records")
    script = _run(name="my-own-training-script", framework=None)

    _app(isolated_project)
    assert granum.Run.from_url(dead.url).status == "interrupted"
    assert granum.Run.from_url(orphan.url).status == "interrupted"
    # Runs from the user's own scripts are not the service's to judge.
    assert granum.Run.from_url(script.url).status == "running"
    assert list((tmp_path / "state" / "granum" / "training").glob("*.json")) == []


def test_round_progress_and_time_left(monkeypatch):
    from granum.service import jobs as jobs_module
    from granum.service.jobs import Job

    clock = [1000.0]
    monkeypatch.setattr(jobs_module.time, "time", lambda: clock[0])
    job = Job(id="j", kind="training")
    job.set_step(0, 700)
    clock[0] += 5
    assert job.to_dict()["round_eta"] is None  # too early to estimate
    clock[0] += 55
    job.set_step(100, 700)
    # 100 steps in 60 s -> 600 steps left take about 360 s.
    assert job.to_dict()["step"] == 100 and job.to_dict()["round_eta"] == 360

    # Joining a round midway (after a restart): only steps seen since then count.
    joined = Job(id="k", kind="training")
    joined.set_step(250, 700)
    clock[0] += 60
    joined.set_step(280, 700)
    assert joined.to_dict()["round_eta"] == 840  # 30 steps in 60 s, 420 left
    job.set_step(5, 700)  # a new round starts the clock again
    assert job.to_dict()["round_eta"] is None
