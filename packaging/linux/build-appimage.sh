#!/usr/bin/env bash
# Build Granum as a single self-contained AppImage: Python, every dependency, the dashboard
# and a Chromium-based window (Qt WebEngine) inside one executable file.
#
#   packaging/linux/build-appimage.sh            -> dist/Granum-<version>-x86_64.AppImage
#
# Needs: curl, tar, Node.js 20+ (to build the dashboard). Build on the oldest Linux you want
# to support (the bundled Python needs glibc 2.17+; Qt 6 needs glibc 2.28+).
set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
PBS_TAG="${PBS_TAG:-20260901}"
PY_FULL="${PY_FULL:-3.12.14}"
PYSIDE="${PYSIDE:-PySide6-Essentials==6.10.* PySide6-Addons==6.10.*}"
BUILD="$REPO/build/appimage"
CACHE="$REPO/build/cache"
APPDIR="$BUILD/Granum.AppDir"
VERSION="$(sed -n 's/^version = "\(.*\)"/\1/p' "$REPO/pyproject.toml" | head -1)"
OUT="$REPO/dist/Granum-$VERSION-x86_64.AppImage"

say() { printf '\033[1;36mbuild\033[0m %s\n' "$*"; }
fetch() { [ -s "$2" ] || { say "downloading $(basename "$2")"; curl -fsSL --retry 6 --retry-all-errors --retry-delay 5 -o "$2.partial" "$1" && mv "$2.partial" "$2"; }; }

mkdir -p "$CACHE" "$REPO/dist"
rm -rf "$APPDIR"
mkdir -p "$APPDIR/usr/lib"

# 1. A relocatable CPython.
PBS="cpython-$PY_FULL+$PBS_TAG-x86_64-unknown-linux-gnu-install_only_stripped.tar.gz"
fetch "https://github.com/astral-sh/python-build-standalone/releases/download/$PBS_TAG/${PBS/+/%2B}" "$CACHE/$PBS"
tar -xzf "$CACHE/$PBS" -C "$APPDIR/usr"
PY="$APPDIR/usr/python/bin/python3"

# 2. The dashboard and the Granum wheel.
say "building the dashboard"
(cd "$REPO/web" && npm ci --no-audit --no-fund >/dev/null && npm run build >/dev/null)
rm -rf "$BUILD/wheel"
say "building the granum wheel"
"$PY" -m pip install --quiet --disable-pip-version-check build
"$PY" -m build --wheel --outdir "$BUILD/wheel" "$REPO" >/dev/null
WHEEL="$(ls "$BUILD"/wheel/granum-*.whl)"

# 3. Everything Granum needs, into the bundled Python.
say "installing granum and its dependencies"
# shellcheck disable=SC2086
"$PY" -m pip install --quiet --disable-pip-version-check --no-warn-script-location \
  "$WHEEL[service,images,pandas]" $PYSIDE
"$PY" -m pip uninstall --quiet -y build pyproject_hooks >/dev/null 2>&1 || true

# 4. Trim what an app never uses.
say "trimming"
PYLIB="$APPDIR/usr/python/lib/python${PY_FULL%.*}"
rm -rf "$PYLIB"/{test,idlelib,tkinter,turtledemo,lib2to3,ensurepip/_bundled} "$APPDIR/usr/python/include" \
       "$APPDIR/usr/python/share" "$APPDIR"/usr/python/lib/{libtcl*,libtk*,tcl*,tk*,itcl*,thread*} 2>/dev/null || true
find "$APPDIR/usr/python" -type d \( -name __pycache__ -o -name tests -o -name testing \) -prune -exec rm -rf {} + 2>/dev/null || true
"$PY" "$REPO/packaging/linux/prune_qt.py" "$PYLIB/site-packages/PySide6"

# Fail the build, not the user's first launch, if trimming broke anything.
say "checking the bundle imports"
PYTHONNOUSERSITE=1 "$PY" -c "import PySide6.QtWebEngineWidgets, PySide6.QtWebEngineCore, granum.service.app, granum.cli.window, pandas, pyarrow, PIL, fastapi, uvicorn; print('bundle imports ok')"

# 5. Libraries Qt needs that desktop distributions do not always ship.
for lib in libxcb-cursor.so.0 libxcb-icccm.so.4 libxcb-keysyms.so.1 libxcb-image.so.0 libxcb-render-util.so.0 libxcb-xkb.so.1 libxkbcommon-x11.so.0; do
  found="$(ldconfig -p | awk -v l="$lib" '$1 == l && /x86-64/ && !seen {print $NF; seen = 1}')"
  if [ -n "$found" ]; then cp -L "$found" "$APPDIR/usr/lib/"; else say "warning: $lib not found on the build machine"; fi
done

# 6. Precompile, since the AppImage is read-only at run time.
"$PY" -m compileall -q -j 0 --invalidation-mode unchecked-hash "$APPDIR/usr/python/lib" >/dev/null || true

# 7. AppDir metadata and the image.
install -m 755 "$REPO/packaging/linux/AppRun" "$APPDIR/AppRun"
sed "s/@VERSION@/$VERSION/" "$REPO/packaging/linux/granum.desktop" > "$APPDIR/granum.desktop"
cp "$REPO/src/granum/assets/granum-256.png" "$APPDIR/granum.png"
cp "$REPO/src/granum/assets/granum-256.png" "$APPDIR/.DirIcon"

fetch "https://github.com/AppImage/appimagetool/releases/download/continuous/appimagetool-x86_64.AppImage" "$CACHE/appimagetool"
chmod +x "$CACHE/appimagetool"
fetch "https://github.com/AppImage/type2-runtime/releases/download/continuous/runtime-x86_64" "$CACHE/runtime-x86_64"
say "packing $(du -sh "$APPDIR" | cut -f1) into one file"
ARCH=x86_64 "$CACHE/appimagetool" --appimage-extract-and-run --no-appstream --comp zstd \
  --runtime-file "$CACHE/runtime-x86_64" "$APPDIR" "$OUT" >/dev/null
say "done: $OUT ($(du -h "$OUT" | cut -f1))"
