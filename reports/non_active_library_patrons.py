"""One-off: list library patrons whose PCO Member Status != Active.

Cross-references:
  - PCO custom field "Member Status" (field_definition_id 965092),
    5 values: Active, Homebound - In/Out, Not Attending - In/Out.
  - Library patrons captured in state/blast_20260527/blast_state.json
    (recipients + skipped), which carry email + patron_id (Libib CCB ID).

Match on PCO `remote_id` == Libib `patron_id`, falling back to email.
"""
from __future__ import annotations
import json
import os
import sys
from collections import defaultdict
from pathlib import Path

import requests
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")

APP_ID = os.environ["PCO_APP_ID"]
SECRET = os.environ["PCO_SECRET"]
AUTH = (APP_ID, SECRET)
BASE = "https://api.planningcenteronline.com/people/v2"
MEMBER_STATUS_FIELD_DEF_ID = 965092

S = requests.Session()


def get(url: str, params: dict | None = None) -> dict:
    r = S.get(url, auth=AUTH, params=params, timeout=30)
    r.raise_for_status()
    return r.json()


def walk_field_data() -> dict[str, str]:
    """Return {person_id: member_status_value} for everyone with the field set."""
    result: dict[str, str] = {}
    url = f"{BASE}/field_data"
    params = {
        "where[field_definition_id]": MEMBER_STATUS_FIELD_DEF_ID,
        "per_page": 100,
    }
    while url:
        payload = get(url, params=params)
        for item in payload["data"]:
            attrs = item["attributes"]
            rels = item.get("relationships", {})
            person_ref = rels.get("customizable", {}).get("data") or {}
            if person_ref.get("type") != "Person":
                continue
            result[str(person_ref["id"])] = attrs.get("value") or ""
        url = (payload.get("links") or {}).get("next")
        params = None
    return result


def fetch_people(ids: list[str]) -> dict[str, dict]:
    """Bulk-fetch /people for given IDs, returning {id: {first_name, last_name, email, remote_id, membership}}."""
    out: dict[str, dict] = {}
    # PCO supports where[id] with comma-separated list per docs.
    CHUNK = 75
    for i in range(0, len(ids), CHUNK):
        batch = ids[i : i + CHUNK]
        params = {
            "where[id]": ",".join(batch),
            "include": "emails",
            "per_page": 100,
        }
        payload = get(f"{BASE}/people", params=params)
        email_by_id: dict[str, tuple[str, bool]] = {}
        for inc in payload.get("included", []):
            if inc.get("type") != "Email":
                continue
            a = inc.get("attributes", {})
            email_by_id[inc["id"]] = (a.get("address") or "", bool(a.get("primary")))
        for item in payload["data"]:
            if item.get("type") != "Person":
                continue
            a = item["attributes"]
            rels = item.get("relationships", {})
            email_refs = rels.get("emails", {}).get("data") or []
            primary = None
            first = None
            for ref in email_refs:
                addr, is_p = email_by_id.get(ref.get("id"), ("", False))
                if not addr:
                    continue
                if first is None:
                    first = addr
                if is_p:
                    primary = addr
                    break
            email = primary or first
            rid = a.get("remote_id")
            out[str(item["id"])] = {
                "first_name": a.get("first_name") or "",
                "last_name": a.get("last_name") or "",
                "email": email,
                "remote_id": str(rid) if rid is not None else None,
                "membership": a.get("membership"),
            }
    return out


def load_library_patrons() -> dict[str, dict]:
    """Return {patron_id: {email, first_name, last_name, csv_status, segment_or_reason}}.

    Pulls both the 410 recipients and 79 frozen-skipped from today's blast_state.
    """
    blast = json.loads(
        (ROOT / "state" / "blast_20260527" / "blast_state.json").read_text(encoding="utf-8")
    )
    patrons: dict[str, dict] = {}
    for bc, rec in blast["recipients"].items():
        patrons[str(rec["patron_id"])] = {
            "email": (rec.get("email") or "").lower(),
            "first_name": rec.get("first_name", ""),
            "last_name": rec.get("last_name", ""),
            "csv_status": rec.get("csv_status", ""),
            "bucket": rec.get("segment", ""),
            "barcode": bc,
        }
    for rec in blast.get("skipped", []):
        patrons[str(rec["patron_id"])] = {
            "email": (rec.get("email") or "").lower(),
            "first_name": rec.get("first_name", ""),
            "last_name": rec.get("last_name", ""),
            "csv_status": rec.get("csv_status", ""),
            "bucket": rec.get("reason", ""),
            "barcode": "",
        }
    return patrons


def main() -> None:
    print("→ walking PCO field_data for Member Status…", file=sys.stderr)
    person_status = walk_field_data()
    print(f"   {len(person_status)} people have Member Status set", file=sys.stderr)

    non_active = {pid: v for pid, v in person_status.items() if v and v != "Active"}
    print(f"   {len(non_active)} are non-Active", file=sys.stderr)

    print("→ bulk-fetching PCO people for non-Active IDs…", file=sys.stderr)
    people = fetch_people(list(non_active.keys()))
    print(f"   resolved {len(people)} people", file=sys.stderr)

    print("→ loading library patrons from blast_state…", file=sys.stderr)
    patrons = load_library_patrons()
    print(f"   {len(patrons)} library patrons (recipients + frozen-skipped)", file=sys.stderr)

    email_to_patron = {p["email"]: pid for pid, p in patrons.items() if p["email"]}
    remoteid_to_patron = {pid: pid for pid in patrons}  # patron_id == remote_id

    matches: list[dict] = []
    for pid, status in non_active.items():
        prof = people.get(pid, {})
        email = (prof.get("email") or "").lower()
        rid = prof.get("remote_id")
        # Match priority: remote_id == patron_id (CCB ID), else email.
        matched_patron_id = None
        if rid and rid in remoteid_to_patron:
            matched_patron_id = rid
        elif email and email in email_to_patron:
            matched_patron_id = email_to_patron[email]
        if matched_patron_id:
            patron = patrons[matched_patron_id]
            matches.append({
                "pco_person_id": pid,
                "first_name": prof.get("first_name") or patron["first_name"],
                "last_name": prof.get("last_name") or patron["last_name"],
                "email": email or patron["email"],
                "patron_id": matched_patron_id,
                "barcode": patron["barcode"],
                "member_status": status,
                "libib_csv_status": patron["csv_status"],
                "libib_bucket": patron["bucket"],
            })

    # Group by member_status for reporting.
    matches.sort(key=lambda m: (m["member_status"], m["last_name"], m["first_name"]))
    by_status: dict[str, list[dict]] = defaultdict(list)
    for m in matches:
        by_status[m["member_status"]].append(m)

    # Write CSV and a markdown summary.
    import csv
    out_csv = ROOT / "reports" / "non_active_library_patrons.csv"
    with out_csv.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(
            f,
            fieldnames=[
                "member_status",
                "first_name",
                "last_name",
                "email",
                "patron_id",
                "barcode",
                "libib_csv_status",
                "libib_bucket",
                "pco_person_id",
            ],
        )
        w.writeheader()
        for m in matches:
            w.writerow(m)
    print(f"   wrote {out_csv} ({len(matches)} rows)", file=sys.stderr)

    # Console summary.
    print()
    print(f"Library patrons whose PCO Member Status ≠ Active: {len(matches)}")
    print(f"(out of {len(patrons)} library patrons and {len(non_active)} non-Active PCO people)")
    print()
    for status, rows in sorted(by_status.items()):
        print(f"── {status} ({len(rows)}) ──")
        for m in rows:
            tag = f"[{m['libib_csv_status']}]" if m["libib_csv_status"] else ""
            print(f"  {m['last_name']}, {m['first_name']:<15}  {m['email']:<35}  {tag}")
        print()


if __name__ == "__main__":
    main()
