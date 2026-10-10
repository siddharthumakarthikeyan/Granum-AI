import json
import runpy
import shutil
import subprocess
import zipfile
from pathlib import Path

import pytest

HELPERS = runpy.run_path(str(Path(__file__).resolve().parents[1] / "build_provenance.py"))


@pytest.fixture
def source(tmp_path, monkeypatch):
    monkeypatch.delenv("GRANUM_RELEASE_BUILD", raising=False)
    package = tmp_path / "src/granum"
    static = package / "service/static"
    static.mkdir(parents=True)
    (static / "index.html").write_text('<script src="/assets/app.js"></script>')
    (static / "assets").mkdir()
    (static / "assets/app.js").write_text("console.log('qualification')")
    (package / "licensing").mkdir()
    (package / "licensing/manager.py").write_text("ENFORCED = False\n")
    web = tmp_path / "web"
    (web / "src").mkdir(parents=True)
    (web / "src/app.ts").write_text("const app = 'qualification';")
    stamp = {"version": 1, "source_sha256": HELPERS["tree_hash"](web, HELPERS["WEB_INPUTS"]),
             "bundle_sha256": HELPERS["tree_hash"](static)}
    (static / "build-stamp.json").write_text(json.dumps(stamp))
    return tmp_path


def wheel(source, output):
    manifest = HELPERS["create_manifest"](source, "0.1.0")
    package = source / "src/granum"
    (package / "_build.json").write_text(json.dumps(manifest))
    with zipfile.ZipFile(output, "w") as archive:
        for path in package.rglob("*"):
            if path.is_file():
                archive.write(path, "granum/" + path.relative_to(package).as_posix())
    return manifest


def test_dashboard_reuse_requires_matching_source_and_built_bytes(source):
    assert HELPERS["dashboard_stamp"](source)
    (source / "web/src/app.ts").write_text("source changed")
    assert HELPERS["dashboard_stamp"](source) is None


def test_corrupt_dashboard_is_not_reused(source):
    (source / "src/granum/service/static/assets/app.js").write_text("bundle changed")
    assert HELPERS["dashboard_stamp"](source) is None


def test_wheel_records_actual_licensing_and_rejects_tampering(source, tmp_path):
    path = tmp_path / "test.whl"
    manifest = wheel(source, path)
    assert manifest["licensing_enforced"] is False
    assert manifest["channel"] == "unrestricted-alpha"
    assert HELPERS["verify_wheel"](path, version="0.1.0") == manifest
    with pytest.raises(ValueError, match="version"):
        HELPERS["verify_wheel"](path, version="2.0.0")
    with zipfile.ZipFile(path, "a") as archive:
        archive.writestr("granum/injected.py", "changed")
    with pytest.raises(ValueError, match="hashes"):
        HELPERS["verify_wheel"](path)


def test_old_wheel_without_provenance_is_not_a_desktop_release(tmp_path):
    path = tmp_path / "old.whl"
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("granum/__init__.py", "")
    with pytest.raises(ValueError, match="rebuild"):
        HELPERS["verify_wheel"](path)


def test_release_requires_known_clean_source(source, monkeypatch):
    monkeypatch.setenv("GRANUM_RELEASE_BUILD", "1")
    with pytest.raises(ValueError, match="clean Git"):
        HELPERS["create_manifest"](source, "0.1.0")


def test_node_stamp_and_python_verification_agree(source):
    node = shutil.which("node")
    if not node:
        pytest.skip("Node not installed")
    scripts = source / "web/scripts"
    scripts.mkdir()
    script = Path(__file__).resolve().parents[1] / "web/scripts/stamp-build.mjs"
    (scripts / script.name).write_bytes(script.read_bytes())
    subprocess.run([node, str(scripts / script.name)], check=True)
    assert HELPERS["dashboard_stamp"](source)