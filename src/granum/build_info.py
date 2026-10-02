"""Read installed build identity without confusing a mutable checkout with a release."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def build_info() -> dict[str, Any]:
    from granum import __version__

    package = Path(__file__).resolve().parent
    try:
        manifest = json.loads((package / "_build.json").read_text())
    except (OSError, ValueError):
        return {"kind": "unverified-source", "version": __version__, "source_revision": None}
    if (package.parent.parent / ".git").exists():
        return {"kind": "source-checkout", "version": __version__, "last_packaged_build": manifest}
    return {"kind": "packaged", **manifest}