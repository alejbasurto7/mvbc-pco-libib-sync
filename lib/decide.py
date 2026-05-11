"""Pure decision logic. No I/O. No mutation of inputs."""
from lib.types import Person

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
