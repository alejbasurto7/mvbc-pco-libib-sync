"""Publish one sample card per segment from a blast_state.json manifest.

Reads the manifest, picks the first recipient in each segment, renders their
card (HTML + webmanifest) via select_card_builders, and pushes both files to
gh-pages via the GitHub Contents API (same path publish_test_card.py uses).

The point is to see what the preview emails actually link to, live, before
committing to publishing all 410.

Usage:
    python publish_blast_samples.py state/blast_20260527/blast_state.json
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

from publish_test_card import _gh_put_file, _gh_repo
from lib.web_card import select_card_builders


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print("usage: python publish_blast_samples.py <blast_state.json>", file=sys.stderr)
        return 2

    state = json.loads(Path(argv[1]).read_text(encoding="utf-8"))
    samples: dict[str, dict] = {}
    for rec in state["recipients"].values():
        samples.setdefault(rec["segment"], rec)

    repo = _gh_repo()
    print(f"repo: {repo}")
    print(f"publishing {len(samples)} sample card(s)...")
    for segment, rec in samples.items():
        html_fn, manifest_fn = select_card_builders(barcode=rec["barcode"])
        html = html_fn(
            first_name=rec["first_name"], last_name=rec["last_name"],
            barcode=rec["barcode"], token=rec["card_token"],
        )
        manifest = manifest_fn(
            first_name=rec["first_name"], last_name=rec["last_name"],
            token=rec["card_token"],
        )
        msg = f"blast sample: {rec['first_name']} {rec['last_name']} ({segment})"
        _gh_put_file(
            repo=repo, path=f"cards/{rec['card_token']}.html",
            content=html.encode("utf-8"), message=msg,
        )
        _gh_put_file(
            repo=repo, path=f"cards/{rec['card_token']}.webmanifest",
            content=manifest.encode("utf-8"), message=msg,
        )
        print(f"  {segment:14s} {rec['first_name']} {rec['last_name']}")
        print(f"    {rec['card_url']}")
    print("Pages may take ~30s to refresh.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
