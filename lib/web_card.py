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

_REPO_ROOT = Path(__file__).resolve().parent.parent
_EMBLEM_PATH = _REPO_ROOT / "lib" / "assets" / "MVBC-Emblem-Navy.png"
_TEMPLATE_PATH = _REPO_ROOT / "templates" / "web_card.html"


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


def _qr_data_uri(data: str) -> str:
    qr = qrcode.QRCode(
        version=2,
        error_correction=qrcode.constants.ERROR_CORRECT_M,
        box_size=10,
        border=2,
    )
    qr.add_data(data)
    qr.make(fit=True)
    img = qr.make_image(fill_color=NAVY, back_color=CREAM)
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
    patron_id: str,
    token: str,
) -> str:
    """Render the per-patron PWA card HTML.

    QR encodes the bare patron_id (matches the Libib barcode), emblem and QR
    are inlined as base64 so the file is self-contained. The page references
    its own manifest at ``<token>.webmanifest`` (sibling file) — see
    ``build_card_manifest``.
    """
    full_name = f"{first_name} {last_name}".strip()
    tpl = Template(_TEMPLATE_PATH.read_text(encoding="utf-8"))
    return tpl.substitute(
        title=f"MVBC Library Card — {full_name}",
        full_name=full_name,
        member_id=patron_id,
        qr_data_uri=_qr_data_uri(patron_id),
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
        "name": f"MVBC Library — {full_name}",
        "short_name": "MVBC Library",
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
