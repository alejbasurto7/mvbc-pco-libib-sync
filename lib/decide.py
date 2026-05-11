"""Pure decision logic. No I/O. No mutation of inputs."""
from lib.types import Action, Patron, Person

MEMBER_STATUSES: set[str] = {"Member", "Associate Member"}


def expected_patron_id(person: Person) -> str:
    """The Libib patron_id we assign when CREATING a new patron for this person.

    Always returns PCO `person.id` — the canonical, post-migration namespace.
    Going forward, every patron we create is keyed by PCO id.
    """
    return person.id


def candidate_patron_ids(person: Person) -> list[str]:
    """All Libib patron_id values that could legitimately match this person.

    Returns [person.id] for post-PCO-only people, or [person.id, person.remote_id]
    for migrated people. Used to match existing Libib patrons regardless of
    which id-scheme they were created under (some Libib patrons have CCB IDs
    from the pre-PCO era, others have PCO IDs from newer additions).
    """
    if person.remote_id and person.remote_id != person.id:
        return [person.id, person.remote_id]
    return [person.id]


def is_eligible(person: Person) -> bool:
    """True if this person should have an active (unfrozen) Libib patron."""
    return (
        person.membership in MEMBER_STATUSES
        and person.email is not None
        and not person.is_destroyed
    )


def _find_matching_patron(
    person: Person,
    patrons_by_id: dict[str, Patron],
) -> Patron | None:
    """Return the Libib patron for this person, checking both id schemes."""
    for pid in candidate_patron_ids(person):
        match = patrons_by_id.get(pid)
        if match is not None:
            return match
    return None


def compute_desired_actions(
    pco_people: list[Person],
    libib_patrons: list[Patron],
) -> list[Action]:
    """Compute actions needed to bring Libib in line with PCO.

    Pure: no I/O, no mutation of inputs.

    Lookup: a PCO person matches the Libib patron whose patron_id equals
    EITHER the person's PCO id OR (for migrated people) their CCB remote_id.
    This handles Libib's mixed historical state where some patron_ids are
    CCB IDs and others are PCO IDs.
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
        existing = _find_matching_patron(person, patrons_by_id)
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
                            "patron_id": expected_patron_id(person),
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
    """Libib patrons whose patron_id matches no PCO person via either id scheme.

    Per spec §4.3, every Libib patron should have a PCO counterpart.
    Orphans are anomalies worth surfacing but never auto-actioned.
    """
    valid_ids: set[str] = set()
    for person in pco_people:
        valid_ids.update(candidate_patron_ids(person))
    return [pat for pat in libib_patrons if pat.patron_id not in valid_ids]
