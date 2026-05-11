import json
from pathlib import Path

import pytest
import responses

from lib.pco_client import PCOClient
from lib.types import Person


FIXTURES = Path(__file__).parent / "fixtures"


def load_fixture(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text())


@pytest.fixture
def client():
    return PCOClient(app_id="app", secret="sec")


@responses.activate
def test_list_all_people_walks_pagination(client):
    page1 = load_fixture("pco_page_1.json")
    page2 = load_fixture("pco_page_2.json")
    responses.add(
        responses.GET,
        "https://api.planningcenteronline.com/people/v2/people",
        json=page1,
        status=200,
    )
    responses.add(
        responses.GET,
        "https://api.planningcenteronline.com/people/v2/people",
        json=page2,
        status=200,
    )

    people = list(client.list_all_people())

    assert len(people) == 3
    assert all(isinstance(p, Person) for p in people)


@responses.activate
def test_list_all_people_extracts_primary_email(client):
    responses.add(
        responses.GET,
        "https://api.planningcenteronline.com/people/v2/people",
        json=load_fixture("pco_page_1.json"),
        status=200,
    )
    responses.add(
        responses.GET,
        "https://api.planningcenteronline.com/people/v2/people",
        json=load_fixture("pco_page_2.json"),
        status=200,
    )
    by_id = {p.id: p for p in client.list_all_people()}
    assert by_id["100"].email == "ana@example.com"
    assert by_id["101"].email is None  # no primary_email relationship
    assert by_id["102"].email == "carol@example.com"


@responses.activate
def test_list_all_people_membership_and_remote_id(client):
    responses.add(
        responses.GET,
        "https://api.planningcenteronline.com/people/v2/people",
        json=load_fixture("pco_page_1.json"),
        status=200,
    )
    responses.add(
        responses.GET,
        "https://api.planningcenteronline.com/people/v2/people",
        json=load_fixture("pco_page_2.json"),
        status=200,
    )
    by_id = {p.id: p for p in client.list_all_people()}
    assert by_id["100"].membership == "Member"
    assert by_id["100"].remote_id == "42"
    assert by_id["101"].remote_id is None
    assert by_id["102"].membership == "Associate Member"


@responses.activate
def test_basic_auth_header_used(client):
    responses.add(
        responses.GET,
        "https://api.planningcenteronline.com/people/v2/people",
        json={"data": [], "included": [], "links": {"self": "..."}, "meta": {"total_count": 0, "count": 0}},
        status=200,
    )
    list(client.list_all_people())
    assert responses.calls[0].request.headers.get("Authorization", "").startswith("Basic ")
