"""Smoke-test that run.main() walks the pipeline correctly with mocks."""
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

from lib.types import Person, Patron


def test_main_creates_pending_for_new_member(tmp_path, monkeypatch):
    # Mock env
    for k, v in {
        "PCO_APP_ID": "x", "PCO_SECRET": "x",
        "LIBIB_API_KEY": "x", "LIBIB_API_USER": "x",
        "RESEND_API_KEY": "x", "EMAIL_FROM": "x",
        "LIBIB_LOGIN_URL": "https://x",
        "STABILITY_HOURS": "24",
    }.items():
        monkeypatch.setenv(k, v)

    person = Person(
        id="pco-1", remote_id=None, first_name="Ana", last_name="Smith",
        email="ana@example.com", membership="Member", is_destroyed=False,
    )
    fake_pco = MagicMock()
    fake_pco.list_all_people.return_value = iter([person])
    fake_libib = MagicMock()
    fake_libib.list_all_patrons.return_value = iter([])

    fixed_now = datetime(2026, 5, 6, 12, tzinfo=timezone.utc)

    import run
    with patch.object(run, "PCOClient", return_value=fake_pco), \
         patch.object(run, "LibibClient", return_value=fake_libib), \
         patch.object(run, "_now", return_value=fixed_now):
        run.main(state_dir=tmp_path)

    # No mature actions yet (just-detected) — so pending should hold one row
    import json
    data = json.loads((tmp_path / "pending.json").read_text())
    assert len(data["rows"]) == 1
    assert data["rows"][0]["person_id"] == "pco-1"
    assert data["rows"][0]["action_type"] == "CREATE_PATRON"
    fake_libib.create_patron.assert_not_called()
