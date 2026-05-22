"""Persistence for pending.json and sync_log/*.jsonl files.

Read/write to a state directory (typically `state/` at repo root). All
timestamps stored as ISO 8601 with timezone offsets.
"""
import json
from dataclasses import asdict
from datetime import datetime
from pathlib import Path

from lib.types import PendingChange

PENDING_VERSION = 1


def load_pending(state_dir: Path) -> list[PendingChange]:
    """Read pending.json. Returns empty list if file is missing."""
    pending_file = Path(state_dir) / "pending.json"
    if not pending_file.exists():
        return []
    data = json.loads(pending_file.read_text())
    return [_pending_from_dict(row) for row in data.get("rows", [])]


def save_pending(
    state_dir: Path,
    rows: list[PendingChange],
    *,
    now: datetime,
) -> None:
    """Write pending.json. Overwrites the file."""
    pending_file = Path(state_dir) / "pending.json"
    pending_file.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "version": PENDING_VERSION,
        "updated_at": now.isoformat(),
        "rows": [_pending_to_dict(row) for row in rows],
    }
    pending_file.write_text(json.dumps(payload, indent=2))


def append_log(state_dir: Path, ts: datetime, entry: dict) -> None:
    """Append a JSON entry (one line) to the monthly sync_log file.

    Adds `ts` field automatically.
    """
    month_key = ts.strftime("%Y-%m")
    log_file = Path(state_dir) / "sync_log" / f"{month_key}.jsonl"
    log_file.parent.mkdir(parents=True, exist_ok=True)
    record = {"ts": ts.isoformat(), **entry}
    with log_file.open("a") as f:
        f.write(json.dumps(record) + "\n")


def _pending_to_dict(row: PendingChange) -> dict:
    d = asdict(row)
    d["detected_at"] = row.detected_at.isoformat()
    d["last_attempt_at"] = (
        row.last_attempt_at.isoformat() if row.last_attempt_at else None
    )
    return d


def _pending_from_dict(d: dict) -> PendingChange:
    return PendingChange(
        person_id=d["person_id"],
        action_type=d["action_type"],
        target=d["target"],
        detected_at=datetime.fromisoformat(d["detected_at"]),
        attempts=d.get("attempts", 0),
        last_attempt_at=(
            datetime.fromisoformat(d["last_attempt_at"])
            if d.get("last_attempt_at")
            else None
        ),
        status=d.get("status", "pending"),
        card_token=d.get("card_token"),
    )
