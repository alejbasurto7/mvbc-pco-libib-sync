from lib.decide import MEMBER_STATUSES, expected_patron_id, is_eligible
from lib.types import Person


def make_person(**overrides) -> Person:
    """Default-everything Person factory for tests."""
    base = dict(
        id="pco-1",
        remote_id=None,
        first_name="Ana",
        last_name="Smith",
        email="ana@example.com",
        membership="Member",
        is_destroyed=False,
    )
    base.update(overrides)
    return Person(**base)


class TestExpectedPatronId:
    """expected_patron_id is the patron_id we ASSIGN when creating new patrons.

    Post-PCO-migration canonical: always person.id.
    """

    def test_returns_person_id_when_remote_id_present(self):
        p = make_person(id="pco-1", remote_id="ccb-42")
        assert expected_patron_id(p) == "pco-1"

    def test_returns_person_id_when_remote_id_none(self):
        p = make_person(id="pco-1", remote_id=None)
        assert expected_patron_id(p) == "pco-1"

    def test_returns_person_id_when_remote_id_empty(self):
        p = make_person(id="pco-1", remote_id="")
        assert expected_patron_id(p) == "pco-1"


class TestCandidatePatronIds:
    """candidate_patron_ids lists ALL valid patron_ids the person could match.

    Used to look up existing Libib patrons whose patron_id might be either
    the PCO id (modern) or the CCB remote_id (legacy).
    """

    def test_no_remote_id_returns_only_pco_id(self):
        from lib.decide import candidate_patron_ids
        p = make_person(id="pco-1", remote_id=None)
        assert candidate_patron_ids(p) == ["pco-1"]

    def test_with_remote_id_returns_both(self):
        from lib.decide import candidate_patron_ids
        p = make_person(id="pco-1", remote_id="ccb-42")
        assert candidate_patron_ids(p) == ["pco-1", "ccb-42"]

    def test_pco_id_first_so_modern_scheme_wins(self):
        from lib.decide import candidate_patron_ids
        p = make_person(id="pco-1", remote_id="ccb-42")
        assert candidate_patron_ids(p)[0] == "pco-1"


class TestIsEligible:
    def test_member_with_email_is_eligible(self):
        assert is_eligible(make_person(membership="Member"))

    def test_associate_member_with_email_is_eligible(self):
        assert is_eligible(make_person(membership="Associate Member"))

    def test_visitor_is_not_eligible(self):
        assert not is_eligible(make_person(membership="Visitor"))

    def test_member_without_email_is_not_eligible(self):
        assert not is_eligible(make_person(membership="Member", email=None))

    def test_destroyed_person_is_not_eligible(self):
        assert not is_eligible(make_person(membership="Member", is_destroyed=True))

    def test_member_statuses_constant(self):
        assert MEMBER_STATUSES == {"Member", "Associate Member"}


from lib.decide import compute_desired_actions
from lib.types import Action, Patron


def make_patron(**overrides) -> Patron:
    base = dict(
        patron_id="pco-1",
        first_name="Ana",
        last_name="Smith",
        email="ana@example.com",
        barcode="BC-1",
        is_frozen=False,
    )
    base.update(overrides)
    return Patron(**base)


class TestComputeDesiredActions_Create:
    def test_eligible_person_with_no_libib_patron_creates(self):
        person = make_person(id="pco-1", remote_id=None)
        actions = compute_desired_actions([person], [])
        assert actions == [
            Action(
                person_id="pco-1",
                action_type="CREATE_PATRON",
                target={
                    "first_name": "Ana",
                    "last_name": "Smith",
                    "email": "ana@example.com",
                    "patron_id": "pco-1",
                },
            )
        ]

    def test_visitor_with_no_libib_patron_does_nothing(self):
        person = make_person(membership="Visitor")
        actions = compute_desired_actions([person], [])
        assert actions == []

    def test_member_without_email_does_nothing(self):
        person = make_person(email=None)
        actions = compute_desired_actions([person], [])
        assert actions == []

    def test_create_uses_pco_id_for_new_patron_even_when_remote_id_present(self):
        # We always assign PCO id when creating; remote_id is for matching only
        person = make_person(id="pco-1", remote_id="ccb-99")
        actions = compute_desired_actions([person], [])
        assert actions[0].target["patron_id"] == "pco-1"

    def test_existing_eligible_patron_no_diff_returns_empty(self):
        person = make_person(id="pco-1", remote_id=None)
        patron = make_patron(patron_id="pco-1")
        actions = compute_desired_actions([person], [patron])
        assert actions == []

    def test_matches_libib_patron_by_pco_id(self):
        # Modern Libib state: patron stored under PCO id
        person = make_person(id="pco-1", remote_id="ccb-42")
        patron = make_patron(patron_id="pco-1")
        assert compute_desired_actions([person], [patron]) == []

    def test_matches_libib_patron_by_ccb_remote_id(self):
        # Legacy Libib state: patron stored under CCB id (the remote_id)
        person = make_person(id="pco-1", remote_id="ccb-42")
        patron = make_patron(patron_id="ccb-42")
        assert compute_desired_actions([person], [patron]) == []

    def test_prefers_pco_id_match_when_both_present(self):
        # Two Libib patrons exist — one with PCO id, one with CCB id —
        # for the same person. (Shouldn't happen normally; defensive.) We
        # match the PCO-id one and leave the CCB-id one as an orphan.
        person = make_person(id="pco-1", remote_id="ccb-42",
                             first_name="Ana", last_name="Smith",
                             email="ana@example.com")
        modern_patron = make_patron(patron_id="pco-1", email="ana@example.com",
                                    first_name="Ana", last_name="Smith")
        legacy_patron = make_patron(patron_id="ccb-42", email="old@example.com",
                                    first_name="Different", last_name="Person")
        # Order in input shouldn't matter
        actions = compute_desired_actions([person], [legacy_patron, modern_patron])
        # Matched modern_patron (same data) → no update needed
        assert actions == []


class TestComputeDesiredActions_Freeze:
    def test_member_to_former_member_freezes(self):
        person = make_person(id="pco-1", membership="Former Member")
        patron = make_patron(patron_id="pco-1", is_frozen=False)
        actions = compute_desired_actions([person], [patron])
        assert actions == [
            Action(
                person_id="pco-1",
                action_type="FREEZE_PATRON",
                target={"email": "ana@example.com"},
            )
        ]

    def test_already_frozen_no_double_freeze(self):
        person = make_person(membership="Former Member")
        patron = make_patron(is_frozen=True)
        actions = compute_desired_actions([person], [patron])
        assert actions == []

    def test_destroyed_person_freezes_existing_patron(self):
        person = make_person(id="pco-1", is_destroyed=True)
        patron = make_patron(patron_id="pco-1", is_frozen=False)
        actions = compute_desired_actions([person], [patron])
        assert actions[0].action_type == "FREEZE_PATRON"

    def test_freeze_target_uses_libib_email(self):
        # Libib's update endpoint is keyed by current Libib email
        person = make_person(id="pco-1", email="new@example.com", membership="Visitor")
        patron = make_patron(patron_id="pco-1", email="old@example.com")
        actions = compute_desired_actions([person], [patron])
        assert actions[0].target == {"email": "old@example.com"}

    def test_visitor_with_no_libib_patron_does_nothing(self):
        # The CREATE branch test covered this for non-eligible+no-patron, but
        # double-check we don't synthesize a freeze when there's nothing to freeze.
        person = make_person(membership="Visitor")
        actions = compute_desired_actions([person], [])
        assert actions == []

    def test_protected_tag_skips_freeze(self):
        """A non-eligible person whose Libib patron is tagged with a protected
        tag (e.g., `ssm`) should NOT be auto-frozen."""
        person = make_person(id="pco-1", membership="Non-Member")
        patron = make_patron(patron_id="pco-1", is_frozen=False, tags=("ssm",))
        actions = compute_desired_actions(
            [person], [patron], protected_tags=frozenset({"ssm"}),
        )
        assert actions == []

    def test_protected_tag_matches_anywhere_in_list(self):
        """Patron tagged with multiple values; any match prevents freeze."""
        person = make_person(membership="Non-Member")
        patron = make_patron(is_frozen=False, tags=("staff", "ssm", "other"))
        actions = compute_desired_actions(
            [person], [patron], protected_tags=frozenset({"ssm"}),
        )
        assert actions == []

    def test_unprotected_tag_still_freezes(self):
        """A non-protected tag offers no protection."""
        person = make_person(membership="Non-Member")
        patron = make_patron(is_frozen=False, tags=("random",))
        actions = compute_desired_actions(
            [person], [patron], protected_tags=frozenset({"ssm"}),
        )
        assert len(actions) == 1
        assert actions[0].action_type == "FREEZE_PATRON"

    def test_default_no_protected_tags(self):
        """With no protected_tags kwarg, even ssm-tagged patrons get frozen."""
        person = make_person(membership="Non-Member")
        patron = make_patron(is_frozen=False, tags=("ssm",))
        actions = compute_desired_actions([person], [patron])
        assert len(actions) == 1
        assert actions[0].action_type == "FREEZE_PATRON"


class TestComputeDesiredActions_Updates:
    def test_first_name_change_emits_update(self):
        person = make_person(id="pco-1", first_name="Anna")
        patron = make_patron(patron_id="pco-1", first_name="Ana")
        actions = compute_desired_actions([person], [patron])
        assert actions == [
            Action(
                person_id="pco-1",
                action_type="UPDATE_FIRST_NAME",
                target={"first_name": "Anna", "email": "ana@example.com"},
            )
        ]

    def test_last_name_change_emits_update(self):
        person = make_person(id="pco-1", last_name="Smyth")
        patron = make_patron(patron_id="pco-1", last_name="Smith")
        actions = compute_desired_actions([person], [patron])
        assert actions == [
            Action(
                person_id="pco-1",
                action_type="UPDATE_LAST_NAME",
                target={"last_name": "Smyth", "email": "ana@example.com"},
            )
        ]

    def test_email_change_emits_update(self):
        person = make_person(id="pco-1", email="new@example.com")
        patron = make_patron(patron_id="pco-1", email="old@example.com")
        actions = compute_desired_actions([person], [patron])
        assert actions == [
            Action(
                person_id="pco-1",
                action_type="UPDATE_EMAIL",
                # Update keyed by *old* email; new email is the target value
                target={"old_email": "old@example.com", "email": "new@example.com"},
            )
        ]

    def test_first_and_last_name_change_emits_two(self):
        person = make_person(id="pco-1", first_name="Anna", last_name="Smyth")
        patron = make_patron(patron_id="pco-1", first_name="Ana", last_name="Smith")
        actions = compute_desired_actions([person], [patron])
        types = [a.action_type for a in actions]
        assert types == ["UPDATE_FIRST_NAME", "UPDATE_LAST_NAME"]

    def test_no_diffs_no_actions(self):
        person = make_person(id="pco-1", first_name="Ana", last_name="Smith", email="ana@example.com")
        patron = make_patron(patron_id="pco-1", first_name="Ana", last_name="Smith", email="ana@example.com")
        assert compute_desired_actions([person], [patron]) == []

    def test_updates_skip_when_patron_already_frozen(self):
        # If the patron is frozen we shouldn't push name/email updates while frozen
        # — they'll un-freeze when the person becomes eligible again.
        person = make_person(id="pco-1", first_name="Anna", membership="Former Member")
        patron = make_patron(patron_id="pco-1", first_name="Ana", is_frozen=True)
        actions = compute_desired_actions([person], [patron])
        # Not eligible AND already frozen → nothing
        assert actions == []


from lib.decide import filter_email_conflicts, find_orphan_patrons


class TestFilterEmailConflicts:
    def test_create_without_conflict_is_kept(self):
        action = Action(
            person_id="pco-1", action_type="CREATE_PATRON",
            target={"first_name": "Ana", "last_name": "Smith",
                    "email": "ana@example.com", "patron_id": "pco-1"},
        )
        kept, skipped = filter_email_conflicts([action], [])
        assert kept == [action]
        assert skipped == []

    def test_create_with_email_used_by_another_patron_is_skipped(self):
        action = Action(
            person_id="pco-jane", action_type="CREATE_PATRON",
            target={"first_name": "Jane", "last_name": "Payne",
                    "email": "shared@example.com", "patron_id": "pco-jane"},
        )
        existing = make_patron(patron_id="pco-william", email="shared@example.com",
                               first_name="William", last_name="Payne")
        kept, skipped = filter_email_conflicts([action], [existing])
        assert kept == []
        assert len(skipped) == 1
        assert skipped[0]["reason"] == "shared_email"
        assert skipped[0]["person_id"] == "pco-jane"
        assert skipped[0]["intended_email"] == "shared@example.com"
        assert skipped[0]["conflicts_with_patron_id"] == "pco-william"
        assert "William Payne" in skipped[0]["conflicts_with_name"]

    def test_email_comparison_is_case_insensitive(self):
        action = Action(
            person_id="pco-1", action_type="CREATE_PATRON",
            target={"first_name": "X", "last_name": "Y",
                    "email": "SHARED@Example.Com", "patron_id": "pco-1"},
        )
        existing = make_patron(email="shared@example.com")
        kept, skipped = filter_email_conflicts([action], [existing])
        assert len(skipped) == 1

    def test_update_email_to_already_used_address_is_skipped(self):
        action = Action(
            person_id="pco-jane", action_type="UPDATE_EMAIL",
            target={"old_email": "jane@example.com", "email": "shared@example.com"},
        )
        existing = make_patron(patron_id="pco-william", email="shared@example.com",
                               first_name="William", last_name="P")
        kept, skipped = filter_email_conflicts([action], [existing])
        assert kept == []
        assert len(skipped) == 1
        assert skipped[0]["action_type"] == "UPDATE_EMAIL"

    def test_update_email_to_unused_address_is_kept(self):
        action = Action(
            person_id="pco-1", action_type="UPDATE_EMAIL",
            target={"old_email": "old@example.com", "email": "new@example.com"},
        )
        existing = make_patron(email="someone-else@example.com")
        kept, skipped = filter_email_conflicts([action], [existing])
        assert kept == [action]
        assert skipped == []

    def test_freeze_and_other_updates_unaffected(self):
        actions = [
            Action(person_id="1", action_type="FREEZE_PATRON",
                   target={"email": "frozen@example.com"}),
            Action(person_id="2", action_type="UPDATE_LAST_NAME",
                   target={"last_name": "New", "email": "stable@example.com"}),
        ]
        # An existing patron with a matching email shouldn't block these
        existing = make_patron(email="frozen@example.com")
        kept, skipped = filter_email_conflicts(actions, [existing])
        assert kept == actions
        assert skipped == []


class TestFindOrphanPatrons:
    def test_no_orphans_when_all_match(self):
        person = make_person(id="pco-1", remote_id=None)
        patron = make_patron(patron_id="pco-1")
        assert find_orphan_patrons([person], [patron]) == []

    def test_libib_patron_with_unknown_id_is_orphan(self):
        person = make_person(id="pco-1")
        orphan = make_patron(patron_id="unknown-99")
        result = find_orphan_patrons([person], [orphan])
        assert result == [orphan]

    def test_orphan_detection_accepts_match_via_ccb_remote_id(self):
        # Legacy Libib state: patron stored under CCB remote_id
        person = make_person(id="pco-1", remote_id="ccb-42")
        patron = make_patron(patron_id="ccb-42")
        assert find_orphan_patrons([person], [patron]) == []

    def test_orphan_detection_accepts_match_via_pco_id(self):
        # Modern Libib state: patron stored under PCO id
        person = make_person(id="pco-1", remote_id="ccb-42")
        patron = make_patron(patron_id="pco-1")
        assert find_orphan_patrons([person], [patron]) == []

    def test_orphan_only_when_neither_key_matches(self):
        person = make_person(id="pco-1", remote_id="ccb-42")
        orphan = make_patron(patron_id="some-other-id")
        assert find_orphan_patrons([person], [orphan]) == [orphan]
