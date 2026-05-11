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
