#!/usr/bin/env python3
"""Loopback-only static preview with the site's clean-URL behaviour; not a production server."""
from __future__ import annotations

import argparse
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

PUBLIC = Path(__file__).resolve().parents[1] / "public"


class Preview(SimpleHTTPRequestHandler):
    extensions_map = {**SimpleHTTPRequestHandler.extensions_map, ".vtt": "text/vtt; charset=utf-8"}

    def translate_path(self, path: str) -> str:
        translated = Path(super().translate_path(path)).resolve()
        if not translated.is_relative_to(PUBLIC.resolve()):
            return str(PUBLIC / ".not-found")
        if not translated.exists() and not translated.suffix and translated.with_suffix(".html").is_file():
            return str(translated.with_suffix(".html"))
        return str(translated)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=18863)
    args = parser.parse_args()
    server = ThreadingHTTPServer(("127.0.0.1", args.port), partial(Preview, directory=str(PUBLIC)))
    print(f"Local documentation preview: http://127.0.0.1:{args.port}/docs/course/start", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()