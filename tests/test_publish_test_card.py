"""Unit tests for publish_test_card.find_person — pure matching logic."""
from unittest.mock import MagicMock

from lib.types import Person
from publish_test_card import find_person


def _person(id_, email=None, remote_id=None, first="Ana", last="Smith"):
    return Person(
        id=id_, remote_id=remote_id,
        first_name=first, last_name=last,
        email=email, membership=None, is_destroyed=False,
    )


def _fake_pco(people):
    pco = MagicMock()
    pco.list_all_people.return_value = iter(people)
    return pco


def test_finds_by_pco_id():
    pco = _fake_pco([_person("1"), _person("2", email="b@example.com"), _person("3")])
    found = find_person(pco, pco_id="2")
    assert found is not None and found.id == "2"


def test_finds_by_email_case_insensitive():
    pco = _fake_pco([_person("1", email="A@Example.com"), _person("2", email="b@example.com")])
    found = find_person(pco, email="a@example.COM")
    assert found is not None and found.id == "1"


def test_returns_none_when_no_match():
    pco = _fake_pco([_person("1", email="a@example.com")])
    assert find_person(pco, pco_id="999") is None
    assert find_person(pco, email="nobody@example.com") is None


def test_pco_id_takes_precedence_over_email_when_both_given():
    # Both args supplied: id match wins on the first person whose id matches,
    # even if a later person matches the email.
    pco = _fake_pco([
        _person("1", email="other@example.com"),
        _person("2", email="target@example.com"),
    ])
    found = find_person(pco, pco_id="1", email="target@example.com")
    assert found is not None and found.id == "1"


def test_empty_or_whitespace_email_is_ignored():
    pco = _fake_pco([_person("1", email="a@example.com")])
    assert find_person(pco, email="") is None
    assert find_person(pco, email="   ") is None
