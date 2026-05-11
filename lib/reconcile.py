"""Pure reconciliation logic.

Given the desired actions for this run and the pending state from last run,
produce the new pending state and the list of actions that are mature
(detected_at >= stability_hours ago) and ready to execute.
"""
from dataclasses import replace
from datetime import datetime, timedelta

from lib.types import Action, PendingChange, PendingStatus


def _key(item) -> tuple[str, str]:
    return (item.person_id, item.action_type)


def reconcile(
    desired: list[Action],
    pending: list[PendingChange],
    *,
    now: datetime,
    stability_hours: float,
    baseline_mode: bool = False,
) -> tuple[list[PendingChange], list[PendingChange]]:
    """Compute (new_pending, mature_actions).

    `new_pending` is the full updated pending list to write back to disk.
    `mature_actions` is a subset of `new_pending` ready to execute now.

    A mature action stays in `new_pending` until execute() succeeds and
    removes it (caller's responsibility, not ours — see lib/execute.py).
    """
    pending_by_key = {_key(p): p for p in pending}
    desired_by_key = {_key(a): a for a in desired}

    new_pending: list[PendingChange] = []

    # Walk desired: keep, refresh, or insert
    for key, action in desired_by_key.items():
        existing = pending_by_key.get(key)
        if existing is None:
            status: PendingStatus = "baseline" if baseline_mode else "pending"
            new_pending.append(
                PendingChange(
                    person_id=action.person_id,
                    action_type=action.action_type,
                    target=action.target,
                    detected_at=now,
                    attempts=0,
                    last_attempt_at=None,
                    status=status,
                )
            )
        else:
            if existing.target == action.target:
                # No change in target — preserve detected_at and counters
                new_pending.append(existing)
            else:
                # Target shifted — reset the gate, preserve attempts? No: a
                # different target means a new clock starts.
                new_pending.append(
                    replace(
                        existing,
                        target=action.target,
                        detected_at=now,
                        attempts=0,
                        last_attempt_at=None,
                        status="pending" if existing.status != "baseline" else "baseline",
                    )
                )

    # Walk pending: drop entries that are no longer desired
    # (we already wrote desired ones above; orphans here are reverts)
    # No further work needed: anything in `pending_by_key` not in
    # `desired_by_key` is implicitly dropped because we built new_pending
    # only from desired keys.

    # Compute mature subset
    threshold = now - timedelta(hours=stability_hours)
    mature = [
        p for p in new_pending
        if p.status == "pending" and p.detected_at <= threshold
    ]

    return new_pending, mature
