"""The download the site offers follows the approved GitHub release, and nothing less."""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from _licence.app import create_app
from _licence.config import site_from_env
from _licence.releases import ApprovedRelease

REPOSITORY = "owner/app"


def release(**changes):
    out = {
        "format_version": 1, "tag": "build-0.1.0-abcdef123456", "version": "0.1.0",
        "channel": "unrestricted-alpha", "source_revision": "c" * 40,
        "files": {
            "linux": {"name": "Granum-0.1.0-x86_64.AppImage", "sha256": "a" * 64, "manifest": "Granum-0.1.0-x86_64.AppImage.manifest.json"},
            "windows": {"name": "Granum-0.1.0-Setup.exe", "sha256": "b" * 64, "manifest": "Granum-0.1.0-Setup.exe.manifest.json"},
        },
    }
    out.update(changes)
    return out


class GitHub:
    """Stands in for GitHub: answers with whatever release is approved right now."""

    def __init__(self, approved=None):
        self.approved, self.asked, self.down = approved, [], False

    def __call__(self, url):
        self.asked.append(url)
        if self.down or self.approved is None:
            raise OSError("404")
        return json.dumps(self.approved).encode()


def site(github, now=lambda: 0.0):
    return TestClient(create_app(None, site=ApprovedRelease(REPOSITORY, contact="hello@example.com", fetch=github, clock=now)))


def test_an_approved_release_is_offered_with_its_links_checksums_and_manifests():
    github = GitHub(release())
    api = site(github)
    shown = api.get("/v1/site").json()
    assert shown == {"version": "0.1.0", "contact": "hello@example.com",
                     "release": {"channel": "unrestricted-alpha", "source_revision": "c" * 40, "qualified": True},
                     "downloads": {"windows": True, "linux": True}}
    assert github.asked == ["https://github.com/owner/app/releases/latest/download/release.json"]

    from _licence.releases import site_of

    settings = site_of(release(), REPOSITORY)
    base = "https://github.com/owner/app/releases/download/build-0.1.0-abcdef123456/"
    assert settings["downloads"] == {"windows": base + "Granum-0.1.0-Setup.exe", "linux": base + "Granum-0.1.0-x86_64.AppImage"}
    assert settings["manifests"]["linux"] == base + "Granum-0.1.0-x86_64.AppImage.manifest.json"
    assert settings["checksums"] == {"windows": "b" * 64, "linux": "a" * 64}


def test_nothing_is_offered_until_a_build_is_approved():
    api = site(GitHub())
    shown = api.get("/v1/site").json()
    assert shown["downloads"] == {"windows": False, "linux": False} and not shown["release"]["qualified"]
    assert shown["contact"] == "hello@example.com"


@pytest.mark.parametrize("broken", [
    {"source_revision": "main"},                       # not a commit
    {"channel": "licensed-alpha"},                     # not the channel the site describes
    {"version": ""},
    {"tag": "../../evil"},                             # would leave the release's folder
    {"files": {"linux": {"name": "a/b.AppImage", "sha256": "a" * 64, "manifest": "m.json"}}},
    {"files": {"linux": {"name": "Granum.AppImage", "sha256": "short", "manifest": "m.json"}}},
    {"files": {"linux": {"name": "Granum.AppImage", "sha256": "a" * 64}}},
    {"files": "none"},
])
def test_a_release_that_does_not_prove_itself_is_not_offered(broken):
    shown = site(GitHub(release(**broken))).get("/v1/site").json()
    assert shown["downloads"] == {"windows": False, "linux": False}


def test_one_platform_can_be_offered_without_the_other():
    only = release(files={"linux": release()["files"]["linux"]})
    assert site(GitHub(only)).get("/v1/site").json()["downloads"] == {"windows": False, "linux": True}


def test_a_newly_approved_build_is_picked_up_and_an_outage_keeps_the_last_one():
    time = [0.0]
    github = GitHub(release())
    api = site(github, now=lambda: time[0])
    revision = lambda: api.get("/v1/site").json()["release"]["source_revision"]  # noqa: E731
    assert revision() == "c" * 40 and revision() == "c" * 40
    assert len(github.asked) == 1  # answered from memory within five minutes

    github.approved = release(source_revision="d" * 40, tag="build-0.1.0-dddddddddddd")
    time[0] = 299
    assert revision() == "c" * 40
    time[0] = 301
    assert revision() == "d" * 40 and len(github.asked) == 2

    github.down = True
    time[0] = 900
    assert revision() == "d" * 40 and len(github.asked) == 3


def test_links_set_by_hand_still_win_over_the_release(monkeypatch):
    for name in ("DOWNLOAD_WINDOWS_URL", "DOWNLOAD_LINUX_URL", "DOWNLOAD_RELEASE_REPOSITORY"):
        monkeypatch.delenv(name, raising=False)
    followed = site_from_env()
    assert isinstance(followed, ApprovedRelease) and followed.repository == "siddharthumakarthikeyan/Granum-AI"
    monkeypatch.setenv("DOWNLOAD_RELEASE_REPOSITORY", "someone/else")
    assert site_from_env().repository == "someone/else"
    monkeypatch.setenv("DOWNLOAD_LINUX_URL", "https://example.com/app.AppImage")
    by_hand = site_from_env()
    assert isinstance(by_hand, dict) and by_hand["downloads"]["linux"] == "https://example.com/app.AppImage"
    with pytest.raises(ValueError):
        ApprovedRelease("not a repository")
