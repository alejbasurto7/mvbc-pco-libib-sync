"""Pure decision logic. No I/O. No mutation of inputs."""
from lib.types import Action, Patron, Person

MEMBER_STATUSES: set[str] = {"Member", "Associate Member"}


def expected_patron_id(person: Person) -> str:
    """The Libib patron_id we expect for this person.

    Post-migration (per spec §16) every Libib patron's patron_id equals the
    PCO person.id; pre-migration the value lives in PCO's remote_id field.
    The `or` covers both populations and people with no remote_id at all.
    """
    return person.remote_id or person.id


def is_eligible(person: Person) -> bool:
    """True if this person should have an active (unfrozen) Libib patron."""
    return (
        person.membership in MEMBER_STATUSES
        and person.email is not None
        and not person.is_destroyed
    )


def compute_desired_actions(
    pco_people: list[Person],
    libib_patrons: list[Patron],
) -> list[Action]:
    """Compute actions needed to bring Libib in line with PCO.

    Pure: no I/O, no mutation of inputs.

    Lookup: a PCO person matches the Libib patron whose patron_id equals the
    person's expected_patron_id (i.e., remote_id or id).
    """
    patrons_by_id: dict[str, Patron] = {}
    for patron in libib_patrons:
        # patron_id is documented as non-unique by Libib (§4.2). On collision
        # we'd rather no-op than write to the wrong patron, so we skip
        # patrons with conflicting ids by leaving the second one out.
        if patron.patron_id not in patrons_by_id:
            patrons_by_id[patron.patron_id] = patron

    actions: list[Action] = []
    for person in pco_people:
        expected_id = expected_patron_id(person)
        existing = patrons_by_id.get(expected_id)
        if is_eligible(person):
            assert person.email is not None
            if existing is None:
                actions.append(
                    Action(
                        person_id=person.id,
                        action_type="CREATE_PATRON",
                        target={
                            "first_name": person.first_name,
                            "last_name": person.last_name,
                            "email": person.email,
                            "patron_id": expected_id,
                        },
                    )
                )
            else:
                # Use existing.email to key Libib API calls (Libib looks up by current email)
                if person.first_name != existing.first_name:
                    actions.append(
                        Action(
                            person_id=person.id,
                            action_type="UPDATE_FIRST_NAME",
                            target={"first_name": person.first_name, "email": existing.email},
                        )
                    )
                if person.last_name != existing.last_name:
                    actions.append(
                        Action(
                            person_id=person.id,
                            action_type="UPDATE_LAST_NAME",
                            target={"last_name": person.last_name, "email": existing.email},
                        )
                    )
                if person.email != existing.email:
                    actions.append(
                        Action(
                            person_id=person.id,
                            action_type="UPDATE_EMAIL",
                            target={"old_email": existing.email, "email": person.email},
                        )
                    )
        else:
            if existing is not None and not existing.is_frozen:
                actions.append(
                    Action(
                        person_id=person.id,
                        action_type="FREEZE_PATRON",
                        # Use the patron's *current* email — Libib's update
                        # endpoint is keyed by the email it currently knows.
                        target={"email": existing.email},
                    )
                )
    return actions


def find_orphan_patrons(
    pco_people: list[Person],
    libib_patrons: list[Patron],
) -> list[Patron]:
    """Libib patrons whose patron_id matches no PCO person.

    Per spec §4.3, every Libib patron should have a PCO counterpart.
    Orphans are anomalies worth surfacing but never auto-actioned.
    """
    expected_ids = {expected_patron_id(p) for p in pco_people}
    return [pat for pat in libib_patrons if pat.patron_id not in expected_ids]
