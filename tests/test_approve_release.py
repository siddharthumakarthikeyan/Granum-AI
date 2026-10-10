"""A build of main is described for the website only when its files prove what they are."""

from __future__ import annotations

import hashlib
import json
import runpy
from pathlib import Path

import pytest

tool = runpy.run_path(str(Path(__file__).resolve().parents[1] / "tools" / "approve_release.py"))
describe, NotPublishable = tool["describe"], tool["NotPublishable"]
REVISION = "c" * 40


def build(folder: Path, *, linux: dict | None = None, windows: dict | None = None) -> Path:
    """The files the two release workflows leave on the ``main-build`` pre-release."""
    for name, content, changes in (("Granum-0.1.0-x86_64.AppImage", b"linux app", linux),
                                   ("Granum-0.1.0-Setup.exe", b"windows installer", windows)):
        sha256 = hashlib.sha256(content).hexdigest()
        made = {"version": "0.1.0", "source_revision": REVISION, "source_dirty": False, "channel": "unrestricted-alpha", **(changes or {})}
        (folder / name).write_bytes(content)
        (folder / f"{name}.sha256").write_text(f"{sha256}  {name}\n")
        (folder / f"{name}.manifest.json").write_text(json.dumps({"format_version": 1, "artifact": name, "sha256": sha256, "build": made}))
    return folder


def test_a_complete_build_is_described_for_the_website(tmp_path):
    release = describe(build(tmp_path), revision=REVISION)
    assert release == {
        "format_version": 1, "tag": "build-0.1.0-cccccccccccc", "version": "0.1.0",
        "channel": "unrestricted-alpha", "source_revision": REVISION,
        "files": {
            "linux": {"name": "Granum-0.1.0-x86_64.AppImage", "sha256": hashlib.sha256(b"linux app").hexdigest(),
                      "manifest": "Granum-0.1.0-x86_64.AppImage.manifest.json"},
            "windows": {"name": "Granum-0.1.0-Setup.exe", "sha256": hashlib.sha256(b"windows installer").hexdigest(),
                        "manifest": "Granum-0.1.0-Setup.exe.manifest.json"},
        },
    }


def test_a_build_that_cannot_be_vouched_for_is_refused(tmp_path):
    def refused(name: str, **kwargs) -> str:
        folder = tmp_path / name
        folder.mkdir()
        build(folder, **{k: v for k, v in kwargs.items() if k in ("linux", "windows")})
        kwargs.get("spoil", lambda _folder: None)(folder)
        with pytest.raises(NotPublishable) as problem:
            describe(folder, revision=kwargs.get("revision"))
        return str(problem.value)

    assert "disagree on their source revision" in refused("mixed", windows={"source_revision": "d" * 40})
    assert "disagree on their version" in refused("versions", linux={"version": "0.2.0"})
    assert "clean tree" in refused("dirty", linux={"source_dirty": True})
    assert "does not name the commit" in refused("unknown", linux={"source_revision": "main"}, windows={"source_revision": "main"})
    assert "not from dddddddddddd" in refused("stale", revision="d" * 40)
    assert "not the file its checksum" in refused("changed", spoil=lambda f: (f / "Granum-0.1.0-Setup.exe").write_bytes(b"something else"))
    assert "found 0" in refused("one-platform", spoil=lambda f: (f / "Granum-0.1.0-x86_64.AppImage").unlink())
    assert "no manifest or checksum" in refused("bare", spoil=lambda f: (f / "Granum-0.1.0-Setup.exe.sha256").unlink())
