import json
from pathlib import Path
from unittest.mock import patch

import pytest
import requests
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
def test_get_patron_returns_patron_on_200(client):
    responses.add(
        responses.GET, "https://api.libib.com/patrons/ana@example.com",
        json={"patron_id": "pco-1", "first_name": "Ana", "last_name": "Smith",
              "email": "ana@example.com", "barcode": "BC-1", "freeze": 0},
        status=200,
    )
    result = client.get_patron("ana@example.com")
    assert result is not None
    assert result.patron_id == "pco-1"
    assert result.email == "ana@example.com"


@responses.activate
def test_get_patron_returns_none_on_404(client):
    responses.add(
        responses.GET, "https://api.libib.com/patrons/missing@example.com",
        status=404,
    )
    assert client.get_patron("missing@example.com") is None


@responses.activate
def test_get_patron_returns_none_on_200_with_empty_body(client):
    """Libib quirk (observed 2026-05-11): returns 200 with null/empty fields
    when patron is not found, instead of a proper 404. Treat as not-found."""
    responses.add(
        responses.GET, "https://api.libib.com/patrons/missing@example.com",
        json={"patron_id": "", "first_name": "", "last_name": "",
              "email": "", "barcode": None, "freeze": 0},
        status=200,
    )
    assert client.get_patron("missing@example.com") is None


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


# ---------------------------------------------------------------------------
# Retry / 429 tests
# ---------------------------------------------------------------------------

@responses.activate
def test_retries_on_429_until_success(client):
    """Libib often 429s; we retry with backoff."""
    # First two responses are 429, third succeeds
    responses.add(responses.GET, "https://api.libib.com/patrons/ana@x", status=429)
    responses.add(responses.GET, "https://api.libib.com/patrons/ana@x", status=429)
    responses.add(
        responses.GET, "https://api.libib.com/patrons/ana@x",
        json={"patron_id": "1", "first_name": "Ana", "last_name": "S",
              "email": "ana@x", "barcode": "BC-1", "freeze": 0},
        status=200,
    )
    # Patch time.sleep so the test runs instantly
    with patch("lib.libib_client.time.sleep") as fake_sleep:
        result = client.get_patron("ana@x")
    assert result is not None
    assert result.patron_id == "1"
    # Should have slept twice (between attempts 1→2 and 2→3)
    assert fake_sleep.call_count == 2


@responses.activate
def test_429_honors_retry_after_header(client):
    responses.add(
        responses.GET, "https://api.libib.com/patrons/ana@x",
        status=429, headers={"Retry-After": "7"},
    )
    responses.add(
        responses.GET, "https://api.libib.com/patrons/ana@x",
        json={"patron_id": "1", "first_name": "Ana", "last_name": "S",
              "email": "ana@x", "barcode": "BC-1", "freeze": 0},
        status=200,
    )
    with patch("lib.libib_client.time.sleep") as fake_sleep:
        client.get_patron("ana@x")
    fake_sleep.assert_called_once_with(7.0)


@responses.activate
def test_429_gives_up_after_max_attempts(client):
    """After 5 attempts of 429, raise."""
    for _ in range(5):
        responses.add(responses.GET, "https://api.libib.com/patrons/ana@x", status=429)
    with patch("lib.libib_client.time.sleep"):
        with pytest.raises(requests.HTTPError):
            client.get_patron("ana@x")


@responses.activate
def test_non_429_errors_do_not_retry(client):
    """400, 404, 500 etc. should NOT be retried — they're not transient."""
    responses.add(responses.GET, "https://api.libib.com/patrons/ana@x", status=500)
    with patch("lib.libib_client.time.sleep") as fake_sleep:
        with pytest.raises(requests.HTTPError):
            client.get_patron("ana@x")
    fake_sleep.assert_not_called()
