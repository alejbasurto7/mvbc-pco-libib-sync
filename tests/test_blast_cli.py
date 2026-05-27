"""Tests for the blast.py CLI — focuses on the --apply send loop.

The --dry-run code path hits the live Libib API (and a CSV); end-to-end
coverage of dry-run lives in manual smoke runs, not here. The pure
segmentation logic it depends on is covered by test_blast.py.
"""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest

import blast


def _state_blob(*, recipients: dict | None = None) -> dict:
    """Build a minimal blast_state.json payload with two recipients."""
    if recipients is None:
        recipients = {
            "2020000000001": {
                "patron_id": "1",
                "first_name": "Ada",
                "last_name": "Lovelace",
                "email": "ada@example.com",
                "barcode": "2020000000001",
                "csv_status": "active",
                "segment": "regulars",
                "card_token": "a" * 32,
                "card_url": "https://example.test/cards/" + "a" * 32 + ".html",
                "status": "pending",
                "attempts": 0,
                "last_attempt_at": None,
                "last_error": None,
            },
            "2020000006497": {  # Joseph — VIP
                "patron_id": "2",
                "first_name": "Joseph",
                "last_name": "Shanahan",
                "email": "joseph@example.com",
                "barcode": "2020000006497",
                "csv_status": "active",
                "segment": "regulars_vip",
                "card_token": "v" * 32,
                "card_url": "https://example.test/cards/" + "v" * 32 + ".html",
                "status": "pending",
                "attempts": 0,
                "last_attempt_at": None,
                "last_error": None,
            },
        }
    return {
        "version": 1,
        "generated_at": "2026-05-27T00:00:00+00:00",
        "source_csv": "Patrons-Status-20260527.csv",
        "base_url": "https://example.test/cards",
        "summary": {},
        "recipients": recipients,
        "skipped": [],
    }


def _write_state(tmp_path: Path, *, date: str = "20260527", recipients=None) -> Path:
    """Write a blast_state.json under the conventional blast_<date>/ directory."""
    blast_dir = tmp_path / f"blast_{date}"
    blast_dir.mkdir()
    path = blast_dir / "blast_state.json"
    path.write_text(json.dumps(_state_blob(recipients=recipients)), encoding="utf-8")
    return path


def _env(monkeypatch):
    monkeypatch.setenv("GMAIL_USER", "test@example.com")
    monkeypatch.setenv("GMAIL_APP_PASSWORD", "abcdefghijklmnop")


def _patch_sender(monkeypatch):
    """Replace GmailSMTPSender with a MagicMock factory so no SMTP fires.

    Returns the mock instance used by cmd_apply.
    """
    instance = MagicMock()
    instance.send = MagicMock(return_value={"to": "x", "status": "sent"})
    factory = MagicMock(return_value=instance)
    monkeypatch.setattr(blast, "GmailSMTPSender", factory)
    return factory, instance


def _no_pace(monkeypatch):
    """Disable inter-send sleep so the test suite stays snappy."""
    monkeypatch.setattr(blast.time, "sleep", lambda *_a, **_k: None)


# --- baseline guard ----------------------------------------------------------


def test_apply_rejects_confirm_mismatch(tmp_path, monkeypatch, capsys):
    _env(monkeypatch)
    factory, _ = _patch_sender(monkeypatch)
    state_path = _write_state(tmp_path, date="20260527")
    rc = blast.main(["--apply", str(state_path), "--confirm", "20260526"])
    assert rc == 2
    factory.assert_not_called()
    err = capsys.readouterr().err
    assert "does not match manifest date 20260527" in err


def test_apply_rejects_state_outside_blast_directory(tmp_path, monkeypatch):
    _env(monkeypatch)
    factory, _ = _patch_sender(monkeypatch)
    # blast_state.json in a non-blast_<date> dir
    bad_path = tmp_path / "blast_state.json"
    bad_path.write_text(json.dumps(_state_blob()), encoding="utf-8")
    rc = blast.main(["--apply", str(bad_path), "--confirm", "20260527"])
    assert rc == 2
    factory.assert_not_called()


def test_apply_rejects_missing_state_file(tmp_path, monkeypatch):
    _env(monkeypatch)
    factory, _ = _patch_sender(monkeypatch)
    rc = blast.main(["--apply", str(tmp_path / "nope.json"), "--confirm", "20260527"])
    assert rc == 2
    factory.assert_not_called()


def test_apply_requires_confirm_flag(tmp_path, monkeypatch, capsys):
    _env(monkeypatch)
    factory, _ = _patch_sender(monkeypatch)
    state_path = _write_state(tmp_path)
    rc = blast.main(["--apply", str(state_path)])
    assert rc == 2
    factory.assert_not_called()
    assert "--apply requires --confirm" in capsys.readouterr().err


def test_apply_rejects_missing_gmail_env(tmp_path, monkeypatch):
    monkeypatch.delenv("GMAIL_USER", raising=False)
    monkeypatch.delenv("GMAIL_APP_PASSWORD", raising=False)
    factory, _ = _patch_sender(monkeypatch)
    state_path = _write_state(tmp_path)
    rc = blast.main(["--apply", str(state_path), "--confirm", "20260527"])
    assert rc == 2
    factory.assert_not_called()


# --- happy path --------------------------------------------------------------


def test_apply_sends_each_pending_recipient_and_marks_sent(tmp_path, monkeypatch):
    _env(monkeypatch)
    _no_pace(monkeypatch)
    _, sender_instance = _patch_sender(monkeypatch)
    state_path = _write_state(tmp_path)

    rc = blast.main(["--apply", str(state_path), "--confirm", "20260527"])

    assert rc == 0
    assert sender_instance.send.call_count == 2

    # Subject + attachment dispatch by segment
    sends_by_to = {call.kwargs["to"]: call.kwargs for call in sender_instance.send.call_args_list}
    assert sends_by_to["ada@example.com"]["subject"] == "Your new MVBC Library card"
    assert sends_by_to["joseph@example.com"]["subject"] == \
        "Your VIP-edition MVBC Library card — now digital too"
    for kwargs in sends_by_to.values():
        assert kwargs["attachment_filename"] == "library-card.png"
        assert kwargs["attachment_content_type"] == "image/png"
        assert isinstance(kwargs["attachment_bytes"], bytes)
        assert len(kwargs["attachment_bytes"]) > 0

    # State persisted: every recipient is now sent, with attempts=1.
    saved = json.loads(state_path.read_text(encoding="utf-8"))
    for rec in saved["recipients"].values():
        assert rec["status"] == "sent"
        assert rec["attempts"] == 1
        assert rec["last_error"] is None
        assert rec["last_attempt_at"] is not None


def test_apply_skips_already_sent_rows(tmp_path, monkeypatch):
    _env(monkeypatch)
    _no_pace(monkeypatch)
    _, sender_instance = _patch_sender(monkeypatch)

    recipients = _state_blob()["recipients"]
    recipients["2020000000001"]["status"] = "sent"  # already done
    state_path = _write_state(tmp_path, recipients=recipients)

    rc = blast.main(["--apply", str(state_path), "--confirm", "20260527"])

    assert rc == 0
    # Only Joseph (pending) was sent; Ada (sent) was skipped.
    assert sender_instance.send.call_count == 1
    sent_to = sender_instance.send.call_args.kwargs["to"]
    assert sent_to == "joseph@example.com"


def test_apply_retries_failed_rows(tmp_path, monkeypatch):
    _env(monkeypatch)
    _no_pace(monkeypatch)
    _, sender_instance = _patch_sender(monkeypatch)

    recipients = _state_blob()["recipients"]
    recipients["2020000000001"]["status"] = "failed"
    recipients["2020000000001"]["attempts"] = 1
    recipients["2020000000001"]["last_error"] = "previous SMTP hiccup"
    state_path = _write_state(tmp_path, recipients=recipients)

    rc = blast.main(["--apply", str(state_path), "--confirm", "20260527"])

    assert rc == 0
    assert sender_instance.send.call_count == 2
    saved = json.loads(state_path.read_text(encoding="utf-8"))
    ada = saved["recipients"]["2020000000001"]
    assert ada["status"] == "sent"
    assert ada["attempts"] == 2  # bumped, not reset
    assert ada["last_error"] is None


def test_apply_marks_row_failed_when_sender_raises_and_continues(tmp_path, monkeypatch):
    _env(monkeypatch)
    _no_pace(monkeypatch)
    _, sender_instance = _patch_sender(monkeypatch)

    # First call (Ada) succeeds; second (Joseph) raises — exit code should be 1
    # and Joseph's row should land in 'failed' with last_error populated.
    sender_instance.send.side_effect = [
        {"to": "ada@example.com", "status": "sent"},
        RuntimeError("SMTP exploded"),
    ]
    state_path = _write_state(tmp_path)

    rc = blast.main(["--apply", str(state_path), "--confirm", "20260527"])

    assert rc == 1
    saved = json.loads(state_path.read_text(encoding="utf-8"))
    assert saved["recipients"]["2020000000001"]["status"] == "sent"
    joseph = saved["recipients"]["2020000006497"]
    assert joseph["status"] == "failed"
    assert "SMTP exploded" in joseph["last_error"]
    assert joseph["attempts"] == 1


def test_apply_only_email_targets_one_recipient(tmp_path, monkeypatch):
    _env(monkeypatch)
    _no_pace(monkeypatch)
    _, sender_instance = _patch_sender(monkeypatch)
    state_path = _write_state(tmp_path)

    rc = blast.main([
        "--apply", str(state_path), "--confirm", "20260527",
        "--only-email", "JOSEPH@EXAMPLE.COM",  # case-insensitive
    ])

    assert rc == 0
    assert sender_instance.send.call_count == 1
    assert sender_instance.send.call_args.kwargs["to"] == "joseph@example.com"
    saved = json.loads(state_path.read_text(encoding="utf-8"))
    # Ada untouched, Joseph sent.
    assert saved["recipients"]["2020000000001"]["status"] == "pending"
    assert saved["recipients"]["2020000006497"]["status"] == "sent"


def test_apply_only_email_no_match_returns_2(tmp_path, monkeypatch):
    _env(monkeypatch)
    _, sender_instance = _patch_sender(monkeypatch)
    state_path = _write_state(tmp_path)

    rc = blast.main([
        "--apply", str(state_path), "--confirm", "20260527",
        "--only-email", "nobody@example.com",
    ])

    assert rc == 2
    sender_instance.send.assert_not_called()


def test_apply_limit_caps_recipients(tmp_path, monkeypatch):
    _env(monkeypatch)
    _no_pace(monkeypatch)
    _, sender_instance = _patch_sender(monkeypatch)
    state_path = _write_state(tmp_path)

    rc = blast.main(["--apply", str(state_path), "--confirm", "20260527", "--limit", "1"])

    assert rc == 0
    assert sender_instance.send.call_count == 1
    # Only the first recipient ran; the second stays pending.
    saved = json.loads(state_path.read_text(encoding="utf-8"))
    statuses = sorted(rec["status"] for rec in saved["recipients"].values())
    assert statuses == ["pending", "sent"]


# --- CLI mode guards ---------------------------------------------------------


def test_dry_run_and_apply_are_mutually_exclusive(monkeypatch):
    # argparse exits with code 2 via SystemExit on mutually-exclusive violation.
    _env(monkeypatch)
    with pytest.raises(SystemExit) as exc:
        blast.main(["--dry-run", "--apply", "foo.json"])
    assert exc.value.code == 2


def test_at_least_one_mode_required(monkeypatch):
    _env(monkeypatch)
    with pytest.raises(SystemExit) as exc:
        blast.main([])
    assert exc.value.code == 2
