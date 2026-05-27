"""Remove published PWA cards (HTML + webmanifest) from gh-pages for the
non-Active PCO members listed in reports/non_active_library_patrons.csv.

Two-stage by design:

  * Default (no --apply): inventories what *would* be deleted. Reports how
    many of the 109 blocked patrons actually have cards on gh-pages right
    now, prints sample paths, and does NOT touch the filesystem or push.

  * --apply: deletes the files in the gh-pages worktree, then creates ONE
    commit on the gh-pages branch and pushes. Single commit (not one per
    file) keeps the gh-pages history readable.

Note on installed PWAs: the service worker is cache-first with no
revalidation, so any patron who already installed the card on their
device will keep seeing the cached copy until the sw.js CACHE constant
is bumped. This script only removes the network copy; cached installs
keep working. See memory: project-pwa-card-updates.
"""
from __future__ import annotations
import argparse
import csv
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
GHPAGES_WORKTREE = Path("C:/Users/T0226129/Claude/Projects/mvbc-gh-pages-tmp")
CARDS_DIR_REL = "cards"
BLOCKLIST_CSV = ROOT / "reports" / "non_active_library_patrons.csv"
TOKENS_JSON = ROOT / "state" / "card_tokens.json"


def load_block_list() -> set[str]:
    return {
        row["patron_id"]
        for row in csv.DictReader(BLOCKLIST_CSV.open(encoding="utf-8"))
    }


def load_token_map() -> dict[str, str]:
    data = json.loads(TOKENS_JSON.read_text(encoding="utf-8"))
    return dict(data["tokens"])


def resolve_barcodes(patron_ids: set[str]) -> tuple[dict[str, str], list[str]]:
    """Map patron_id -> barcode by hitting the Libib API. Returns (mapping, unmatched)."""
    try:
        from dotenv import load_dotenv
        load_dotenv(ROOT / ".env")
    except ImportError:
        pass

    from lib.libib_client import LibibClient

    libib = LibibClient(
        api_key=os.environ["LIBIB_API_KEY"],
        api_user=os.environ["LIBIB_API_USER"],
    )
    patrons = list(libib.list_all_patrons())
    by_pid = {p.patron_id: p.barcode for p in patrons if p.barcode}
    mapping: dict[str, str] = {}
    unmatched: list[str] = []
    for pid in patron_ids:
        bc = by_pid.get(pid)
        if bc:
            mapping[pid] = bc
        else:
            unmatched.append(pid)
    return mapping, unmatched


def run_git(args: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", "-C", str(GHPAGES_WORKTREE), *args],
        capture_output=True, text=True, check=False,
    )


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--apply", action="store_true",
                    help="Actually delete files and push a commit. Default: dry-run.")
    args = ap.parse_args(argv)

    if not GHPAGES_WORKTREE.exists():
        print(f"error: gh-pages worktree not found at {GHPAGES_WORKTREE}", file=sys.stderr)
        return 2
    if not (GHPAGES_WORKTREE / CARDS_DIR_REL).is_dir():
        print(f"error: {CARDS_DIR_REL}/ not present in worktree", file=sys.stderr)
        return 2

    patron_ids = load_block_list()
    print(f"block-list:                 {len(patron_ids)} patron_ids")

    print("resolving barcodes via Libib API...")
    pid_to_barcode, unmatched = resolve_barcodes(patron_ids)
    print(f"  matched to barcode:       {len(pid_to_barcode)}")
    print(f"  unmatched in Libib:       {len(unmatched)}")
    if unmatched:
        print(f"  (sample unmatched: {unmatched[:5]})")

    tokens = load_token_map()
    print(f"card_tokens.json entries:   {len(tokens)}")

    cards_dir = GHPAGES_WORKTREE / CARDS_DIR_REL

    to_delete: list[tuple[str, str, str]] = []   # (pid, barcode, token) for files that exist
    no_token: list[tuple[str, str]] = []
    not_on_pages: list[tuple[str, str, str]] = []
    html_count = 0
    manifest_count = 0

    for pid, bc in pid_to_barcode.items():
        tok = tokens.get(bc)
        if not tok:
            no_token.append((pid, bc))
            continue
        html_p = cards_dir / f"{tok}.html"
        mf_p = cards_dir / f"{tok}.webmanifest"
        if html_p.exists() or mf_p.exists():
            to_delete.append((pid, bc, tok))
            html_count += int(html_p.exists())
            manifest_count += int(mf_p.exists())
        else:
            not_on_pages.append((pid, bc, tok))

    print()
    print(f"cards present on gh-pages:  {len(to_delete)} patrons")
    print(f"  .html files to remove:    {html_count}")
    print(f"  .webmanifest to remove:   {manifest_count}")
    print(f"never published (no token): {len(no_token)}")
    print(f"token exists but no file:   {len(not_on_pages)}")

    if not to_delete:
        print("\nnothing to delete.")
        return 0

    sample = to_delete[:5]
    print("\nsample of files that would be removed:")
    for pid, bc, tok in sample:
        print(f"  patron_id={pid:<10} barcode={bc:<13} cards/{tok}.html + .webmanifest")

    if not args.apply:
        print("\n(dry-run) re-run with --apply to delete + commit + push.")
        return 0

    # --apply: ensure worktree is clean and up-to-date, then delete, commit, push.
    print("\n--- applying ---")
    st = run_git(["status", "--porcelain"])
    if st.stdout.strip():
        print(f"error: gh-pages worktree is not clean:\n{st.stdout}", file=sys.stderr)
        return 3

    print("fetching origin...")
    f = run_git(["fetch", "origin", "gh-pages"])
    if f.returncode != 0:
        print(f"error: git fetch failed: {f.stderr}", file=sys.stderr)
        return 3
    r = run_git(["reset", "--hard", "origin/gh-pages"])
    if r.returncode != 0:
        print(f"error: git reset failed: {r.stderr}", file=sys.stderr)
        return 3

    # Re-evaluate which files exist after the reset (in case the worktree was stale).
    surviving: list[tuple[str, str, str]] = []
    for pid, bc, tok in to_delete:
        html_p = cards_dir / f"{tok}.html"
        mf_p = cards_dir / f"{tok}.webmanifest"
        if html_p.exists() or mf_p.exists():
            surviving.append((pid, bc, tok))
    print(f"after reset, {len(surviving)} patrons still have cards to remove")

    removed_paths: list[str] = []
    for pid, bc, tok in surviving:
        for ext in ("html", "webmanifest"):
            p = cards_dir / f"{tok}.{ext}"
            if p.exists():
                p.unlink()
                removed_paths.append(f"{CARDS_DIR_REL}/{tok}.{ext}")

    if not removed_paths:
        print("nothing removed after reset.")
        return 0

    add = run_git(["add", "-A"])
    if add.returncode != 0:
        print(f"error: git add failed: {add.stderr}", file=sys.stderr)
        return 3

    msg = (
        f"remove cards for {len(surviving)} non-Active PCO members\n"
        f"\n"
        f"Removes {len(removed_paths)} files ({CARDS_DIR_REL}/<token>.html + .webmanifest)\n"
        f"for patrons whose PCO Member Status is Homebound/Not-Attending\n"
        f"(treated as frozen for blast-email purposes).\n"
        f"\n"
        f"Source: reports/non_active_library_patrons.csv on main.\n"
        f"Note: installed PWAs keep working from service-worker cache until\n"
        f"sw.js CACHE constant is bumped."
    )
    commit = run_git(["commit", "-m", msg])
    if commit.returncode != 0:
        print(f"error: git commit failed: {commit.stderr}", file=sys.stderr)
        return 3
    print(commit.stdout.strip())

    push = run_git(["push", "origin", "gh-pages"])
    if push.returncode != 0:
        print(f"error: git push failed: {push.stderr}", file=sys.stderr)
        return 3
    print(push.stdout.strip() or "push ok")

    print(f"\nremoved {len(removed_paths)} files in 1 commit on gh-pages.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
