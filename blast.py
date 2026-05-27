"""One-shot blast email send path (dry-run only in this slice).

Reads a Patrons-Status-YYYYMMDD.csv export from Libib, hydrates real
barcodes via the Libib API, partitions patrons into segments, mints
per-recipient card tokens, and writes:

    state/blast_<DATE>/blast_state.json
    state/blast_<DATE>/preview-regulars.html
    state/blast_<DATE>/preview-regulars-vip.html       (if any VIP)
    state/blast_<DATE>/preview-reminder.html

No emails are sent. The state JSON is the manifest you review (and
may hand-edit) before the eventual real-send step uses it as input.

Usage:
    python blast.py Patrons-Status-20260526.csv --dry-run
    python blast.py Patrons-Status-20260526.csv --dry-run \\
        --base-url https://alejbasurto7.github.io/mvbc-pco-libib-sync/cards
"""
from __future__ import annotations

import argparse
import json
import os
import sys
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
from lib.libib_client import LibibClient
from lib.sender import (
    render_regulars_email,
    render_reminder_email,
)


SCHEMA_VERSION = 1


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


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("csv_path", type=Path, help="Patrons-Status-YYYYMMDD.csv from Libib")
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Generate blast_state.json + previews. No emails sent. Required in this slice.",
    )
    parser.add_argument(
        "--state-dir", type=Path, default=Path("state"),
        help="Where to write blast_<DATE>/ (default: state/)",
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
        help="Override the YYYYMMDD suffix for the output directory (default: today, UTC)",
    )
    args = parser.parse_args()

    if not args.dry_run:
        print("error: --dry-run is required (real-send mode not built yet)", file=sys.stderr)
        return 2
    if not args.base_url:
        print("error: --base-url is required (or set $CARD_BASE_URL)", file=sys.stderr)
        return 2
    if not args.csv_path.exists():
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

    recipients, skipped = partition(csv_rows, patrons_by_patron_id)

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
    print("  you don't want emailed. The real-send step (not built yet) will read this")
    print("  file as input and send only to rows with status='pending' or 'failed'.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
