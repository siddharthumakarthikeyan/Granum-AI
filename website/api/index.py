"""Vercel entry point: every ``/v1/*`` request is rewritten here (see vercel.json)."""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(__file__))

from _licence.app import create_app  # noqa: E402
from _licence.config import service_from_env, site_from_env  # noqa: E402

app = create_app(service_from_env(), admin_token=os.environ.get("LICENCE_ADMIN_TOKEN", ""), site=site_from_env())
