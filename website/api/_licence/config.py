"""Building the server from environment variables (see README.md)."""

from __future__ import annotations

import base64
import os
from collections.abc import Callable
from pathlib import Path
from typing import Any

from .db import Database
from .mail import Mailer
from .service import LicenceService, Settings


def _private_key() -> Any:
    from cryptography.hazmat.primitives import serialization

    text = os.environ.get("LICENCE_SIGNING_KEY_PEM", "").strip()
    if text:
        # Pasted into a single-line secret, the line breaks can arrive as "\n".
        data = text.replace("\\n", "\n").encode()
    else:
        path = os.environ.get("LICENCE_SIGNING_KEY") or str(Path.home() / ".config/granum-admin/signing-k1.pem")
        data = Path(path).read_bytes()
    return serialization.load_pem_private_key(data, password=None)


def service_from_env() -> LicenceService:
    from cryptography.hazmat.primitives import serialization

    private_key = _private_key()
    kid = os.environ.get("LICENCE_KID", "k1")
    public = private_key.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    projects = os.environ.get("LICENCE_TRIAL_PROJECTS", "1")
    settings = Settings(
        trial_days=int(os.environ.get("LICENCE_TRIAL_DAYS", "7")),
        trial_projects=None if projects in ("", "0", "none") else int(projects),
        kid=kid,
        dev=os.environ.get("LICENCE_DEV") == "1",
    )
    mailer = Mailer(
        host=os.environ.get("SMTP_HOST", ""), port=int(os.environ.get("SMTP_PORT", "587")),
        user=os.environ.get("SMTP_USER", ""), password=os.environ.get("SMTP_PASSWORD", ""),
        sender=os.environ.get("SMTP_FROM", ""),
    )
    url = os.environ.get("DATABASE_URL") or os.environ.get("POSTGRES_URL") or os.environ.get("LICENCE_DB", "licence-server.sqlite3")
    return LicenceService(Database(url), private_key, {kid: base64.urlsafe_b64encode(public).rstrip(b"=").decode()},
                          mailer=mailer, settings=settings)


#: The public repository whose approved release the site offers, unless links are set by hand.
RELEASE_REPOSITORY = "siddharthumakarthikeyan/Granum-AI"


def site_from_env() -> dict[str, Any] | Callable[[], dict[str, Any]]:
    """What the pages show. Installer links set by hand win; otherwise the approved release is followed."""
    if not (os.environ.get("DOWNLOAD_WINDOWS_URL") or os.environ.get("DOWNLOAD_LINUX_URL")):
        from .releases import ApprovedRelease

        return ApprovedRelease(os.environ.get("DOWNLOAD_RELEASE_REPOSITORY") or RELEASE_REPOSITORY,
                               contact=os.environ.get("CONTACT_EMAIL", ""))
    return {
        "version": os.environ.get("APP_VERSION", ""),
        "contact": os.environ.get("CONTACT_EMAIL", ""),
        "downloads": {"windows": os.environ.get("DOWNLOAD_WINDOWS_URL", ""), "linux": os.environ.get("DOWNLOAD_LINUX_URL", "")},
        "checksums": {name: os.environ.get(f"DOWNLOAD_{name.upper()}_SHA256", "") for name in ("windows", "linux")},
        "manifests": {name: os.environ.get(f"DOWNLOAD_{name.upper()}_MANIFEST_URL", "") for name in ("windows", "linux")},
        "release": {
            "channel": "unrestricted-alpha",
            "source_revision": os.environ.get("APP_SOURCE_REVISION", ""),
            "qualified": os.environ.get("APP_RELEASE_QUALIFIED") == "1",
        },
    }
