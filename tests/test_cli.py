import subprocess
import sys
from pathlib import Path

from granum.core.url import Url

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
