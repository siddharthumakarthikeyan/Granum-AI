from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from _licence.app import create_app


@pytest.mark.parametrize("missing", ["release", "checksums", "manifests", "version"])
def test_unproven_downloads_are_not_published(missing):
    site = {"version": "0.1.0", "downloads": {"linux": "https://example.com/app.AppImage"},
            "checksums": {"linux": "a" * 64}, "manifests": {"linux": "https://example.com/app.manifest.json"},
            "release": {"qualified": True, "channel": "unrestricted-alpha", "source_revision": "b" * 40}}
    site.pop(missing)
    api = TestClient(create_app(None, site=site))
    result = api.get("/v1/site").json()
    assert result["downloads"] == {"windows": False, "linux": False}
    assert not result["release"]["qualified"]


def test_manual_qualification_is_required_even_with_complete_metadata():
    site = {"version": "0.1.0", "downloads": {"linux": "https://example.com/app.AppImage"},
            "checksums": {"linux": "a" * 64}, "manifests": {"linux": "https://example.com/app.manifest.json"},
            "release": {"qualified": False, "channel": "unrestricted-alpha", "source_revision": "b" * 40}}
    assert not TestClient(create_app(None, site=site)).get("/v1/site").json()["downloads"]["linux"]


def test_public_sales_pages_do_not_promise_disabled_licensing():
    public = Path(__file__).resolve().parents[1] / "public"
    for name in ("index.html", "download.html", "quote.html", "site.js"):
        text = (public / name).read_text().lower()
        for obsolete in ("7-day trial", "free for 7 days", "buy single", "buy team", "$39", "$149"):
            assert obsolete not in text, (name, obsolete)
    assert "unrestricted alpha" in (public / "index.html").read_text().lower()


@pytest.mark.parametrize("purpose", ["download", "signin"])
def test_customer_emails_match_current_alpha_policy(monkeypatch, purpose):
    from _licence.mail import Mailer

    mailer = Mailer(host="smtp.example.com", sender="support@example.com")
    messages = []
    monkeypatch.setattr(mailer, "_send", messages.append)
    mailer.send_code("person@example.com", "123456", purpose)
    body = messages[0].get_content().lower()
    assert "unrestricted alpha" in body
    assert "7-day" not in body and "free trial" not in body
    assert "activate this computer" not in body