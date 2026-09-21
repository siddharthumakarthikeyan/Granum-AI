"""The licence key format: a signed, readable JSON payload.

A key is ``GRN1.<payload>.<signature>``, both parts base64url without padding. The
payload is JSON; the signature is Ed25519 over ``GRN1.<payload>``, made with a private
key that never ships. The app holds only public keys (:mod:`granum.licensing.keys`), so
it can check a key but never make one, and any edit to the payload breaks the signature.

Payload fields:

``v``            format version (1)
``kid``          which signing key made it
``lid``          licence id: one purchase, shared by every machine it is activated on
``email``        the account it belongs to
``customer``     who bought it (a person or a company)
``plan``         the plan's name, for display
``machines``     how many machines the licence may be activated on
``machine``      the one machine this key works on (:mod:`granum.licensing.machine`)
``kind``         ``online``: works offline for a lease, then renews from the licence
                 server; ``offline``: no renewal, for computers that are never online
``issued``       when it was made (UTC, ISO 8601), by the issuer's clock
``expires``      when the plan ends (UTC), or null for no end
``lease_until``  online keys: when it must have renewed by (UTC)
``max_projects`` how many projects it allows, or null for no limit
"""

from __future__ import annotations

import base64
import json
from datetime import datetime, timezone
from typing import Any

from granum.errors import GranumError

PREFIX = "GRN1"
KINDS = ("online", "offline")


class LicenceError(GranumError):
    """A licence key that cannot be used, or an action the licence does not allow."""


def _b64encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _b64decode(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def parse_time(value: Any) -> float | None:
    """Seconds since the epoch for an ISO time (naive means UTC), or None."""
    if value in (None, ""):
        return None
    moment = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment.timestamp()


def format_time(seconds: float) -> str:
    return datetime.fromtimestamp(seconds, timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def encode(payload: dict[str, Any], private_key: Any) -> str:
    """Sign ``payload`` with an Ed25519 private key (cryptography's Ed25519PrivateKey)."""
    body = _b64encode(json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8"))
    signed = f"{PREFIX}.{body}"
    return f"{signed}.{_b64encode(private_key.sign(signed.encode('ascii')))}"


def decode(token: str, public_keys: dict[str, str]) -> dict[str, Any]:
    """The payload of a key whose signature checks out against ``public_keys``."""
    from cryptography.exceptions import InvalidSignature
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

    text = "".join((token or "").split())
    parts = text.split(".")
    if len(parts) != 3 or parts[0] != PREFIX:
        raise LicenceError("this is not a Granum licence key")
    try:
        payload = json.loads(_b64decode(parts[1]))
        signature = _b64decode(parts[2])
    except (ValueError, UnicodeDecodeError) as exc:
        raise LicenceError("the licence key is damaged; copy it again in full") from exc
    if not isinstance(payload, dict):
        raise LicenceError("the licence key is damaged; copy it again in full")
    key = public_keys.get(str(payload.get("kid")))
    if key is None:
        raise LicenceError("this licence key was signed by a key this version of Granum does not know; update Granum")
    try:
        Ed25519PublicKey.from_public_bytes(_b64decode(key)).verify(signature, f"{parts[0]}.{parts[1]}".encode("ascii"))
    except (InvalidSignature, ValueError) as exc:
        raise LicenceError("the licence key's signature is not valid; it was changed or not issued by Granum") from exc
    _check_fields(payload)
    return payload


def _check_fields(payload: dict[str, Any]) -> None:
    if payload.get("v") != 1:
        raise LicenceError("this licence key is for a newer version of Granum; update Granum")
    for name in ("lid", "email", "machine", "kind", "issued"):
        if not payload.get(name):
            raise LicenceError(f"the licence key has no {name}")
    if payload["kind"] not in KINDS:
        raise LicenceError(f"unknown licence kind {payload['kind']!r}")
    if payload["kind"] == "online" and not payload.get("lease_until"):
        raise LicenceError("an online licence key needs a lease end")
    for name in ("issued", "expires", "lease_until"):
        try:
            parse_time(payload.get(name))
        except ValueError as exc:
            raise LicenceError(f"the licence key's {name} is not a time") from exc
