"""Build a matching dashboard and embed source/content provenance in every wheel.

`pip install .` or `pip install git+https://...` then produces a complete app with the
dashboard, as long as Node.js and npm are available. Without them the package still
builds and serves the API only, with a warning.
"""

from __future__ import annotations

import json
import os
import runpy
import shutil
import subprocess
from pathlib import Path

from hatchling.builders.hooks.plugin.interface import BuildHookInterface


class DashboardBuildHook(BuildHookInterface):
    PLUGIN_NAME = "custom"

    def initialize(self, version: str, build_data: dict) -> None:
        root = Path(self.root)
        static = root / "src" / "granum" / "service" / "static" / "index.html"
        web = root / "web"
        provenance = runpy.run_path(str(root / "build_provenance.py"))
        if provenance["dashboard_stamp"](root) is None:
            npm = shutil.which("npm")
            if npm is None or not (web / "package.json").exists():
                if static.exists() or os.environ.get("GRANUM_RELEASE_BUILD") == "1":
                    raise RuntimeError("Stale/missing dashboard: install Node.js 20+ and rebuild before packaging")
                self.app.display_warning("granum: npm unavailable; building API-only, not a desktop release")
            else:
                self.app.display_info("granum: rebuilding missing or stale dashboard (npm ci && npm run build)")
                install = "ci" if (web / "package-lock.json").exists() else "install"
                subprocess.run([npm, install, "--no-audit", "--no-fund"], cwd=web, check=True)
                subprocess.run([npm, "run", "build"], cwd=web, check=True)
        manifest = provenance["create_manifest"](root, self.metadata.version)
        (root / "src/granum/_build.json").write_text(json.dumps(manifest, indent=2) + "\n")
        build_data.setdefault("artifacts", []).append("src/granum/_build.json")
