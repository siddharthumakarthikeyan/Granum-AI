"""The licence server: codes, one trial per email and machine, paid plans and seats, renewal,
downloads. Runs on SQLite, and on Postgres too when TEST_DATABASE_URL is set."""

from __future__ import annotations

import base64
import os
import sys
import uuid
from pathlib import Path

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "api"))

from _licence.app import create_app  # noqa: E402
from _licence.db import Database  # noqa: E402
from _licence.mail import Mailer  # noqa: E402
from _licence.service import LicenceService, Settings  # noqa: E402
from _licence.token import decode, parse_time  # noqa: E402

DAY = 86400.0
M1 = "GM-1111-1111-1111-1111-1111-1111"
M2 = "GM-2222-2222-2222-2222-2222-2222"
M3 = "GM-3333-3333-3333-3333-3333-3333"

BACKENDS = ["sqlite"] + (["postgres"] if os.environ.get("TEST_DATABASE_URL") else [])


class Clock:
    def __init__(self) -> None:
        self.now = 1_800_000_000.0

    def __call__(self) -> float:
        return self.now


def _database(kind: str, tmp_path: Path) -> Database:
    if kind == "sqlite":
        return Database(str(tmp_path / "licences.sqlite3"))
    # A fresh Postgres database per test, so tests never see each other's rows.
    from urllib.parse import urlsplit, urlunsplit

    base = os.environ["TEST_DATABASE_URL"]
    name = f"t_{uuid.uuid4().hex[:12]}"
    Database(base).run(f"CREATE DATABASE {name}")
    return Database(urlunsplit(urlsplit(base)._replace(path=f"/{name}")))


@pytest.fixture(params=BACKENDS)
def server(request, tmp_path):
    key = Ed25519PrivateKey.generate()
    public = key.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    keys = {"t1": base64.urlsafe_b64encode(public).rstrip(b"=").decode()}
    clock = Clock()
    mailer = Mailer()
    service = LicenceService(_database(request.param, tmp_path), key, keys, mailer=mailer,
                             settings=Settings(trial_days=7, trial_projects=1, kid="t1"), clock=clock)
    site = {"version": "0.1.0", "contact": "hello@example.com",
            "downloads": {"windows": "https://example.com/Granum-Setup.exe", "linux": ""}}
    api = TestClient(create_app(service, admin_token="secret", site=site))
    return api, service, keys, clock, mailer


def _sign_in(api, mailer, email, machine):
    assert api.post("/v1/login/code", json={"email": email}).status_code == 200
    code = [c for to, c in mailer.sent if to == email.lower()][-1]
    return api.post("/v1/activate", json={"email": email, "code": code, "machine": machine})


def test_a_new_email_gets_one_free_trial_on_one_computer(server):
    api, _service, keys, clock, mailer = server
    first = _sign_in(api, mailer, "New@Buyer.com", M1)
    assert first.status_code == 200, first.text
    payload = decode(first.json()["key"], keys)
    assert payload["plan"] == "Free trial" and payload["machine"] == M1 and payload["kind"] == "online"
    assert payload["email"] == "new@buyer.com" and payload["max_projects"] == 1
    assert parse_time(payload["expires"]) - clock.now == 7 * DAY

    again = _sign_in(api, mailer, "new@buyer.com", M1)
    assert decode(again.json()["key"], keys)["lid"] == payload["lid"]
    other_email = _sign_in(api, mailer, "second@buyer.com", M1)
    assert other_email.status_code == 409 and other_email.json()["code"] == "trial_used"
    other_machine = _sign_in(api, mailer, "new@buyer.com", M2)
    assert other_machine.status_code == 409 and other_machine.json()["code"] == "trial_used"

    clock.now += 7 * DAY + 1
    ended = _sign_in(api, mailer, "new@buyer.com", M1)
    assert ended.status_code == 402 and ended.json()["code"] == "trial_ended"
    assert api.post("/v1/refresh", json={"key": first.json()["key"]}).json()["code"] == "ended"


def test_codes_expire_and_cannot_be_guessed(server):
    api, _service, _keys, clock, mailer = server
    api.post("/v1/login/code", json={"email": "a@b.com"})
    code = mailer.sent[-1][1]
    wrong = "000000" if code != "000000" else "111111"
    for _ in range(5):
        assert api.post("/v1/activate", json={"email": "a@b.com", "code": wrong, "machine": M1}).json()["code"] == "code_wrong"
    assert api.post("/v1/activate", json={"email": "a@b.com", "code": code, "machine": M1}).json()["code"] == "code_attempts"
    api.post("/v1/login/code", json={"email": "a@b.com"})
    clock.now += 11 * 60
    assert api.post("/v1/activate", json={"email": "a@b.com", "code": mailer.sent[-1][1], "machine": M1}).json()["code"] == "code_expired"
    for _ in range(3):
        api.post("/v1/login/code", json={"email": "a@b.com"})
    assert api.post("/v1/login/code", json={"email": "a@b.com"}).status_code == 429
    assert api.post("/v1/login/code", json={"email": "not-an-email"}).status_code == 400
    assert api.post("/v1/activate", json={"email": "a@b.com", "code": "1", "machine": "PC-1"}).status_code == 400


def test_a_paid_plan_covers_its_machines_and_moves_between_them(server):
    api, service, keys, clock, mailer = server
    _sign_in(api, mailer, "team@co.com", M1)
    assert api.post("/v1/admin/grant", json={"email": "team@co.com", "plan": "Pro", "days": 30, "machines": 2}).status_code == 401
    lid = api.post("/v1/admin/grant", json={"email": "team@co.com", "plan": "Pro", "days": 30, "machines": 2, "max_projects": 20},
                   headers={"Authorization": "Bearer secret"}).json()["lid"]
    one = _sign_in(api, mailer, "team@co.com", M1).json()
    assert decode(one["key"], keys)["lid"] == lid and one["licence"]["plan"] == "Pro"
    two = _sign_in(api, mailer, "team@co.com", M2)
    assert two.status_code == 200
    third = _sign_in(api, mailer, "team@co.com", M3)
    assert third.status_code == 409 and third.json()["code"] == "machines_full"

    assert api.post("/v1/deactivate", json={"key": one["key"]}).status_code == 200
    assert _sign_in(api, mailer, "team@co.com", M3).status_code == 200
    assert api.post("/v1/refresh", json={"key": one["key"]}).json()["code"] == "deactivated"

    clock.now += 3 * DAY
    renewed = api.post("/v1/refresh", json={"key": two.json()["key"]})
    assert renewed.status_code == 200 and parse_time(decode(renewed.json()["key"], keys)["issued"]) == clock.now
    service.extend(lid, 10)
    expires = parse_time(decode(api.post("/v1/refresh", json={"key": two.json()["key"]}).json()["key"], keys)["expires"])
    assert expires == pytest.approx(clock.now - 3 * DAY + 40 * DAY)
    service.revoke(lid)
    assert api.post("/v1/refresh", json={"key": two.json()["key"]}).json()["code"] == "revoked"

    account = api.get("/v1/admin/account", params={"email": "team@co.com"}, headers={"Authorization": "Bearer secret"}).json()
    assert {lic["kind"] for lic in account["licences"]} == {"trial", "paid"}


def test_downloads_need_a_real_email_proven_by_a_code(server):
    api, service, _keys, _clock, mailer = server
    site = api.get("/v1/site").json()
    assert site == {"version": "0.1.0", "contact": "hello@example.com", "downloads": {"windows": True, "linux": False}}
    assert api.post("/v1/download/code", json={"email": "bad"}).status_code == 400

    # A made-up or throwaway address gets no links: the code goes to the real inbox only.
    assert api.post("/v1/download/code", json={"email": "someone@mailinator.com"}).json()["code"] == "disposable"
    assert api.post("/v1/download/code", json={"email": "x@inbox.yopmail.com"}).json()["code"] == "disposable"
    assert api.post("/v1/download/code", json={"email": "Lead@Site.com"}).status_code == 200
    guess = api.post("/v1/download", json={"email": "lead@site.com", "code": "000000", "os": "windows"})
    assert guess.status_code == 400 and not service.db.value("SELECT COUNT(*) AS n FROM downloads")

    code = mailer.sent[-1][1]
    got = api.post("/v1/download", json={"email": "Lead@Site.com", "code": code, "os": "windows", "name": "Lea", "company": "Site Ltd"})
    assert got.status_code == 200 and got.json()["downloads"] == {"windows": "https://example.com/Granum-Setup.exe"}
    account = service.db.row("SELECT source, name, company FROM accounts WHERE email = 'lead@site.com'")
    assert account == {"source": "website", "name": "Lea", "company": "Site Ltd"}
    assert service.db.value("SELECT COUNT(*) AS n FROM downloads WHERE email = 'lead@site.com'") == 1
    # The code is spent.
    assert api.post("/v1/download", json={"email": "lead@site.com", "code": code, "os": "linux"}).status_code == 400

    # Trials refuse throwaway inboxes too.
    assert api.post("/v1/login/code", json={"email": "t@guerrillamail.com"}).json()["code"] == "disposable"


def test_racing_requests_cannot_share_a_code_or_split_a_trial(server):
    """Many sign-ins at once with one code: exactly one computer gets the trial."""
    from concurrent.futures import ThreadPoolExecutor

    from _licence.service import Refused

    _api, service, _keys, _clock, mailer = server
    service.send_code("race@co.com")
    code = mailer.sent[-1][1]
    machines = [f"GM-{i:04X}-0000-0000-0000-0000-0000" for i in range(8)]

    def attempt(machine):
        try:
            return service.activate("race@co.com", code, machine)["licence"]["lid"]
        except Refused as exc:
            return exc.code

    with ThreadPoolExecutor(8) as pool:
        results = list(pool.map(attempt, machines))
    winners = [r for r in results if r.startswith("T-")]
    assert len(winners) == 1, results
    assert service.db.value("SELECT COUNT(*) AS n FROM licences WHERE email = 'race@co.com'") == 1


def test_a_quote_request_is_kept_and_emailed_to_us(server):
    api, service, _keys, _clock, mailer = server
    asked = api.post("/v1/quote", json={"email": "Buyer@BigCo.com", "name": "Ana", "company": "BigCo", "computers": 40, "plan": "Team",
                                        "message": "Yearly, invoice billing."})
    assert asked.status_code == 200, asked.text
    row = service.db.row("SELECT * FROM quotes")
    assert row["email"] == "buyer@bigco.com" and row["computers"] == 40 and row["plan"] == "Team"
    to, subject, body = mailer.notices[-1]
    assert to == "hello@example.com" and subject == "Granum Team request: BigCo" and "invoice billing" in body

    assert api.post("/v1/quote", json={"email": "x@bigco.com", "name": "", "company": "BigCo"}).status_code == 400
    assert api.post("/v1/quote", json={"email": "x@mailinator.com", "name": "X", "company": "Y"}).status_code == 400
    bot = api.post("/v1/quote", json={"email": "bot@spam.com", "name": "B", "company": "C", "website": "http://spam"})
    assert bot.status_code == 200 and service.db.value("SELECT COUNT(*) AS n FROM quotes") == 1
    for _ in range(2):
        api.post("/v1/quote", json={"email": "buyer@bigco.com", "name": "Ana", "company": "BigCo"})
    assert api.post("/v1/quote", json={"email": "buyer@bigco.com", "name": "Ana", "company": "BigCo"}).status_code == 429
