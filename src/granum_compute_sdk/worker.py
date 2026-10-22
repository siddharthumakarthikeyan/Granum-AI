"""Private subprocess entry point; plugin code never imports the host application."""
from __future__ import annotations

import importlib
import json
import sys
from dataclasses import asdict
from pathlib import Path

from . import Context, Result, Sample


def entrypoint(text: str):
    module, name = text.split(":")
    function = getattr(importlib.import_module(module), name)
    if not callable(function):
        raise TypeError("plugin entry point must be callable")
    return function


def main() -> None:
    if sys.argv[1] == "--check":
        entrypoint(sys.argv[2])
        print("Plugin entry point is ready", flush=True)
        return
    source, target = map(Path, sys.argv[1:3])
    payload = json.loads(source.read_text(encoding="utf-8"))
    context = Context([Sample(**row) for row in payload["samples"]], payload["parameters"], payload["source"])
    result = entrypoint(payload["entrypoint"])(context)
    if not isinstance(result, Result):
        raise TypeError("plugin must return granum_compute_sdk.Result")
    temporary = target.with_suffix(".tmp")
    temporary.write_text(json.dumps(asdict(result), allow_nan=False), encoding="utf-8")
    temporary.replace(target)


if __name__ == "__main__":
    main()
