"""Run with the installed/bundled Python (-I): no source path or existing user data."""
from __future__ import annotations

import json
import re
import tempfile
from pathlib import Path

import granum
from granum import Config, Table
from granum.build_info import build_info
from granum.core.index import Index
from granum.licensing import Licensing
from granum.service.app import create_app


def main() -> None:
    info = build_info()
    assert info["kind"] == "packaged", "Smoke test must use an installed wheel, not checkout imports"
    assert info["dashboard"], "A desktop package must contain its dashboard"
    static = Path(granum.__file__).parent / "service/static"
    html = (static / "index.html").read_text()
    for asset in re.findall(r'(?:src|href)="/(assets/[^"?#]+)', html):
        assert (static / asset).is_file(), f"Missing dashboard asset: {asset}"
    with tempfile.TemporaryDirectory(prefix="granum-package-smoke-") as temporary:
        config = Config.load(overrides={"project-root-url": temporary}, use_env=False, use_config_files=False)
        granum.set_config(config)
        table = Table.from_dict_data({"score": [1.0, 2.0]}, project_name="smoke", dataset_name="test")
        assert Table.from_url(table.url)[1]["score"] == 2.0
        index = Index([temporary])
        index.refresh()
        app = create_app(index=index, config=config, licensing=Licensing.open())
        assert "/api/qa/approve" in {route.path for route in app.routes}
    print(json.dumps({"smoke": "passed", "build": info}))


if __name__ == "__main__":
    main()