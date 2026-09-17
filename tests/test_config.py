import pytest

from granum.core.config import Config, Tier
from granum.core.url import get_registered_url_aliases
from granum.errors import ConfigError


def test_defaults_have_default_provenance():
    config = Config.load(use_config_files=False, use_env=False)
    item = config.provenance("log-level")
    assert item.value == "WARNING"
    assert item.tier is Tier.DEFAULT
    assert item.is_default


def test_env_beats_default(monkeypatch):
    monkeypatch.setenv("GRANUM_LOG_LEVEL", "DEBUG")
    config = Config.load(use_config_files=False)
    item = config.provenance("log-level")
    assert item.value == "DEBUG"
    assert item.tier is Tier.ENV
    assert "GRANUM_LOG_LEVEL" in item.source


def test_override_beats_env(monkeypatch):
    monkeypatch.setenv("GRANUM_LOG_LEVEL", "DEBUG")
    config = Config.load(overrides={"log-level": "ERROR"}, use_config_files=False)
    assert config.get("log-level") == "ERROR"
    assert config.provenance("log-level").tier is Tier.OVERRIDE


def test_file_beats_default_and_reports_path(tmp_path):
    path = tmp_path / "config.granum.yaml"
    path.write_text("log-level: INFO\nindexing:\n  scan-interval: 42\n")
    config = Config.load(config_file=str(path), use_env=False)
    assert config.get("log-level") == "INFO"
    assert config.get("indexing.scan-interval") == 42
    assert str(path) in config.provenance("log-level").source


def test_typed_env_parsing(monkeypatch):
    monkeypatch.setenv("GRANUM_INDEXING_SCAN_INTERVAL", "30")
    monkeypatch.setenv("GRANUM_DISPLAY_PROGRESS", "false")
    config = Config.load(use_config_files=False)
    assert config.get("indexing.scan-interval") == 30
    assert config.get("display-progress") is False


def test_aliases_from_config_file(tmp_path):
    path = tmp_path / "config.granum.yaml"
    path.write_text("aliases:\n  PROJECT_DATA: /mnt/data\n")
    Config.load(config_file=str(path), use_env=False)
    assert get_registered_url_aliases()["PROJECT_DATA"] == "/mnt/data"


def test_validate_catches_bad_values():
    config = Config.load(
        overrides={"log-level": "LOUD", "indexing.scan-interval": 0},
        use_config_files=False,
        use_env=False,
    )
    problems = config.validate()
    assert len(problems) == 2


def test_unknown_option_raises():
    config = Config.load(use_config_files=False, use_env=False)
    with pytest.raises(ConfigError):
        config.get("no-such-option")


def test_to_yaml_roundtrips(tmp_path):
    config = Config.load(overrides={"log-level": "INFO"}, use_config_files=False, use_env=False)
    path = tmp_path / "out.yaml"
    path.write_text(config.to_yaml())
    reloaded = Config.load(config_file=str(path), use_env=False)
    assert reloaded.get("log-level") == "INFO"


def test_malformed_yaml_raises(tmp_path):
    path = tmp_path / "config.granum.yaml"
    path.write_text("- just\n- a list\n")
    with pytest.raises(ConfigError):
        Config.load(config_file=str(path), use_env=False)
