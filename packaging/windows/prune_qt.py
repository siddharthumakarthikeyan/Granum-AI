"""Remove the parts of PySide6 the Granum window never loads (Windows).

The Windows counterpart of ``packaging/linux/prune_qt.py``. PySide6-Addons ships every Qt
module; the window needs only Qt WebEngine and what it links against. The DLL closure of the
kept bindings, plugins and QtWebEngineProcess.exe is computed from their PE import tables
(``pefile``), and every other Qt DLL and binding is deleted.

    python prune_qt.py <site-packages>/PySide6
"""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

import pefile

KEEP_MODULES = {"QtCore", "QtGui", "QtWidgets", "QtNetwork", "QtWebEngineCore", "QtWebEngineWidgets", "QtWebChannel"}
KEEP_PLUGINS = {"platforms", "styles", "imageformats", "iconengines", "tls", "networkinformation", "generic"}
KEEP_PLATFORMS = ("qwindows", "qoffscreen", "qminimal")
#: Loaded at run time rather than linked: software OpenGL for machines without a usable GPU
#: driver (virtual machines, remote desktop), and the Direct3D shader compiler ANGLE uses.
ALWAYS_KEEP = {"opengl32sw.dll", "d3dcompiler_47.dll"}


def imports(path: Path) -> set[str]:
    try:
        pe = pefile.PE(str(path), fast_load=True)
        pe.parse_data_directories(directories=[pefile.DIRECTORY_ENTRY["IMAGE_DIRECTORY_ENTRY_IMPORT"],
                                               pefile.DIRECTORY_ENTRY["IMAGE_DIRECTORY_ENTRY_DELAY_IMPORT"]])
    except pefile.PEFormatError:
        return set()
    found = set()
    for attribute in ("DIRECTORY_ENTRY_IMPORT", "DIRECTORY_ENTRY_DELAY_IMPORT"):
        for entry in getattr(pe, attribute, []):
            found.add(entry.dll.decode(errors="replace").lower())
    pe.close()
    return found


def main(pyside: Path) -> None:
    before = sum(f.stat().st_size for f in pyside.rglob("*") if f.is_file())
    # Qt DLLs sit beside the bindings in the Windows wheels; allow a Qt/bin layout too.
    dll_dirs = [d for d in (pyside, pyside / "Qt" / "bin") if d.is_dir()]
    dlls = {f.name.lower(): f for d in dll_dirs for f in d.glob("*.dll")}

    for stub in pyside.glob("*.pyi"):
        stub.unlink()

    plugins = next((p for p in (pyside / "plugins", pyside / "Qt" / "plugins") if p.is_dir()), None)
    if plugins is not None:
        for folder in plugins.iterdir():
            if folder.is_dir() and folder.name not in KEEP_PLUGINS:
                shutil.rmtree(folder)
        for plugin in (plugins / "platforms").glob("*.dll") if (plugins / "platforms").is_dir() else []:
            if not plugin.stem.lower().startswith(KEEP_PLATFORMS):
                plugin.unlink()

    def closure(bindings: set[str]) -> set[str]:
        roots = [*(pyside / f"{m}.pyd" for m in bindings), *pyside.glob("pyside6*.dll"), *pyside.glob("shiboken6*.dll"),
                 *(plugins.rglob("*.dll") if plugins is not None else []), *pyside.rglob("QtWebEngineProcess.exe")]
        found: set[str] = set()
        queue = [r for r in roots if r.exists()]
        while queue:
            for name in imports(queue.pop()):
                if name not in found and name in dlls:
                    found.add(name)
                    queue.append(dlls[name])
        return found

    # A binding imports the bindings of the libraries it links, so keep every binding whose
    # Qt library is still needed.
    available = {b.name.split(".")[0] for b in pyside.glob("Qt*.pyd")}
    modules = set(KEEP_MODULES) & available
    while True:
        keep = closure(modules)
        linked = {m for m in available if f"qt6{m[2:].lower()}.dll" in keep}
        if linked <= modules:
            break
        modules |= linked

    for binding in pyside.glob("Qt*.pyd"):
        if binding.name.split(".")[0] not in modules:
            binding.unlink()
    for name, library in dlls.items():
        if name.startswith("qt6") and name not in keep and name not in ALWAYS_KEEP:
            library.unlink()

    for extra in ("qml", "metatypes", "include", "mkspecs", "modules", "typesystems", "glue", "doc", "examples",
                  "scripts", "sbom", "lib"):
        target = pyside / extra
        if target.is_dir():
            shutil.rmtree(target)
    for tool in pyside.glob("*.exe"):
        if tool.name.lower() != "qtwebengineprocess.exe":
            tool.unlink()  # designer, linguist, assistant, qmlls, ...

    translations = pyside / "translations"
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
