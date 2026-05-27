"""Patch today's blast_state.json to skip patrons whose PCO Member Status != Active.

Reads reports/non_active_library_patrons.csv as the block-list. For each blocked
patron currently in `recipients`, moves the entry into `skipped` with
reason='non_active_pco'. Idempotent: already-skipped patrons are left alone.

Writes a .bak alongside the original on first run.
"""
from __future__ import annotations
import csv
import json
import shutil
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
STATE = ROOT / "state" / "blast_20260527" / "blast_state.json"
BLOCK = ROOT / "reports" / "non_active_library_patrons.csv"

REASON = "non_active_pco"


def main() -> None:
    block_rows = list(csv.DictReader(BLOCK.open(encoding="utf-8")))
    blocked_patron_ids = {r["patron_id"] for r in block_rows}
    blocked_status_by_pid = {r["patron_id"]: r["member_status"] for r in block_rows}

    state = json.loads(STATE.read_text(encoding="utf-8"))

    # Backup once.
    bak = STATE.with_suffix(STATE.suffix + ".bak")
    if not bak.exists():
        shutil.copy2(STATE, bak)
        print(f"backup written: {bak.name}")
    else:
        print(f"backup already exists ({bak.name}), leaving as-is")

    # Move blocked recipients → skipped.
    new_skipped = list(state.get("skipped", []))
    new_recipients: dict[str, dict] = {}
    moved: list[dict] = []
    for bc, rec in state["recipients"].items():
        pid = str(rec["patron_id"])
        if pid in blocked_patron_ids:
            moved.append({
                "patron_id": pid,
                "first_name": rec.get("first_name", ""),
                "last_name": rec.get("last_name", ""),
                "email": rec.get("email", ""),
                "csv_status": rec.get("csv_status", ""),
                "reason": REASON,
                "pco_member_status": blocked_status_by_pid.get(pid, ""),
                "previous_segment": rec.get("segment"),
                "barcode": bc,
            })
        else:
            new_recipients[bc] = rec
    new_skipped.extend(moved)

    state["recipients"] = new_recipients
    state["skipped"] = new_skipped

    # Recompute summary.
    seg_counts = Counter(r["segment"] for r in new_recipients.values())
    skip_counts = Counter(r["reason"] for r in new_skipped)
    state["summary"]["segments"] = dict(seg_counts)
    state["summary"]["skipped"] = dict(skip_counts)
    state["summary"]["total_recipients"] = sum(seg_counts.values())
    state["summary"]["total_skipped"] = sum(skip_counts.values())

    STATE.write_text(
        json.dumps(state, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    print()
    print(f"moved {len(moved)} from recipients to skipped")
    by_prev = Counter((m["previous_segment"], m["csv_status"]) for m in moved)
    for k, v in sorted(by_prev.items()):
        print(f"  {k}: {v}")
    print()
    print("new summary:")
    print(json.dumps(state["summary"], indent=2))


if __name__ == "__main__":
    main()
