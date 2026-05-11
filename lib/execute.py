"""Dispatch a mature pending action to Libib (and email, in Phase 4).

This module is the bridge from pure decision logic to live API calls.
All side effects pass through here. Returns an ExecutionResult per action;
the caller updates pending state and writes the audit log entry.
"""
from dataclasses import dataclass
from typing import Any, Optional

import requests

from lib.types import PendingChange


@dataclass
class ExecutionResult:
    success: bool
    libib_status: Optional[int] = None
    libib_error: Optional[str] = None
    created_patron: Optional[Any] = None  # the Patron returned by create
    email_sent: bool = False
    email_error: Optional[str] = None


def execute_action(
    pending: PendingChange,
    *,
    libib,           # LibibClient — typed loose so tests can MagicMock
    sender,          # EmailSender or None (Phase 4)
    card_generator,  # CardGenerator or None (Phase 4)
) -> ExecutionResult:
    try:
        if pending.action_type == "CREATE_PATRON":
            patron = libib.create_patron(
                first_name=pending.target["first_name"],
                last_name=pending.target["last_name"],
                email=pending.target["email"],
                patron_id=pending.target["patron_id"],
            )
            return ExecutionResult(success=True, libib_status=201, created_patron=patron)

        elif pending.action_type == "FREEZE_PATRON":
            libib.freeze_patron(email=pending.target["email"])
            return ExecutionResult(success=True, libib_status=200)

        elif pending.action_type == "UPDATE_FIRST_NAME":
            libib.update_patron(
                email=pending.target["email"],
                first_name=pending.target["first_name"],
            )
            return ExecutionResult(success=True, libib_status=200)

        elif pending.action_type == "UPDATE_LAST_NAME":
            libib.update_patron(
                email=pending.target["email"],
                last_name=pending.target["last_name"],
            )
            return ExecutionResult(success=True, libib_status=200)

        elif pending.action_type == "UPDATE_EMAIL":
            libib.update_patron(
                email=pending.target["old_email"],
                new_email=pending.target["email"],
            )
            return ExecutionResult(success=True, libib_status=200)

        else:
            return ExecutionResult(
                success=False,
                libib_error=f"unknown action_type {pending.action_type}",
            )

    except requests.HTTPError as e:
        status = getattr(e.response, "status_code", None) if e.response is not None else None
        body = getattr(e.response, "text", str(e))[:1000] if e.response is not None else str(e)
        return ExecutionResult(success=False, libib_status=status, libib_error=body)
    except Exception as e:
        return ExecutionResult(success=False, libib_error=f"{type(e).__name__}: {e}"[:1000])
