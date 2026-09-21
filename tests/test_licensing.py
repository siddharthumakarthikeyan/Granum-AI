"""Licences: signed keys, one machine, plan end, offline lease, clock rollback, limits."""

from __future__ import annotations

import base64
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from granum.licensing import Licensing, set_licensing
from granum.licensing.token import LicenceError, decode, encode, format_time

DAY = 86400.0
T0 = 1_800_000_000.0  # a fixed "now" for the tests
MACHINE = "GM-AAAA-BBBB-CCCC-DDDD-EEEE-FFFF"


class Clocks:
    """A calendar clock and a monotonic clock the test moves by hand."""

    def __init__(self) -> None:
        self.now = T0
        self.mono = 1000.0

    def run_for(self, seconds: float, *, calendar: bool = True) -> None:
        self.mono += seconds
        if calendar:
            self.now += seconds


@pytest.fixture
def signing():
    key = Ed25519PrivateKey.generate()
    public = key.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    return key, {"t1": base64.urlsafe_b64encode(public).rstrip(b"=").decode()}


def _payload(**changes):
    payload = {
        "v": 1, "kid": "t1", "lid": "L-TEST", "email": "a@b.com", "customer": "A", "plan": "Pro", "machines": 1,
        "machine": MACHINE, "kind": "offline", "issued": format_time(T0), "expires": format_time(T0 + 30 * DAY),
        "lease_until": None, "max_projects": 3,
    }
    payload.update(changes)
    return payload


def _licensing(tmp_path, keys, clocks, **kwargs):
    return Licensing(folder=tmp_path / "data", mark_folder=tmp_path / "state", public_keys=keys, machine=MACHINE,
                     clock=lambda: clocks.now, monotonic=lambda: clocks.mono, **kwargs)


def test_keys_are_checked_by_signature(signing):
    key, keys = signing
    token = encode(_payload(), key)
    assert decode(token, keys)["email"] == "a@b.com"
    head, body, sig = token.split(".")
    forged = json.loads(base64.urlsafe_b64decode(body + "=="))
    forged["max_projects"] = None
    forged_body = base64.urlsafe_b64encode(json.dumps(forged).encode()).rstrip(b"=").decode()
    with pytest.raises(LicenceError, match="signature"):
        decode(f"{head}.{forged_body}.{sig}", keys)
    with pytest.raises(LicenceError, match="does not know"):
        decode(encode(_payload(kid="zz"), key), keys)
    other = Ed25519PrivateKey.generate()
    with pytest.raises(LicenceError, match="signature"):
        decode(encode(_payload(), other), keys)
    with pytest.raises(LicenceError, match="not a Granum licence"):
        decode("hello", keys)


def test_a_key_works_on_its_own_machine_until_the_plan_ends(tmp_path, signing):
    key, keys = signing
    clocks = Clocks()
    licensing = _licensing(tmp_path, keys, clocks)
    assert licensing.status()["state"] == "missing" and licensing.status()["mode"] == "read_only"

    with pytest.raises(LicenceError, match="another computer"):
        licensing.install(encode(_payload(machine="GM-0000-0000-0000-0000-0000-0000"), key))
    status = licensing.install(encode(_payload(), key))
    assert status["mode"] == "full" and status["days_left"] == 30.0 and status["max_projects"] == 3

    clocks.run_for(31 * DAY)
    status = licensing.heartbeat()
    assert status["state"] == "expired" and status["mode"] == "read_only"
    with pytest.raises(LicenceError, match="read-only"):
        licensing.require_write()


def test_a_key_copied_to_another_machine_is_refused(tmp_path, signing):
    key, keys = signing
    clocks = Clocks()
    _licensing(tmp_path, keys, clocks).install(encode(_payload(), key))
    elsewhere = Licensing(folder=tmp_path / "data", mark_folder=tmp_path / "state", public_keys=keys,
                          machine="GM-9999-9999-9999-9999-9999-9999", clock=lambda: clocks.now)
    assert elsewhere.status()["state"] == "wrong_machine"


def test_turning_the_clock_back_makes_it_read_only(tmp_path, signing):
    key, keys = signing
    clocks = Clocks()
    licensing = _licensing(tmp_path, keys, clocks)
    licensing.install(encode(_payload(), key))
    clocks.run_for(20 * DAY)
    licensing.heartbeat()
    clocks.now -= 15 * DAY  # back to "day 5"
    status = licensing.heartbeat()
    assert status["state"] == "clock" and status["mode"] == "read_only"
    # The beat did not learn the wrong time; setting the clock right restores the licence.
    clocks.now += 15 * DAY
    assert licensing.heartbeat()["state"] == "active"
    # The mark survives a new Licensing (a restart), and the second copy survives the first being deleted.
    clocks.now -= 15 * DAY
    (tmp_path / "data" / "state.json").unlink()
    assert _licensing(tmp_path, keys, clocks).status()["state"] == "clock"


def test_newer_projects_than_the_clock_mean_it_was_turned_back(tmp_path, signing):
    key, keys = signing
    clocks = Clocks()
    licensing = _licensing(tmp_path, keys, clocks, latest_seen=lambda: T0 + 10 * DAY)
    licensing.install(encode(_payload(), key))
    assert licensing.status(fresh=True)["state"] == "clock"


def test_online_keys_last_seven_days_of_use_without_renewal(tmp_path, signing):
    key, keys = signing
    clocks = Clocks()
    licensing = _licensing(tmp_path, keys, clocks)
    online = _payload(kind="online", lease_until=format_time(T0 + 7 * DAY), expires=format_time(T0 + 90 * DAY))
    status = licensing.install(encode(online, key))
    assert status["mode"] == "full" and status["offline_days_left"] == 7.0

    # Running with the calendar frozen (or turned back each day) still uses up the lease.
    for _ in range(6):
        clocks.run_for(DAY, calendar=False)
        licensing.heartbeat()
    assert licensing.status()["state"] == "active" and licensing.status()["offline_days_left"] == 1.0
    clocks.run_for(1.5 * DAY, calendar=False)
    assert licensing.heartbeat()["state"] == "lease_expired"

    # A renewed key (new issue time and lease) starts a fresh allowance.
    clocks.now += 2 * DAY
    renewed = {**online, "issued": format_time(clocks.now), "lease_until": format_time(clocks.now + 7 * DAY)}
    assert licensing.install(encode(renewed, key))["mode"] == "full"


def test_online_lease_also_ends_by_the_calendar(tmp_path, signing):
    key, keys = signing
    clocks = Clocks()
    licensing = _licensing(tmp_path, keys, clocks)
    licensing.install(encode(_payload(kind="online", lease_until=format_time(T0 + 7 * DAY)), key))
    clocks.now += 8 * DAY  # the computer was off
    assert licensing.heartbeat()["state"] == "lease_expired"


def test_edited_or_missing_state_counts_the_lease_as_spent(tmp_path, signing):
    key, keys = signing
    clocks = Clocks()
    licensing = _licensing(tmp_path, keys, clocks)
    token = encode(_payload(kind="online", lease_until=format_time(T0 + 7 * DAY)), key)
    licensing.install(token)
    clocks.run_for(DAY)
    licensing.heartbeat()
    state_file = tmp_path / "data" / "state.json"
    record = json.loads(state_file.read_text())
    record["body"]["usage"] = 0
    state_file.write_text(json.dumps(record))
    assert licensing.status(fresh=True)["state"] == "lease_expired"

    # Reinstalling the same key does not reset it either: time since issue counts as used.
    state_file.unlink()
    status = licensing.install(token)
    assert status["mode"] == "full" and status["offline_days_left"] == 6.0


def test_project_limit(tmp_path, signing):
    key, keys = signing
    licensing = _licensing(tmp_path, keys, Clocks())
    licensing.install(encode(_payload(max_projects=2), key))
    licensing.require_new_project(1)
    with pytest.raises(LicenceError, match="allows 2 projects"):
        licensing.require_new_project(2)
    licensing.install(encode(_payload(max_projects=None, lid="L-2"), key))
    licensing.require_new_project(500)


def test_the_service_is_read_only_without_a_licence(tmp_path, signing):
    from fastapi.testclient import TestClient

    import granum
    from granum.core.index import Index
    from granum.service.app import create_app
    from granum.service.cache import ByteCache

    key, keys = signing
    clocks = Clocks()
    licensing = _licensing(tmp_path, keys, clocks)
    index = Index(config=granum.get_config())
    index.refresh()
    api = TestClient(create_app(index=index, config=granum.get_config(), cache=ByteCache(), allowed_hosts=["testserver"],
                                serve_dashboard=False, licensing=licensing))
    status = api.get("/api/licence").json()
    assert status["mode"] == "read_only" and status["machine"] == MACHINE and status["projects_used"] == 0
    assert api.get("/api/projects").status_code == 200
    # Refused before the request is even looked at.
    refused = api.post("/api/projects/nothing/rename", json={"new_name": "x"})
    assert refused.status_code == 402 and refused.json()["licence"]["state"] == "missing"
    assert api.post("/api/images/boxes", json={"project": "demo", "dataset": "x", "items": []}).status_code != 402
    assert api.post("/api/licence/install", json={"key": "GRN1.bad.key"}).status_code == 400

    installed = api.post("/api/licence/install", json={"key": encode(_payload(max_projects=1), key)})
    assert installed.status_code == 200 and installed.json()["mode"] == "full"
    assert api.post("/api/projects/nothing/rename", json={"new_name": "x"}).status_code == 404

    # Imports fill the plan: the first project fits, a second is refused.
    folder = tmp_path / "shop" / "train"
    folder.mkdir(parents=True)
    from PIL import Image

    Image.new("RGB", (8, 8)).save(folder / "a.jpg")
    (folder / "_annotations.coco.json").write_text(json.dumps({
        "images": [{"id": 1, "file_name": "a.jpg", "width": 8, "height": 8}],
        "annotations": [{"id": 1, "image_id": 1, "category_id": 1, "bbox": [1, 1, 3, 3]}],
        "categories": [{"id": 1, "name": "can"}],
    }))
    api_with_data = TestClient(create_app(index=index, config=granum.get_config(), cache=ByteCache(), allowed_hosts=["testserver"],
                                          serve_dashboard=False, licensing=licensing, data_roots=[str(tmp_path)]))
    job = api_with_data.post("/api/import/preflight", json={"sources": [{"split": "train", "annotations": str(folder / "_annotations.coco.json")}], "media": "none"}).json()
    import time

    while api_with_data.get(f"/api/jobs/{job['id']}").json()["status"] == "running":
        time.sleep(0.05)
    first = api_with_data.post("/api/import/commit", json={"preflight_job": job["id"], "project_name": "first"})
    assert first.status_code == 200, first.text
    while api_with_data.get(f"/api/jobs/{first.json()['id']}").json()["status"] == "running":
        time.sleep(0.05)
    index.refresh(force=True)
    job = api_with_data.post("/api/import/preflight", json={"sources": [{"split": "train", "annotations": str(folder / "_annotations.coco.json")}], "media": "none"}).json()
    while api_with_data.get(f"/api/jobs/{job['id']}").json()["status"] == "running":
        time.sleep(0.05)
    commit = api_with_data.post("/api/import/commit", json={"preflight_job": job["id"], "project_name": "second"})
    assert commit.status_code == 402 and "allows 1 project" in commit.text
    # Adding to the project that exists is fine.
    more = api_with_data.post("/api/import/commit", json={"preflight_job": job["id"], "project_name": "first", "dataset_name": "more"})
    assert more.status_code == 200, more.text


def test_runs_need_a_licence_that_allows_writing(tmp_path, signing):
    import granum
    from granum.core.objects.run import RunError

    key, keys = signing
    set_licensing(_licensing(tmp_path, keys, Clocks()))
    with pytest.raises(RunError, match="read-only"):
        granum.init("fresh", "r1")


def test_admin_tool_issues_keys_the_app_accepts(tmp_path):
    tool = Path(__file__).resolve().parents[1] / "tools" / "granum_licence.py"
    env = {**os.environ, "GRANUM_ADMIN_DIR": str(tmp_path / "admin")}
    made = subprocess.run([sys.executable, str(tool), "keygen", "--kid", "t9"], capture_output=True, text=True, env=env, check=True)
    public = made.stdout.split('"t9": "')[1].split('"')[0]
    issued = subprocess.run([sys.executable, str(tool), "issue", "--kid", "t9", "--email", "Buyer@Example.com", "--machine", MACHINE.lower(),
                             "--days", "30", "--projects", "5", "--json"], capture_output=True, text=True, env=env, check=True)
    token = json.loads(issued.stdout)["key"]
    payload = decode(token, {"t9": public})
    assert payload["email"] == "buyer@example.com" and payload["machine"] == MACHINE and payload["max_projects"] == 5
    assert payload["kind"] == "offline" and payload["lease_until"] is None
    # keygen never overwrites a key.
    again = subprocess.run([sys.executable, str(tool), "keygen", "--kid", "t9"], capture_output=True, text=True, env=env)
    assert again.returncode != 0


class FakeServer:
    """A licence server in miniature: signs keys for one account and can revoke them."""

    def __init__(self, key, clocks, *, plan="Free trial", days=7, projects=1):
        self.key, self.clocks, self.plan, self.days, self.projects = key, clocks, plan, days, projects
        self.codes, self.revoked = {}, False

    def _key(self, email, machine):
        now = self.clocks.now
        return encode(_payload(email=email, machine=machine, kind="online", plan=self.plan, max_projects=self.projects,
                               issued=format_time(now), expires=format_time(T0 + self.days * DAY),
                               lease_until=format_time(min(now + 7 * DAY, T0 + self.days * DAY))), self.key)

    def send_code(self, email):
        self.codes[email] = "123456"
        return {"sent": True, "minutes": 10}

    def activate(self, email, code, machine):
        from granum.licensing.client import Refused

        if self.codes.get(email) != code:
            raise Refused("That code is not right.", status=400, code="code_wrong")
        return self._key(email, machine)

    def refresh(self, key):
        from granum.licensing.client import Refused

        if self.revoked:
            raise Refused("This licence was cancelled.", status=403, code="revoked")
        return self._key("me@home.com", MACHINE)

    def deactivate(self, key):
        self.revoked = True


def test_the_app_signs_in_renews_and_loses_a_revoked_licence(tmp_path, signing):
    key, keys = signing
    clocks = Clocks()
    server = FakeServer(key, clocks)
    licensing = _licensing(tmp_path, keys, clocks, server=server)
    assert licensing.status()["server"] is True
    assert "Sign in" in licensing.status()["reason"]
    licensing.send_code("me@home.com")
    from granum.licensing.client import Refused

    with pytest.raises(Refused):
        licensing.activate("me@home.com", "000000")
    status = licensing.activate("me@home.com", "123456")
    assert status["mode"] == "full" and status["plan"] == "Free trial" and status["max_projects"] == 1

    clocks.run_for(2 * DAY)
    assert licensing.renew()["offline_days_left"] == 5.0  # the lease never runs past the plan's end

    server.revoked = True
    with pytest.raises(Refused):
        licensing.renew()
    assert licensing.status()["state"] == "missing" and licensing.status()["server_message"] == "This licence was cancelled."
