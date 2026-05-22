"""Shared dataclasses. Pure data — no behavior."""
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Literal, Optional

ActionType = Literal[
    "CREATE_PATRON",
    "FREEZE_PATRON",
    "UNFREEZE_PATRON",
    "UPDATE_FIRST_NAME",
    "UPDATE_LAST_NAME",
    "UPDATE_EMAIL",
]

PendingStatus = Literal["pending", "baseline", "failed"]


@dataclass(frozen=True)
class Person:
    """A person as we model them from PCO."""
    id: str
    remote_id: Optional[str]
    first_name: str
    last_name: str
    email: Optional[str]
    membership: Optional[str]
    is_destroyed: bool = False


@dataclass(frozen=True)
class Patron:
    """A patron as we model them from Libib."""
    patron_id: str
    first_name: str
    last_name: str
    email: str
    barcode: Optional[str]
    is_frozen: bool
    tags: tuple[str, ...] = ()


@dataclass(frozen=True)
class Action:
    """A desired action (newly computed each run)."""
    person_id: str
    action_type: ActionType
    target: dict[str, Any]


@dataclass
class PendingChange:
    """A row in pending.json. Mutable so we can update attempts/status."""
    person_id: str
    action_type: ActionType
    target: dict[str, Any]
    detected_at: datetime
    attempts: int = 0
    last_attempt_at: Optional[datetime] = None
    status: PendingStatus = "pending"
    # Opaque 32-char hex UUID4 minted at CREATE_PATRON enqueue time.
    # Used as the URL slug for the patron's hosted PWA card page.
    # None for non-CREATE actions and for legacy rows written before this field existed.
    card_token: Optional[str] = None
