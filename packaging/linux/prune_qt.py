"""Remove the parts of PySide6 the Granum window never loads.

PySide6-Addons ships every Qt module (3D, multimedia, charts, ...). The window needs only
Qt WebEngine and what it links against, so everything else is deleted, keeping exactly the
closure of shared libraries the kept modules, plugins and QtWebEngineProcess depend on.

    python prune_qt.py <site-packages>/PySide6
"""

from __future__ import annotations

import re
import shutil
import subprocess
import sys
from pathlib import Path

KEEP_MODULES = {"QtCore", "QtGui", "QtWidgets", "QtNetwork", "QtWebEngineCore", "QtWebEngineWidgets", "QtWebChannel"}
KEEP_PLUGINS = {
    "platforms", "platformthemes", "platforminputcontexts", "xcbglintegrations", "wayland-decoration-client",
    "wayland-graphics-integration-client", "wayland-shell-integration", "imageformats", "iconengines", "tls",
    "networkinformation", "egldeviceintegrations",
}
KEEP_PLATFORMS = ("libqxcb.so", "libqwayland", "libqoffscreen.so")


def needed(path: Path) -> set[str]:
    out = subprocess.run(["readelf", "-d", str(path)], capture_output=True, text=True).stdout
    return set(re.findall(r"\(NEEDED\)\s+Shared library: \[(.+?)\]", out))


def main(pyside: Path) -> None:
    qt = pyside / "Qt"
    lib = qt / "lib"
    before = sum(f.stat().st_size for f in pyside.rglob("*") if f.is_file())

    for stub in pyside.glob("*.pyi"):
        stub.unlink()

    plugins = qt / "plugins"
    for folder in plugins.iterdir() if plugins.is_dir() else []:
        if folder.name not in KEEP_PLUGINS:
            shutil.rmtree(folder)
    for plugin in (plugins / "platforms").glob("*.so") if (plugins / "platforms").is_dir() else []:
        if not plugin.name.startswith(KEEP_PLATFORMS):
            plugin.unlink()

    def closure(bindings: set[str]) -> set[str]:
        roots = [*(pyside / f"{m}.abi3.so" for m in bindings), *pyside.glob("libpyside6*.so*"),
                 *plugins.rglob("*.so"), *(qt / "libexec").glob("QtWebEngineProcess")]
        found: set[str] = set()
        queue = [r for r in roots if r.exists()]
        while queue:
            for name in needed(queue.pop()):
                candidate = lib / name
                if name not in found and candidate.exists():
                    found.add(name)
                    queue.append(candidate)
        return found

    # A binding imports the bindings of the libraries it links (QtWebEngineCore imports
    # QtPrintSupport, QtQuick, ...), so keep every binding whose library is still needed.
    available = {b.name.split(".")[0] for b in pyside.glob("Qt*.abi3.so")}
    modules = set(KEEP_MODULES) & available
    while True:
        keep = closure(modules)
        linked = {m for m in available if f"libQt6{m[2:]}.so.6" in keep}
        if linked <= modules:
            break
        modules |= linked

    for binding in pyside.glob("Qt*.abi3.so"):
        if binding.name.split(".")[0] not in modules:
            binding.unlink()
    for library in lib.glob("*.so*"):
        if library.name not in keep and library.name.startswith(("libQt6", "libicu")):
            library.unlink()

    for extra in ("qml", "metatypes", "include", "mkspecs", "modules", "sbom"):
        shutil.rmtree(qt / extra, ignore_errors=True)
    for extra in ("include", "typesystems", "glue", "doc", "examples", "scripts"):
        shutil.rmtree(pyside / extra, ignore_errors=True)
    for tool in pyside.iterdir():
        if tool.is_file() and tool.suffix == "" and tool.stat().st_mode & 0o111:
            tool.unlink()  # designer, linguist, assistant, qmlls, ...
    for app in ("Designer.app", "Linguist.app", "Assistant.app"):
        shutil.rmtree(pyside / app, ignore_errors=True)

    translations = qt / "translations"
    if translations.is_dir():
        for item in translations.iterdir():
            if item.name != "qtwebengine_locales":
                shutil.rmtree(item) if item.is_dir() else item.unlink()
        locales = translations / "qtwebengine_locales"
        for pak in locales.glob("*.pak") if locales.is_dir() else []:
            if pak.name != "en-US.pak":
                pak.unlink()

    after = sum(f.stat().st_size for f in pyside.rglob("*") if f.is_file())
    print(f"PySide6 trimmed from {before / 1e6:.0f} MB to {after / 1e6:.0f} MB; kept {len(keep)} Qt libraries, "
          f"bindings: {', '.join(sorted(modules))}")


if __name__ == "__main__":
    main(Path(sys.argv[1]))
