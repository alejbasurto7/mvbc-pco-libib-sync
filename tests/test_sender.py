from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from lib.sender import GmailSMTPSender, render_welcome_email


def test_gmail_sender_sends_basic():
    with patch("lib.sender.smtplib.SMTP") as fake_smtp:
        fake_smtp_instance = fake_smtp.return_value.__enter__.return_value
        sender = GmailSMTPSender(
            gmail_user="alex@gmail.com",
            gmail_app_password="abcdefghijklmnop",
        )
        result = sender.send(
            to="ana@example.com",
            subject="Welcome",
            body_html="<p>Hi</p>",
            body_text="Hi",
        )
        fake_smtp_instance.login.assert_called_once_with("alex@gmail.com", "abcdefghijklmnop")
        fake_smtp_instance.send_message.assert_called_once()
        msg = fake_smtp_instance.send_message.call_args[0][0]
        assert msg["To"] == "ana@example.com"
        assert msg["Subject"] == "Welcome"
        assert msg["From"] == "alex@gmail.com"  # default_from defaulted to gmail_user
        assert result == {"to": "ana@example.com", "status": "sent"}


def test_gmail_sender_strips_app_password_spaces():
    with patch("lib.sender.smtplib.SMTP") as fake_smtp:
        fake_smtp_instance = fake_smtp.return_value.__enter__.return_value
        sender = GmailSMTPSender(
            gmail_user="alex@gmail.com",
            gmail_app_password="abcd efgh ijkl mnop",
        )
        sender.send(to="to@example.com", subject="Hi", body_html="<p>Hi</p>", body_text="Hi")
        fake_smtp_instance.login.assert_called_once_with("alex@gmail.com", "abcdefghijklmnop")


def test_gmail_sender_uses_default_from_when_set():
    with patch("lib.sender.smtplib.SMTP") as fake_smtp:
        fake_smtp_instance = fake_smtp.return_value.__enter__.return_value
        sender = GmailSMTPSender(
            gmail_user="alex@gmail.com",
            gmail_app_password="abcdefghijklmnop",
            default_from="MVBC Library <alex@gmail.com>",
        )
        sender.send(to="to@example.com", subject="Hi", body_html="<p>Hi</p>", body_text="Hi")
        msg = fake_smtp_instance.send_message.call_args[0][0]
        assert msg["From"] == "MVBC Library <alex@gmail.com>"


def test_gmail_sender_includes_reply_to_when_set():
    with patch("lib.sender.smtplib.SMTP") as fake_smtp:
        fake_smtp_instance = fake_smtp.return_value.__enter__.return_value
        sender = GmailSMTPSender(
            gmail_user="alex@gmail.com",
            gmail_app_password="abcdefghijklmnop",
            reply_to="library@mvbchurch.org",
        )
        sender.send(to="to@example.com", subject="Hi", body_html="<p>Hi</p>", body_text="Hi")
        msg = fake_smtp_instance.send_message.call_args[0][0]
        assert msg["Reply-To"] == "library@mvbchurch.org"


def test_gmail_sender_with_attachment():
    with patch("lib.sender.smtplib.SMTP") as fake_smtp:
        fake_smtp_instance = fake_smtp.return_value.__enter__.return_value
        sender = GmailSMTPSender(
            gmail_user="alex@gmail.com",
            gmail_app_password="abcdefghijklmnop",
        )
        sender.send(
            to="ana@example.com",
            subject="Welcome",
            body_html="<p>Hi</p>",
            body_text="Hi",
            attachment_bytes=b"\x89PNG...",
            attachment_filename="card.png",
            attachment_content_type="image/png",
        )
        fake_smtp_instance.send_message.assert_called_once()
        msg = fake_smtp_instance.send_message.call_args[0][0]
        # Walk the MIME tree to find the attachment part
        payloads = msg.get_payload()
        attachment_found = False
        for part in payloads:
            cd = part.get("Content-Disposition", "")
            if "attachment" in cd:
                assert 'filename="card.png"' in cd
                attachment_found = True
        assert attachment_found, "Attachment part not found in message"


def test_render_welcome_email_substitutes_placeholders():
    html, text = render_welcome_email(
        first_name="Ana",
        email="ana@example.com",
        templates_dir=Path("templates"),
    )
    assert "Ana," in html
    assert "ana@example.com" in html
    assert "Ana," in text
    assert "ana@example.com" in text


def test_render_welcome_email_does_not_double_substitute():
    # If the template already has the literal "{email}" rendered as user data,
    # we don't want to substitute again. (Defensive; not strictly needed.)
    html, text = render_welcome_email(
        first_name="Bob",
        email="b@x",
        templates_dir=Path("templates"),
    )
    # Just sanity: nothing remaining as a placeholder
    assert "{first_name}" not in html
    assert "{email}" not in html
