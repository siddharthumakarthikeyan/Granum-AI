"""Build the dashboard into the package when it has not been built yet.

`pip install .` or `pip install git+https://...` then produces a complete app with the
dashboard, as long as Node.js and npm are available. Without them the package still
builds and serves the API only, with a warning.
"""

from __future__ import annotations

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
        if static.exists() or not (web / "package.json").exists():
            return
        npm = shutil.which("npm")
        if npm is None:
            self.app.display_warning(
                "granum: npm not found, so the dashboard is not built; the service will serve the API only. "
                "Install Node.js 20+ and reinstall to include it."
            )
            return
        self.app.display_info("granum: building the dashboard (npm ci && npm run build)")
        install = "ci" if (web / "package-lock.json").exists() else "install"
        subprocess.run([npm, install, "--no-audit", "--no-fund"], cwd=web, check=True)
        subprocess.run([npm, "run", "build"], cwd=web, check=True)
