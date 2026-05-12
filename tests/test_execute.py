from datetime import datetime, timezone
from unittest.mock import MagicMock

import pytest

from lib.execute import ExecutionResult, execute_action
from lib.types import PendingChange


def make_pending(action_type, target, status="pending", attempts=0):
    return PendingChange(
        person_id="pco-1",
        action_type=action_type,
        target=target,
        detected_at=datetime(2026, 5, 6, 12, tzinfo=timezone.utc),
        attempts=attempts,
        last_attempt_at=None,
        status=status,
    )


def test_create_patron_calls_libib_create_and_returns_success():
    libib = MagicMock()
    fake_patron = MagicMock(barcode="BC-NEW")
    libib.create_patron.return_value = fake_patron

    pending = make_pending("CREATE_PATRON", {
        "first_name": "Ana", "last_name": "Smith",
        "email": "ana@example.com", "patron_id": "pco-1",
    })
    result = execute_action(pending, libib=libib, sender=None, card_generator=None)

    libib.create_patron.assert_called_once_with(
        first_name="Ana", last_name="Smith",
        email="ana@example.com", patron_id="pco-1",
    )
    assert result.success is True
    assert result.libib_status == 201
    assert result.created_patron is fake_patron


def test_freeze_patron_calls_libib_freeze():
    libib = MagicMock()
    libib.freeze_patron.return_value = MagicMock()
    pending = make_pending("FREEZE_PATRON", {"email": "ana@example.com"})
    result = execute_action(pending, libib=libib, sender=None, card_generator=None)
    libib.freeze_patron.assert_called_once_with(email="ana@example.com")
    assert result.success


def test_unfreeze_patron_calls_libib_unfreeze():
    libib = MagicMock()
    libib.unfreeze_patron.return_value = MagicMock()
    pending = make_pending("UNFREEZE_PATRON", {"email": "ana@example.com"})
    result = execute_action(pending, libib=libib, sender=None, card_generator=None)
    libib.unfreeze_patron.assert_called_once_with(email="ana@example.com")
    assert result.success


def test_update_first_name_calls_libib_update():
    libib = MagicMock()
    libib.update_patron.return_value = MagicMock()
    pending = make_pending("UPDATE_FIRST_NAME", {"first_name": "Anna", "email": "ana@x"})
    execute_action(pending, libib=libib, sender=None, card_generator=None)
    libib.update_patron.assert_called_once_with(email="ana@x", first_name="Anna")


def test_update_email_calls_libib_with_old_email_and_new_email():
    libib = MagicMock()
    libib.update_patron.return_value = MagicMock()
    pending = make_pending("UPDATE_EMAIL", {"old_email": "old@x", "email": "new@x"})
    execute_action(pending, libib=libib, sender=None, card_generator=None)
    libib.update_patron.assert_called_once_with(email="old@x", new_email="new@x")


def test_libib_failure_returns_failure_result():
    import requests
    libib = MagicMock()
    libib.create_patron.side_effect = requests.HTTPError("500", response=MagicMock(status_code=500, text="oops"))
    pending = make_pending("CREATE_PATRON", {
        "first_name": "Ana", "last_name": "Smith",
        "email": "x@y", "patron_id": "pco-1",
    })
    result = execute_action(pending, libib=libib, sender=None, card_generator=None)
    assert result.success is False
    assert result.libib_status == 500
    assert "oops" in (result.libib_error or "")


def test_create_patron_sends_welcome_email_with_card():
    libib = MagicMock()
    fake_patron = MagicMock(barcode="BC-NEW", email="ana@example.com",
                            first_name="Ana", last_name="Smith")
    libib.create_patron.return_value = fake_patron

    sender = MagicMock()
    sender.send.return_value = {"id": "msg-1"}

    card_gen = MagicMock()
    card_gen.return_value = b"\x89PNG_FAKE"

    pending = make_pending("CREATE_PATRON", {
        "first_name": "Ana", "last_name": "Smith",
        "email": "ana@example.com", "patron_id": "pco-1",
    })
    result = execute_action(pending, libib=libib, sender=sender, card_generator=card_gen)

    assert result.success
    assert result.email_sent is True
    sender.send.assert_called_once()
    call_kwargs = sender.send.call_args.kwargs
    assert call_kwargs["to"] == "ana@example.com"
    assert call_kwargs["attachment_bytes"] == b"\x89PNG_FAKE"
    assert call_kwargs["attachment_filename"] == "library-card.png"
    assert call_kwargs["attachment_content_type"] == "image/png"
    card_gen.assert_called_once_with(
        first_name="Ana", last_name="Smith",
        email="ana@example.com", barcode="BC-NEW",
    )


def test_create_patron_libib_succeeds_email_fails_does_not_rollback():
    libib = MagicMock()
    fake_patron = MagicMock(barcode="BC-1", email="ana@x",
                            first_name="Ana", last_name="S")
    libib.create_patron.return_value = fake_patron

    sender = MagicMock()
    sender.send.side_effect = RuntimeError("Resend down")

    pending = make_pending("CREATE_PATRON", {
        "first_name": "Ana", "last_name": "S", "email": "ana@x", "patron_id": "pco-1",
    })
    result = execute_action(pending, libib=libib, sender=sender, card_generator=lambda **k: b"x")

    # Libib was successful; overall result.success is True
    assert result.success is True
    assert result.email_sent is False
    assert "Resend down" in (result.email_error or "")


def test_freeze_does_not_send_email():
    libib = MagicMock()
    libib.freeze_patron.return_value = MagicMock()
    sender = MagicMock()
    pending = make_pending("FREEZE_PATRON", {"email": "ana@x"})
    execute_action(pending, libib=libib, sender=sender, card_generator=None)
    sender.send.assert_not_called()
