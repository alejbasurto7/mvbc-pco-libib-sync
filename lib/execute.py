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
            result = ExecutionResult(success=True, libib_status=201, created_patron=patron)
            # Best-effort welcome email + card. Failure does not roll back the patron.
            if sender is not None and card_generator is not None:
                try:
                    card_bytes = card_generator(
                        first_name=patron.first_name,
                        last_name=patron.last_name,
                        email=patron.email,
                        barcode=patron.barcode or "",
                    )
                    from pathlib import Path as _P
                    from lib.sender import render_welcome_email
                    html, text = render_welcome_email(
                        first_name=patron.first_name,
                        email=patron.email,
                        templates_dir=_P("templates"),
                    )
                    sender.send(
                        to=patron.email,
                        subject="Welcome to the MVBC Library",
                        body_html=html,
                        body_text=text,
                        attachment_bytes=card_bytes,
                        attachment_filename="library-card.png",
                        attachment_content_type="image/png",
                    )
                    result.email_sent = True
                except Exception as e:
                    result.email_error = f"{type(e).__name__}: {e}"[:1000]
            return result

        elif pending.action_type == "FREEZE_PATRON":
            libib.freeze_patron(email=pending.target["email"])
            return ExecutionResult(success=True, libib_status=200)

        elif pending.action_type == "UNFREEZE_PATRON":
            libib.unfreeze_patron(email=pending.target["email"])
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
