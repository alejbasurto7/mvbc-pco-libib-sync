"""Entry point for the live PCO ↔ Libib sync.

Invoked every 15 minutes by GitHub Actions. Reads the current state of PCO
and Libib, reconciles against pending changes, executes mature ones, and
writes back state.
"""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict, replace
from datetime import datetime, timezone
from pathlib import Path

from lib.config import load_config
from lib.decide import compute_desired_actions, find_orphan_patrons
from lib.execute import execute_action
from lib.libib_client import LibibClient
from lib.pco_client import PCOClient
from lib.reconcile import reconcile
from lib.state import append_log, load_pending, save_pending


def _now() -> datetime:
    return datetime.now(timezone.utc)


def main(*, state_dir: Path = Path("state"), dry_run: bool = False) -> int:
    cfg = load_config()
    now = _now()

    print(f"[{now.isoformat()}] starting sync (baseline_mode={cfg.baseline_mode}, dry_run={dry_run})")

    pco = PCOClient(app_id=cfg.pco_app_id, secret=cfg.pco_secret)
    libib = LibibClient(api_key=cfg.libib_api_key, api_user=cfg.libib_api_user)

    people = list(pco.list_all_people())
    patrons = list(libib.list_all_patrons())
    print(f"  fetched: {len(people)} PCO people, {len(patrons)} Libib patrons")

    desired = compute_desired_actions(people, patrons)
    pending = load_pending(state_dir)
    new_pending, mature = reconcile(
        desired, pending,
        now=now,
        stability_hours=cfg.stability_hours,
        baseline_mode=cfg.baseline_mode,
    )
    print(f"  desired={len(desired)}  pending_after={len(new_pending)}  mature={len(mature)}")

    orphans = find_orphan_patrons(people, patrons)
    for orphan in orphans:
        append_log(state_dir, now, {
            "action": "ORPHAN_DETECTED",
            "patron_id": orphan.patron_id,
            "email": orphan.email,
        })
    if orphans:
        print(f"  orphans={len(orphans)} (logged)")

    if dry_run:
        print("  --dry-run: skipping execution")
        for action in mature:
            print(f"    would execute: {action.action_type} for {action.person_id}")
        return 0

    # Execute mature actions
    final_pending: list = []
    for row in new_pending:
        if row in mature:
            result = execute_action(row, libib=libib, sender=None, card_generator=None)
            append_log(state_dir, now, {
                "person_id": row.person_id,
                "action": row.action_type,
                "success": result.success,
                "libib_status": result.libib_status,
                "libib_error": result.libib_error,
                "attempts": row.attempts + 1,
            })
            if result.success:
                # Drop from pending — done
                continue
            else:
                # Increment attempts; mark failed if attempts >= 3
                attempts = row.attempts + 1
                status = "failed" if attempts >= 3 else row.status
                final_pending.append(replace(
                    row, attempts=attempts, last_attempt_at=now, status=status,
                ))
        else:
            final_pending.append(row)

    save_pending(state_dir, final_pending, now=now)
    print(f"[{_now().isoformat()}] done")
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true",
                        help="Print plan without executing")
    parser.add_argument("--state-dir", default="state",
                        help="Path to state directory")
    args = parser.parse_args()
    sys.exit(main(state_dir=Path(args.state_dir), dry_run=args.dry_run))
