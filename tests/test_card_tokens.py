import json
from datetime import datetime, timezone

import pytest

from lib.card_tokens import (
    CARD_TOKENS_VERSION,
    get_or_mint,
    load,
    save,
)


NOW = datetime(2026, 5, 27, 12, 0, 0, tzinfo=timezone.utc)


# --- load / save -------------------------------------------------------------


def test_load_returns_empty_when_file_missing(tmp_path):
    assert load(tmp_path) == {}


def test_save_then_load_roundtrip(tmp_path):
    tokens = {"2020000006497": "abc123", "2020000099999": "deadbeef"}
    save(tmp_path, tokens, now=NOW)
    assert load(tmp_path) == tokens


def test_save_writes_versioned_schema(tmp_path):
    save(tmp_path, {"2020000000001": "aa"}, now=NOW)
    payload = json.loads((tmp_path / "card_tokens.json").read_text(encoding="utf-8"))
    assert payload["version"] == CARD_TOKENS_VERSION
    assert payload["updated_at"] == NOW.isoformat()
    assert payload["tokens"] == {"2020000000001": "aa"}


def test_save_sorts_keys_for_stable_diffs(tmp_path):
    # Sorted keys keep diffs of card_tokens.json small + reviewable as
    # the file grows. (Real-world it'll have a few hundred entries.)
    save(tmp_path, {"2020c": "c", "2020a": "a", "2020b": "b"}, now=NOW)
    text = (tmp_path / "card_tokens.json").read_text(encoding="utf-8")
    a_pos, b_pos, c_pos = text.index("2020a"), text.index("2020b"), text.index("2020c")
    assert a_pos < b_pos < c_pos


def test_save_creates_state_dir_if_missing(tmp_path):
    target = tmp_path / "nested" / "state"
    save(target, {"x": "y"}, now=NOW)
    assert (target / "card_tokens.json").exists()


# --- get_or_mint -------------------------------------------------------------


def test_get_or_mint_returns_existing_token_unchanged():
    tokens = {"2020000006497": "preminted-token"}
    result = get_or_mint(tokens, "2020000006497")
    assert result == "preminted-token"
    assert tokens == {"2020000006497": "preminted-token"}  # unchanged


def test_get_or_mint_creates_new_token_when_absent():
    tokens: dict[str, str] = {}
    result = get_or_mint(tokens, "2020000099999")
    assert tokens == {"2020000099999": result}
    # UUID4 hex is 32 chars
    assert len(result) == 32


def test_get_or_mint_is_idempotent_for_same_barcode():
    tokens: dict[str, str] = {}
    first = get_or_mint(tokens, "2020000099999")
    second = get_or_mint(tokens, "2020000099999")
    assert first == second
    assert len(tokens) == 1


def test_get_or_mint_mints_distinct_tokens_per_barcode():
    tokens: dict[str, str] = {}
    a = get_or_mint(tokens, "2020000000001")
    b = get_or_mint(tokens, "2020000000002")
    assert a != b


def test_get_or_mint_rejects_empty_barcode():
    # Empty barcodes would collide under the empty-string key, masking
    # data-quality issues. Fail loudly instead.
    with pytest.raises(ValueError, match="barcode is required"):
        get_or_mint({}, "")
