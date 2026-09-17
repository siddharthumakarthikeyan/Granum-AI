"""The Granum window: the dashboard in a standalone Qt WebEngine (Chromium) window.

Used by the self-contained app, which bundles PySide6. Browser storage is kept in a
persistent profile, so the reviewer name and unsaved-edit recovery survive restarts, and
the window reopens at its last size. Closing the window leaves the service running.
"""

from __future__ import annotations

import json
import os
import sys
from importlib import resources
from pathlib import Path


def available() -> bool:
    import importlib.util

    try:
        return importlib.util.find_spec("PySide6.QtWebEngineWidgets") is not None
    except ModuleNotFoundError:
        return False


def run(url: str, storage: Path, state: Path) -> int:
    """Show ``url`` in a window and block until it is closed. Returns the exit code."""
    # Chromium's sandbox needs privileges an unprivileged, relocatable bundle does not have.
    os.environ.setdefault("QTWEBENGINE_DISABLE_SANDBOX", "1")
    os.environ.setdefault("QTWEBENGINE_CHROMIUM_FLAGS", "--enable-gpu-rasterization --ignore-gpu-blocklist")

    from PySide6.QtCore import QSize, QUrl
    from PySide6.QtGui import QDesktopServices, QIcon
    from PySide6.QtWebEngineCore import QWebEnginePage, QWebEngineProfile
    from PySide6.QtWebEngineWidgets import QWebEngineView
    from PySide6.QtWidgets import QApplication, QMainWindow

    app = QApplication.instance() or QApplication(sys.argv[:1])
    app.setApplicationName("Granum")
    app.setOrganizationName("Granum")
    # The Wayland app id and X11 WM class, so the dock shows the Granum launcher's icon.
    app.setDesktopFileName("granum")
    icon = QIcon(str(resources.files("granum") / "assets" / "granum-256.png"))
    app.setWindowIcon(icon)

    storage.mkdir(parents=True, exist_ok=True)
    state.mkdir(parents=True, exist_ok=True)
    profile = QWebEngineProfile("granum", app)
    profile.setPersistentStoragePath(str(storage / "storage"))
    profile.setCachePath(str(storage / "cache"))
    profile.setPersistentCookiesPolicy(QWebEngineProfile.PersistentCookiesPolicy.AllowPersistentCookies)

    class Page(QWebEnginePage):
        def acceptNavigationRequest(self, target: QUrl, kind, is_main_frame: bool) -> bool:  # noqa: N802 - Qt API
            # Anything outside the local service opens in the user's browser.
            if target.host() not in ("127.0.0.1", "localhost") and target.scheme() in ("http", "https"):
                QDesktopServices.openUrl(target)
                return False
            return super().acceptNavigationRequest(target, kind, is_main_frame)

        def createWindow(self, _kind):  # noqa: N802 - Qt API
            return self  # links meant for a new tab stay in this window

    size_file = state / "window.json"

    class Window(QMainWindow):
        def closeEvent(self, event) -> None:  # noqa: N802 - Qt API
            try:
                size_file.write_text(json.dumps({"width": self.width(), "height": self.height(),
                                                 "maximized": self.isMaximized()}))
            except OSError:
                pass
            super().closeEvent(event)

    view = QWebEngineView()
    page = Page(profile, view)
    view.setPage(page)
    view.titleChanged.connect(lambda title: window.setWindowTitle(title or "Granum"))

    window = Window()
    window.setWindowTitle("Granum")
    window.setWindowIcon(icon)
    window.setCentralWidget(view)
    window.setMinimumSize(QSize(900, 600))
    saved = _saved_size(size_file)
    window.resize(saved[0], saved[1])
    view.load(QUrl(url))
    if saved[2]:
        window.showMaximized()
    else:
        window.show()
    return app.exec()


def _saved_size(path: Path) -> tuple[int, int, bool]:
    try:
        data = json.loads(path.read_text())
        return max(900, int(data["width"])), max(600, int(data["height"])), bool(data.get("maximized"))
    except (OSError, ValueError, KeyError, TypeError):
        return 1440, 900, False
