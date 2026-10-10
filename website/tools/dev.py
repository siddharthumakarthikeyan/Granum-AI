#!/usr/bin/env python3
"""Run the whole site locally, as Vercel would: pages from public/, the API under /v1.

    LICENCE_DEV=1 python tools/dev.py          # http://127.0.0.1:3000, codes shown instead of emailed
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "api"))


def main() -> None:
    import uvicorn
    from fastapi.responses import FileResponse
    from fastapi.staticfiles import StaticFiles

    from _licence.app import create_app
    from _licence.config import service_from_env, site_from_env

    app = create_app(service_from_env(), admin_token=os.environ.get("LICENCE_ADMIN_TOKEN", ""), site=site_from_env())
    public = ROOT / "public"

    @app.get("/{page:path}")
    def clean_url(page: str) -> FileResponse:
        """Vercel's cleanUrls, at any depth: /download -> download.html, /docs -> docs/index.html."""
        page = page.strip("/")
        for target in (public / page, public / f"{page}.html", public / page / "index.html"):
            if target.is_file() and public in target.resolve().parents:
                return FileResponse(target)
        return FileResponse(public / "404.html", status_code=404)

    app.mount("/", StaticFiles(directory=public, html=True), name="public")
    uvicorn.run(app, host="127.0.0.1", port=int(os.environ.get("PORT", "3000")))


if __name__ == "__main__":
    main()
