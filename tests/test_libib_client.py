import json
from pathlib import Path

import pytest
import responses

from lib.libib_client import LibibClient
from lib.types import Patron


FIXTURES = Path(__file__).parent / "fixtures"


def load_fixture(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text())


@pytest.fixture
def client():
    return LibibClient(api_key="key", api_user="user")


@responses.activate
def test_list_all_patrons_walks_pagination(client):
    responses.add(
        responses.GET, "https://api.libib.com/patrons",
        json=load_fixture("libib_page_1.json"), status=200,
    )
    responses.add(
        responses.GET, "https://api.libib.com/patrons",
        json=load_fixture("libib_page_2.json"), status=200,
    )
    patrons = list(client.list_all_patrons())
    assert len(patrons) == 3


@responses.activate
def test_list_all_patrons_normalizes_freeze_to_bool(client):
    responses.add(
        responses.GET, "https://api.libib.com/patrons",
        json=load_fixture("libib_page_1.json"), status=200,
    )
    responses.add(
        responses.GET, "https://api.libib.com/patrons",
        json={"patrons": [], "page": 2, "max_per_page": 50, "total_count": 2}, status=200,
    )
    by_id = {p.patron_id: p for p in client.list_all_patrons()}
    assert by_id["100"].is_frozen is False
    assert by_id["200"].is_frozen is True


@responses.activate
def test_list_all_patrons_returns_patron_dataclasses(client):
    responses.add(
        responses.GET, "https://api.libib.com/patrons",
        json=load_fixture("libib_page_1.json"), status=200,
    )
    responses.add(
        responses.GET, "https://api.libib.com/patrons",
        json={"patrons": [], "page": 2, "max_per_page": 50, "total_count": 2}, status=200,
    )
    patrons = list(client.list_all_patrons())
    assert all(isinstance(p, Patron) for p in patrons)


@responses.activate
def test_libib_headers_are_sent(client):
    responses.add(
        responses.GET, "https://api.libib.com/patrons",
        json={"patrons": [], "page": 1, "max_per_page": 50, "total_count": 0}, status=200,
    )
    list(client.list_all_patrons())
    headers = responses.calls[0].request.headers
    assert headers["x-api-key"] == "key"
    assert headers["x-api-user"] == "user"


@responses.activate
def test_create_patron_posts_correct_params(client):
    responses.add(
        responses.POST, "https://api.libib.com/patrons",
        json={"patron_id": "pco-1", "barcode": "BC-NEW", "first_name": "Ana",
              "last_name": "Smith", "email": "ana@example.com", "freeze": 0},
        status=201,
    )
    result = client.create_patron(
        first_name="Ana",
        last_name="Smith",
        email="ana@example.com",
        patron_id="pco-1",
    )
    assert result.barcode == "BC-NEW"
    call = responses.calls[0]
    # Libib expects query params, not JSON body
    assert "first_name=Ana" in call.request.url
    assert "last_name=Smith" in call.request.url
    assert "email=ana%40example.com" in call.request.url
    assert "patron_id=pco-1" in call.request.url


@responses.activate
def test_freeze_patron_uses_email_as_id(client):
    responses.add(
        responses.POST, "https://api.libib.com/patrons/ana@example.com",
        json={"patron_id": "pco-1", "email": "ana@example.com", "freeze": 1,
              "first_name": "Ana", "last_name": "Smith", "barcode": "BC-1"},
        status=200,
    )
    result = client.freeze_patron(email="ana@example.com")
    assert result.is_frozen is True
    assert "freeze=1" in responses.calls[0].request.url


@responses.activate
def test_update_patron_first_name(client):
    responses.add(
        responses.POST, "https://api.libib.com/patrons/ana@example.com",
        json={"patron_id": "pco-1", "email": "ana@example.com", "first_name": "Anna",
              "last_name": "Smith", "barcode": "BC-1", "freeze": 0},
        status=200,
    )
    result = client.update_patron(email="ana@example.com", first_name="Anna")
    assert result.first_name == "Anna"
    assert "first_name=Anna" in responses.calls[0].request.url


@responses.activate
def test_update_patron_email_changes_email(client):
    responses.add(
        responses.POST, "https://api.libib.com/patrons/old@example.com",
        json={"patron_id": "pco-1", "email": "new@example.com", "first_name": "Ana",
              "last_name": "Smith", "barcode": "BC-1", "freeze": 0},
        status=200,
    )
    result = client.update_patron(email="old@example.com", new_email="new@example.com")
    assert result.email == "new@example.com"
    assert "email=new%40example.com" in responses.calls[0].request.url


@responses.activate
def test_update_patron_patron_id(client):
    """Used by the migration script."""
    responses.add(
        responses.POST, "https://api.libib.com/patrons/ana@example.com",
        json={"patron_id": "pco-NEW", "email": "ana@example.com", "first_name": "Ana",
              "last_name": "Smith", "barcode": "BC-1", "freeze": 0},
        status=200,
    )
    result = client.update_patron(email="ana@example.com", patron_id="pco-NEW")
    assert result.patron_id == "pco-NEW"
    assert "patron_id=pco-NEW" in responses.calls[0].request.url
