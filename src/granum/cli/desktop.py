"""Granum as an installed app: a background service that starts at login, a launcher in
the application menu, and one fixed home for everything it writes.

Nothing here touches project data. Installing again (for example after an upgrade)
rewrites the service and launcher files and leaves projects, reviews, shipments, runs and
model weights exactly as they were; uninstalling removes only the service and launcher.

Linux uses a systemd user service and a freedesktop launcher. Elsewhere the files are not
written and ``granum open`` starts the service in the background on demand instead; on
Windows the installer adds the Start menu shortcut, and closing the window stops an idle
service (``granum open`` starts it again).

The self-contained app (an AppImage) copies itself to ``~/.local/share/granum/Granum.AppImage``
on first launch, and the service and launcher run that copy, so the downloaded file can be
moved or deleted afterwards. Launching a newer download replaces the copy and restarts the
service.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import time
import urllib.request
from dataclasses import dataclass
from importlib import resources
from pathlib import Path

from granum.core import appdirs
from granum.processes import console_python, popen_detached

UNIT_NAME = "granum.service"
DESKTOP_NAME = "granum.desktop"
ICON_NAME = "granum"


def _xdg(variable: str, fallback: str) -> Path:
    return Path(os.environ.get(variable) or Path.home() / fallback)


@dataclass(frozen=True)
class AppPaths:
    """Where the installed app keeps its files. Project data lives under the project root."""

    unit: Path
    desktop: Path
    icon_svg: Path
    icon_png: Path
    state: Path

    @classmethod
    def for_user(cls) -> AppPaths:
        config = _xdg("XDG_CONFIG_HOME", ".config")
        data = _xdg("XDG_DATA_HOME", ".local/share")
        state = appdirs.state_dir()
        return cls(
            unit=config / "systemd" / "user" / UNIT_NAME,
            desktop=data / "applications" / DESKTOP_NAME,
            icon_svg=data / "icons" / "hicolor" / "scalable" / "apps" / f"{ICON_NAME}.svg",
            icon_png=data / "icons" / "hicolor" / "256x256" / "apps" / f"{ICON_NAME}.png",
            state=state,
        )


def installed_appimage() -> Path:
    return appdirs.data_dir() / "Granum.AppImage"


def running_appimage() -> Path | None:
    """The AppImage file this process was started from, if any."""
    path = os.environ.get("APPIMAGE")
    return Path(path) if path and Path(path).is_file() else None


def app_executable() -> list[str]:
    """How to run Granum: the installed AppImage when bundled, else this Python."""
    if running_appimage() is not None:
        return [str(installed_appimage())]
    if os.name == "nt":
        # UTF-8 mode, so text files read and write the same bytes as on Linux (not cp1252).
        return [console_python(sys.executable), "-X", "utf8", "-m", "granum"]
    return [sys.executable, "-m", "granum"]


def _same_file(a: Path, b: Path) -> bool:
    """Cheap identity check for large files: size plus the first and last megabyte."""
    try:
        if a.stat().st_size != b.stat().st_size:
            return False
        with a.open("rb") as fa, b.open("rb") as fb:
            if fa.read(1 << 20) != fb.read(1 << 20):
                return False
            size = a.stat().st_size
            fa.seek(max(0, size - (1 << 20)))
            fb.seek(max(0, size - (1 << 20)))
            return fa.read() == fb.read()
    except OSError:
        return False


def install_appimage() -> bool:
    """Copy the running AppImage into place. Returns True if the installed copy changed.

    Written to a temporary file and renamed, so a service still running the previous copy
    keeps its (now unlinked) file until it restarts.
    """
    source = running_appimage()
    target = installed_appimage()
    if source is None or source.resolve() == target.resolve() or (target.exists() and _same_file(source, target)):
        return False
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_suffix(".partial")
    shutil.copyfile(source, temporary)
    temporary.chmod(0o755)
    temporary.replace(target)
    return True


def needs_install(port: int) -> bool:
    """Whether the bundled app still has to be copied into place or its launcher written."""
    paths = AppPaths.for_user()
    source = running_appimage()
    if source is None:
        return False
    target = installed_appimage()
    stale = not target.exists() or (source.resolve() != target.resolve() and not _same_file(source, target))
    return stale or not paths.desktop.exists() or (has_systemd() and not paths.unit.exists())


def training_dir(project_root: Path) -> Path:
    """Where dashboard training writes model weights and downloads pretrained ones.

    Beside the project root, as ``granum.training.train`` has always used, so existing runs
    keep finding their weights.
    """
    return project_root.parent / "granum-training"


def service_command(port: int) -> list[str]:
    """The service, run by the installed app (or this same Python) so versions always match."""
    return [*app_executable(), "service", "--host", "127.0.0.1", "--port", str(port)]


def unit_text(port: int, project_root: Path, log_file: Path) -> str:
    command = " ".join(_quote(part) for part in service_command(port))
    return f"""[Unit]
Description=Granum data workbench (dashboard on http://127.0.0.1:{port})
After=network.target

[Service]
Type=simple
ExecStart={command}
WorkingDirectory={_quote(str(training_dir(project_root)))}
Environment=GRANUM_PROJECT_ROOT_URL={_quote(str(project_root))}
Environment=PYTHONUNBUFFERED=1
Restart=on-failure
RestartSec=3
# Restarting the service must not stop trainings it started: they run in their own sessions
# and the service reattaches to them when it comes back.
KillMode=process
StandardOutput=append:{log_file}
StandardError=append:{log_file}

[Install]
WantedBy=default.target
"""


def desktop_text(icon: Path) -> str:
    return f"""[Desktop Entry]
Type=Application
Name=Granum
GenericName=Data workbench
Comment=Better data. Better models.
Exec={" ".join(_quote(part) for part in app_executable())}{"" if running_appimage() else " open"}
Icon={icon}
Terminal=false
Categories=Development;Science;Graphics;
Keywords=dataset;annotation;review;computer vision;training;
StartupNotify=false
StartupWMClass=granum
"""


def _quote(value: str) -> str:
    return f'"{value}"' if any(c in value for c in ' "\\') else value


def url_for(port: int) -> str:
    return f"http://127.0.0.1:{port}"


def is_up(port: int, timeout: float = 1.0) -> bool:
    try:
        with urllib.request.urlopen(f"{url_for(port)}/api/health", timeout=timeout) as response:
            return response.status == 200
    except OSError:
        return False


def has_systemd() -> bool:
    # GRANUM_NO_SYSTEMD keeps test and portable runs away from the user's real service manager.
    if os.environ.get("GRANUM_NO_SYSTEMD"):
        return False
    return sys.platform.startswith("linux") and shutil.which("systemctl") is not None


def systemctl(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["systemctl", "--user", *args], capture_output=True, text=True)


def write_icons(paths: AppPaths) -> None:
    assets = resources.files("granum") / "assets"
    for name, target in (("granum.svg", paths.icon_svg), ("granum-256.png", paths.icon_png)):
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes((assets / name).read_bytes())


def install(port: int, project_root: Path, *, autostart: bool = True, launcher: bool = True) -> list[str]:
    """Set up the service and launcher. Returns what was done, one line per step."""
    paths = AppPaths.for_user()
    done: list[str] = []
    if install_appimage():
        done.append(f"app installed: {installed_appimage()}")
    for folder in (project_root, training_dir(project_root), paths.state):
        folder.mkdir(parents=True, exist_ok=True)
    done.append(f"data kept in {project_root} (projects) and {training_dir(project_root)} (model weights)")

    if autostart and has_systemd():
        paths.unit.parent.mkdir(parents=True, exist_ok=True)
        paths.unit.write_text(unit_text(port, project_root, paths.state / "service.log"))
        systemctl("daemon-reload")
        enabled = systemctl("enable", UNIT_NAME)
        # Restart, not start, so an upgrade or a changed port takes effect now.
        started = systemctl("restart", UNIT_NAME)
        if enabled.returncode or started.returncode:
            raise RuntimeError((enabled.stderr or started.stderr).strip() or "systemctl failed")
        done.append(f"background service installed and started: {paths.unit}")
    elif autostart:
        done.append("automatic start is only set up on Linux with systemd; use `granum open` to start Granum")

    if launcher and sys.platform.startswith("linux"):
        write_icons(paths)
        paths.desktop.parent.mkdir(parents=True, exist_ok=True)
        paths.desktop.write_text(desktop_text(paths.icon_svg))
        paths.desktop.chmod(0o755)
        if shutil.which("update-desktop-database"):
            subprocess.run(["update-desktop-database", str(paths.desktop.parent)], capture_output=True)
        done.append(f"launcher added to the application menu: {paths.desktop}")
    return done


def uninstall() -> list[str]:
    """Remove the service and launcher. Project data is never touched."""
    paths = AppPaths.for_user()
    done: list[str] = []
    if paths.unit.exists():
        if has_systemd():
            systemctl("disable", "--now", UNIT_NAME)
        paths.unit.unlink()
        if has_systemd():
            systemctl("daemon-reload")
        done.append(f"background service removed: {paths.unit}")
    for target in (paths.desktop, paths.icon_svg, paths.icon_png, installed_appimage()):
        if target.exists():
            target.unlink()
            done.append(f"removed {target}")
    return done or ["nothing was installed"]


SESSION_VARIABLES = ("WAYLAND_DISPLAY", "DISPLAY", "XAUTHORITY", "XDG_RUNTIME_DIR", "DBUS_SESSION_BUS_ADDRESS")


def adopt_session_display() -> None:
    """Fill in the display variables a launcher did not pass on.

    Apps started from the GNOME dock or menu can arrive without ``WAYLAND_DISPLAY`` and
    ``DISPLAY``; the login session still knows them, through the systemd user manager.
    """
    if not sys.platform.startswith("linux") or (os.environ.get("WAYLAND_DISPLAY") or os.environ.get("DISPLAY")):
        return
    runtime = Path(os.environ.get("XDG_RUNTIME_DIR") or f"/run/user/{os.getuid()}")
    if runtime.is_dir():
        os.environ.setdefault("XDG_RUNTIME_DIR", str(runtime))
    if shutil.which("systemctl") is not None:
        try:
            shown = subprocess.run(["systemctl", "--user", "show-environment"], capture_output=True, text=True, timeout=5).stdout
        except (OSError, subprocess.SubprocessError):
            shown = ""
        for line in shown.splitlines():
            name, _, value = line.partition("=")
            if name in SESSION_VARIABLES and value and not os.environ.get(name):
                os.environ[name] = value
    # Last resort: the compositor's sockets themselves.
    if not os.environ.get("WAYLAND_DISPLAY"):
        sockets = sorted(p.name for p in runtime.glob("wayland-[0-9]*") if not p.name.endswith(".lock")) if runtime.is_dir() else []
        if sockets:
            os.environ["WAYLAND_DISPLAY"] = sockets[0]
    if not os.environ.get("DISPLAY"):
        displays = sorted(Path("/tmp/.X11-unix").glob("X[0-9]*"))
        if displays:
            os.environ["DISPLAY"] = ":" + displays[0].name[1:]


def installed_runner() -> list[str] | None:
    """Granum's own installation that can show the window, when this process cannot.

    An older launcher (or a menu cache that still holds one) may start Granum with a Python
    that lacks the window toolkit; handing over to the installed app fixes that for good.
    """
    if os.environ.get("GRANUM_HANDED_OVER"):
        return None
    appimage = installed_appimage()
    if appimage.is_file() and os.access(appimage, os.X_OK):
        return [str(appimage)]
    venv_root = appdirs.data_dir() / "venv"
    venv = venv_root / "bin" / "python"
    # Compare environments, not interpreters: a venv's python is a symlink to the system one.
    if venv.exists() and Path(sys.prefix).resolve() != venv_root.resolve():
        probe = subprocess.run([str(venv), "-c", "import webview"], capture_output=True)
        if probe.returncode == 0:
            return [str(venv), "-m", "granum"]
    return None


def log_launch_environment() -> None:
    """Record why a launch chose the window or the browser, in the state folder's launch.log."""
    import importlib.util
    import traceback
    from datetime import datetime

    lines = [f"--- {datetime.now().isoformat(timespec='seconds')} pid {os.getpid()}",
             f"executable {sys.executable}", f"cwd {os.getcwd()}", f"platform {sys.platform}"]
    for name in (*SESSION_VARIABLES, "XDG_SESSION_TYPE", "PYTHONPATH", "PYTHONHOME", "VIRTUAL_ENV", "APPIMAGE"):
        lines.append(f"env {name}={os.environ.get(name)}")
    try:
        from granum.cli import window

        lines.append(f"qt window available {window.available()}")
    except Exception:  # noqa: BLE001 - diagnostics must never stop the launch
        lines.append("qt check failed: " + traceback.format_exc(limit=2).replace("\n", " | "))
    try:
        lines.append(f"webview spec {importlib.util.find_spec('webview')}")
    except Exception:  # noqa: BLE001
        lines.append("webview check failed: " + traceback.format_exc(limit=2).replace("\n", " | "))
    lines.append(f"sys.path {sys.path}")
    try:
        state = AppPaths.for_user().state
        state.mkdir(parents=True, exist_ok=True)
        with (state / "launch.log").open("a") as handle:
            handle.write("\n".join(lines) + "\n")
    except OSError:
        pass


def window_available() -> bool:
    """Whether a standalone window can be opened: a window toolkit and a display to show it on."""
    import importlib.util

    from granum.cli import window

    if not window.available() and importlib.util.find_spec("webview") is None:
        return False
    adopt_session_display()
    found = bool(os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY"))
    try:
        with (AppPaths.for_user().state / "launch.log").open("a") as handle:
            handle.write(f"after adopting: WAYLAND_DISPLAY={os.environ.get('WAYLAND_DISPLAY')} DISPLAY={os.environ.get('DISPLAY')} display found {found}\n")
    except OSError:
        pass
    if sys.platform.startswith("linux") and not found:
        return False
    return True


def _window_size(state: Path) -> tuple[int, int]:
    try:
        import json

        saved = json.loads((state / "window.json").read_text())
        return max(900, int(saved["width"])), max(600, int(saved["height"]))
    except (OSError, ValueError, KeyError, TypeError):
        return 1440, 900


def open_window(port: int) -> None:
    """Show the dashboard in its own window and block until it is closed.

    The window keeps browser storage between launches (the reviewer name, unsaved edit
    recovery), remembers its size, and closing it leaves the background service running.
    """
    import json

    from granum.cli import window as qt_window

    paths = AppPaths.for_user()
    if qt_window.available():
        qt_window.run(url_for(port), appdirs.data_dir() / "window-qt", paths.state)
        return

    import webview

    paths.state.mkdir(parents=True, exist_ok=True)
    storage = appdirs.data_dir() / "window"
    storage.mkdir(parents=True, exist_ok=True)
    if sys.platform.startswith("linux"):
        try:
            # The window's app id, so the dock shows it under the Granum launcher and icon.
            from gi.repository import GLib

            GLib.set_prgname(ICON_NAME)
            GLib.set_application_name("Granum")
        except (ImportError, ValueError):
            pass

    width, height = _window_size(paths.state)
    window = webview.create_window(
        "Granum", url_for(port), width=width, height=height, min_size=(900, 600), text_select=True,
    )

    def remember(new_width: int, new_height: int) -> None:
        try:
            (paths.state / "window.json").write_text(json.dumps({"width": new_width, "height": new_height}))
        except OSError:
            pass

    window.events.resized += remember
    icon = resources.files("granum") / "assets" / "granum-256.png"
    webview.start(private_mode=False, storage_path=str(storage), icon=str(icon))


def show_error(message: str, *, icon: str = "error", once: str | None = None) -> None:
    """Tell the user in a dialog when there is no terminal to print to (the Windows launcher).

    ``once`` names a marker file in the state folder: the dialog is then shown only the first
    time, so a permanent condition does not nag on every launch.
    """
    if os.name != "nt" or sys.stderr is not None:
        return
    if once is not None:
        marker = AppPaths.for_user().state / once
        if marker.exists():
            return
        try:
            marker.parent.mkdir(parents=True, exist_ok=True)
            marker.write_text("shown\n")
        except OSError:
            pass
    import ctypes

    try:
        flag = 0x10 if icon == "error" else 0x40  # MB_ICONERROR / MB_ICONINFORMATION
        flag |= 0x00040000 | 0x00010000  # MB_TOPMOST | MB_SETFOREGROUND: in front of the browser
        ctypes.windll.user32.MessageBoxW(None, message, "Granum", flag)
    except (AttributeError, OSError):
        pass


def stop_if_idle(port: int) -> bool:
    """Ask the service to exit unless it is busy (an import, a training it follows, an add-on
    install). Used on Windows, where nothing else would ever stop it. Returns whether it stops."""
    import json

    request = urllib.request.Request(f"{url_for(port)}/api/service/quit", data=b"{}", method="POST",
                                     headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=5) as response:
            return bool(json.loads(response.read()).get("stopping"))
    except (OSError, ValueError):
        return False


def ensure_running(port: int, project_root: Path, wait: float = 20.0) -> bool:
    """Start the service if it is not answering: through systemd when installed, else detached."""
    if is_up(port):
        return True
    paths = AppPaths.for_user()
    if paths.unit.exists() and has_systemd():
        systemctl("start", UNIT_NAME)
        if _wait_up(port, min(wait, 12.0)):
            return True
        # The service manager could not bring it up (a broken unit, a disabled user
        # session manager): start it directly so the app still opens.
    if not is_up(port):
        paths.state.mkdir(parents=True, exist_ok=True)
        folder = training_dir(project_root)
        folder.mkdir(parents=True, exist_ok=True)
        log = open(paths.state / "service.log", "ab")  # noqa: SIM115 - handed to the child process
        popen_detached(
            service_command(port), cwd=folder, stdout=log, stderr=log, stdin=subprocess.DEVNULL,
            env={**os.environ, "GRANUM_PROJECT_ROOT_URL": str(project_root), "PYTHONUTF8": "1"},
        )
    return _wait_up(port, wait)


def _wait_up(port: int, wait: float) -> bool:
    deadline = time.monotonic() + wait
    while time.monotonic() < deadline:
        if is_up(port):
            return True
        time.sleep(0.4)
    return False
