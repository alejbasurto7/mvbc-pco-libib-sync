from lib.decide import MEMBER_STATUSES, expected_patron_id, is_eligible
from lib.types import Person


def make_person(**overrides) -> Person:
    """Default-everything Person factory for tests."""
    base = dict(
        id="pco-1",
        remote_id=None,
        first_name="Ana",
        last_name="Smith",
        email="ana@example.com",
        membership="Member",
        is_destroyed=False,
    )
    base.update(overrides)
    return Person(**base)


class TestExpectedPatronId:
    def test_uses_remote_id_when_present(self):
        p = make_person(id="pco-1", remote_id="ccb-42")
        assert expected_patron_id(p) == "ccb-42"

    def test_falls_back_to_id_when_remote_id_is_none(self):
        p = make_person(id="pco-1", remote_id=None)
        assert expected_patron_id(p) == "pco-1"

    def test_falls_back_to_id_when_remote_id_is_empty_string(self):
        p = make_person(id="pco-1", remote_id="")
        assert expected_patron_id(p) == "pco-1"


class TestIsEligible:
    def test_member_with_email_is_eligible(self):
        assert is_eligible(make_person(membership="Member"))

    def test_associate_member_with_email_is_eligible(self):
        assert is_eligible(make_person(membership="Associate Member"))

    def test_visitor_is_not_eligible(self):
        assert not is_eligible(make_person(membership="Visitor"))

    def test_member_without_email_is_not_eligible(self):
        assert not is_eligible(make_person(membership="Member", email=None))

    def test_destroyed_person_is_not_eligible(self):
        assert not is_eligible(make_person(membership="Member", is_destroyed=True))

    def test_member_statuses_constant(self):
        assert MEMBER_STATUSES == {"Member", "Associate Member"}


from lib.decide import compute_desired_actions
from lib.types import Action, Patron


def make_patron(**overrides) -> Patron:
    base = dict(
        patron_id="pco-1",
        first_name="Ana",
        last_name="Smith",
        email="ana@example.com",
        barcode="BC-1",
        is_frozen=False,
    )
    base.update(overrides)
    return Patron(**base)


class TestComputeDesiredActions_Create:
    def test_eligible_person_with_no_libib_patron_creates(self):
        person = make_person(id="pco-1", remote_id=None)
        actions = compute_desired_actions([person], [])
        assert actions == [
            Action(
                person_id="pco-1",
                action_type="CREATE_PATRON",
                target={
                    "first_name": "Ana",
                    "last_name": "Smith",
                    "email": "ana@example.com",
                    "patron_id": "pco-1",
                },
            )
        ]

    def test_visitor_with_no_libib_patron_does_nothing(self):
        person = make_person(membership="Visitor")
        actions = compute_desired_actions([person], [])
        assert actions == []

    def test_member_without_email_does_nothing(self):
        person = make_person(email=None)
        actions = compute_desired_actions([person], [])
        assert actions == []

    def test_create_uses_remote_id_when_present(self):
        person = make_person(id="pco-1", remote_id="ccb-99")
        actions = compute_desired_actions([person], [])
        assert actions[0].target["patron_id"] == "ccb-99"

    def test_existing_eligible_patron_no_diff_returns_empty(self):
        person = make_person(id="pco-1", remote_id=None)
        patron = make_patron(patron_id="pco-1")
        actions = compute_desired_actions([person], [patron])
        assert actions == []


class TestComputeDesiredActions_Freeze:
    def test_member_to_former_member_freezes(self):
        person = make_person(id="pco-1", membership="Former Member")
        patron = make_patron(patron_id="pco-1", is_frozen=False)
        actions = compute_desired_actions([person], [patron])
        assert actions == [
            Action(
                person_id="pco-1",
                action_type="FREEZE_PATRON",
                target={"email": "ana@example.com"},
            )
        ]

    def test_already_frozen_no_double_freeze(self):
        person = make_person(membership="Former Member")
        patron = make_patron(is_frozen=True)
        actions = compute_desired_actions([person], [patron])
        assert actions == []

    def test_destroyed_person_freezes_existing_patron(self):
        person = make_person(id="pco-1", is_destroyed=True)
        patron = make_patron(patron_id="pco-1", is_frozen=False)
        actions = compute_desired_actions([person], [patron])
        assert actions[0].action_type == "FREEZE_PATRON"

    def test_freeze_target_uses_libib_email(self):
        # Libib's update endpoint is keyed by current Libib email
        person = make_person(id="pco-1", email="new@example.com", membership="Visitor")
        patron = make_patron(patron_id="pco-1", email="old@example.com")
        actions = compute_desired_actions([person], [patron])
        assert actions[0].target == {"email": "old@example.com"}

    def test_visitor_with_no_libib_patron_does_nothing(self):
        # The CREATE branch test covered this for non-eligible+no-patron, but
        # double-check we don't synthesize a freeze when there's nothing to freeze.
        person = make_person(membership="Visitor")
        actions = compute_desired_actions([person], [])
        assert actions == []


class TestComputeDesiredActions_Updates:
    def test_first_name_change_emits_update(self):
        person = make_person(id="pco-1", first_name="Anna")
        patron = make_patron(patron_id="pco-1", first_name="Ana")
        actions = compute_desired_actions([person], [patron])
        assert actions == [
            Action(
                person_id="pco-1",
                action_type="UPDATE_FIRST_NAME",
                target={"first_name": "Anna", "email": "ana@example.com"},
            )
        ]

    def test_last_name_change_emits_update(self):
        person = make_person(id="pco-1", last_name="Smyth")
        patron = make_patron(patron_id="pco-1", last_name="Smith")
        actions = compute_desired_actions([person], [patron])
        assert actions == [
            Action(
                person_id="pco-1",
                action_type="UPDATE_LAST_NAME",
                target={"last_name": "Smyth", "email": "ana@example.com"},
            )
        ]

    def test_email_change_emits_update(self):
        person = make_person(id="pco-1", email="new@example.com")
        patron = make_patron(patron_id="pco-1", email="old@example.com")
        actions = compute_desired_actions([person], [patron])
        assert actions == [
            Action(
                person_id="pco-1",
                action_type="UPDATE_EMAIL",
                # Update keyed by *old* email; new email is the target value
                target={"old_email": "old@example.com", "email": "new@example.com"},
            )
        ]

    def test_first_and_last_name_change_emits_two(self):
        person = make_person(id="pco-1", first_name="Anna", last_name="Smyth")
        patron = make_patron(patron_id="pco-1", first_name="Ana", last_name="Smith")
        actions = compute_desired_actions([person], [patron])
        types = [a.action_type for a in actions]
        assert types == ["UPDATE_FIRST_NAME", "UPDATE_LAST_NAME"]

    def test_no_diffs_no_actions(self):
        person = make_person(id="pco-1", first_name="Ana", last_name="Smith", email="ana@example.com")
        patron = make_patron(patron_id="pco-1", first_name="Ana", last_name="Smith", email="ana@example.com")
        assert compute_desired_actions([person], [patron]) == []

    def test_updates_skip_when_patron_already_frozen(self):
        # If the patron is frozen we shouldn't push name/email updates while frozen
        # — they'll un-freeze when the person becomes eligible again.
        person = make_person(id="pco-1", first_name="Anna", membership="Former Member")
        patron = make_patron(patron_id="pco-1", first_name="Ana", is_frozen=True)
        actions = compute_desired_actions([person], [patron])
        # Not eligible AND already frozen → nothing
        assert actions == []
