"""Wrapper around Planning Center People API.

Authenticates with a Personal Access Token (App ID + Secret) via HTTP Basic.
Yields normalized Person objects, handling pagination and email lookup.
"""
from typing import Iterator

import requests

from lib.types import Person

API_BASE = "https://api.planningcenteronline.com/people/v2"


class PCOClient:
    def __init__(self, app_id: str, secret: str, session: requests.Session | None = None):
        self.app_id = app_id
        self.secret = secret
        self.session = session or requests.Session()

    def list_all_people(self, per_page: int = 100) -> Iterator[Person]:
        """Yield every PCO person, walking pagination.

        Includes related email records to extract the primary email.
        """
        url = f"{API_BASE}/people"
        params = {"include": "emails", "per_page": per_page}

        while url:
            resp = self.session.get(
                url,
                params=params if "offset" not in url else None,
                auth=(self.app_id, self.secret),
                timeout=30,
            )
            resp.raise_for_status()
            payload = resp.json()

            email_by_id = {
                inc["id"]: inc["attributes"]["address"]
                for inc in payload.get("included", [])
                if inc.get("type") == "Email"
            }

            for item in payload["data"]:
                if item.get("type") != "Person":
                    continue
                attrs = item["attributes"]
                rels = item.get("relationships", {})
                primary_rel = rels.get("primary_email", {}).get("data")
                email = email_by_id.get(primary_rel["id"]) if primary_rel else None

                yield Person(
                    id=item["id"],
                    remote_id=attrs.get("remote_id"),
                    first_name=attrs.get("first_name") or "",
                    last_name=attrs.get("last_name") or "",
                    email=email,
                    membership=attrs.get("membership"),
                    is_destroyed=False,  # PCO does not return destroyed people in list
                )

            url = payload.get("links", {}).get("next")
            params = None  # next URL has its own query
