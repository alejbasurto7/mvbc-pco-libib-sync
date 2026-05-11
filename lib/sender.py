"""Email sending — Sender protocol + GmailSMTPSender implementation.

The protocol exists so we can swap in a MicrosoftGraphSender later when
library@mvbchurch.org becomes a real mailbox. No code change needed in
execute.py; just a different config value.
"""
from __future__ import annotations

import smtplib
from email.mime.application import MIMEApplication
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path
from typing import Optional, Protocol


class EmailSender(Protocol):
    def send(
        self,
        *,
        to: str,
        subject: str,
        body_html: str,
        body_text: str,
        attachment_bytes: Optional[bytes] = None,
        attachment_filename: Optional[str] = None,
        attachment_content_type: Optional[str] = None,
    ) -> dict: ...


class GmailSMTPSender:
    """Send via Gmail SMTP using an App Password.

    Requires 2FA on the Gmail account. App passwords are 16 chars; we strip
    whitespace to be lenient.
    """

    SMTP_HOST = "smtp.gmail.com"
    SMTP_PORT = 587

    def __init__(
        self,
        gmail_user: str,
        gmail_app_password: str,
        default_from: Optional[str] = None,
        reply_to: Optional[str] = None,
    ):
        self.gmail_user = gmail_user
        self.app_password = gmail_app_password.replace(" ", "")
        # default_from controls the displayed "From:" header (e.g. "MVBC Library <alex@gmail.com>").
        # Gmail will rewrite the envelope sender to gmail_user regardless.
        self.default_from = default_from or gmail_user
        self.reply_to = reply_to

    def send(
        self,
        *,
        to: str,
        subject: str,
        body_html: str,
        body_text: str,
        attachment_bytes: Optional[bytes] = None,
        attachment_filename: Optional[str] = None,
        attachment_content_type: Optional[str] = None,
    ) -> dict:
        msg = MIMEMultipart("mixed")
        msg["From"] = self.default_from
        msg["To"] = to
        msg["Subject"] = subject
        if self.reply_to:
            msg["Reply-To"] = self.reply_to

        alternative = MIMEMultipart("alternative")
        alternative.attach(MIMEText(body_text, "plain", "utf-8"))
        alternative.attach(MIMEText(body_html, "html", "utf-8"))
        msg.attach(alternative)

        if attachment_bytes is not None:
            ct = attachment_content_type or "application/octet-stream"
            maintype, _, subtype = ct.partition("/")
            part = MIMEApplication(attachment_bytes, _subtype=subtype or "octet-stream")
            part.add_header(
                "Content-Disposition",
                "attachment",
                filename=attachment_filename or "attachment.bin",
            )
            msg.attach(part)

        with smtplib.SMTP(self.SMTP_HOST, self.SMTP_PORT) as smtp:
            smtp.ehlo()
            smtp.starttls()
            smtp.ehlo()
            smtp.login(self.gmail_user, self.app_password)
            smtp.send_message(msg)

        return {"to": to, "status": "sent"}


def render_welcome_email(
    *,
    first_name: str,
    email: str,
    templates_dir: Path,
) -> tuple[str, str]:
    """Read templates/welcome.html and welcome.txt and substitute placeholders.

    Returns (html, text). Uses str.format() with the only placeholders
    being {first_name} and {email}. Any other braces in the templates
    must be doubled to escape (e.g. CSS `{{ ... }}` if used) — but the
    current welcome.html has no such conflicts.
    """
    html_path = Path(templates_dir) / "welcome.html"
    text_path = Path(templates_dir) / "welcome.txt"

    html = html_path.read_text(encoding="utf-8").format(
        first_name=first_name, email=email,
    )
    text = text_path.read_text(encoding="utf-8").format(
        first_name=first_name, email=email,
    )
    return html, text
