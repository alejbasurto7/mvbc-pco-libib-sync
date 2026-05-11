from datetime import datetime, timezone

from lib.types import Action, ActionType, PendingChange, Patron, Person


def test_person_minimal_construction():
    p = Person(
        id="123",
        remote_id="ccb-456",
        first_name="Ana",
        last_name="Smith",
        email="ana@example.com",
        membership="Member",
        is_destroyed=False,
    )
    assert p.id == "123"
    assert p.remote_id == "ccb-456"


def test_person_destroyed_defaults_to_false():
    p = Person(id="1", remote_id=None, first_name="A", last_name="B", email=None, membership=None)
    assert p.is_destroyed is False


def test_patron_minimal_construction():
    pat = Patron(
        patron_id="123",
        first_name="Ana",
        last_name="Smith",
        email="ana@example.com",
        barcode="BC-001",
        is_frozen=False,
    )
    assert pat.is_frozen is False


def test_action_type_literals():
    a = Action(person_id="1", action_type="CREATE_PATRON", target={"email": "x@y"})
    assert a.action_type == "CREATE_PATRON"


def test_pending_change_construction():
    pc = PendingChange(
        person_id="1",
        action_type="CREATE_PATRON",
        target={"email": "x@y"},
        detected_at=datetime(2026, 5, 6, 12, 0, tzinfo=timezone.utc),
        attempts=0,
        last_attempt_at=None,
        status="pending",
    )
    assert pc.attempts == 0
    assert pc.status == "pending"
