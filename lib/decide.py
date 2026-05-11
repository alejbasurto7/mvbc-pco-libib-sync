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
            if existing is None:
                # CREATE: type narrowing — is_eligible guarantees email
                assert person.email is not None
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
    return actions
