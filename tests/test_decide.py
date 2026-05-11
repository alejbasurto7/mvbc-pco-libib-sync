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
