"""Smoke tests for publish_blast_cards — dry-run path only.

The --apply path hits the GitHub Contents API and is exercised manually
(`python publish_blast_cards.py state/blast_<DATE>/blast_state.json --apply --limit 1`)
before any production run.
"""
from __future__ import annotations

import json
from pathlib import Path

from publish_blast_cards import main


def _make_state(tmp_path: Path, *, vip_token: str = "v" * 32) -> Path:
    state = {
        "version": 1,
        "recipients": {
            "2020000000001": {
                "patron_id": "1",
                "first_name": "Ada",
                "last_name": "Lovelace",
                "email": "ada@example.com",
                "barcode": "2020000000001",
                "csv_status": "active",
                "segment": "regulars",
                "card_token": "a" * 32,
                "card_url": "https://example.test/cards/" + "a" * 32 + ".html",
                "status": "pending",
                "attempts": 0,
                "last_attempt_at": None,
                "last_error": None,
            },
            # Joseph's barcode — exercises the VIP dispatch.
            "2020000006497": {
                "patron_id": "2",
                "first_name": "Joseph",
                "last_name": "Shanahan",
                "email": "joseph@example.com",
                "barcode": "2020000006497",
                "csv_status": "active",
                "segment": "regulars_vip",
                "card_token": vip_token,
                "card_url": "https://example.test/cards/" + vip_token + ".html",
                "status": "pending",
                "attempts": 0,
                "last_attempt_at": None,
                "last_error": None,
            },
        },
    }
    path = tmp_path / "blast_state.json"
    path.write_text(json.dumps(state), encoding="utf-8")
    return path


def test_dry_run_writes_html_and_manifest_for_each_recipient(tmp_path, monkeypatch):
    state_path = _make_state(tmp_path)
    monkeypatch.chdir(tmp_path)

    rc = main([str(state_path)])

    assert rc == 0
    out_dir = tmp_path / ".blast-cards"
    files = sorted(p.name for p in out_dir.iterdir())
    assert files == [
        "a" * 32 + ".html",
        "a" * 32 + ".webmanifest",
        "v" * 32 + ".html",
        "v" * 32 + ".webmanifest",
    ]


def test_dry_run_vip_recipient_gets_vip_template(tmp_path, monkeypatch):
    vip_token = "v" * 32
    state_path = _make_state(tmp_path, vip_token=vip_token)
    monkeypatch.chdir(tmp_path)

    main([str(state_path)])

    # The VIP card's HTML carries the "VIP PATRON" wordmark; the standard
    # card does not. This is the cheapest way to confirm dispatch worked.
    vip_html = (tmp_path / ".blast-cards" / f"{vip_token}.html").read_text(encoding="utf-8")
    assert "VIP" in vip_html
    standard_html = (tmp_path / ".blast-cards" / ("a" * 32 + ".html")).read_text(encoding="utf-8")
    assert "VIP" not in standard_html


def test_limit_caps_recipients(tmp_path, monkeypatch):
    state_path = _make_state(tmp_path)
    monkeypatch.chdir(tmp_path)

    main([str(state_path), "--limit", "1"])

    out_dir = tmp_path / ".blast-cards"
    # Sorted by barcode → 2020000000001 (Ada) comes first; Joseph is dropped.
    files = sorted(p.name for p in out_dir.iterdir())
    assert files == ["a" * 32 + ".html", "a" * 32 + ".webmanifest"]


def test_missing_state_file_returns_2(tmp_path):
    rc = main([str(tmp_path / "nope.json")])
    assert rc == 2


# --- --apply skip/retry logic (gh API mocked) --------------------------------


def test_apply_skips_only_when_both_html_and_webmanifest_exist(tmp_path, monkeypatch):
    """A token with html-only on gh-pages (TCP timeout mid-PUT) must finish
    publishing on retry, not be skipped. Token with both files: skip."""
    import publish_blast_cards as mod

    state_path = _make_state(tmp_path)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(mod, "_gh_repo", lambda: "owner/repo")

    # Ada has both files (skip). Joseph has html but no webmanifest (re-publish).
    ada_token = "a" * 32
    joseph_token = "v" * 32

    def fake_sha(repo, path, branch):
        if path == f"cards/{ada_token}.html":         return "sha-ada-html"
        if path == f"cards/{ada_token}.webmanifest":  return "sha-ada-manifest"
        if path == f"cards/{joseph_token}.html":      return "sha-joseph-html"
        if path == f"cards/{joseph_token}.webmanifest": return None  # missing!
        return None

    puts = []
    def fake_put(*, repo, path, content, message, branch="gh-pages"):
        puts.append(path)

    monkeypatch.setattr(mod, "_gh_contents_get_sha", fake_sha)
    monkeypatch.setattr(mod, "_gh_put_file", fake_put)

    rc = main([str(state_path), "--apply"])

    assert rc == 0
    # Ada (both present) was skipped; Joseph had both files re-PUT to finish him.
    assert puts == [
        f"cards/{joseph_token}.html",
        f"cards/{joseph_token}.webmanifest",
    ]
