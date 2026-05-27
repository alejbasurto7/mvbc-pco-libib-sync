from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from lib.sender import (
    GmailSMTPSender,
    render_regulars_email,
    render_reminder_email,
    render_welcome_email,
)


JOSEPH_BARCODE = "2020000006497"  # mirrors lib.web_card.VIP_BARCODES seed
NON_VIP_BARCODE = "2020000000001"


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
            reply_to="familyministry@mvbchurch.org",
        )
        sender.send(to="to@example.com", subject="Hi", body_html="<p>Hi</p>", body_text="Hi")
        msg = fake_smtp_instance.send_message.call_args[0][0]
        assert msg["Reply-To"] == "familyministry@mvbchurch.org"


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
    assert "{card_section}" not in html
    assert "{card_section}" not in text


def test_render_welcome_email_includes_card_section_when_url_provided():
    url = "https://example.github.io/repo/cards/abc123.html"
    html, text = render_welcome_email(
        first_name="Ana",
        email="ana@x",
        templates_dir=Path("templates"),
        card_url=url,
    )
    # The URL appears, the install instructions appear, the placeholders are gone.
    assert url in html
    assert url in text
    assert "Add to Home Screen" in html
    assert "Add to Home Screen" in text
    assert "Safari" in html and "Chrome" in html
    assert "{card_url}" not in html


def test_render_welcome_email_omits_card_section_when_no_url():
    html, text = render_welcome_email(
        first_name="Ana",
        email="ana@x",
        templates_dir=Path("templates"),
    )
    # No leftover marker, no install instructions.
    assert "{card_section}" not in html
    assert "Add to Home Screen" not in html
    assert "Add to Home Screen" not in text


# --- regulars (standard + VIP) -----------------------------------------------


def test_render_regulars_email_uses_standard_template_for_non_vip():
    html, text = render_regulars_email(
        first_name="Ana", email="ana@example.com",
        barcode=NON_VIP_BARCODE, templates_dir=Path("templates"),
    )
    assert "Ana," in html
    assert "ana@example.com" in html
    assert "Ana," in text
    # Standard regulars greets with "thanks for being part of the community",
    # not the VIP recognition line.
    assert "thanks for being part of the community" in html
    assert "VIP-edition" not in html
    assert "VIP-edition" not in text


def test_render_regulars_email_uses_vip_template_for_joseph():
    html, text = render_regulars_email(
        first_name="Joseph", email="shanajp3@gmail.com",
        barcode=JOSEPH_BARCODE, templates_dir=Path("templates"),
    )
    assert "Joseph," in html
    # VIP recognition wording present in both formats. The VIP card is a
    # singular designation — one patron, not a class — so the phrasing is
    # "single most active patron" (not "most active patrons").
    assert "VIP-edition" in html
    assert "VIP-edition" in text
    assert "single most active patron" in html
    assert "single most active patron" in text
    # Header carries the VIP EDITION marker (case-insensitive substring).
    assert "VIP Edition" in html
    # Sanity: not delivering the standard regulars opener.
    assert "thanks for being part of the community" not in html


def test_render_regulars_email_substitutes_all_placeholders_vip():
    html, text = render_regulars_email(
        first_name="Joseph", email="shanajp3@gmail.com",
        barcode=JOSEPH_BARCODE, templates_dir=Path("templates"),
    )
    for placeholder in ("{first_name}", "{email}", "{card_section}"):
        assert placeholder not in html
        assert placeholder not in text


def test_render_regulars_email_substitutes_all_placeholders_standard():
    html, text = render_regulars_email(
        first_name="Ana", email="ana@x",
        barcode=NON_VIP_BARCODE, templates_dir=Path("templates"),
    )
    for placeholder in ("{first_name}", "{email}", "{card_section}"):
        assert placeholder not in html
        assert placeholder not in text


def test_render_regulars_email_includes_card_section_when_url_provided():
    url = "https://example.github.io/repo/cards/abc123.html"
    html, text = render_regulars_email(
        first_name="Joseph", email="shanajp3@gmail.com",
        barcode=JOSEPH_BARCODE, templates_dir=Path("templates"),
        card_url=url,
    )
    assert url in html
    assert url in text
    assert "Add to Home Screen" in html
    assert "Safari" in html and "Chrome" in html
    assert "{card_url}" not in html


def test_render_regulars_email_omits_card_section_when_no_url():
    html, text = render_regulars_email(
        first_name="Ana", email="ana@x",
        barcode=NON_VIP_BARCODE, templates_dir=Path("templates"),
    )
    assert "{card_section}" not in html
    assert "Add to Home Screen" not in html
    assert "Add to Home Screen" not in text


def test_render_reminder_email_substitutes_placeholders():
    html, text = render_reminder_email(
        first_name="Ana", email="ana@example.com",
        templates_dir=Path("templates"),
    )
    assert "Ana," in html
    assert "ana@example.com" in html
    for placeholder in ("{first_name}", "{email}", "{card_section}"):
        assert placeholder not in html
        assert placeholder not in text


def test_render_reminder_email_includes_card_section_when_url_provided():
    url = "https://example.github.io/repo/cards/abc.html"
    html, text = render_reminder_email(
        first_name="Ana", email="ana@x",
        templates_dir=Path("templates"),
        card_url=url,
    )
    assert url in html
    assert url in text
    assert "Add to Home Screen" in html


def test_render_reminder_email_omits_card_section_when_no_url():
    html, _ = render_reminder_email(
        first_name="Ana", email="ana@x",
        templates_dir=Path("templates"),
    )
    assert "Add to Home Screen" not in html


def test_render_regulars_email_empty_barcode_falls_back_to_standard():
    # An empty barcode must NEVER opt into the VIP template by accident.
    # Mirrors select_card_builders' behavior for the same reason.
    html, _ = render_regulars_email(
        first_name="Ana", email="ana@x",
        barcode="", templates_dir=Path("templates"),
    )
    assert "VIP-edition" not in html
    assert "thanks for being part of the community" in html
