"""Publish every recipient's PWA card from a blast_state.json manifest.

Bulk variant of publish_blast_samples.py — instead of one sample per segment,
this walks every recipient and pushes their card (HTML + webmanifest) to
gh-pages via the GitHub Contents API.

Defaults are conservative:
  * dry-run by default — nothing is pushed without ``--apply``
  * already-published tokens are skipped (idempotent re-runs are free); pass
    ``--force`` to re-publish and overwrite
  * a ``--limit N`` knob is available for staged rollouts ("publish 10 first
    and eyeball them before doing the rest")

Usage:
    # Dry-run: render to ./.blast-cards/, no push
    python publish_blast_cards.py state/blast_20260527/blast_state.json

    # Real publish (skips already-published tokens)
    python publish_blast_cards.py state/blast_20260527/blast_state.json --apply

    # Force re-publish everything (note: every file becomes a new commit, so
    # you'll get 410 commits on gh-pages — only do this when you actually
    # want a template refresh)
    python publish_blast_cards.py state/blast_20260527/blast_state.json --apply --force

    # Staged: publish just the first 10
    python publish_blast_cards.py state/blast_20260527/blast_state.json --apply --limit 10
"""
from __future__ import annotations

import truststore
truststore.inject_into_ssl()

import argparse
import json
import sys
from pathlib import Path

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

from publish_test_card import _gh_contents_get_sha, _gh_put_file, _gh_repo
from lib.web_card import select_card_builders


def _render(rec: dict) -> tuple[bytes, bytes]:
    html_fn, manifest_fn = select_card_builders(barcode=rec["barcode"])
    html = html_fn(
        first_name=rec["first_name"], last_name=rec["last_name"],
        barcode=rec["barcode"], token=rec["card_token"],
    )
    manifest = manifest_fn(
        first_name=rec["first_name"], last_name=rec["last_name"],
        token=rec["card_token"],
    )
    return html.encode("utf-8"), manifest.encode("utf-8")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="Publish every card from a blast_state.json manifest.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument("state_path", type=Path, help="path to blast_state.json")
    ap.add_argument("--apply", action="store_true",
                    help="actually push to gh-pages (default: dry-run, writes to ./.blast-cards/)")
    ap.add_argument("--force", action="store_true",
                    help="re-publish even if the token already exists on gh-pages")
    ap.add_argument("--limit", type=int, default=None,
                    help="stop after publishing N recipients (for staged rollouts)")
    ap.add_argument("--branch", default="gh-pages",
                    help="target branch (default: gh-pages)")
    args = ap.parse_args(argv)

    if not args.state_path.exists():
        print(f"error: state file not found: {args.state_path}", file=sys.stderr)
        return 2

    state = json.loads(args.state_path.read_text(encoding="utf-8"))
    recipients = list(state["recipients"].values())
    recipients.sort(key=lambda r: r["barcode"])  # stable ordering across runs
    if args.limit is not None:
        recipients = recipients[: args.limit]

    print(f"manifest:   {args.state_path}")
    print(f"recipients: {len(recipients)} (limit={args.limit or 'none'})")
    print(f"mode:       {'APPLY' if args.apply else 'dry-run'}"
          f"{' --force' if args.force else ''}")

    if not args.apply:
        out_dir = Path("./.blast-cards")
        out_dir.mkdir(parents=True, exist_ok=True)
        for rec in recipients:
            html, manifest = _render(rec)
            (out_dir / f"{rec['card_token']}.html").write_bytes(html)
            (out_dir / f"{rec['card_token']}.webmanifest").write_bytes(manifest)
        print(f"dry-run: wrote {len(recipients) * 2} files to {out_dir}/")
        print(f"re-run with --apply to push to gh-pages")
        return 0

    repo = _gh_repo()
    print(f"repo:       {repo}")
    print()

    published = 0
    skipped = 0
    failures: list[tuple[str, str]] = []  # (token, error)

    for i, rec in enumerate(recipients, start=1):
        token = rec["card_token"]
        name = f"{rec['first_name']} {rec['last_name']}"
        html_path = f"cards/{token}.html"
        manifest_path = f"cards/{token}.webmanifest"

        if not args.force:
            # Skip only when BOTH files are present. A token that has the
            # HTML but not the webmanifest (e.g. a TCP timeout dropped the
            # second PUT mid-run) needs to finish publishing on retry, not
            # be skipped over.
            html_sha = _gh_contents_get_sha(repo, html_path, args.branch)
            manifest_sha = (
                _gh_contents_get_sha(repo, manifest_path, args.branch)
                if html_sha is not None
                else None
            )
            if html_sha is not None and manifest_sha is not None:
                print(f"  [{i:3d}/{len(recipients)}] skip {name} (already published)")
                skipped += 1
                continue

        try:
            html, manifest = _render(rec)
            msg = f"publish card: {name} (token={token[:8]}…)"
            _gh_put_file(repo=repo, path=html_path, content=html, message=msg, branch=args.branch)
            _gh_put_file(repo=repo, path=manifest_path, content=manifest, message=msg, branch=args.branch)
            print(f"  [{i:3d}/{len(recipients)}] publish {name}")
            published += 1
        except Exception as exc:  # surface and continue — one bad card shouldn't stop the run
            print(f"  [{i:3d}/{len(recipients)}] FAIL {name}: {exc}")
            failures.append((token, str(exc)))

    print()
    print(f"published: {published}")
    print(f"skipped:   {skipped} (already on gh-pages; pass --force to re-publish)")
    print(f"failures:  {len(failures)}")
    for token, err in failures:
        print(f"  {token[:8]}…  {err}")
    print()
    print("Pages may take ~30s to refresh.")
    return 0 if not failures else 1


if __name__ == "__main__":
    sys.exit(main())
