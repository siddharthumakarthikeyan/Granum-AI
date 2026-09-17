#!/usr/bin/env bash
# Install or upgrade Granum for the current user.
#
#   ./install.sh                 install or upgrade (run it again after `git pull`)
#   ./install.sh --dev           editable install: code changes apply after a restart
#   ./install.sh --training      also install Ultralytics (YOLO, RT-DETR) for training
#   ./install.sh --no-autostart  do not start Granum in the background at login
#   ./install.sh --uninstall     remove the app; projects, reviews and weights are kept
#
# Granum lives in its own virtual environment (~/.local/share/granum/venv), which can see
# packages already installed for this Python (for example PyTorch). Your data stays in
# ~/granum (projects) and ~/granum-training (model weights), and is never modified here.
set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DATA_HOME="${XDG_DATA_HOME:-$HOME/.local/share}"
VENV="$DATA_HOME/granum/venv"
BIN="${GRANUM_BIN_DIR:-$HOME/.local/bin}"
DEV=0; TRAINING=0; UNINSTALL=0; APP_FLAGS=()

for arg in "$@"; do
  case "$arg" in
    --dev) DEV=1 ;;
    --training) TRAINING=1 ;;
    --no-autostart) APP_FLAGS+=(--no-autostart) ;;
    --no-launcher) APP_FLAGS+=(--no-launcher) ;;
    --uninstall) UNINSTALL=1 ;;
    -h|--help) sed -n '2,13p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) echo "unknown option: $arg (see --help)" >&2; exit 2 ;;
  esac
done

say() { printf '\033[1;36mgranum\033[0m %s\n' "$*"; }
fail() { printf '\033[1;31mgranum\033[0m %s\n' "$*" >&2; exit 1; }

if [ "$UNINSTALL" = 1 ]; then
  if [ -x "$VENV/bin/granum" ]; then "$VENV/bin/granum" app uninstall; fi
  if [ -L "$BIN/granum" ] && [ "$(readlink "$BIN/granum")" = "$VENV/bin/granum" ]; then rm "$BIN/granum"; fi
  rm -rf "$VENV"
  say "uninstalled. Projects, reviews, shipments and model weights were kept."
  exit 0
fi

PYTHON="${PYTHON:-python3}"
command -v "$PYTHON" >/dev/null || fail "python3 not found; install Python 3.10 or newer"
"$PYTHON" -c 'import sys; sys.exit(sys.version_info < (3, 10))' || fail "Python 3.10 or newer is required ($("$PYTHON" --version))"
"$PYTHON" -c 'import venv, ensurepip' 2>/dev/null || fail "Python venv support is missing; on Ubuntu: sudo apt install python3-venv"

if [ ! -f "$REPO/src/granum/service/static/index.html" ] || [ "$DEV" = 1 ]; then
  command -v npm >/dev/null || fail "npm not found; install Node.js 20 or newer to build the dashboard"
  say "building the dashboard"
  (cd "$REPO/web" && npm ci --no-audit --no-fund && npm run build)
fi

say "installing into $VENV"
mkdir -p "$(dirname "$VENV")" "$BIN"
[ -x "$VENV/bin/python" ] || "$PYTHON" -m venv --system-site-packages "$VENV"
"$VENV/bin/python" -m pip install --quiet --upgrade pip
if [ "$DEV" = 1 ]; then
  "$VENV/bin/python" -m pip install --quiet -e "$REPO[service,desktop,images,pandas,dev]"
else
  "$VENV/bin/python" -m pip install --quiet --upgrade "$REPO[service,desktop,images,pandas]"
fi
if [ "$TRAINING" = 1 ]; then
  say "installing Ultralytics for training"
  "$VENV/bin/python" -m pip install --quiet ultralytics
fi

if [ "$(uname -s)" = Linux ] && ! "$VENV/bin/python" -c 'import gi
try:
    gi.require_version("WebKit2", "4.1")
except ValueError:
    gi.require_version("WebKit2", "4.0")' 2>/dev/null; then
  say "the Granum window needs WebKitGTK; install it with: sudo apt install python3-gi gir1.2-webkit2-4.1"
  say "(until then Granum opens in your web browser)"
fi

if [ -e "$BIN/granum" ] && [ ! -L "$BIN/granum" ]; then
  mv "$BIN/granum" "$BIN/granum.previous"
  say "an older granum command was moved to $BIN/granum.previous"
fi
ln -sfn "$VENV/bin/granum" "$BIN/granum"
case ":$PATH:" in *":$BIN:"*) ;; *) say "add $BIN to your PATH to use the granum command in a terminal" ;; esac

"$VENV/bin/granum" app install "${APP_FLAGS[@]}"
say "done. Open Granum from the application menu, or run: granum open"
