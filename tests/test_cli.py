import json
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from granum.core.url import Url, sample_key

SRC = str(Path(__file__).resolve().parents[1] / "src")


def run(*args, env=None):
    import os

    environment = {**os.environ, "PYTHONPATH": SRC}
    if env:
        environment.update(env)
    return subprocess.run(
        [sys.executable, "-m", "granum.cli.main", *args],
        capture_output=True,
        text=True,
        env=environment,
    )


def test_version():
    result = run("version")
    assert result.returncode == 0
    assert "granum" in result.stdout


def test_build_info_identifies_source_or_packaged_build():
    result = run("build-info")
    assert result.returncode == 0, result.stderr
    info = json.loads(result.stdout)
    assert info["version"] and info["kind"] in {"packaged", "source-checkout", "unverified-source"}


def test_network_service_without_auth_and_tls_fails_closed(tmp_path):
    result = run("--project-root-url", str(tmp_path), "service", "--host", "0.0.0.0", "--no-watch")
    assert result.returncode != 0
    assert "Network binding requires" in result.stderr


def test_config_show_lists_options():
    result = run("--no-config-file", "config", "show")
    assert result.returncode == 0
    assert "project-root-url" in result.stdout
    assert "log-level" in result.stdout


def test_config_show_detail_reports_provenance():
    result = run("--no-config-file", "config", "show", "--detail")
    assert "built-in default" in result.stdout


def test_config_show_single_option():
    result = run("--no-config-file", "config", "show", "log-level")
    assert "GRANUM_LOG_LEVEL" in result.stdout
    assert "env var" in result.stdout


def test_config_show_unknown_option_fails():
    result = run("--no-config-file", "config", "show", "not-an-option")
    assert result.returncode == 2


def test_config_show_yaml():
    result = run("--no-config-file", "config", "show", "-f", "yaml")
    assert "log-level:" in result.stdout


def test_config_validate_passes():
    result = run("--no-config-file", "config", "validate")
    assert result.returncode == 0
    assert "valid" in result.stdout


def test_config_validate_fails_on_bad_level():
    result = run("--no-config-file", "--log-level", "LOUD", "config", "validate")
    assert result.returncode == 1


def test_project_root_override(tmp_path):
    result = run("--project-root-url", str(tmp_path), "config", "project-root")
    assert str(Url(tmp_path)) in result.stdout


def test_competing_integrity_snapshots_do_not_overwrite(isolated_project, tmp_path):
    from granum import Table
    from granum.core.schemas import ImageSchema

    image = tmp_path / "media.png"
    image.write_bytes(b"baseline media")
    Table.from_dict_data({"image": [str(image)]}, schema={"image": ImageSchema(sample_type="url")}, project_name="p", dataset_name="d")
    manifest = tmp_path / "integrity.json"

    def snapshot(_):
        return run("--no-config-file", "--project-root-url", str(isolated_project), "integrity", "snapshot", "p", "--output", str(manifest))

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(snapshot, range(2)))
    assert sorted(result.returncode for result in results) == [0, 2], [result.stderr for result in results]
    assert "overwritten" in next(result.stderr for result in results if result.returncode)
    assert json.loads(manifest.read_text())["files"][sample_key(str(image))]["bytes"] == len(b"baseline media")
    assert run("integrity", "verify", str(manifest)).returncode == 0


def test_integrity_verify_reports_invalid_input_without_traceback(tmp_path):
    manifest = tmp_path / "invalid.json"
    manifest.write_text("[]")
    result = run("integrity", "verify", str(manifest))
    assert result.returncode == 1 and "unsupported media manifest" in result.stderr
    assert "Traceback" not in result.stderr
