"""Verify a desktop wheel and emit per-artifact checksums and its exact provenance."""
from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import os
import platform
import runpy
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--wheel", type=Path, required=True)
    parser.add_argument("--version", required=True)
    parser.add_argument("--artifact", type=Path)
    args = parser.parse_args()
    helpers = runpy.run_path(str(Path(__file__).resolve().parents[1] / "build_provenance.py"))
    manifest = helpers["verify_wheel"](args.wheel, version=args.version, revision=os.environ.get("GITHUB_SHA") if os.environ.get("GRANUM_RELEASE_BUILD") == "1" else None)
    if args.artifact:
        digest = hashlib.sha256()
        with args.artifact.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        report = {
            "format_version": 1, "artifact": args.artifact.name, "sha256": digest.hexdigest(),
            "bytes": args.artifact.stat().st_size, "build": manifest,
            "python": platform.python_version(), "platform": platform.platform(),
            "dependencies": sorted({(d.metadata["Name"], d.version) for d in importlib.metadata.distributions()}),
            "signing": "unsigned", "qualification": "automated checks only; manual platform qualification required before publication",
        }
        args.artifact.with_name(args.artifact.name + ".manifest.json").write_text(json.dumps(report, indent=2) + "\n")
        args.artifact.with_name(args.artifact.name + ".sha256").write_text(f"{digest.hexdigest()}  {args.artifact.name}\n")
    print(json.dumps(manifest, indent=2))


if __name__ == "__main__":
    main()