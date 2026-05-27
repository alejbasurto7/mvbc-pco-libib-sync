"""Long-lived per-patron PWA card token storage.

A patron's installed PWA card lives at `cards/<token>.html` — the URL is
baked into their home-screen icon at install time. Minting a fresh token
for the same patron on a subsequent email/blast would orphan that icon.
This module is the central registry that keeps one stable token per
patron for life.

**Keyed on Libib barcode**, NOT patron_id. Barcodes are immutable;
patron_id can be remapped during migrations (see [[feedback-identifier-choice]]).

Schema (state/card_tokens.json):
    {
      "version": 1,
      "updated_at": "2026-05-27T17:33:25+00:00",
      "tokens": {
        "<barcode>": "<token>",
        ...
      }
    }

All callers that need a card token for a patron should go through
``get_or_mint`` rather than calling ``new_card_token`` directly.
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from lib.web_card import new_card_token


CARD_TOKENS_VERSION = 1
_FILENAME = "card_tokens.json"


def load(state_dir: Path) -> dict[str, str]:
    """Return the barcode → token map. Empty dict if the file is missing."""
    path = Path(state_dir) / _FILENAME
    if not path.exists():
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    return dict(data.get("tokens", {}))


def save(state_dir: Path, tokens: dict[str, str], *, now: datetime) -> None:
    """Write the barcode → token map. Overwrites the file."""
    path = Path(state_dir) / _FILENAME
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "version": CARD_TOKENS_VERSION,
        "updated_at": now.isoformat(),
        "tokens": dict(sorted(tokens.items())),  # sorted for stable diffs
    }
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def get_or_mint(tokens: dict[str, str], barcode: str) -> str:
    """Return the token for ``barcode``, minting + persisting in the map if absent.

    Mutates ``tokens`` in place. Caller is responsible for persisting via
    ``save`` after all mints in a session are done.

    Raises ValueError on empty barcode — defensive against accidentally
    minting a token under the empty-string key (which would later collide
    with any patron whose lookup failed).
    """
    if not barcode:
        raise ValueError("barcode is required to look up or mint a card token")
    existing = tokens.get(barcode)
    if existing:
        return existing
    token = new_card_token()
    tokens[barcode] = token
    return token
