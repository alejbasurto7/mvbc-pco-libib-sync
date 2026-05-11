import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from lib.state import load_pending, save_pending
from lib.types import PendingChange


@pytest.fixture
def tmp_state_dir(tmp_path):
    return tmp_path


def test_load_pending_missing_file_returns_empty(tmp_state_dir):
    assert load_pending(tmp_state_dir) == []


def test_load_pending_empty_rows_returns_empty(tmp_state_dir):
    (tmp_state_dir / "pending.json").write_text(
        '{"version": 1, "updated_at": null, "rows": []}'
    )
    assert load_pending(tmp_state_dir) == []


def test_load_pending_round_trips_a_row(tmp_state_dir):
    (tmp_state_dir / "pending.json").write_text(json.dumps({
        "version": 1,
        "updated_at": "2026-05-06T18:30:00+00:00",
        "rows": [{
            "person_id": "pco-1",
            "action_type": "CREATE_PATRON",
            "target": {"email": "x@y", "first_name": "Ana", "last_name": "S", "patron_id": "pco-1"},
            "detected_at": "2026-05-06T14:00:00+00:00",
            "attempts": 0,
            "last_attempt_at": None,
            "status": "pending",
        }],
    }))
    rows = load_pending(tmp_state_dir)
    assert len(rows) == 1
    assert rows[0].person_id == "pco-1"
    assert rows[0].detected_at == datetime(2026, 5, 6, 14, 0, tzinfo=timezone.utc)


def test_save_pending_writes_valid_json(tmp_state_dir):
    row = PendingChange(
        person_id="pco-1",
        action_type="CREATE_PATRON",
        target={"email": "x@y"},
        detected_at=datetime(2026, 5, 6, 14, 0, tzinfo=timezone.utc),
        attempts=1,
        last_attempt_at=datetime(2026, 5, 6, 15, 0, tzinfo=timezone.utc),
        status="pending",
    )
    save_pending(tmp_state_dir, [row], now=datetime(2026, 5, 6, 18, 0, tzinfo=timezone.utc))
    data = json.loads((tmp_state_dir / "pending.json").read_text())
    assert data["version"] == 1
    assert data["updated_at"] == "2026-05-06T18:00:00+00:00"
    assert len(data["rows"]) == 1
    assert data["rows"][0]["attempts"] == 1


def test_save_then_load_round_trip(tmp_state_dir):
    rows_in = [
        PendingChange(
            person_id="pco-1",
            action_type="CREATE_PATRON",
            target={"email": "a@b"},
            detected_at=datetime(2026, 5, 6, 14, 0, tzinfo=timezone.utc),
            attempts=0,
            last_attempt_at=None,
            status="pending",
        ),
    ]
    save_pending(tmp_state_dir, rows_in, now=datetime(2026, 5, 6, 18, 0, tzinfo=timezone.utc))
    rows_out = load_pending(tmp_state_dir)
    assert rows_out == rows_in


from lib.state import append_log


def test_append_log_creates_file_for_month(tmp_state_dir):
    ts = datetime(2026, 5, 6, 18, 30, tzinfo=timezone.utc)
    append_log(tmp_state_dir, ts, {"person_id": "1", "action": "CREATE_PATRON", "success": True})
    log_file = tmp_state_dir / "sync_log" / "2026-05.jsonl"
    assert log_file.exists()
    line = log_file.read_text().strip()
    obj = json.loads(line)
    assert obj["person_id"] == "1"
    assert obj["action"] == "CREATE_PATRON"
    assert obj["ts"] == ts.isoformat()


def test_append_log_appends_to_existing(tmp_state_dir):
    ts = datetime(2026, 5, 6, 18, 30, tzinfo=timezone.utc)
    append_log(tmp_state_dir, ts, {"event": "first"})
    append_log(tmp_state_dir, ts, {"event": "second"})
    log_file = tmp_state_dir / "sync_log" / "2026-05.jsonl"
    lines = log_file.read_text().strip().split("\n")
    assert len(lines) == 2
    assert json.loads(lines[0])["event"] == "first"
    assert json.loads(lines[1])["event"] == "second"


def test_append_log_separate_file_per_month(tmp_state_dir):
    append_log(tmp_state_dir, datetime(2026, 5, 6, tzinfo=timezone.utc), {"x": 1})
    append_log(tmp_state_dir, datetime(2026, 6, 1, tzinfo=timezone.utc), {"x": 2})
    assert (tmp_state_dir / "sync_log" / "2026-05.jsonl").exists()
    assert (tmp_state_dir / "sync_log" / "2026-06.jsonl").exists()
