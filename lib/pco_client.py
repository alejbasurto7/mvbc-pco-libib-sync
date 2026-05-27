"""Wrapper around Planning Center People API.

Authenticates with a Personal Access Token (App ID + Secret) via HTTP Basic.
Yields normalized Person objects, handling pagination and email lookup.
"""
import time
from typing import Iterator

import requests

from lib.types import Person

API_BASE = "https://api.planningcenteronline.com/people/v2"

_MAX_ATTEMPTS = 5
_BASE_DELAY = 1.0  # seconds

MEMBER_STATUS_FIELD_DEFINITION_ID = 965092
MEMBER_STATUS_ACTIVE_VALUE = "Active"


class PCOClient:
    def __init__(self, app_id: str, secret: str, session: requests.Session | None = None):
        self.app_id = app_id
        self.secret = secret
        self.session = session or requests.Session()

    def _get(self, url: str, **kwargs) -> requests.Response:
        """GET with retry on 429, honoring Retry-After when present.

        PCO documents a limit of 100 requests / 20s per app; a transient 429
        on the first request of a run should not take the whole sync down.
        """
        kwargs.setdefault("timeout", 30)
        resp = None
        for attempt in range(_MAX_ATTEMPTS):
            resp = self.session.get(url, auth=(self.app_id, self.secret), **kwargs)
            if resp.status_code != 429:
                return resp
            retry_after = resp.headers.get("Retry-After")
            if retry_after:
                try:
                    delay = float(retry_after)
                except ValueError:
                    delay = _BASE_DELAY * (2 ** attempt)
            else:
                delay = _BASE_DELAY * (2 ** attempt)
            time.sleep(delay)
        return resp  # final 429; caller raises_for_status

    def list_all_people(self, per_page: int = 100) -> Iterator[Person]:
        """Yield every PCO person, walking pagination.

        Includes related email records to extract the primary email.
        """
        url = f"{API_BASE}/people"
        params = {"include": "emails", "per_page": per_page}

        while url:
            resp = self._get(
                url,
                params=params if "offset" not in url else None,
            )
            resp.raise_for_status()
            payload = resp.json()

            # Build a lookup of Email resources by id, capturing both the
            # address and whether it's the primary one for that person.
            email_by_id: dict[str, tuple[str, bool]] = {}
            for inc in payload.get("included", []):
                if inc.get("type") != "Email":
                    continue
                attrs_e = inc.get("attributes", {})
                email_by_id[inc["id"]] = (
                    attrs_e.get("address") or "",
                    bool(attrs_e.get("primary", False)),
                )

            for item in payload["data"]:
                if item.get("type") != "Person":
                    continue
                attrs = item["attributes"]
                rels = item.get("relationships", {})
                # PCO's People API exposes emails as a relationship array
                # named `emails`. Pick the one marked primary; fall back to
                # the first if none are flagged primary.
                email_refs = rels.get("emails", {}).get("data") or []
                email = None
                first_addr = None
                for ref in email_refs:
                    addr, is_primary = email_by_id.get(ref.get("id"), (None, False))
                    if not addr:
                        continue
                    if first_addr is None:
                        first_addr = addr
                    if is_primary:
                        email = addr
                        break
                if email is None:
                    email = first_addr

                # remote_id comes back as an int in some PCO responses;
                # normalize to str for comparison with Libib patron_id (str).
                rid_raw = attrs.get("remote_id")
                remote_id = str(rid_raw) if rid_raw is not None else None

                yield Person(
                    id=str(item["id"]),
                    remote_id=remote_id,
                    first_name=attrs.get("first_name") or "",
                    last_name=attrs.get("last_name") or "",
                    email=email,
                    membership=attrs.get("membership"),
                    is_destroyed=False,  # PCO does not return destroyed people in list
                )

            url = payload.get("links", {}).get("next")
            params = None  # next URL has its own query

    def fetch_non_active_patron_ids(self) -> set[str]:
        """Return the set of Libib patron_ids whose PCO Member Status != Active.

        Two-step query:
          1. Walk /field_data for the Member Status custom field, collecting
             {person_id: status} for everyone who has the field set.
          2. Bulk-fetch /people for the non-Active person_ids to read their
             ``remote_id`` (= Libib patron_id = CCB ID).

        Returned set is suitable for use as a block-list against CSV
        ``patron_id`` values. People without a ``remote_id`` (i.e. no Libib
        mirror) are omitted — they aren't library patrons anyway.
        """
        # Step 1: enumerate everyone with a Member Status value.
        non_active_person_ids: list[str] = []
        url = f"{API_BASE}/field_data"
        params: dict | None = {
            "where[field_definition_id]": MEMBER_STATUS_FIELD_DEFINITION_ID,
            "per_page": 100,
        }
        while url:
            resp = self._get(url, params=params)
            resp.raise_for_status()
            payload = resp.json()
            for item in payload.get("data", []):
                value = (item.get("attributes") or {}).get("value") or ""
                if value == MEMBER_STATUS_ACTIVE_VALUE or not value:
                    continue
                person_ref = (
                    (item.get("relationships") or {}).get("customizable", {}).get("data") or {}
                )
                if person_ref.get("type") == "Person":
                    non_active_person_ids.append(str(person_ref["id"]))
            url = (payload.get("links") or {}).get("next")
            params = None

        if not non_active_person_ids:
            return set()

        # Step 2: resolve remote_ids in batches via /people?where[id]=...
        patron_ids: set[str] = set()
        CHUNK = 75  # keep URLs comfortably under common query-string limits
        for i in range(0, len(non_active_person_ids), CHUNK):
            batch = non_active_person_ids[i : i + CHUNK]
            resp = self._get(
                f"{API_BASE}/people",
                params={"where[id]": ",".join(batch), "per_page": 100},
            )
            resp.raise_for_status()
            for item in resp.json().get("data", []):
                if item.get("type") != "Person":
                    continue
                rid = (item.get("attributes") or {}).get("remote_id")
                if rid is not None:
                    patron_ids.add(str(rid))
        return patron_ids
