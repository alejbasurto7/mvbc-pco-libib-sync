"""One-time migration of Libib patron_id values from CCB IDs to PCO IDs.

Run manually after Phase 4, before deploying the live sync (Phase 6).
The live sync expects every Libib patron's patron_id to equal the
corresponding PCO person's id. This script makes that true.

Usage:
    python migrate_patron_ids.py             # dry-run report (default)
    python migrate_patron_ids.py --apply     # actually perform updates
"""
from __future__ import annotations

import truststore
truststore.inject_into_ssl()

import argparse
import json
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from lib.config import load_config
from lib.libib_client import LibibClient
from lib.pco_client import PCOClient
from lib.types import Patron, Person


@dataclass
class MigrationItem:
    old_patron_id: str
    new_patron_id: str
    email: str
    first_name: str
    last_name: str


@dataclass
class MigrationPlan:
    to_migrate: list[MigrationItem] = field(default_factory=list)
    already_migrated: list[Patron] = field(default_factory=list)
    orphans: list[Patron] = field(default_factory=list)
    missing_id: list[Patron] = field(default_factory=list)
    pre_collisions: list[tuple[str, list[Patron]]] = field(default_factory=list)
    post_collisions: list[tuple[str, list[str]]] = field(default_factory=list)


def plan_migration(pco_people: list[Person], libib_patrons: list[Patron]) -> MigrationPlan:
    plan = MigrationPlan()

    # Pre-migration collisions: any duplicate patron_ids in current Libib?
    by_id: dict[str, list[Patron]] = defaultdict(list)
    for p in libib_patrons:
        if p.patron_id:
            by_id[p.patron_id].append(p)
    for pid, group in by_id.items():
        if len(group) > 1:
            plan.pre_collisions.append((pid, group))

    # Map CCB ID → PCO id (only for migrated PCO people with non-empty remote_id)
    ccb_to_pco: dict[str, str] = {
        person.remote_id: person.id
        for person in pco_people
        if person.remote_id
    }
    pco_ids: set[str] = {person.id for person in pco_people}

    # Decide each Libib patron's fate
    for patron in libib_patrons:
        if not patron.patron_id:
            plan.missing_id.append(patron)
            continue
        if patron.patron_id in pco_ids:
            plan.already_migrated.append(patron)
            continue
        if patron.patron_id in ccb_to_pco:
            new_id = ccb_to_pco[patron.patron_id]
            plan.to_migrate.append(MigrationItem(
                old_patron_id=patron.patron_id,
                new_patron_id=new_id,
                email=patron.email,
                first_name=patron.first_name,
                last_name=patron.last_name,
            ))
        else:
            plan.orphans.append(patron)

    # Post-migration collisions: do any planned new ids overlap with existing
    # patron_ids that aren't being migrated?
    planned_new_ids = Counter(item.new_patron_id for item in plan.to_migrate)
    untouched_ids = {p.patron_id for p in plan.already_migrated} | \
                    {p.patron_id for p in plan.orphans} | \
                    {p.patron_id for p in plan.missing_id if p.patron_id}
    for new_id, count in planned_new_ids.items():
        sources = []
        if count > 1:
            sources.append(f"{count}x in to_migrate")
        if new_id in untouched_ids:
            sources.append("non-migrating patron")
        if sources:
            plan.post_collisions.append((new_id, sources))

    return plan


def print_report(plan: MigrationPlan) -> None:
    print(f"  to_migrate:       {len(plan.to_migrate)}")
    print(f"  already_migrated: {len(plan.already_migrated)}")
    print(f"  orphans:          {len(plan.orphans)}")
    print(f"  missing_id:       {len(plan.missing_id)}")
    print(f"  pre_collisions:   {len(plan.pre_collisions)}")
    print(f"  post_collisions:  {len(plan.post_collisions)}")
    if plan.pre_collisions:
        print("\n  PRE-COLLISIONS (duplicate patron_ids in Libib already):")
        for pid, group in plan.pre_collisions:
            print(f"    {pid}: {[p.email for p in group]}")
    if plan.post_collisions:
        print("\n  POST-COLLISIONS (planned new ids would clash):")
        for new_id, sources in plan.post_collisions:
            print(f"    {new_id}: {', '.join(sources)}")
    if plan.orphans:
        print(f"\n  ORPHANS (first 10):")
        for p in plan.orphans[:10]:
            print(f"    patron_id={p.patron_id} email={p.email}")


def apply_migration(libib: LibibClient, plan: MigrationPlan, log_path: Path) -> int:
    """Execute updates one at a time. Halts on first non-2xx response."""
    log_path.parent.mkdir(parents=True, exist_ok=True)
    successes = 0
    for item in plan.to_migrate:
        try:
            updated = libib.update_patron(email=item.email, patron_id=item.new_patron_id)
        except Exception as e:
            entry = {
                "ts": datetime.now(timezone.utc).isoformat(),
                "old_patron_id": item.old_patron_id,
                "new_patron_id": item.new_patron_id,
                "email": item.email,
                "success": False,
                "error": f"{type(e).__name__}: {e}"[:1000],
            }
            with log_path.open("a") as f:
                f.write(json.dumps(entry) + "\n")
            print(f"\n  HALTED on {item.email}: {entry['error']}")
            return successes
        entry = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "old_patron_id": item.old_patron_id,
            "new_patron_id": item.new_patron_id,
            "email": item.email,
            "success": True,
            "verified_patron_id": updated.patron_id,
        }
        with log_path.open("a") as f:
            f.write(json.dumps(entry) + "\n")
        successes += 1
        print(f"  migrated: {item.old_patron_id} → {item.new_patron_id} ({item.email})")
    return successes


def main(*, apply: bool, log_path: Path = Path("migration_log.jsonl")) -> int:
    cfg = load_config()
    pco = PCOClient(app_id=cfg.pco_app_id, secret=cfg.pco_secret)
    libib = LibibClient(api_key=cfg.libib_api_key, api_user=cfg.libib_api_user)

    print("Fetching PCO people...")
    people = list(pco.list_all_people())
    print(f"  {len(people)} people")
    print("Fetching Libib patrons...")
    patrons = list(libib.list_all_patrons())
    print(f"  {len(patrons)} patrons")

    plan = plan_migration(people, patrons)
    print("\n=== MIGRATION PLAN ===")
    print_report(plan)

    if plan.pre_collisions or plan.post_collisions:
        print("\nABORT: collisions present. Resolve before retrying.")
        return 2

    if not apply:
        print("\n(dry-run; pass --apply to execute)")
        return 0

    if not plan.to_migrate:
        print("\nNothing to migrate. Done.")
        return 0

    confirm = input(f"\nApply {len(plan.to_migrate)} updates? Type 'yes' to confirm: ")
    if confirm.strip().lower() != "yes":
        print("Aborted by operator.")
        return 1

    successes = apply_migration(libib, plan, log_path)
    print(f"\nApplied {successes}/{len(plan.to_migrate)} successfully.")
    print(f"Audit log: {log_path}")
    return 0 if successes == len(plan.to_migrate) else 3


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true",
                        help="Actually perform updates (default: dry-run)")
    parser.add_argument("--log-path", default="migration_log.jsonl")
    args = parser.parse_args()
    sys.exit(main(apply=args.apply, log_path=Path(args.log_path)))
