"""Wrapper around the Libib REST API.

Authenticates via x-api-key and x-api-user headers.
"""
from typing import Iterator

import requests

from lib.types import Patron

API_BASE = "https://api.libib.com/v1"


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

    def list_all_patrons(self) -> Iterator[Patron]:
        page = 1
        fetched = 0
        while True:
            resp = self.session.get(
                f"{API_BASE}/patrons",
                params={"page": page},
                timeout=30,
            )
            resp.raise_for_status()
            payload = resp.json()
            rows = payload.get("patrons", [])
            if not rows:
                break
            for row in rows:
                yield Patron(
                    patron_id=str(row.get("patron_id", "")),
                    first_name=row.get("first_name") or "",
                    last_name=row.get("last_name") or "",
                    email=row.get("email") or "",
                    barcode=row.get("barcode"),
                    is_frozen=bool(row.get("freeze", 0)),
                )
            fetched += len(rows)
            total_count = int(payload.get("total_count", 0))
            # Stop when we've fetched all records; total_count=0 means stop too
            if total_count == 0 or fetched >= total_count:
                break
            page += 1

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
        resp = self.session.post(
            f"{API_BASE}/patrons",
            params=params,
            timeout=30,
        )
        resp.raise_for_status()
        return self._patron_from_dict(resp.json())

    def freeze_patron(self, *, email: str) -> Patron:
        resp = self.session.post(
            f"{API_BASE}/patrons/{email}",
            params={"freeze": 1},
            timeout=30,
        )
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

        resp = self.session.post(
            f"{API_BASE}/patrons/{email}",
            params=params,
            timeout=30,
        )
        resp.raise_for_status()
        return self._patron_from_dict(resp.json())

    @staticmethod
    def _patron_from_dict(row: dict) -> Patron:
        return Patron(
            patron_id=str(row.get("patron_id", "")),
            first_name=row.get("first_name") or "",
            last_name=row.get("last_name") or "",
            email=row.get("email") or "",
            barcode=row.get("barcode"),
            is_frozen=bool(row.get("freeze", 0)),
        )
