#!/usr/bin/env python3
"""Serve an isolated, real-data documentation workspace; never load personal configuration."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", type=Path, required=True)
    parser.add_argument("--data", type=Path, required=True)
    parser.add_argument("--port", type=int, default=18861)
    args = parser.parse_args()
    import uvicorn

    import granum
    from granum.core.index import Index
    from granum.licensing import Licensing
    from granum.service.app import create_app

    args.workspace.mkdir(parents=True, exist_ok=True)
    config = granum.Config.load(overrides={"project-root-url": str(args.workspace.resolve()),
                                          "service.data-roots": str(args.data.resolve())},
                                use_config_files=False, use_env=False)
    granum.set_config(config)
    index = Index(config=config)
    index.refresh(force=True)
    index.start()
    try:
        app = create_app(index=index, config=config, licensing=Licensing.open(),
                         data_roots=[str(args.data.resolve())], allowed_hosts=["127.0.0.1", "localhost"])
        uvicorn.run(app, host="127.0.0.1", port=args.port, log_level="warning")
    finally:
        index.stop()


if __name__ == "__main__":
    main()