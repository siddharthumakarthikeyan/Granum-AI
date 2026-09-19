"""The rules: sign-in codes, free trials, paid plans, machines, renewals, downloads.

Every date in a key comes from this server's clock. Keys are ``online``: a lease of
:data:`LEASE_DAYS` days that the app renews while it runs; past the plan's end the app
turns read-only by itself, even offline.
"""

from __future__ import annotations

import hashlib
import hmac
import re
import secrets
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from .db import Database
from .mail import Mailer
from .token import LicenceError, decode, encode, format_time

LEASE_DAYS = 7
CODE_MINUTES = 10
CODE_ATTEMPTS = 5
CODES_PER_HOUR = 5
QUOTES_PER_HOUR = 3
QUOTES_PER_HOUR_ALL = 60
PLANS = ("Single", "Team", "Enterprise")
EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
MACHINE = re.compile(r"^GM(-[0-9A-F]{4}){6}$")
OPERATING_SYSTEMS = ("windows", "linux")
#: Throwaway-address services: no downloads or trials for them.
DISPOSABLE = frozenset("""
10minutemail.com 10minutemail.net 20minutemail.com 33mail.com anonbox.net burnermail.io discard.email
dispostable.com dropmail.me emailondeck.com fakeinbox.com fakemail.net getairmail.com getnada.com guerrillamail.biz
guerrillamail.com guerrillamail.de guerrillamail.info guerrillamail.net guerrillamail.org guerrillamailblock.com
harakirimail.com incognitomail.org inboxbear.com mail.tm mail-temp.com maildrop.cc mailinator.com mailinator.net
mailnesia.com mailpoof.com mintemail.com moakt.com mohmal.com mytemp.email mytrashmail.com nada.email sharklasers.com
spam4.me spambog.com spamgourmet.com temp-mail.io temp-mail.org tempail.com tempmail.dev tempmail.net tempmailo.com
tempr.email throwawaymail.com trash-mail.com trashmail.com trashmail.de trashmail.net yopmail.com yopmail.fr
yopmail.net emailfake.com fakemailgenerator.com minuteinbox.com tmpmail.org tmpmail.net linshiyouxiang.net
""".split())


class Refused(Exception):
    """A request the rules turn down; ``status`` is the HTTP status to answer with."""

    def __init__(self, status: int, message: str, code: str = "") -> None:
        super().__init__(message)
        self.status, self.message, self.code = status, message, code


@dataclass
class Settings:
    trial_days: int = 7
    trial_projects: int | None = 1
    kid: str = "k1"
    #: Development only: sign-in codes are returned in the response.
    dev: bool = False


def normalize_email(email: str) -> str:
    email = (email or "").strip().lower()
    if not EMAIL.match(email) or len(email) > 254:
        raise Refused(400, "Enter a valid email address.", "email")
    domain = email.rsplit("@", 1)[1]
    if domain in DISPOSABLE or any(domain.endswith(f".{d}") for d in DISPOSABLE):
        raise Refused(400, "Use a permanent email address; temporary inboxes are not accepted.", "disposable")
    return email


def normalize_machine(machine: str) -> str:
    machine = (machine or "").strip().upper()
    if not MACHINE.match(machine):
        raise Refused(400, "That is not a Granum machine ID.", "machine")
    return machine


class LicenceService:
    def __init__(self, db: Database, private_key: Any, public_keys: dict[str, str], *, mailer: Mailer | None = None,
                 settings: Settings | None = None, clock: Callable[[], float] = time.time) -> None:
        self.db = db
        self.private_key = private_key
        self.public_keys = public_keys
        self.mailer = mailer or Mailer()
        self.settings = settings or Settings()
        self.clock = clock

    # -- accounts, downloads and codes ------------------------------------------------------

    def register(self, email: str, source: str = "website", *, name: str = "", company: str = "") -> str:
        email = normalize_email(email)
        self.db.run("INSERT INTO accounts(email, created, source, name, company) VALUES (:email, :now, :source, :name, :company) "
                    "ON CONFLICT (email) DO NOTHING",
                    email=email, now=self.clock(), source=source, name=name[:120] or None, company=company[:120] or None)
        if name or company:
            self.db.run("UPDATE accounts SET name = COALESCE(name, :name), company = COALESCE(company, :company) WHERE email = :email",
                        email=email, name=name[:120] or None, company=company[:120] or None)
        return email

    def download(self, email: str, code: str, os: str, *, name: str = "", company: str = "") -> str:
        """The download form, once the emailed code proves the address: remember who took which installer."""
        email = normalize_email(email)
        self._check_code(email, code)
        email = self.register(email, "website", name=name, company=company)
        os = os if os in OPERATING_SYSTEMS else None
        self.db.run("INSERT INTO downloads(email, os, created) VALUES (:email, :os, :now)", email=email, os=os, now=self.clock())
        return email

    def quote(self, email: str, *, name: str, company: str, computers: int | None, message: str,
              plan: str = "", notify: str = "") -> dict[str, Any]:
        """Someone asks to buy a plan or for an Enterprise quote: keep it, and email it to ``notify``."""
        plan = plan if plan in PLANS else "Enterprise"
        email = normalize_email(email)
        name, company, message = name.strip()[:120], company.strip()[:160], message.strip()[:4000]
        if not name or not company:
            raise Refused(400, "Enter your name and company.", "quote_fields")
        now = self.clock()
        mine = self.db.value("SELECT COUNT(*) AS n FROM quotes WHERE email = :email AND created > :since", email=email, since=now - 3600)
        everyone = self.db.value("SELECT COUNT(*) AS n FROM quotes WHERE created > :since", since=now - 3600)
        if int(mine or 0) >= QUOTES_PER_HOUR or int(everyone or 0) >= QUOTES_PER_HOUR_ALL:
            raise Refused(429, "We already have your request. We will reply by email.", "rate")
        self.db.run("INSERT INTO quotes(email, name, company, plan, computers, message, created) "
                    "VALUES (:email, :name, :company, :plan, :computers, :message, :now)",
                    email=email, name=name, company=company, plan=plan, computers=computers, message=message or None, now=now)
        self.register(email, "quote", name=name, company=company)
        if notify:
            self.mailer.send_notice(
                notify, f"Granum {plan} request: {company}",
                f"Plan:      {plan}\nCompany:   {company}\nName:      {name}\nEmail:     {email}\n"
                f"Computers: {computers if computers else 'not given'}\n\n{message or '(no message)'}\n",
                reply_to=email)
        return {"ok": True}

    def _hash(self, email: str, code: str) -> str:
        return hashlib.sha256(f"{email}:{code}".encode()).hexdigest()

    def send_code(self, email: str, purpose: str = "signin") -> dict[str, Any]:
        """Email a 6-digit code: ``signin`` for the app, ``download`` for the website's download form."""
        email = normalize_email(email)
        now = self.clock()
        recent = self.db.value("SELECT COUNT(*) AS n FROM codes WHERE email = :email AND created > :since", email=email, since=now - 3600)
        if int(recent or 0) >= CODES_PER_HOUR:
            raise Refused(429, "Too many codes asked for this email. Try again in an hour.", "rate")
        code = f"{secrets.randbelow(1_000_000):06d}"
        with self.db.transaction():
            self.db.run("UPDATE codes SET used = 1 WHERE email = :email AND used = 0", email=email)
            self.db.run("INSERT INTO codes(email, code_hash, created, expires) VALUES (:email, :hash, :now, :expires)",
                        email=email, hash=self._hash(email, code), now=now, expires=now + CODE_MINUTES * 60)
        self.register(email, source="app" if purpose == "signin" else "website")
        self.mailer.send_code(email, code, purpose)
        return {"sent": True, "minutes": CODE_MINUTES, **({"dev_code": code} if self.settings.dev else {})}

    def _check_code(self, email: str, code: str) -> None:
        row = self.db.row("SELECT id, code_hash, expires, attempts FROM codes WHERE email = :email AND used = 0 "
                          "ORDER BY created DESC LIMIT 1", email=email)
        if row is None or row["expires"] < self.clock():
            raise Refused(400, "The code has expired. Ask for a new one.", "code_expired")
        if row["attempts"] >= CODE_ATTEMPTS:
            raise Refused(400, "Too many wrong codes. Ask for a new one.", "code_attempts")
        if not hmac.compare_digest(row["code_hash"], self._hash(email, (code or "").strip())):
            self.db.run("UPDATE codes SET attempts = attempts + 1 WHERE id = :id", id=row["id"])
            raise Refused(400, "That code is not right.", "code_wrong")
        # Used once: of two requests racing with the same code, only one gets it.
        if self.db.row("UPDATE codes SET used = 1 WHERE id = :id AND used = 0 RETURNING id", id=row["id"]) is None:
            raise Refused(400, "The code was already used. Ask for a new one.", "code_used")

    # -- keys ------------------------------------------------------------------------------

    def _key(self, licence: dict[str, Any], machine: str) -> str:
        now = self.clock()
        lease = now + LEASE_DAYS * 86400
        if licence["expires"] is not None:
            lease = min(lease, max(now, licence["expires"]))
        payload = {
            "v": 1, "kid": self.settings.kid, "lid": licence["lid"], "email": licence["email"],
            "customer": licence["customer"] or licence["email"], "plan": licence["plan"],
            "machines": licence["machines"], "machine": machine, "kind": "online",
            "issued": format_time(now),
            "expires": None if licence["expires"] is None else format_time(licence["expires"]),
            "lease_until": format_time(lease), "max_projects": licence["max_projects"],
        }
        return encode(payload, self.private_key)

    def _live(self, licence: dict[str, Any]) -> bool:
        return not licence["revoked"] and (licence["expires"] is None or licence["expires"] > self.clock())

    def _answer(self, licence: dict[str, Any], machine: str) -> dict[str, Any]:
        return {
            "key": self._key(licence, machine),
            "licence": {"lid": licence["lid"], "plan": licence["plan"], "kind": licence["kind"],
                        "expires": None if licence["expires"] is None else format_time(licence["expires"]),
                        "machines": licence["machines"], "max_projects": licence["max_projects"]},
        }

    def _seat(self, licence: dict[str, Any], machine: str, app_version: str) -> None:
        now = self.clock()
        args = {"lid": licence["lid"], "machine": machine}
        existing = self.db.row("SELECT deactivated FROM activations WHERE lid = :lid AND machine = :machine", **args)
        if existing is not None and existing["deactivated"] is None:
            self.db.run("UPDATE activations SET last_seen = :now, app_version = :version WHERE lid = :lid AND machine = :machine",
                        now=now, version=app_version, **args)
            return
        used = int(self.db.value("SELECT COUNT(*) AS n FROM activations WHERE lid = :lid AND deactivated IS NULL", lid=licence["lid"]) or 0)
        if used >= licence["machines"]:
            n = licence["machines"]
            raise Refused(409, f"All {n} machine{'s' if n != 1 else ''} of this plan are in use. Free one from your account, "
                               "or sign out of Granum on a computer you no longer use.", "machines_full")
        if existing is None:
            self.db.run("INSERT INTO activations(lid, machine, created, last_seen, app_version) VALUES (:lid, :machine, :now, :now, :version)",
                        now=now, version=app_version, **args)
        else:
            self.db.run("UPDATE activations SET deactivated = NULL, last_seen = :now, app_version = :version WHERE lid = :lid AND machine = :machine",
                        now=now, version=app_version, **args)

    def activate(self, email: str, code: str, machine: str, app_version: str = "") -> dict[str, Any]:
        """Sign in on a computer: its paid plan if the email has one, else a free trial."""
        email = normalize_email(email)
        machine = normalize_machine(machine)
        self._check_code(email, code)
        # One activation per email at a time, so two computers cannot take the last machine slot together.
        with self.db.transaction(lock=f"activate:{email}"):
            paid = [lic for lic in self.db.rows("SELECT * FROM licences WHERE email = :email AND kind = 'paid' ORDER BY created", email=email)
                    if self._live(lic)]
            if paid:
                on_this = [lic for lic in paid if self.db.row(
                    "SELECT 1 AS yes FROM activations WHERE lid = :lid AND machine = :machine AND deactivated IS NULL",
                    lid=lic["lid"], machine=machine)]
                last_refusal: Refused | None = None
                for licence in on_this or paid:
                    try:
                        self._seat(licence, machine, app_version)
                        return self._answer(licence, machine)
                    except Refused as exc:
                        last_refusal = exc
                raise last_refusal or Refused(409, "No machine is free on this plan.", "machines_full")
        # One trial decision at a time: a trial is one per email and one per machine, both at once.
        with self.db.transaction(lock="trial"):
            return self._trial(email, machine, app_version)

    def _trial(self, email: str, machine: str, app_version: str) -> dict[str, Any]:
        now = self.clock()
        mine = self.db.row("SELECT * FROM licences WHERE email = :email AND kind = 'trial'", email=email)
        if mine is not None:
            seated = self.db.row("SELECT 1 AS yes FROM activations WHERE lid = :lid AND machine = :machine", lid=mine["lid"], machine=machine)
            if not seated:
                raise Refused(409, "This email's free trial was used on another computer. Buy a plan to continue.", "trial_used")
            if not self._live(mine):
                raise Refused(402, "Your free trial has ended. Buy a plan on the website to continue.", "trial_ended")
            self._seat(mine, machine, app_version)
            return self._answer(mine, machine)
        if self.db.row("SELECT email FROM trials WHERE machine = :machine", machine=machine) is not None:
            raise Refused(409, "This computer has already had a free trial. Buy a plan to continue.", "trial_used")
        lid = f"T-{uuid.uuid4().hex[:12].upper()}"
        self.db.run("INSERT INTO licences(lid, email, customer, plan, kind, created, expires, machines, max_projects) "
                    "VALUES (:lid, :email, :email, 'Free trial', 'trial', :now, :expires, 1, :projects)",
                    lid=lid, email=email, now=now, expires=now + self.settings.trial_days * 86400, projects=self.settings.trial_projects)
        self.db.run("INSERT INTO trials(machine, email, lid, created) VALUES (:machine, :email, :lid, :now)",
                    machine=machine, email=email, lid=lid, now=now)
        licence = self.db.row("SELECT * FROM licences WHERE lid = :lid", lid=lid)
        assert licence is not None
        self._seat(licence, machine, app_version)
        return self._answer(licence, machine)

    def _from_key(self, key: str) -> tuple[dict[str, Any], str]:
        try:
            payload = decode(key, self.public_keys)
        except LicenceError as exc:
            raise Refused(400, str(exc), "key") from exc
        licence = self.db.row("SELECT * FROM licences WHERE lid = :lid", lid=payload["lid"])
        if licence is None:
            raise Refused(404, "This licence is not known to the server.", "unknown")
        return licence, payload["machine"]

    def refresh(self, key: str, app_version: str = "") -> dict[str, Any]:
        """A fresh key with a new lease, for a machine still on a live plan."""
        licence, machine = self._from_key(key)
        seat = self.db.row("SELECT deactivated FROM activations WHERE lid = :lid AND machine = :machine", lid=licence["lid"], machine=machine)
        if seat is None or seat["deactivated"] is not None:
            raise Refused(403, "This computer was signed out of the licence. Sign in again.", "deactivated")
        if licence["revoked"]:
            raise Refused(403, "This licence was cancelled.", "revoked")
        if not self._live(licence):
            raise Refused(402, "The plan has ended. Renew it on the website.", "ended")
        self.db.run("UPDATE activations SET last_seen = :now, app_version = :version WHERE lid = :lid AND machine = :machine",
                    now=self.clock(), version=app_version, lid=licence["lid"], machine=machine)
        return self._answer(licence, machine)

    def deactivate(self, key: str) -> dict[str, Any]:
        """Free this key's machine, so the plan can move to another computer."""
        licence, machine = self._from_key(key)
        self.db.run("UPDATE activations SET deactivated = :now WHERE lid = :lid AND machine = :machine AND deactivated IS NULL",
                    now=self.clock(), lid=licence["lid"], machine=machine)
        return {"freed": machine, "lid": licence["lid"]}

    # -- plans (payments and the admin tool) -------------------------------------------------

    def grant(self, email: str, *, plan: str, days: float | None, machines: int = 1, max_projects: int | None = None,
              customer: str | None = None, note: str = "") -> dict[str, Any]:
        email = normalize_email(email)
        self.register(email, source="purchase")
        now = self.clock()
        lid = f"L-{uuid.uuid4().hex[:12].upper()}"
        self.db.run("INSERT INTO licences(lid, email, customer, plan, kind, created, expires, machines, max_projects, note) "
                    "VALUES (:lid, :email, :customer, :plan, 'paid', :now, :expires, :machines, :projects, :note)",
                    lid=lid, email=email, customer=customer or email, plan=plan, now=now,
                    expires=None if days is None else now + days * 86400, machines=machines, projects=max_projects, note=note)
        return {"lid": lid}

    def extend(self, lid: str, days: float) -> None:
        licence = self.db.row("SELECT expires FROM licences WHERE lid = :lid", lid=lid)
        if licence is None:
            raise Refused(404, f"no licence {lid}")
        base = max(licence["expires"] or self.clock(), self.clock())
        self.db.run("UPDATE licences SET expires = :expires WHERE lid = :lid", expires=base + days * 86400, lid=lid)

    def revoke(self, lid: str) -> None:
        self.db.run("UPDATE licences SET revoked = 1 WHERE lid = :lid", lid=lid)

    def free_machine(self, lid: str, machine: str) -> None:
        self.db.run("UPDATE activations SET deactivated = :now WHERE lid = :lid AND machine = :machine",
                    now=self.clock(), lid=lid, machine=normalize_machine(machine))

    def account(self, email: str) -> dict[str, Any]:
        email = normalize_email(email)
        out = []
        for licence in self.db.rows("SELECT * FROM licences WHERE email = :email ORDER BY created DESC", email=email):
            machines = self.db.rows("SELECT machine, created, last_seen, app_version FROM activations "
                                    "WHERE lid = :lid AND deactivated IS NULL", lid=licence["lid"])
            out.append({**licence, "live": self._live(licence), "active_machines": machines})
        return {"email": email, "licences": out}
