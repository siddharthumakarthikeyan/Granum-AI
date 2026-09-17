"""Granum as an installed app: service and launcher files, and that data is never touched."""

import subprocess
import sys
from pathlib import Path

import pytest

from granum.cli import desktop
from granum.core.url import Url

SRC = str(Path(__file__).resolve().parents[1] / "src")
#: systemd units, freedesktop launchers and AppImages exist only on Linux.
linux_only = pytest.mark.skipif(sys.platform == "win32", reason="Linux app integration")


@pytest.fixture
def home(tmp_path, monkeypatch):
    """Point every per-user location at a temporary home."""
    for name, folder in (("XDG_CONFIG_HOME", ".config"), ("XDG_DATA_HOME", ".local/share"), ("XDG_STATE_HOME", ".local/state")):
        monkeypatch.setenv(name, str(tmp_path / folder))
    # Never reach the real user's service manager from a test.
    monkeypatch.setenv("GRANUM_NO_SYSTEMD", "1")
    monkeypatch.delenv("APPIMAGE", raising=False)
    return tmp_path


@linux_only
def test_unit_runs_this_python_on_a_fixed_root_and_port(tmp_path):
    root = tmp_path / "granum"
    text = desktop.unit_text(8123, root, tmp_path / "service.log")
    assert f"ExecStart={sys.executable} -m granum service --host 127.0.0.1 --port 8123" in text
    assert f"Environment=GRANUM_PROJECT_ROOT_URL={root}" in text
    assert f"WorkingDirectory={tmp_path / 'granum-training'}" in text
    assert "Restart=on-failure" in text and "WantedBy=default.target" in text


def test_launcher_install_and_uninstall_keep_project_data(home, monkeypatch):
    monkeypatch.setattr(desktop.sys, "platform", "linux")
    root = home / "granum"
    (root / "projects" / "aerial").mkdir(parents=True)
    (root / "projects" / "aerial" / "keep.txt").write_text("data")

    steps = desktop.install(8000, root, autostart=False, launcher=True)
    paths = desktop.AppPaths.for_user()
    assert paths.desktop.exists() and "-m granum open" in paths.desktop.read_text()
    assert paths.icon_svg.read_bytes().startswith(b"<svg") and paths.icon_png.stat().st_size > 1000
    assert (home / "granum-training").is_dir()
    assert any("launcher" in s for s in steps)

    # Installing again is an upgrade, not a reset.
    desktop.install(8000, root, autostart=False, launcher=True)
    desktop.uninstall()
    assert not paths.desktop.exists() and not paths.icon_svg.exists()
    assert (root / "projects" / "aerial" / "keep.txt").read_text() == "data"


def test_app_install_pins_the_project_root(home):
    import os

    # HOME stays real so user-installed packages still import; XDG folders isolate the app files.
    env = {**{k: v for k, v in os.environ.items() if not k.startswith("GRANUM_")}, "HOME": os.environ.get("HOME", ""),
           "GRANUM_NO_SYSTEMD": "1",
           "PYTHONPATH": SRC, "XDG_CONFIG_HOME": str(home / ".config"),
           "XDG_DATA_HOME": str(home / ".local/share"), "XDG_STATE_HOME": str(home / ".local/state")}
    root = home / "data" / "granum"
    done = subprocess.run(
        [sys.executable, "-m", "granum", "--project-root-url", str(root), "app", "install", "--no-autostart", "--no-launcher"],
        capture_output=True, text=True, env=env,
    )
    assert done.returncode == 0, done.stderr
    config = (home / ".config" / "granum" / "config.granum.yaml").read_text()
    assert f"project-root-url: {root}" in config
    # Without any flag, later commands now use the pinned root.
    shown = subprocess.run([sys.executable, "-m", "granum", "config", "project-root"], capture_output=True, text=True, env=env)
    assert shown.stdout.strip() == str(Url(root))
    status = subprocess.run([sys.executable, "-m", "granum", "app", "status"], capture_output=True, text=True, env=env)
    assert status.returncode == 0 and "not installed" in status.stdout and str(root) in status.stdout


@linux_only
def test_appimage_installs_a_copy_that_the_service_and_launcher_use(home, monkeypatch):
    monkeypatch.setattr(desktop.sys, "platform", "linux")
    download = home / "Downloads" / "Granum-0.1.0-x86_64.AppImage"
    download.parent.mkdir()
    download.write_bytes(b"\x7fELF" + b"v1" * 1000)
    monkeypatch.setenv("APPIMAGE", str(download))

    assert desktop.needs_install(8000)
    desktop.install(8000, home / "granum", autostart=False, launcher=True)
    installed = desktop.installed_appimage()
    assert installed.read_bytes() == download.read_bytes() and installed.stat().st_mode & 0o111
    assert desktop.service_command(8000)[:2] == [str(installed), "service"]
    assert desktop.AppPaths.for_user().desktop.read_text().splitlines()[5] == f"Exec={installed}"
    assert not desktop.needs_install(8000)

    # The downloaded file can be deleted; a newer download replaces the installed copy.
    download.write_bytes(b"\x7fELF" + b"v2" * 1000)
    assert desktop.needs_install(8000) and desktop.install_appimage()
    assert installed.read_bytes().endswith(b"v2")


def test_training_addon_installs_into_its_own_folder(home, tmp_path, monkeypatch):
    import sys as system
    import zipfile

    from granum import addons

    # A tiny local wheel stands in for PyTorch, so the test needs no network.
    wheel = tmp_path / "granumprobe-1.0-py3-none-any.whl"
    with zipfile.ZipFile(wheel, "w") as archive:
        archive.writestr("granumprobe/__init__.py", "VALUE = 42\n")
        archive.writestr("granumprobe-1.0.dist-info/METADATA", "Metadata-Version: 2.1\nName: granumprobe\nVersion: 1.0\n")
        archive.writestr("granumprobe-1.0.dist-info/WHEEL", "Wheel-Version: 1.0\nGenerator: test\nRoot-Is-Purelib: true\nTag: py3-none-any\n")
        archive.writestr("granumprobe-1.0.dist-info/RECORD", "")
    monkeypatch.setattr(addons, "TRAINING_PACKAGES", ["--no-index", str(wheel)])
    monkeypatch.setattr(system, "path", list(system.path))
    monkeypatch.setenv("PYTHONPATH", "")

    lines = []
    target = addons.install_training(lines.append)
    assert target == addons.training_dir() and (target / ".complete").exists()
    assert str(target).startswith(str(home)) and (target / "granumprobe" / "__init__.py").exists()
    assert addons.installed_dirs() == [target] and str(target) in system.path
    assert not target.with_name(target.name + ".partial").exists() and lines


def test_window_finds_the_display_when_a_launcher_does_not_pass_it(tmp_path, monkeypatch):
    """GNOME can start apps without WAYLAND_DISPLAY/DISPLAY; the window must still find the screen."""
    runtime = tmp_path / "run"
    runtime.mkdir()
    (runtime / "wayland-0").write_text("")
    (runtime / "wayland-0.lock").write_text("")
    for name in desktop.SESSION_VARIABLES:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(runtime))
    monkeypatch.setattr(desktop.sys, "platform", "linux")
    monkeypatch.setattr(desktop.shutil, "which", lambda _name: None)  # no systemd: use the sockets

    desktop.adopt_session_display()
    assert desktop.os.environ["WAYLAND_DISPLAY"] == "wayland-0"
