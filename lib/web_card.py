"""Per-patron PWA card support.

Each new patron is issued an opaque URL on the project's GitHub Pages site
that hosts a Progressive Web App card mirroring the printed PNG. This
module mints tokens, formats the public URL, and builds the per-patron HTML
page and its accompanying webmanifest.
"""
from __future__ import annotations

import base64
import io
import json
import uuid
from pathlib import Path
from string import Template

import qrcode

# Brand palette — duplicated from lib.card (the PNG path) so the two stay
# independently editable. If they drift, that's intentional: print and web
# can refine separately.
NAVY = "#113355"
CREAM = "#F3F0EB"
CHARCOAL = "#2C2A2B"  # VIP card surface color (brand's stand-in for black)

_REPO_ROOT = Path(__file__).resolve().parent.parent
_EMBLEM_PATH = _REPO_ROOT / "lib" / "assets" / "MVBC-Emblem-Navy.png"
_TEMPLATE_PATH = _REPO_ROOT / "templates" / "web_card.html"
_VIP_TEMPLATE_PATH = _REPO_ROOT / "templates" / "web_card_vip.html"

# Patrons that receive the VIP card variant. Keyed by Libib barcode (the
# scannable value, same as Patron.barcode and what the QR encodes), not by
# patron_id (the CCB ID). Adding an entry here is all that's needed to opt
# a patron into the VIP design — `select_card_builder` reads this set.
VIP_BARCODES: frozenset[str] = frozenset({
    "2020000006497",  # Joseph Shanahan
})


def new_card_token() -> str:
    """Generate a fresh card token.

    UUID4 in 32-char hex form. Tokens are unguessable and NOT derived from
    the Libib patron_id (which is sequential and must never appear in a
    public URL).
    """
    return uuid.uuid4().hex


def card_url(*, base_url: str, token: str) -> str:
    """Build the public card page URL.

    ``base_url`` is the directory the per-patron HTML files live in, e.g.
    ``https://mvbchurch.github.io/MVBC-PCO-Libib-Sync/cards``. Trailing
    slashes are tolerated.
    """
    return f"{base_url.rstrip('/')}/{token}.html"


def _qr_data_uri(data: str, *, fill: str = NAVY, back: str = CREAM) -> str:
    qr = qrcode.QRCode(
        version=2,
        error_correction=qrcode.constants.ERROR_CORRECT_M,
        box_size=10,
        border=2,
    )
    qr.add_data(data)
    qr.make(fit=True)
    img = qr.make_image(fill_color=fill, back_color=back)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()


def _emblem_data_uri() -> str:
    return "data:image/png;base64," + base64.b64encode(
        _EMBLEM_PATH.read_bytes()
    ).decode()


def build_card_html(
    *,
    first_name: str,
    last_name: str,
    barcode: str,
    token: str,
) -> str:
    """Render the per-patron PWA card HTML.

    QR encodes the Libib ``barcode`` (e.g. ``2020000010739``) — the same value
    the kiosk scanner expects and the same field the printed PNG card uses.
    This is distinct from ``Patron.patron_id`` (the CCB ID), which must never
    appear on the card. Emblem and QR are inlined as base64 so the file is
    self-contained. The page references its own manifest at
    ``<token>.webmanifest`` (sibling file) — see ``build_card_manifest``.
    """
    if not barcode:
        raise ValueError("barcode is required to render a PWA card")
    full_name = f"{first_name} {last_name}".strip()
    tpl = Template(_TEMPLATE_PATH.read_text(encoding="utf-8"))
    return tpl.substitute(
        title=f"MVBC Library Card — {full_name}",
        full_name=full_name,
        barcode=barcode,
        qr_data_uri=_qr_data_uri(barcode),
        emblem_data_uri=_emblem_data_uri(),
        manifest_filename=f"{token}.webmanifest",
    )


def build_card_manifest(
    *,
    first_name: str,
    last_name: str,
    token: str,
) -> str:
    """Render the per-patron webmanifest JSON.

    Each patron gets their own ``<token>.webmanifest`` because PWA install
    semantics tie one ``start_url`` to one installed icon — sharing a single
    manifest across patrons would point every installed icon at the same URL.
    """
    full_name = f"{first_name} {last_name}".strip()
    manifest = {
        "name": f"MVBC Card — {full_name}",
        "short_name": "MVBC Card",
        "description": f"{full_name}'s MVBC Library card.",
        "start_url": f"{token}.html",
        "scope": f"{token}.html",
        "display": "standalone",
        "orientation": "portrait",
        "background_color": "#E7E2D6",
        "theme_color": "#113355",
        "icons": [
            {
                "src": "../icons/icon-192.png",
                "sizes": "192x192",
                "type": "image/png",
                "purpose": "any maskable",
            },
            {
                "src": "../icons/icon-512.png",
                "sizes": "512x512",
                "type": "image/png",
                "purpose": "any maskable",
            },
        ],
    }
    return json.dumps(manifest, indent=2)


def build_vip_card_html(
    *,
    first_name: str,
    last_name: str,
    barcode: str,
    token: str,
) -> str:
    """Render the per-patron VIP PWA card HTML.

    Same patron-data contract as ``build_card_html``: ``barcode`` is the
    Libib ``Patron.barcode`` (the kiosk-scannable value), NOT the CCB
    patron_id. The VIP variant is a different visual design (charcoal
    surface, gilded text, holographic shine) but behaves identically as a
    PWA — same per-patron token URL, same manifest sibling pattern, same
    QR contents.

    The QR is rendered Cream-on-Charcoal to match the dark badge surface
    (inverse of the standard Navy-on-Cream QR).
    """
    if not barcode:
        raise ValueError("barcode is required to render a VIP PWA card")
    full_name = f"{first_name} {last_name}".strip()
    tpl = Template(_VIP_TEMPLATE_PATH.read_text(encoding="utf-8"))
    return tpl.substitute(
        title=f"MVBC Library Card — {full_name}",
        full_name=full_name,
        barcode=barcode,
        qr_data_uri=_qr_data_uri(barcode, fill=CREAM, back=CHARCOAL),
        emblem_data_uri=_emblem_data_uri(),
        manifest_filename=f"{token}.webmanifest",
    )


def build_vip_card_manifest(
    *,
    first_name: str,
    last_name: str,
    token: str,
) -> str:
    """Render the per-patron VIP webmanifest JSON.

    Mirrors ``build_card_manifest`` but tweaks the surfaced metadata for
    the VIP variant: name carries "VIP", theme_color matches the charcoal
    badge (drives the iOS status-bar tint when launched from home screen).
    """
    full_name = f"{first_name} {last_name}".strip()
    manifest = {
        "name": f"MVBC VIP Card — {full_name}",
        "short_name": "MVBC VIP",
        "description": f"{full_name}'s MVBC Library VIP card.",
        "start_url": f"{token}.html",
        "scope": f"{token}.html",
        "display": "standalone",
        "orientation": "portrait",
        "background_color": "#ECE6DA",
        "theme_color": CHARCOAL,
        "icons": [
            {
                "src": "../icons/icon-192.png",
                "sizes": "192x192",
                "type": "image/png",
                "purpose": "any maskable",
            },
            {
                "src": "../icons/icon-512.png",
                "sizes": "512x512",
                "type": "image/png",
                "purpose": "any maskable",
            },
        ],
    }
    return json.dumps(manifest, indent=2)


def is_vip_patron(*, barcode: str) -> bool:
    """Return True if this patron should receive the VIP card variant.

    Keyed on Libib barcode (the QR-encoded scannable value), not patron_id.
    To opt another patron into the VIP card, add their barcode to
    ``VIP_BARCODES`` at module scope.
    """
    return barcode in VIP_BARCODES


def select_card_builders(*, barcode: str):
    """Return the (html_builder, manifest_builder) pair appropriate for this
    patron, so callers don't have to branch on identity at the call site.

    The two returned callables share the same keyword-only signatures as
    ``build_card_html`` / ``build_card_manifest`` (and their VIP twins), so
    a caller can do::

        html_fn, manifest_fn = select_card_builders(barcode=patron.barcode)
        html = html_fn(first_name=..., last_name=..., barcode=..., token=...)
        manifest = manifest_fn(first_name=..., last_name=..., token=...)

    No call site changes if/when the VIP set grows beyond Joseph.
    """
    if is_vip_patron(barcode=barcode):
        return build_vip_card_html, build_vip_card_manifest
    return build_card_html, build_card_manifest
