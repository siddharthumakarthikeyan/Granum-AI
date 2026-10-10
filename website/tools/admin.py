#!/usr/bin/env python3
"""Manage plans on the licence database by hand, until payments do it.

Point it at the production database with DATABASE_URL (from Vercel: Storage -> your
database -> .env.local), and the signing key with LICENCE_SIGNING_KEY (a file path).

    tools/admin.py grant --email a@b.com --plan Pro --days 30 --machines 5 --projects 20
    tools/admin.py extend L-XXXX --days 30
    tools/admin.py revoke L-XXXX
    tools/admin.py free L-XXXX GM-....
    tools/admin.py show a@b.com
    tools/admin.py list                 # every licence, newest first
    tools/admin.py leads                # emails from the download form
    tools/admin.py quotes               # Enterprise quote requests
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "api"))

from _licence.config import service_from_env  # noqa: E402


def _when(seconds: float | None) -> str:
    return "no end" if seconds is None else datetime.fromtimestamp(seconds, timezone.utc).strftime("%Y-%m-%d %H:%M UTC")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    commands = parser.add_subparsers(dest="command", required=True)
    g = commands.add_parser("grant")
    g.add_argument("--email", required=True)
    g.add_argument("--plan", required=True)
    g.add_argument("--days", type=float, help="omit for no end")
    g.add_argument("--machines", type=int, default=1)
    g.add_argument("--projects", type=int, help="omit for no limit")
    g.add_argument("--customer")
    g.add_argument("--note", default="")
    e = commands.add_parser("extend")
    e.add_argument("lid")
    e.add_argument("--days", type=float, required=True)
    r = commands.add_parser("revoke")
    r.add_argument("lid")
    f = commands.add_parser("free")
    f.add_argument("lid")
    f.add_argument("machine")
    s = commands.add_parser("show")
    s.add_argument("email")
    commands.add_parser("list")
    commands.add_parser("leads")
    commands.add_parser("quotes")
    args = parser.parse_args()

    service = service_from_env()
    db = service.db
    if args.command == "grant":
        print(json.dumps(service.grant(args.email, plan=args.plan, days=args.days, machines=args.machines,
                                       max_projects=args.projects, customer=args.customer, note=args.note)))
    elif args.command == "extend":
        service.extend(args.lid, args.days)
    elif args.command == "revoke":
        service.revoke(args.lid)
    elif args.command == "free":
        service.free_machine(args.lid, args.machine)
    elif args.command == "show":
        print(json.dumps(service.account(args.email), indent=2, default=str))
    elif args.command == "leads":
        for row in db.rows("SELECT a.email, a.name, a.company, a.source, a.created, "
                           "(SELECT COUNT(*) FROM downloads d WHERE d.email = a.email) AS downloads "
                           "FROM accounts a ORDER BY a.created DESC"):
            print(f"{_when(row['created'])}  {row['email']:34}  {row['source'] or '':8}  downloads {row['downloads']}  "
                  f"{row['name'] or ''} {('(' + row['company'] + ')') if row['company'] else ''}")
    elif args.command == "quotes":
        for row in db.rows("SELECT * FROM quotes ORDER BY created DESC"):
            print(f"{_when(row['created'])}  {row['plan'] or 'Enterprise':10}  {row['company']}  {row['name']} <{row['email']}>  "
                  f"computers {row['computers'] or '?'}")
            if row["message"]:
                print("    " + row["message"].replace("\n", "\n    "))
    else:
        for row in db.rows("SELECT l.*, (SELECT COUNT(*) FROM activations a WHERE a.lid = l.lid AND a.deactivated IS NULL) AS used "
                           "FROM licences l ORDER BY created DESC"):
            state = "revoked" if row["revoked"] else ("live" if service._live(row) else "ended")
            print(f"{row['lid']}  {row['kind']:5}  {row['email']:32}  {row['plan']:12}  ends {_when(row['expires'])}  "
                  f"machines {row['used']}/{row['machines']}  {state}")


if __name__ == "__main__":
    main()
