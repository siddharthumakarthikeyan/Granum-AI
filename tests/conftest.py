import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from granum.core.config import Config, set_config  # noqa: E402
from granum.core.url import _clear_url_aliases  # noqa: E402
from granum.licensing import Licensing, set_licensing  # noqa: E402


@pytest.fixture(autouse=True)
def isolated_project(tmp_path, monkeypatch):
    """Every test gets a fresh project root, config and alias registry."""
    _clear_url_aliases()
    for key in [k for k in os.environ if k.startswith("GRANUM_")]:
        monkeypatch.delenv(key, raising=False)
    root = tmp_path / "granum-root"
    config = Config.load(
        overrides={"project-root-url": str(root)},
        use_config_files=False,
        use_env=False,
    )
    set_config(config)
    # Tests run with no licence limits; tests of licensing make their own Licensing.
    set_licensing(Licensing.open())
    yield root
    set_licensing(None)
    set_config(None)
    _clear_url_aliases()


@pytest.fixture
def image_folder(tmp_path):
    """A directory-per-class image folder with real (tiny) files."""
    root = tmp_path / "pets"
    for label, count in [("cat", 3), ("dog", 2)]:
        d = root / label
        d.mkdir(parents=True)
        for i in range(count):
            (d / f"{label}_{i}.jpg").write_bytes(b"\xff\xd8\xff\xe0not-a-real-jpeg")
    (root / "notes.txt").write_text("ignored: not an image")
    return root
