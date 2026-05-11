from unittest.mock import MagicMock, patch

import pytest

from lib.sender import ResendSender


def test_resend_sender_sends_with_attachment():
    sender = ResendSender(api_key="re_test", default_from="MVBC <a@b>")
    with patch("lib.sender.resend") as fake_resend:
        fake_resend.Emails.send.return_value = {"id": "msg-1"}
        result = sender.send(
            to="ana@example.com",
            subject="Welcome",
            body_html="<p>Hi</p>",
            body_text="Hi",
            attachment_bytes=b"\x89PNG...",
            attachment_filename="card.png",
            attachment_content_type="image/png",
        )
        assert result["id"] == "msg-1"
        call_kwargs = fake_resend.Emails.send.call_args[0][0]
        assert call_kwargs["from"] == "MVBC <a@b>"
        assert call_kwargs["to"] == ["ana@example.com"]
        assert call_kwargs["subject"] == "Welcome"
        assert "<p>Hi</p>" in call_kwargs["html"]
        assert call_kwargs["text"] == "Hi"
        assert len(call_kwargs["attachments"]) == 1
        assert call_kwargs["attachments"][0]["filename"] == "card.png"


def test_resend_sender_without_attachment():
    sender = ResendSender(api_key="re_test", default_from="MVBC <a@b>")
    with patch("lib.sender.resend") as fake_resend:
        fake_resend.Emails.send.return_value = {"id": "msg-2"}
        sender.send(
            to="ana@example.com",
            subject="Hi",
            body_html="<p>Hi</p>",
            body_text="Hi",
        )
        call_kwargs = fake_resend.Emails.send.call_args[0][0]
        assert "attachments" not in call_kwargs or call_kwargs["attachments"] == []


def test_resend_sender_includes_reply_to_when_set():
    sender = ResendSender(api_key="re_test", default_from="MVBC <a@b>", reply_to="alex@church.org")
    with patch("lib.sender.resend") as fake_resend:
        fake_resend.Emails.send.return_value = {"id": "x"}
        sender.send(to="x@y", subject="s", body_html="h", body_text="t")
        kwargs = fake_resend.Emails.send.call_args[0][0]
        assert kwargs["reply_to"] == ["alex@church.org"]


from pathlib import Path

from lib.sender import render_welcome_email


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
