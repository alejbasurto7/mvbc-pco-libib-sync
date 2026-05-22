from datetime import datetime, timedelta, timezone

from lib.reconcile import reconcile
from lib.types import Action, PendingChange


def now() -> datetime:
    return datetime(2026, 5, 6, 12, 0, tzinfo=timezone.utc)


def make_action(action_type="CREATE_PATRON", person_id="pco-1", target=None) -> Action:
    return Action(person_id=person_id, action_type=action_type, target=target or {"email": "x@y"})


def make_pending(action_type="CREATE_PATRON", person_id="pco-1", detected_offset_hours=0,
                 target=None, attempts=0, status="pending") -> PendingChange:
    return PendingChange(
        person_id=person_id,
        action_type=action_type,
        target=target or {"email": "x@y"},
        detected_at=now() - timedelta(hours=detected_offset_hours),
        attempts=attempts,
        last_attempt_at=None,
        status=status,
    )


class TestReconcile:
    def test_brand_new_action_added_with_current_timestamp(self):
        action = make_action()
        new_pending, mature = reconcile([action], [], now=now(), stability_hours=24.0)
        assert len(new_pending) == 1
        assert new_pending[0].person_id == "pco-1"
        assert new_pending[0].detected_at == now()
        assert new_pending[0].status == "pending"
        assert mature == []

    def test_existing_pending_action_target_unchanged_keeps_detected_at(self):
        existing = make_pending(detected_offset_hours=10)  # detected 10h ago
        action = make_action()  # same target as existing
        new_pending, mature = reconcile([action], [existing], now=now(), stability_hours=24.0)
        assert new_pending[0].detected_at == existing.detected_at
        assert mature == []

    def test_existing_pending_action_target_changed_resets_detected_at(self):
        existing = make_pending(target={"email": "old@x"}, detected_offset_hours=10)
        action = make_action(target={"email": "new@x"})
        new_pending, mature = reconcile([action], [existing], now=now(), stability_hours=24.0)
        assert new_pending[0].detected_at == now()
        assert new_pending[0].target == {"email": "new@x"}

    def test_pending_action_no_longer_desired_is_removed(self):
        existing = make_pending(detected_offset_hours=5)
        new_pending, mature = reconcile([], [existing], now=now(), stability_hours=24.0)
        assert new_pending == []
        assert mature == []

    def test_mature_action_returned_for_execution(self):
        existing = make_pending(detected_offset_hours=25)  # past stability gate
        action = make_action()  # still desired
        new_pending, mature = reconcile([action], [existing], now=now(), stability_hours=24.0)
        assert len(mature) == 1
        assert mature[0].person_id == "pco-1"
        # Still in pending until execute() succeeds and removes it
        assert len(new_pending) == 1

    def test_immature_action_not_returned(self):
        existing = make_pending(detected_offset_hours=23)  # not yet mature
        action = make_action()
        new_pending, mature = reconcile([action], [existing], now=now(), stability_hours=24.0)
        assert mature == []
        assert len(new_pending) == 1

    def test_failed_status_does_not_re_mature(self):
        existing = make_pending(detected_offset_hours=99, attempts=3, status="failed")
        action = make_action()
        new_pending, mature = reconcile([action], [existing], now=now(), stability_hours=24.0)
        assert mature == []
        # But the row stays pending — preserved for manual reset
        assert len(new_pending) == 1
        assert new_pending[0].status == "failed"

    def test_baseline_status_does_not_mature(self):
        existing = make_pending(detected_offset_hours=99, status="baseline")
        action = make_action()
        new_pending, mature = reconcile([action], [existing], now=now(), stability_hours=24.0)
        assert mature == []

    def test_baseline_mode_writes_baseline_status(self):
        action = make_action()
        new_pending, mature = reconcile([action], [], now=now(), stability_hours=24.0, baseline_mode=True)
        assert new_pending[0].status == "baseline"
        assert mature == []

    def test_new_create_patron_gets_card_token(self):
        action = make_action(action_type="CREATE_PATRON")
        new_pending, _ = reconcile([action], [], now=now(), stability_hours=24.0)
        token = new_pending[0].card_token
        assert token is not None
        assert len(token) == 32
        # Must not leak the patron_id into the URL slug
        assert token != action.target.get("patron_id")

    def test_freeze_patron_does_not_get_card_token(self):
        action = make_action(action_type="FREEZE_PATRON")
        new_pending, _ = reconcile([action], [], now=now(), stability_hours=24.0)
        assert new_pending[0].card_token is None

    def test_existing_token_preserved_when_target_unchanged(self):
        existing = make_pending(detected_offset_hours=10)
        # Hand-set a token to simulate one that was minted on a prior run
        existing = PendingChange(
            person_id=existing.person_id,
            action_type=existing.action_type,
            target=existing.target,
            detected_at=existing.detected_at,
            attempts=existing.attempts,
            last_attempt_at=existing.last_attempt_at,
            status=existing.status,
            card_token="aa" * 16,
        )
        action = make_action()  # same target
        new_pending, _ = reconcile([action], [existing], now=now(), stability_hours=24.0)
        assert new_pending[0].card_token == "aa" * 16

    def test_existing_token_preserved_when_target_shifts(self):
        existing = PendingChange(
            person_id="pco-1",
            action_type="CREATE_PATRON",
            target={"email": "old@x"},
            detected_at=now() - timedelta(hours=10),
            attempts=0,
            last_attempt_at=None,
            status="pending",
            card_token="bb" * 16,
        )
        action = make_action(target={"email": "new@x"})  # same key, different target
        new_pending, _ = reconcile([action], [existing], now=now(), stability_hours=24.0)
        # detected_at resets but token sticks with the patron
        assert new_pending[0].detected_at == now()
        assert new_pending[0].card_token == "bb" * 16
