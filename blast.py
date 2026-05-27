"""One-shot blast email pipeline: dry-run (CSV to manifest) and real-send (--apply).

Two modes:

  Dry-run (default starting point):
    python blast.py Patrons-Status-20260526.csv --dry-run

  Reads a Patrons-Status-YYYYMMDD.csv export from Libib, hydrates real
  barcodes via the Libib API, partitions patrons into segments, mints
  per-recipient card tokens, and writes:

      state/blast_<DATE>/blast_state.json
      state/blast_<DATE>/preview-regulars.html
      state/blast_<DATE>/preview-regulars-vip.html       (if any VIP)
      state/blast_<DATE>/preview-reminder.html

  No emails are sent.

  Real send:
    python blast.py --apply state/blast_20260527/blast_state.json --confirm 20260527

  Reads the manifest (NOT the CSV), iterates recipients with
  status in {pending, failed}, renders + sends, updates each row's
  status in place, and persists after every attempt. --confirm must
  match the manifest's date suffix (the baseline guard against a
  stray --apply hitting yesterday's manifest).
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

from lib import card_tokens
from lib.blast import (
    Recipient,
    Skipped,
    load_status_csv,
    partition,
)
from lib.card import select_png_generator
from lib.libib_client import LibibClient
from lib.pco_client import PCOClient
from lib.sender import (
    GmailSMTPSender,
    render_regulars_email,
    render_reminder_email,
)


SCHEMA_VERSION = 1

# Subject lines per segment — confirmed 2026-05-27, see
# [[project-blast-email-segmentation]].
SUBJECTS: dict[str, str] = {
    "regulars":     "Your new MVBC Library card",
    "regulars_vip": "Your VIP-edition MVBC Library card — now digital too",
    "reminder":     "An invitation to start using the MVBC Library",
}


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _build_state(
    *,
    recipients: list[Recipient],
    skipped: list[Skipped],
    base_url: str,
    source_csv: Path,
    generated_at: datetime,
    tokens: dict[str, str],
) -> dict:
    """Build the blast_state.json payload. Mutates ``tokens`` in place for any
    barcode that doesn't yet have a long-lived token (it'll be minted)."""
    seg_counts = Counter(r.segment for r in recipients)
    skip_counts = Counter(s.reason for s in skipped)
    recipients_map: dict[str, dict] = {}
    for r in recipients:
        token = card_tokens.get_or_mint(tokens, r.barcode)
        recipients_map[r.barcode] = {
            "patron_id": r.patron_id,
            "first_name": r.first_name,
            "last_name": r.last_name,
            "email": r.email,
            "barcode": r.barcode,
            "csv_status": r.csv_status,
            "segment": r.segment,
            "card_token": token,
            "card_url": f"{base_url.rstrip('/')}/{token}.html",
            "status": "pending",
            "attempts": 0,
            "last_attempt_at": None,
            "last_error": None,
        }
    return {
        "version": SCHEMA_VERSION,
        "generated_at": generated_at.isoformat(),
        "source_csv": str(source_csv),
        "base_url": base_url.rstrip("/"),
        "summary": {
            "segments": dict(seg_counts),
            "skipped": dict(skip_counts),
            "total_recipients": len(recipients),
            "total_skipped": len(skipped),
        },
        "recipients": recipients_map,
        "skipped": [
            {
                "patron_id": s.patron_id,
                "first_name": s.first_name,
                "last_name": s.last_name,
                "email": s.email,
                "csv_status": s.csv_status,
                "reason": s.reason,
            }
            for s in skipped
        ],
    }


def _render_previews(
    *,
    state: dict,
    templates_dir: Path,
    output_dir: Path,
) -> list[Path]:
    """Render one preview HTML per segment using the first recipient as the sample.

    Returns the list of written file paths.
    """
    by_segment: dict[str, dict] = {}
    for rec in state["recipients"].values():
        by_segment.setdefault(rec["segment"], rec)  # first one wins
    written: list[Path] = []
    for segment, sample in by_segment.items():
        if segment == "regulars" or segment == "regulars_vip":
            html, _ = render_regulars_email(
                first_name=sample["first_name"],
                email=sample["email"],
                barcode=sample["barcode"],
                templates_dir=templates_dir,
                card_url=sample["card_url"],
            )
        else:  # reminder
            html, _ = render_reminder_email(
                first_name=sample["first_name"],
                email=sample["email"],
                templates_dir=templates_dir,
                card_url=sample["card_url"],
            )
        filename = f"preview-{segment.replace('_', '-')}.html"
        path = output_dir / filename
        path.write_text(html, encoding="utf-8")
        written.append(path)
    return written


def _print_summary(state: dict, recipients: list[Recipient], skipped: list[Skipped]) -> None:
    summary = state["summary"]
    print()
    print(f"  Total recipients: {summary['total_recipients']}")
    print(f"  Total skipped:    {summary['total_skipped']}")
    print()
    print("  By segment:")
    for seg, n in sorted(summary["segments"].items()):
        sample_names = [
            f"{r.first_name} {r.last_name}" for r in recipients if r.segment == seg
        ][:3]
        sample = ", ".join(sample_names)
        more = f" (+{n - len(sample_names)} more)" if n > len(sample_names) else ""
        print(f"    {seg:14s} {n:4d}   e.g. {sample}{more}")
    if summary["skipped"]:
        print()
        print("  Skipped (will not be emailed):")
        for reason, n in sorted(summary["skipped"].items()):
            sample = ", ".join(
                f"{s.first_name} {s.last_name}" for s in skipped if s.reason == reason
            )
            sample_short = sample if len(sample) < 80 else sample[:77] + "..."
            print(f"    {reason:14s} {n:4d}   {sample_short}")


def _render_email_for(rec: dict, *, templates_dir: Path) -> tuple[str, str, str]:
    """Pick subject + render (html, text) for one recipient.

    Dispatch by segment. Regulars dispatches its VIP variant internally
    via barcode → ``is_vip_patron``; reminder has no VIP today.
    """
    segment = rec["segment"]
    subject = SUBJECTS[segment]
    if segment in ("regulars", "regulars_vip"):
        html, text = render_regulars_email(
            first_name=rec["first_name"],
            email=rec["email"],
            barcode=rec["barcode"],
            templates_dir=templates_dir,
            card_url=rec["card_url"],
        )
    else:  # reminder
        html, text = render_reminder_email(
            first_name=rec["first_name"],
            email=rec["email"],
            templates_dir=templates_dir,
            card_url=rec["card_url"],
        )
    return subject, html, text


def _manifest_date_suffix(state_path: Path) -> str | None:
    """Return the YYYYMMDD suffix from a ``blast_<YYYYMMDD>/blast_state.json``
    path, or None if the parent doesn't follow the convention.

    The convention is set by dry-run output; the apply step uses this to
    validate ``--confirm`` against the manifest's intended date.
    """
    parent = state_path.parent.name
    if not parent.startswith("blast_"):
        return None
    suffix = parent.removeprefix("blast_")
    return suffix if suffix.isdigit() and len(suffix) == 8 else None


def cmd_apply(args: argparse.Namespace) -> int:
    state_path: Path = args.apply
    if not state_path.exists():
        print(f"error: state file not found: {state_path}", file=sys.stderr)
        return 2

    state = json.loads(state_path.read_text(encoding="utf-8"))

    manifest_date = _manifest_date_suffix(state_path)
    if manifest_date is None:
        print(
            f"error: state file not in a blast_<YYYYMMDD>/ directory: {state_path}",
            file=sys.stderr,
        )
        return 2
    if args.confirm != manifest_date:
        print(
            f"error: --confirm {args.confirm} does not match manifest date {manifest_date}",
            file=sys.stderr,
        )
        return 2

    gmail_user = os.environ.get("GMAIL_USER")
    gmail_password = os.environ.get("GMAIL_APP_PASSWORD")
    if not gmail_user or not gmail_password:
        print(
            "error: GMAIL_USER and GMAIL_APP_PASSWORD must be set in the environment",
            file=sys.stderr,
        )
        return 2

    sender = args._sender_factory(
        gmail_user=gmail_user,
        gmail_app_password=gmail_password,
        default_from=os.environ.get("EMAIL_FROM") or gmail_user,
        reply_to=os.environ.get("EMAIL_REPLY_TO") or None,
    )

    candidates = [
        (barcode, rec)
        for barcode, rec in state["recipients"].items()
        if rec["status"] in {"pending", "failed"}
    ]
    if args.only_email:
        target = args.only_email.strip().lower()
        candidates = [
            (b, r) for b, r in candidates
            if (r.get("email") or "").strip().lower() == target
        ]
        if not candidates:
            print(
                f"error: --only-email {args.only_email!r} matched no pending/failed recipient",
                file=sys.stderr,
            )
            return 2
    if args.limit is not None:
        candidates = candidates[: args.limit]

    print(f"manifest: {state_path}")
    print(f"to send : {len(candidates)} (pending+failed); pace={args.pace}s")
    print()

    sent = 0
    failed = 0
    for i, (barcode, rec) in enumerate(candidates, start=1):
        name = f"{rec['first_name']} {rec['last_name']}"
        rec["attempts"] = rec.get("attempts", 0) + 1
        rec["last_attempt_at"] = _now().isoformat()
        try:
            subject, html, text = _render_email_for(rec, templates_dir=args.templates_dir)
            png_fn = select_png_generator(barcode=rec["barcode"])
            png = png_fn(
                first_name=rec["first_name"],
                last_name=rec["last_name"],
                email=rec["email"],
                barcode=rec["barcode"],
            )
            sender.send(
                to=rec["email"],
                subject=subject,
                body_html=html,
                body_text=text,
                attachment_bytes=png,
                attachment_filename="library-card.png",
                attachment_content_type="image/png",
            )
            rec["status"] = "sent"
            rec["last_error"] = None
            sent += 1
            print(f"  [{i:3d}/{len(candidates)}] sent {name} <{rec['email']}>")
        except Exception as exc:  # one bad send shouldn't halt the batch
            rec["status"] = "failed"
            rec["last_error"] = str(exc)
            failed += 1
            print(f"  [{i:3d}/{len(candidates)}] FAIL {name}: {exc}")

        # Persist after every attempt — a crash mid-loop preserves what's
        # already been sent so a resume only retries the remainder.
        state_path.write_text(json.dumps(state, indent=2), encoding="utf-8")

        if i < len(candidates) and args.pace > 0:
            time.sleep(args.pace)

    print()
    print(f"sent:   {sent}")
    print(f"failed: {failed}")
    if failed:
        print("  re-run --apply with the same args to retry failed rows (sent rows are skipped).")
    return 0 if not failed else 1


def cmd_dry_run(args: argparse.Namespace) -> int:
    if not args.base_url:
        print("error: --base-url is required (or set $CARD_BASE_URL)", file=sys.stderr)
        return 2
    if args.csv_path is None or not args.csv_path.exists():
        print(f"error: CSV not found: {args.csv_path}", file=sys.stderr)
        return 2

    libib_key = os.environ.get("LIBIB_API_KEY")
    libib_user = os.environ.get("LIBIB_API_USER")
    if not libib_key or not libib_user:
        print(
            "error: LIBIB_API_KEY and LIBIB_API_USER must be set in the environment",
            file=sys.stderr,
        )
        return 2

    pco_app_id = os.environ.get("PCO_APP_ID")
    pco_secret = os.environ.get("PCO_SECRET")
    if not args.skip_pco_filter and (not pco_app_id or not pco_secret):
        print(
            "error: PCO_APP_ID and PCO_SECRET must be set to enforce the "
            "non-Active Member Status filter (or pass --skip-pco-filter to "
            "bypass — only safe for offline dry-runs)",
            file=sys.stderr,
        )
        return 2

    now = _now()
    date_suffix = args.date or now.strftime("%Y%m%d")
    output_dir = args.state_dir / f"blast_{date_suffix}"

    print(f"[{now.isoformat()}] blast (dry-run) — date={date_suffix}")
    print(f"  csv:      {args.csv_path}")
    print(f"  base_url: {args.base_url}")
    print(f"  output:   {output_dir}/")

    csv_rows = load_status_csv(args.csv_path)
    print(f"  loaded {len(csv_rows)} rows from CSV")

    libib = LibibClient(api_key=libib_key, api_user=libib_user)
    print("  fetching patrons from Libib...")
    patrons = list(libib.list_all_patrons())
    patrons_by_patron_id = {p.patron_id: p for p in patrons}
    print(f"  fetched {len(patrons)} Libib patrons")

    if args.skip_pco_filter:
        print("  WARNING: --skip-pco-filter set; non-Active PCO members will NOT be skipped")
        non_active_pco_patron_ids: set[str] = set()
    else:
        print("  fetching PCO Member Status (non-Active patrons will be skipped)...")
        pco = PCOClient(app_id=pco_app_id, secret=pco_secret)
        non_active_pco_patron_ids = pco.fetch_non_active_patron_ids()
        print(f"  PCO non-Active patron_ids: {len(non_active_pco_patron_ids)}")

    recipients, skipped = partition(
        csv_rows,
        patrons_by_patron_id,
        non_active_pco_patron_ids=non_active_pco_patron_ids,
    )

    # Load the long-lived barcode→token map. Any barcode already in here
    # reuses its token (so a previously-published card URL stays stable
    # for that patron forever); new barcodes get a fresh mint that's then
    # written back to the file so the next caller sees it too.
    tokens = card_tokens.load(args.state_dir)
    tokens_before = dict(tokens)

    state = _build_state(
        recipients=recipients,
        skipped=skipped,
        base_url=args.base_url,
        source_csv=args.csv_path,
        generated_at=now,
        tokens=tokens,
    )

    output_dir.mkdir(parents=True, exist_ok=True)
    state_path = output_dir / "blast_state.json"
    state_path.write_text(json.dumps(state, indent=2), encoding="utf-8")

    if tokens != tokens_before:
        card_tokens.save(args.state_dir, tokens, now=now)
        minted = len(tokens) - len(tokens_before)
        print(f"  minted {minted} new card token(s); persisted to {args.state_dir}/card_tokens.json")
    else:
        print(f"  all {len(recipients)} recipient(s) already had tokens; card_tokens.json unchanged")

    preview_paths = _render_previews(
        state=state, templates_dir=args.templates_dir, output_dir=output_dir,
    )

    _print_summary(state, recipients, skipped)
    print()
    print(f"  wrote {state_path}")
    for p in preview_paths:
        print(f"  wrote {p}")
    print()
    print("  Review the state JSON and previews. Hand-edit the JSON to remove anyone")
    print("  you don't want emailed. Run --apply with --confirm <YYYYMMDD> to send.")
    return 0


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument(
        "--dry-run", action="store_true",
        help="Read a Patrons-Status CSV and generate blast_state.json + previews. No emails sent.",
    )
    mode.add_argument(
        "--apply", metavar="STATE_JSON", type=Path, default=None,
        help="Real-send mode: read a blast_state.json and email each pending/failed recipient.",
    )
    parser.add_argument(
        "csv_path", nargs="?", type=Path, default=None,
        help="Patrons-Status-YYYYMMDD.csv from Libib (required for --dry-run; ignored for --apply)",
    )
    parser.add_argument(
        "--confirm", metavar="YYYYMMDD",
        help="Required with --apply: must match the manifest's date suffix (baseline guard).",
    )
    parser.add_argument(
        "--state-dir", type=Path, default=Path("state"),
        help="Where to write blast_<DATE>/ during --dry-run (default: state/)",
    )
    parser.add_argument(
        "--templates-dir", type=Path, default=Path("templates"),
        help="Email template directory (default: templates/)",
    )
    parser.add_argument(
        "--base-url",
        default=os.environ.get("CARD_BASE_URL"),
        help="Base URL for hosted card pages (default: $CARD_BASE_URL)",
    )
    parser.add_argument(
        "--date",
        default=None,
        help="Override the YYYYMMDD suffix for the --dry-run output directory (default: today, UTC)",
    )
    parser.add_argument(
        "--pace", type=float, default=1.5,
        help="--apply: seconds to sleep between sends (default: 1.5; Gmail-friendly)",
    )
    parser.add_argument(
        "--limit", type=int, default=None,
        help="--apply: stop after N recipients (for staged rollouts).",
    )
    parser.add_argument(
        "--only-email", metavar="ADDRESS", default=None,
        help="--apply: send only to the recipient whose email matches "
             "(case-insensitive). Combine with --limit 1 for self-test sends.",
    )
    parser.add_argument(
        "--skip-pco-filter", action="store_true",
        help="--dry-run: skip the PCO Member Status check (default: enforced). "
             "Only use when PCO is unreachable for an offline dry-run.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    # Sender factory injection point — overridden in tests to avoid live SMTP.
    args._sender_factory = GmailSMTPSender

    if args.apply is not None:
        if not args.confirm:
            print("error: --apply requires --confirm <YYYYMMDD>", file=sys.stderr)
            return 2
        return cmd_apply(args)
    return cmd_dry_run(args)


if __name__ == "__main__":
    sys.exit(main())
