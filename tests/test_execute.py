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
