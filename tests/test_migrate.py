from unittest.mock import MagicMock

from lib.types import Patron, Person
from migrate_patron_ids import plan_migration, MigrationPlan


def make_person(id, remote_id=None, **kw):
    return Person(id=id, remote_id=remote_id, first_name=kw.get("first_name", "F"),
                  last_name=kw.get("last_name", "L"), email=kw.get("email", "x@y"),
                  membership=kw.get("membership", "Member"), is_destroyed=False)


def make_patron(patron_id, **kw):
    return Patron(patron_id=patron_id, first_name=kw.get("first_name", "F"),
                  last_name=kw.get("last_name", "L"), email=kw.get("email", "x@y"),
                  barcode=kw.get("barcode", "BC"), is_frozen=kw.get("is_frozen", False))


def test_plan_skips_libib_patrons_with_empty_patron_id():
    pco = [make_person(id="pco-1", remote_id="ccb-42")]
    libib = [make_patron(patron_id="")]
    plan = plan_migration(pco, libib)
    assert len(plan.missing_id) == 1
    assert len(plan.to_migrate) == 0


def test_plan_skips_already_migrated_when_patron_id_equals_pco_id():
    pco = [make_person(id="pco-1", remote_id="ccb-42")]
    libib = [make_patron(patron_id="pco-1")]
    plan = plan_migration(pco, libib)
    assert len(plan.already_migrated) == 1
    assert len(plan.to_migrate) == 0


def test_plan_marks_orphans_when_no_pco_match():
    pco = [make_person(id="pco-1", remote_id="ccb-42")]
    libib = [make_patron(patron_id="ccb-99")]  # CCB ID with no PCO counterpart
    plan = plan_migration(pco, libib)
    assert len(plan.orphans) == 1
    assert len(plan.to_migrate) == 0


def test_plan_migrates_when_libib_patron_id_matches_pco_remote_id():
    pco = [make_person(id="pco-1", remote_id="ccb-42")]
    libib = [make_patron(patron_id="ccb-42", email="ana@x")]
    plan = plan_migration(pco, libib)
    assert len(plan.to_migrate) == 1
    assert plan.to_migrate[0].old_patron_id == "ccb-42"
    assert plan.to_migrate[0].new_patron_id == "pco-1"
    assert plan.to_migrate[0].email == "ana@x"


def test_plan_detects_pre_migration_collisions():
    pco = [
        make_person(id="pco-1", remote_id="ccb-42"),
        make_person(id="pco-2", remote_id="ccb-99"),
    ]
    libib = [
        make_patron(patron_id="ccb-42", email="a@x"),
        make_patron(patron_id="ccb-42", email="b@x"),  # duplicate patron_id!
    ]
    plan = plan_migration(pco, libib)
    assert len(plan.pre_collisions) > 0


def test_plan_detects_post_migration_collisions():
    # The post-collision case is when a planned new patron_id would collide
    # with a non-migrating Libib patron_id.
    pco = [make_person(id="pco-1", remote_id="ccb-42")]
    libib = [
        make_patron(patron_id="ccb-42", email="a@x"),  # planned new id = pco-1
        make_patron(patron_id="pco-1", email="b@x"),    # already pco-1, would collide
    ]
    plan = plan_migration(pco, libib)
    assert len(plan.post_collisions) > 0
