"""Sending sign-in codes and notices: by SMTP when configured, else to the server log (development)."""

from __future__ import annotations

import logging
import smtplib
from email.message import EmailMessage

logger = logging.getLogger("granum_licence")


class Mailer:
    def __init__(self, *, host: str = "", port: int = 587, user: str = "", password: str = "", sender: str = "") -> None:
        self.host, self.port, self.user, self.password = host, port, user, password
        self.sender = sender or user
        self.sent: list[tuple[str, str]] = []  # (to, code), for tests and development
        self.notices: list[tuple[str, str, str]] = []  # (to, subject, body)

    @property
    def configured(self) -> bool:
        return bool(self.host and self.sender)

    def send_code(self, to: str, code: str, purpose: str = "signin") -> None:
        self.sent.append((to, code))
        if not self.configured:
            logger.warning("no SMTP configured; sign-in code for %s is %s", to, code)
            return
        message = EmailMessage()
        message["From"] = self.sender
        message["To"] = to
        if purpose == "download":
            message["Subject"] = f"Your Granum download code: {code}"
            message.set_content(
                f"Your Granum download code is {code}\n\n"
                "Enter it on the download page to get the installer. It expires in 10 minutes.\n"
                "The current unrestricted alpha has no application activation step or automatic expiry.\n"
                "This code verifies your download email; it is not a shared-workspace password.\n"
                "Usage permission is governed by the proprietary licence.\n\n"
                "If you did not ask for it, ignore this email.\n"
            )
        else:
            message["Subject"] = f"Your Granum sign-in code: {code}"
            message.set_content(
                f"Your Granum sign-in code is {code}\n\n"
                "For an older activation-enabled build, enter it in the licence sign-in screen. It expires in 10 minutes.\n"
                "The current unrestricted alpha does not require application activation.\n"
                "If you did not ask for it, ignore this email.\n"
            )
        self._send(message)

    def send_notice(self, to: str, subject: str, body: str, *, reply_to: str = "") -> None:
        """A plain message to us, e.g. a quote request; replying goes to ``reply_to``."""
        self.notices.append((to, subject, body))
        if not self.configured:
            logger.warning("no SMTP configured; notice to %s: %s\n%s", to, subject, body)
            return
        message = EmailMessage()
        message["From"] = self.sender
        message["To"] = to
        if reply_to:
            message["Reply-To"] = reply_to
        message["Subject"] = subject
        message.set_content(body)
        self._send(message)

    def _send(self, message: EmailMessage) -> None:
        with smtplib.SMTP(self.host, self.port, timeout=20) as smtp:
            smtp.starttls()
            if self.user:
                smtp.login(self.user, self.password)
            smtp.send_message(message)
