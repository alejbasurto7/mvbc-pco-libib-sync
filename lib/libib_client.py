"""Wrapper around the Libib REST API.

Authenticates via x-api-key and x-api-user headers.
"""
import time
from typing import Iterator

import requests

from lib.types import Patron

API_BASE = "https://api.libib.com"

_MAX_ATTEMPTS = 5
_BASE_DELAY = 1.0  # seconds


class LibibClient:
    def __init__(
        self,
        api_key: str,
        api_user: str,
        session: requests.Session | None = None,
    ):
        self.api_key = api_key
        self.api_user = api_user
        self.session = session or requests.Session()
        self.session.headers.update({
            "x-api-key": api_key,
            "x-api-user": api_user,
        })

    def _request(self, method: str, url: str, **kwargs) -> requests.Response:
        """Send an HTTP request, retrying on 429 with exponential backoff.

        Retries up to _MAX_ATTEMPTS times total. Honors the Retry-After
        response header when present. All other error statuses propagate
        immediately (caller is responsible for raise_for_status).
        """
        kwargs.setdefault("timeout", 30)
        resp = None
        for attempt in range(_MAX_ATTEMPTS):
            resp = self.session.request(method, url, **kwargs)
            if resp.status_code != 429:
                return resp
            # 429 — decide how long to wait before the next attempt
            retry_after = resp.headers.get("Retry-After")
            if retry_after:
                try:
                    delay = float(retry_after)
                except ValueError:
                    delay = _BASE_DELAY * (2 ** attempt)
            else:
                delay = _BASE_DELAY * (2 ** attempt)
            time.sleep(delay)
        # Exhausted all attempts — raise the final 429
        resp.raise_for_status()
        return resp  # unreachable

    def list_all_patrons(self) -> Iterator[Patron]:
        """Yield every Libib patron, paginating via the `page` query param.

        Stop condition: when a response returns fewer rows than the page's
        `max_per_page`, it's the last page. Real Libib responses don't
        appear to include a reliable grand-total field, so we don't trust
        `total_count` for termination.
        """
        page = 1
        while True:
            resp = self._request(
                "GET",
                f"{API_BASE}/patrons",
                params={"page": page},
            )
            resp.raise_for_status()
            payload = resp.json()
            rows = payload.get("patrons", [])
            if not rows:
                break
            for row in rows:
                yield self._patron_from_dict(row)
            max_per_page = int(payload.get("max_per_page", 50))
            if len(rows) < max_per_page:
                break  # last (partial) page
            page += 1

    def get_patron(self, email_or_barcode: str) -> Patron | None:
        """Fetch a single patron by email or barcode. None if not found.

        Libib's GET /patrons/{id} returns HTTP 200 with empty/null fields
        when the patron is missing (rather than 404), so we also treat a
        response with empty patron_id as "not found".
        """
        resp = self._request("GET", f"{API_BASE}/patrons/{email_or_barcode}")
        if resp.status_code == 404:
            return None
        resp.raise_for_status()
        patron = self._patron_from_dict(resp.json())
        if not patron.patron_id:
            return None
        return patron

    def create_patron(
        self,
        *,
        first_name: str,
        last_name: str,
        email: str,
        patron_id: str,
    ) -> Patron:
        params = {
            "first_name": first_name,
            "last_name": last_name,
            "email": email,
            "patron_id": patron_id,
        }
        resp = self._request("POST", f"{API_BASE}/patrons", params=params)
        resp.raise_for_status()
        return self._patron_from_dict(resp.json())

    def freeze_patron(self, *, email: str) -> Patron:
        resp = self._request("POST", f"{API_BASE}/patrons/{email}", params={"freeze": 1})
        resp.raise_for_status()
        return self._patron_from_dict(resp.json())

    def unfreeze_patron(self, *, email: str) -> Patron:
        resp = self._request("POST", f"{API_BASE}/patrons/{email}", params={"freeze": 0})
        resp.raise_for_status()
        return self._patron_from_dict(resp.json())

    def update_patron(
        self,
        *,
        email: str,
        first_name: str | None = None,
        last_name: str | None = None,
        new_email: str | None = None,
        patron_id: str | None = None,
    ) -> Patron:
        """Update fields on a patron, looked up by their current email."""
        params: dict[str, str] = {}
        if first_name is not None:
            params["first_name"] = first_name
        if last_name is not None:
            params["last_name"] = last_name
        if new_email is not None:
            params["email"] = new_email
        if patron_id is not None:
            params["patron_id"] = patron_id
        if not params:
            raise ValueError("update_patron requires at least one field")

        resp = self._request("POST", f"{API_BASE}/patrons/{email}", params=params)
        resp.raise_for_status()
        return self._patron_from_dict(resp.json())

    @staticmethod
    def _patron_from_dict(row: dict) -> Patron:
        tags_raw = row.get("tags") or ""
        tags = tuple(t.strip() for t in tags_raw.split(",") if t.strip())
        return Patron(
            patron_id=str(row.get("patron_id", "")),
            first_name=row.get("first_name") or "",
            last_name=row.get("last_name") or "",
            email=row.get("email") or "",
            barcode=row.get("barcode"),
            is_frozen=bool(row.get("freeze", 0)),
            tags=tags,
        )
