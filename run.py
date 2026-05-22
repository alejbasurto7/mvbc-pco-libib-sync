"""Entry point for the live PCO ↔ Libib sync.

Invoked every 15 minutes by GitHub Actions. Reads the current state of PCO
and Libib, reconciles against pending changes, executes mature ones, and
writes back state.
"""
from __future__ import annotations

# Use the OS native trust store (Windows cert store, macOS keychain, Linux
# system OpenSSL) instead of just Python's bundled certifi. Required on
# corporate networks that do TLS interception with an in-house root CA.
import truststore
truststore.inject_into_ssl()

import argparse
import json
import sys
from dataclasses import asdict, replace
from datetime import datetime, timezone
from pathlib import Path

from lib.card import generate_card_png
from lib.config import load_config
from lib.decide import compute_desired_actions, filter_email_conflicts, find_orphan_patrons
from lib.execute import execute_action
from lib.libib_client import LibibClient
from lib.pco_client import PCOClient
from lib.reconcile import reconcile
from lib.sender import GmailSMTPSender
from lib.state import append_log, load_pending, save_pending


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _make_web_card_publisher(cfg):
    """Return a callable that writes per-patron card HTML + manifest and yields the URL.

    Returns None when either env var is unset — callers treat None as "skip".
    """
    if not cfg.card_base_url or not cfg.web_cards_output_dir:
        return None

    from lib.web_card import build_card_html, build_card_manifest, card_url

    output_dir = Path(cfg.web_cards_output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    base_url = cfg.card_base_url

    def publish(*, first_name, last_name, patron_id, token):
        html = build_card_html(
            first_name=first_name, last_name=last_name,
            patron_id=patron_id, token=token,
        )
        manifest = build_card_manifest(
            first_name=first_name, last_name=last_name, token=token,
        )
        (output_dir / f"{token}.html").write_text(html, encoding="utf-8")
        (output_dir / f"{token}.webmanifest").write_text(manifest, encoding="utf-8")
        return card_url(base_url=base_url, token=token)

    return publish


def main(*, state_dir: Path = Path("state"), dry_run: bool = False) -> int:
    cfg = load_config()
    now = _now()

    print(f"[{now.isoformat()}] starting sync (baseline_mode={cfg.baseline_mode}, dry_run={dry_run})")

    pco = PCOClient(app_id=cfg.pco_app_id, secret=cfg.pco_secret)
    libib = LibibClient(api_key=cfg.libib_api_key, api_user=cfg.libib_api_user)

    people = list(pco.list_all_people())
    patrons = list(libib.list_all_patrons())
    print(f"  fetched: {len(people)} PCO people, {len(patrons)} Libib patrons")

    desired_all = compute_desired_actions(
        people, patrons,
        protected_tags=frozenset(cfg.protected_tags),
    )
    desired, email_skipped = filter_email_conflicts(desired_all, patrons)
    for skip in email_skipped:
        append_log(state_dir, now, {"action": "SKIPPED", **skip})
    if email_skipped:
        print(f"  email_conflicts_skipped={len(email_skipped)} (logged)")
    pending = load_pending(state_dir)
    new_pending, mature = reconcile(
        desired, pending,
        now=now,
        stability_hours=cfg.stability_hours,
        baseline_mode=cfg.baseline_mode,
    )
    print(f"  desired={len(desired)}  pending_after={len(new_pending)}  mature={len(mature)}")

    orphans = find_orphan_patrons(people, patrons)
    for orphan in orphans:
        append_log(state_dir, now, {
            "action": "ORPHAN_DETECTED",
            "patron_id": orphan.patron_id,
            "email": orphan.email,
        })
    if orphans:
        print(f"  orphans={len(orphans)} (logged)")

    if dry_run:
        print("  --dry-run: skipping execution")
        # Breakdown of desired actions by type
        from collections import Counter
        by_type = Counter(a.action_type for a in desired)
        if by_type:
            print("  desired action breakdown:")
            for action_type in sorted(by_type):
                print(f"    {action_type}: {by_type[action_type]}")
            # Show up to 5 examples of each type with target detail
            actions_by_type: dict[str, list] = {}
            for a in desired:
                actions_by_type.setdefault(a.action_type, []).append(a)
            for action_type in sorted(actions_by_type):
                print(f"  {action_type} examples (first 5):")
                for a in actions_by_type[action_type][:5]:
                    print(f"    person_id={a.person_id}  target={a.target}")
        if mature:
            print(f"  would execute now ({len(mature)} mature):")
            for action in mature:
                print(f"    {action.action_type} for {action.person_id}: {action.target}")
        if email_skipped:
            print(f"  email_conflicts_skipped examples (first 10):")
            for skip in email_skipped[:10]:
                print(
                    f"    {skip['action_type']} for {skip['person_id']} "
                    f"intended={skip['intended_email']} "
                    f"conflicts_with=patron_id={skip['conflicts_with_patron_id']} ({skip['conflicts_with_name']})"
                )
        return 0

    sender = GmailSMTPSender(
        gmail_user=cfg.gmail_user,
        gmail_app_password=cfg.gmail_app_password,
        default_from=cfg.email_from,
        reply_to=cfg.email_reply_to,
    )
    card_generator = generate_card_png

    web_card_publisher = _make_web_card_publisher(cfg)
    if web_card_publisher is None:
        print("  web card publishing disabled (CARD_BASE_URL or WEB_CARDS_OUTPUT_DIR unset)")

    # Execute mature actions
    final_pending: list = []
    for row in new_pending:
        if row in mature:
            result = execute_action(
                row,
                libib=libib,
                sender=sender,
                card_generator=card_generator,
                web_card_publisher=web_card_publisher,
            )
            append_log(state_dir, now, {
                "person_id": row.person_id,
                "action": row.action_type,
                "success": result.success,
                "libib_status": result.libib_status,
                "libib_error": result.libib_error,
                "attempts": row.attempts + 1,
            })
            if result.success:
                # Drop from pending — done
                continue
            else:
                # Increment attempts; mark failed if attempts >= 3
                attempts = row.attempts + 1
                status = "failed" if attempts >= 3 else row.status
                final_pending.append(replace(
                    row, attempts=attempts, last_attempt_at=now, status=status,
                ))
        else:
            final_pending.append(row)

    save_pending(state_dir, final_pending, now=now)
    print(f"[{_now().isoformat()}] done")
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true",
                        help="Print plan without executing")
    parser.add_argument("--state-dir", default="state",
                        help="Path to state directory")
    args = parser.parse_args()
    sys.exit(main(state_dir=Path(args.state_dir), dry_run=args.dry_run))
