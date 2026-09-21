#!/usr/bin/env python3
"""Issue Granum licence keys. For the owner only: it needs the private signing key.

The private key lives outside the repository, by default in
``~/.config/granum-admin/signing-<kid>.pem`` (mode 600). Keep a backup somewhere safe and
offline: without it no new key can be issued for copies of Granum already shipped.

    granum_licence.py keygen --kid k2                      # a new key pair (prints the public half)
    granum_licence.py issue --email a@b.com --machine GM-... --days 30 --projects 3
    granum_licence.py issue --email a@b.com --machine GM-... --kind offline --until 2027-12-31
    granum_licence.py inspect KEY                          # what a key says (no signature check)

``--kind offline`` keys never renew; they are for computers with no internet. ``online``
keys hold a 7-day lease and are renewed by the licence server.
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from granum.licensing.token import KINDS, encode, format_time  # noqa: E402

ADMIN_DIR = Path(os.environ.get("GRANUM_ADMIN_DIR") or Path.home() / ".config" / "granum-admin")


def _load_key(kid: str):
    from cryptography.hazmat.primitives import serialization

    path = ADMIN_DIR / f"signing-{kid}.pem"
    if not path.exists():
        sys.exit(f"no private key {path}; run keygen, or copy the key there")
    return serialization.load_pem_private_key(path.read_bytes(), password=None)


def keygen(args: argparse.Namespace) -> None:
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

    ADMIN_DIR.mkdir(parents=True, exist_ok=True, mode=0o700)
    path = ADMIN_DIR / f"signing-{args.kid}.pem"
    key = Ed25519PrivateKey.generate()
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)  # never overwrites a key
    with os.fdopen(fd, "wb") as handle:
        handle.write(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))
    public = key.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    print(f"private key: {path}")
    print(f'add to src/granum/licensing/keys.py: "{args.kid}": "{base64.urlsafe_b64encode(public).rstrip(b"=").decode()}",')


def _end(args: argparse.Namespace, now: float) -> float | None:
    if args.until:
        moment = datetime.fromisoformat(args.until)
        if moment.tzinfo is None:
            moment = moment.replace(hour=23, minute=59, second=59, tzinfo=timezone.utc) if len(args.until) <= 10 else moment.replace(tzinfo=timezone.utc)
        return moment.timestamp()
    if args.days:
        return now + args.days * 86400
    return None


def issue(args: argparse.Namespace) -> None:
    now = time.time()
    expires = _end(args, now)
    if expires is None and not args.perpetual:
        sys.exit("give --days, --until, or --perpetual")
    payload = {
        "v": 1,
        "kid": args.kid,
        "lid": args.lid or f"L-{uuid.uuid4().hex[:12].upper()}",
        "email": args.email.strip().lower(),
        "customer": args.customer or args.email.strip().lower(),
        "plan": args.plan,
        "machines": args.machines,
        "machine": args.machine.strip().upper(),
        "kind": args.kind,
        "issued": format_time(now),
        "expires": None if expires is None else format_time(expires),
        "lease_until": format_time(min(now + args.lease_days * 86400, expires or now + args.lease_days * 86400)) if args.kind == "online" else None,
        "max_projects": None if args.projects in (None, 0) else args.projects,
    }
    token = encode(payload, _load_key(args.kid))
    if args.json:
        print(json.dumps({"key": token, "payload": payload}, indent=2))
    else:
        print(token)
        print(json.dumps(payload, indent=2), file=sys.stderr)


def inspect(args: argparse.Namespace) -> None:
    parts = "".join(args.key.split()).split(".")
    if len(parts) != 3:
        sys.exit("not a Granum licence key")
    print(json.dumps(json.loads(base64.urlsafe_b64decode(parts[1] + "=" * (-len(parts[1]) % 4))), indent=2))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    commands = parser.add_subparsers(dest="command", required=True)

    k = commands.add_parser("keygen", help="make a new signing key pair")
    k.add_argument("--kid", required=True, help="key id, e.g. k2")
    k.set_defaults(run=keygen)

    i = commands.add_parser("issue", help="make a licence key for one machine")
    i.add_argument("--email", required=True)
    i.add_argument("--machine", required=True, help="the GM-... id shown on the customer's Licence page")
    i.add_argument("--customer", help="person or company name (defaults to the email)")
    i.add_argument("--plan", default="Standard", help="plan name shown in the app")
    i.add_argument("--days", type=int, help="plan length from now")
    i.add_argument("--until", help="plan end date, YYYY-MM-DD (end of that day, UTC)")
    i.add_argument("--perpetual", action="store_true", help="no end date")
    i.add_argument("--projects", type=int, help="project limit (0 or omitted: no limit)")
    i.add_argument("--machines", type=int, default=1, help="machines the purchase covers (shown; the server enforces it)")
    i.add_argument("--kind", choices=KINDS, default="offline")
    i.add_argument("--lease-days", type=int, default=7)
    i.add_argument("--lid", help="licence id to reuse, for another machine of the same purchase")
    i.add_argument("--kid", default="k1", help="signing key id")
    i.add_argument("--json", action="store_true", help="print key and payload as JSON")
    i.set_defaults(run=issue)

    s = commands.add_parser("inspect", help="show a key's payload")
    s.add_argument("key")
    s.set_defaults(run=inspect)

    args = parser.parse_args()
    args.run(args)


if __name__ == "__main__":
    main()
