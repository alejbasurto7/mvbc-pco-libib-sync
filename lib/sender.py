"""Email sending — Sender protocol + ResendSender implementation.

The protocol exists so we can swap in a MicrosoftGraphSender later when
library@mvbchurch.org becomes a real mailbox. No code change needed in
execute.py; just a different config value.
"""
from __future__ import annotations

import base64
from pathlib import Path
from typing import Optional, Protocol

import resend


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


class ResendSender:
    def __init__(self, api_key: str, default_from: str, reply_to: Optional[str] = None):
        resend.api_key = api_key
        self.default_from = default_from
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
        params: dict = {
            "from": self.default_from,
            "to": [to],
            "subject": subject,
            "html": body_html,
            "text": body_text,
        }
        if self.reply_to:
            params["reply_to"] = [self.reply_to]
        if attachment_bytes is not None:
            params["attachments"] = [{
                "filename": attachment_filename or "attachment.bin",
                "content": base64.b64encode(attachment_bytes).decode("ascii"),
                "content_type": attachment_content_type or "application/octet-stream",
            }]
        return resend.Emails.send(params)


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
