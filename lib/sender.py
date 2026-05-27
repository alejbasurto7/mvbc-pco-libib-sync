"""Email sending — Sender protocol + GmailSMTPSender implementation.

The protocol exists so we can swap in a MicrosoftGraphSender later when
familyministry@mvbchurch.org becomes a real mailbox. No code change needed
in execute.py; just a different config value.
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


def _render_card_section(*, templates_dir: Path, card_url: Optional[str]) -> tuple[str, str]:
    # Shared install-instructions snippet — same content for welcome and
    # regulars, since the iOS/Android Add-to-Home-Screen UX is identical
    # regardless of which email delivered the link. Lives in
    # templates/welcome_card_section.{html,txt} for historical reasons;
    # not renamed to keep the diff small.
    if not card_url:
        return "", ""
    tdir = Path(templates_dir)
    html = (tdir / "welcome_card_section.html").read_text(encoding="utf-8").format(
        card_url=card_url,
    )
    text = (tdir / "welcome_card_section.txt").read_text(encoding="utf-8").format(
        card_url=card_url,
    )
    return html, text


def render_welcome_email(
    *,
    first_name: str,
    email: str,
    templates_dir: Path,
    card_url: Optional[str] = None,
) -> tuple[str, str]:
    """Read templates/welcome.html and welcome.txt and substitute placeholders.

    Returns (html, text). Uses str.format() with placeholders {first_name},
    {email}, and {card_section}. When `card_url` is provided, the per-format
    snippet in templates/welcome_card_section.{html,txt} is rendered and
    spliced in; otherwise {card_section} is replaced with an empty string.
    """
    tdir = Path(templates_dir)
    html_main = (tdir / "welcome.html").read_text(encoding="utf-8")
    text_main = (tdir / "welcome.txt").read_text(encoding="utf-8")
    html_snippet, text_snippet = _render_card_section(
        templates_dir=tdir, card_url=card_url,
    )
    html = html_main.format(
        first_name=first_name, email=email, card_section=html_snippet,
    )
    text = text_main.format(
        first_name=first_name, email=email, card_section=text_snippet,
    )
    return html, text


def render_reminder_email(
    *,
    first_name: str,
    email: str,
    templates_dir: Path,
    card_url: Optional[str] = None,
) -> tuple[str, str]:
    """Render the reminder-template email for inactive/new patrons.

    Reminder has no VIP variant today (and isn't keyed by barcode).
    Returns (html, text). Same placeholder contract as the other two
    render helpers and shares the card-section snippet.
    """
    tdir = Path(templates_dir)
    html_main = (tdir / "reminder.html").read_text(encoding="utf-8")
    text_main = (tdir / "reminder.txt").read_text(encoding="utf-8")
    html_snippet, text_snippet = _render_card_section(
        templates_dir=tdir, card_url=card_url,
    )
    html = html_main.format(
        first_name=first_name, email=email, card_section=html_snippet,
    )
    text = text_main.format(
        first_name=first_name, email=email, card_section=text_snippet,
    )
    return html, text


def render_regulars_email(
    *,
    first_name: str,
    email: str,
    barcode: str,
    templates_dir: Path,
    card_url: Optional[str] = None,
) -> tuple[str, str]:
    """Render the regulars-template email, dispatching by VIP membership.

    Mirrors ``render_welcome_email`` but for the existing-patron touchpoint.
    Returns (html, text). Dispatches on Libib ``barcode`` via
    ``is_vip_patron`` from lib.web_card: VIP patrons get
    ``regulars_vip.{html,txt}``; everyone else gets the standard
    ``regulars.{html,txt}``. The card-section snippet is shared with
    welcome.

    Note: this only renders the body. Choosing the right PNG attachment
    (standard vs ``generate_vip_card_png``) is the caller's job at send
    time, also keyed on barcode.
    """
    from lib.web_card import is_vip_patron

    tdir = Path(templates_dir)
    if is_vip_patron(barcode=barcode):
        html_main = (tdir / "regulars_vip.html").read_text(encoding="utf-8")
        text_main = (tdir / "regulars_vip.txt").read_text(encoding="utf-8")
    else:
        html_main = (tdir / "regulars.html").read_text(encoding="utf-8")
        text_main = (tdir / "regulars.txt").read_text(encoding="utf-8")
    html_snippet, text_snippet = _render_card_section(
        templates_dir=tdir, card_url=card_url,
    )
    html = html_main.format(
        first_name=first_name, email=email, card_section=html_snippet,
    )
    text = text_main.format(
        first_name=first_name, email=email, card_section=text_snippet,
    )
    return html, text
