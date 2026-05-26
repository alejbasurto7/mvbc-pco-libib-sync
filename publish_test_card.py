"""One-shot publish of a single PWA library card for pre-launch smoke testing.

Bypasses reconcile and pending-state — looks up a PCO person directly,
renders the card HTML + webmanifest, and pushes them to ``gh-pages`` via
the GitHub Contents API. Use this to put up a real, installable card for
yourself or a test patron, walk through the iPhone/Android install + QR
flow, then run with ``--cleanup TOKEN`` to remove the test artifact.

Usage:
    # Dry-run: render to ./.test-card/, print the would-be URL, no push
    python publish_test_card.py --pco-id 123456
    python publish_test_card.py --email user@example.com

    # Actually publish to gh-pages
    python publish_test_card.py --pco-id 123456 --apply

    # Full e2e: publish AND send the production welcome email (with PNG attachment)
    python publish_test_card.py --email user@example.com --apply --send-email
    python publish_test_card.py --email user@example.com --apply --send-email \
        --send-email-to me@example.com   # override recipient

    # Remove a previously-published test card (always real, no dry-run)
    python publish_test_card.py --cleanup <token>

Reads PCO_APP_ID and PCO_SECRET from environment (via .env if present).
CARD_BASE_URL defaults to the value derived from the active GitHub remote;
override with ``--base-url`` if needed.
"""
from __future__ import annotations

import truststore
truststore.inject_into_ssl()

import argparse
import base64
import json
import os
import subprocess
import sys
from pathlib import Path

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

from lib.card import generate_card_png
from lib.libib_client import LibibClient
from lib.pco_client import PCOClient
from lib.sender import GmailSMTPSender, render_welcome_email
from lib.types import Person
from lib.web_card import (
    build_card_html,
    build_card_manifest,
    card_url,
    new_card_token,
)


def find_person(
    pco,
    *,
    pco_id: str | None = None,
    email: str | None = None,
) -> Person | None:
    """Locate a PCO person by id or primary email; return None if absent."""
    target_email = (email or "").strip().lower() or None
    for person in pco.list_all_people():
        if pco_id is not None and person.id == pco_id:
            return person
        if target_email is not None and (person.email or "").lower() == target_email:
            return person
    return None


def _gh_repo() -> str:
    out = subprocess.check_output(
        ["gh", "repo", "view", "--json", "nameWithOwner"], text=True,
    )
    return json.loads(out)["nameWithOwner"]


def _derive_base_url() -> str:
    owner, repo = _gh_repo().split("/", 1)
    return f"https://{owner}.github.io/{repo}/cards"


def _gh_contents_get_sha(repo: str, path: str, branch: str) -> str | None:
    r = subprocess.run(
        ["gh", "api", f"repos/{repo}/contents/{path}?ref={branch}"],
        capture_output=True, text=True,
    )
    if r.returncode != 0:
        return None
    return json.loads(r.stdout).get("sha")


def _gh_put_file(*, repo: str, path: str, content: bytes, message: str, branch: str = "gh-pages") -> None:
    sha = _gh_contents_get_sha(repo, path, branch)
    args = [
        "gh", "api", "--method", "PUT", f"repos/{repo}/contents/{path}",
        "-f", f"message={message}",
        "-f", f"content={base64.b64encode(content).decode()}",
        "-f", f"branch={branch}",
    ]
    if sha:
        args += ["-f", f"sha={sha}"]
    r = subprocess.run(args, capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(f"gh api PUT {path} failed: {r.stderr.strip()}")


def _gh_delete_file(*, repo: str, path: str, message: str, branch: str = "gh-pages") -> bool:
    sha = _gh_contents_get_sha(repo, path, branch)
    if not sha:
        return False
    r = subprocess.run(
        ["gh", "api", "--method", "DELETE", f"repos/{repo}/contents/{path}",
         "-f", f"message={message}",
         "-f", f"sha={sha}",
         "-f", f"branch={branch}"],
        capture_output=True, text=True,
    )
    if r.returncode != 0:
        raise RuntimeError(f"gh api DELETE {path} failed: {r.stderr.strip()}")
    return True


def cmd_publish(args: argparse.Namespace) -> int:
    if not args.pco_id and not args.email:
        print("error: one of --pco-id or --email is required", file=sys.stderr)
        return 2
    required = ("PCO_APP_ID", "PCO_SECRET", "LIBIB_API_KEY", "LIBIB_API_USER")
    missing = [k for k in required if not os.environ.get(k)]
    if missing:
        print(f"error: missing env vars: {', '.join(missing)} (see .env)", file=sys.stderr)
        return 2

    pco = PCOClient(app_id=os.environ["PCO_APP_ID"], secret=os.environ["PCO_SECRET"])
    person = find_person(pco, pco_id=args.pco_id, email=args.email)
    if person is None:
        needle = f"--pco-id {args.pco_id}" if args.pco_id else f"--email {args.email}"
        print(f"error: no PCO person matched {needle}", file=sys.stderr)
        return 1
    if not person.email:
        print(f"error: PCO person {person.id} has no email — can't look up Libib patron", file=sys.stderr)
        return 1

    libib = LibibClient(api_key=os.environ["LIBIB_API_KEY"], api_user=os.environ["LIBIB_API_USER"])
    patron = libib.get_patron(person.email)
    if patron is None:
        print(f"error: no Libib patron found for {person.email}", file=sys.stderr)
        return 1
    if not patron.barcode:
        print(f"error: Libib patron {patron.patron_id} has no barcode set", file=sys.stderr)
        return 1

    token = args.token or new_card_token()
    base_url = args.base_url or os.environ.get("CARD_BASE_URL") or _derive_base_url()

    html = build_card_html(
        first_name=person.first_name, last_name=person.last_name,
        barcode=patron.barcode, token=token,
    )
    manifest = build_card_manifest(
        first_name=person.first_name, last_name=person.last_name, token=token,
    )
    url = card_url(base_url=base_url, token=token)

    print(f"person : {person.first_name} {person.last_name} (pco_id={person.id})")
    print(f"barcode: {patron.barcode}")
    print(f"token  : {token}")
    print(f"url    : {url}")

    if not args.apply:
        out_dir = Path("./.test-card")
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / f"{token}.html").write_text(html, encoding="utf-8")
        (out_dir / f"{token}.webmanifest").write_text(manifest, encoding="utf-8")
        print(f"dry-run: wrote files to {out_dir}/ (not published)")
        print(f"re-run with --apply to push to gh-pages")
        return 0

    repo = _gh_repo()
    msg = f"test card for {person.first_name} {person.last_name} (token={token[:8]}…)"
    _gh_put_file(repo=repo, path=f"cards/{token}.html",        content=html.encode("utf-8"),     message=msg)
    _gh_put_file(repo=repo, path=f"cards/{token}.webmanifest", content=manifest.encode("utf-8"), message=msg)
    print("published to gh-pages (Pages may take ~30s to refresh)")
    print(f"  open in browser: {url}")
    print(f"  to remove later: python publish_test_card.py --cleanup {token}")

    if args.send_email:
        to_addr = args.send_email_to or person.email
        _send_welcome_email(person=person, patron_barcode=patron.barcode, card_url_=url, to_addr=to_addr)
        print(f"welcome email sent to {to_addr}")

    return 0


def _send_welcome_email(*, person: Person, patron_barcode: str, card_url_: str, to_addr: str) -> None:
    """Render and send the production welcome email — same code paths as CREATE_PATRON."""
    missing = [k for k in ("GMAIL_USER", "GMAIL_APP_PASSWORD") if not os.environ.get(k)]
    if missing:
        raise RuntimeError(f"--send-email requires env vars: {', '.join(missing)}")

    png_bytes = generate_card_png(
        first_name=person.first_name, last_name=person.last_name,
        email=person.email or "", barcode=patron_barcode,
    )
    html_body, text_body = render_welcome_email(
        first_name=person.first_name, email=person.email or to_addr,
        templates_dir=Path("templates"), card_url=card_url_,
    )
    sender = GmailSMTPSender(
        gmail_user=os.environ["GMAIL_USER"],
        gmail_app_password=os.environ["GMAIL_APP_PASSWORD"],
        default_from=os.environ.get("EMAIL_FROM") or os.environ["GMAIL_USER"],
        reply_to=os.environ.get("EMAIL_REPLY_TO") or None,
    )
    sender.send(
        to=to_addr,
        subject="Welcome to the MVBC Library",
        body_html=html_body, body_text=text_body,
        attachment_bytes=png_bytes,
        attachment_filename="library-card.png",
        attachment_content_type="image/png",
    )


def cmd_cleanup(args: argparse.Namespace) -> int:
    token = args.cleanup
    repo = _gh_repo()
    msg = f"cleanup test card token={token[:8]}…"
    h = _gh_delete_file(repo=repo, path=f"cards/{token}.html",        message=msg)
    m = _gh_delete_file(repo=repo, path=f"cards/{token}.webmanifest", message=msg)
    if not h and not m:
        print(f"no files found for token {token}")
        return 1
    print(f"deleted: html={h}, manifest={m}")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="Publish a single PWA library card for smoke testing.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument("--pco-id", help="PCO person id to look up")
    ap.add_argument("--email", help="primary email to look up the PCO person by")
    ap.add_argument("--token", help="reuse a specific UUID4 hex token (default: fresh)")
    ap.add_argument("--base-url", help="override CARD_BASE_URL (default: derived from origin)")
    ap.add_argument("--cleanup", metavar="TOKEN", help="delete a previously-published test card")
    ap.add_argument("--apply", action="store_true", help="actually push (default: dry-run)")
    ap.add_argument("--send-email", action="store_true",
                    help="also send the production welcome email (requires --apply)")
    ap.add_argument("--send-email-to", metavar="ADDRESS",
                    help="override the recipient address (default: the PCO person's primary email)")
    args = ap.parse_args(argv)

    if args.send_email and not args.apply:
        print("error: --send-email requires --apply (the email contains the live card URL)", file=sys.stderr)
        return 2
    if args.send_email_to and not args.send_email:
        print("error: --send-email-to only makes sense with --send-email", file=sys.stderr)
        return 2

    if args.cleanup:
        return cmd_cleanup(args)
    return cmd_publish(args)


if __name__ == "__main__":
    raise SystemExit(main())
