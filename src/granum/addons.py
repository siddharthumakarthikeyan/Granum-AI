"""Optional add-ons installed by Granum itself, into its own folder.

The self-contained app ships without PyTorch (several gigabytes with CUDA). The first time
someone wants to train, Granum installs the training add-on with its own Python and pip into
``~/.local/share/granum/addons/training-py<version>``: nothing goes into the system Python,
and removing the folder removes the add-on.

``activate()`` puts installed add-ons on ``sys.path`` and ``PYTHONPATH``, so the service and
every process it starts (training, environment checks) can import them.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from collections.abc import Callable, Iterator
from pathlib import Path

#: What the training add-on installs. PyTorch from PyPI includes CUDA on Linux.
TRAINING_PACKAGES = ["torch", "torchvision", "ultralytics"]
#: Rough download size, shown before installing.
TRAINING_DOWNLOAD = "about 3 GB"


def addons_root() -> Path:
    base = os.environ.get("XDG_DATA_HOME") or os.path.join(os.path.expanduser("~"), ".local", "share")
    return Path(base) / "granum" / "addons"


def training_dir() -> Path:
    """Packages are tied to the Python version that installed them."""
    return addons_root() / f"training-py{sys.version_info.major}{sys.version_info.minor}"


def installed_dirs() -> list[Path]:
    return [d for d in (training_dir(),) if (d / ".complete").exists()]


def activate() -> None:
    for folder in installed_dirs():
        text = str(folder)
        if text not in sys.path:
            sys.path.append(text)
        parts = [p for p in os.environ.get("PYTHONPATH", "").split(os.pathsep) if p]
        if text not in parts:
            os.environ["PYTHONPATH"] = os.pathsep.join([*parts, text])


def is_bundled() -> bool:
    """Running from the self-contained app rather than a pip install."""
    return bool(os.environ.get("GRANUM_BUNDLED"))


def install_training(on_line: Callable[[str], None], cancelled: Callable[[], bool] = lambda: False) -> Path:
    """Install the training add-on with this Python's pip, streaming pip's output.

    Installs into a temporary folder and renames it into place at the end, so an interrupted
    install never leaves a half-working add-on behind.
    """
    target = training_dir()
    partial = target.with_name(target.name + ".partial")
    shutil.rmtree(partial, ignore_errors=True)
    partial.mkdir(parents=True)
    command = [sys.executable, "-m", "pip", "install", "--no-input", "--disable-pip-version-check",
               "--progress-bar", "off", "--target", str(partial), *TRAINING_PACKAGES]
    env = {k: v for k, v in os.environ.items() if k != "PYTHONPATH"}
    process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1, env=env)
    assert process.stdout is not None
    for line in _lines(process.stdout):
        on_line(line)
        if cancelled():
            process.terminate()
            break
    code = process.wait()
    if cancelled() or code != 0:
        shutil.rmtree(partial, ignore_errors=True)
        raise RuntimeError("installation was cancelled" if cancelled() else f"pip failed with exit code {code}")
    (partial / ".complete").write_text("ok\n")
    shutil.rmtree(target, ignore_errors=True)
    partial.rename(target)
    activate()
    return target


def _lines(stream) -> Iterator[str]:
    for raw in stream:
        line = raw.strip()
        if line:
            yield line[:400]
