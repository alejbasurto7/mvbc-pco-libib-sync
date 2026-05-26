"""Tests for lib/web_card — token machinery, URL formatting, and the
HTML + webmanifest builders that emit a per-patron PWA card.
"""
import json
import re

from lib.web_card import (
    build_card_html,
    build_card_manifest,
    card_url,
    new_card_token,
)


HEX32 = re.compile(r"^[0-9a-f]{32}$")


def test_new_card_token_is_32_char_lowercase_hex():
    token = new_card_token()
    assert HEX32.match(token), f"expected 32-char hex, got {token!r}"


def test_new_card_tokens_are_unique_across_calls():
    # UUID4 collisions are astronomically unlikely; this catches accidental
    # constant returns / improperly-seeded RNGs.
    tokens = {new_card_token() for _ in range(50)}
    assert len(tokens) == 50


def test_card_token_is_not_the_libib_patron_id():
    # Libib patron_ids are 13-digit sequential numbers (e.g. 2020000006497).
    # Tokens must NOT be derived from or equal to any plausible patron_id —
    # if a token can be guessed from an ID, the privacy story collapses.
    patron_ids = [
        "2020000006497",
        "2020000000001",
        "2025123456789",
    ]
    for pid in patron_ids:
        token = new_card_token()
        assert token != pid
        assert pid not in token
        assert len(token) != len(pid)


def test_card_url_format():
    base = "https://mvbchurch.github.io/MVBC-PCO-Libib-Sync/cards"
    token = "a" * 32
    assert card_url(base_url=base, token=token) == (
        f"{base}/{token}.html"
    )


def test_card_url_tolerates_trailing_slash_in_base():
    base_with_slash = "https://example.github.io/repo/cards/"
    base_without = "https://example.github.io/repo/cards"
    token = "deadbeef" * 4
    assert card_url(base_url=base_with_slash, token=token) == (
        card_url(base_url=base_without, token=token)
    )


def test_card_url_uses_https_scheme_from_base():
    # The formatter is dumb about scheme — it just joins. Verify it doesn't
    # silently rewrite http/https, in case a misconfig points to http://.
    out = card_url(base_url="http://localhost:8000/cards", token="x" * 32)
    assert out.startswith("http://localhost:8000/cards/")


# --- build_card_html ---------------------------------------------------------


def _render_card(token="a" * 32):
    return build_card_html(
        first_name="Sebastian", last_name="Parra-Diaz",
        barcode="2020000006497", token=token,
    )


def test_build_card_html_contains_name_and_barcode():
    html = _render_card()
    assert "Sebastian Parra-Diaz" in html
    assert "2020000006497" in html


def test_build_card_html_rejects_empty_barcode():
    # The barcode is what the kiosk scanner reads. Rendering a card without
    # one would produce a useless QR — fail fast instead of silently shipping.
    import pytest
    with pytest.raises(ValueError):
        build_card_html(
            first_name="X", last_name="Y", barcode="", token="a" * 32,
        )


def test_build_card_html_inlines_qr_and_emblem_as_base64():
    html = _render_card()
    # Two distinct base64 image data URIs: emblem (in stripe) + QR (in qr-wrap)
    data_uris = re.findall(r'data:image/png;base64,', html)
    assert len(data_uris) >= 2


def test_build_card_html_links_to_patron_specific_manifest():
    token = "feedface" * 4
    html = build_card_html(
        first_name="A", last_name="B", barcode="123", token=token,
    )
    assert f'<link rel="manifest" href="{token}.webmanifest">' in html


def test_build_card_html_marks_page_noindex_and_pwa_capable():
    html = _render_card()
    # Privacy: no search engine should index per-patron pages.
    assert '<meta name="robots" content="noindex,nofollow">' in html
    # PWA: required for full-screen iOS standalone launch.
    assert '<meta name="apple-mobile-web-app-capable" content="yes">' in html
    assert '<link rel="apple-touch-icon"' in html


def test_build_card_html_includes_install_instructions_for_both_platforms():
    html = _render_card()
    assert "iPhone" in html and "iPad" in html
    assert "Android" in html
    assert "Add to Home Screen" in html


def test_build_card_html_registers_service_worker():
    # Without the SW the card won't be available offline at the kiosk.
    assert "serviceWorker" in _render_card()


def test_build_card_html_leaves_no_unresolved_placeholders():
    html = _render_card()
    # string.Template placeholders all start with '$' (and we only use the
    # straight-substitute form). If any are left, substitution missed something.
    for placeholder in (
        "$title", "$full_name", "$barcode",
        "$qr_data_uri", "$emblem_data_uri", "$manifest_filename",
    ):
        assert placeholder not in html, f"unresolved placeholder {placeholder!r}"


# --- build_card_manifest -----------------------------------------------------


def test_build_card_manifest_is_valid_json_with_required_fields():
    token = "deadbeef" * 4
    manifest = build_card_manifest(
        first_name="Ana", last_name="Smith", token=token,
    )
    data = json.loads(manifest)
    assert data["name"].endswith("Ana Smith")
    assert data["short_name"] == "MVBC Library"
    assert data["display"] == "standalone"
    assert data["theme_color"] == "#113355"


def test_build_card_manifest_start_url_is_patron_specific():
    # Each installed PWA must launch into its own card — sharing a single
    # manifest across patrons would point every home-screen icon at the same URL.
    token = "0123456789abcdef" * 2
    data = json.loads(build_card_manifest(
        first_name="X", last_name="Y", token=token,
    ))
    assert data["start_url"] == f"{token}.html"
    assert data["scope"] == f"{token}.html"
