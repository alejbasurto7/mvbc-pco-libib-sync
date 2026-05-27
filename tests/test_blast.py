from pathlib import Path

import pytest

from lib.blast import (
    CsvRow,
    Recipient,
    Skipped,
    assign_segment,
    load_status_csv,
    partition,
)
from lib.types import Patron


# --- Test helpers ------------------------------------------------------------


def _patron(patron_id: str, barcode: str = "2020000099999", is_frozen: bool = False) -> Patron:
    """Build a Patron with sensible defaults for partition tests."""
    return Patron(
        patron_id=patron_id, first_name="X", last_name="Y", email="x@y",
        barcode=barcode, is_frozen=is_frozen,
    )


JOSEPH_BARCODE = "2020000006497"  # mirrors lib.web_card.VIP_BARCODES seed
SOME_BARCODE = "2020000099999"


# --- load_status_csv ---------------------------------------------------------


def _write_csv(path: Path, rows: list[str]) -> None:
    header = "patron_id,first_name,last_name,email,barcode,Patron Status\n"
    path.write_text(header + "\n".join(rows) + "\n", encoding="utf-8")


def test_load_status_csv_parses_well_formed_rows(tmp_path):
    p = tmp_path / "patrons.csv"
    _write_csv(p, [
        "1503,Joseph,Shanahan,shanajp3@gmail.com,2.02E+12,active",
        "3548,Sebastian,Parra,sebastianparra8@pm.me,2.02E+12,inactive",
        "189393830,Jay,Raynor,yajraynor@gmail.com,2.02E+12,new",
        "2946,John,Folmar,john@eccdubai.com,2.02E+12,frozen",
    ])
    rows = load_status_csv(p)
    assert len(rows) == 4
    assert rows[0] == CsvRow(
        patron_id="1503", first_name="Joseph", last_name="Shanahan",
        email="shanajp3@gmail.com", csv_barcode="2.02E+12", csv_status="active",
    )
    assert rows[3].csv_status == "frozen"


def test_load_status_csv_lowercases_status(tmp_path):
    # Defensive: accept Status values that may have leading caps or stray whitespace.
    p = tmp_path / "patrons.csv"
    _write_csv(p, ["1,A,B,a@b,2.02E+12,Active"])
    rows = load_status_csv(p)
    assert rows[0].csv_status == "active"


def test_load_status_csv_rejects_unknown_status(tmp_path):
    p = tmp_path / "patrons.csv"
    _write_csv(p, ["1,A,B,a@b,2.02E+12,ghosted"])
    with pytest.raises(ValueError, match="unknown Patron Status"):
        load_status_csv(p)


def test_load_status_csv_rejects_missing_columns(tmp_path):
    p = tmp_path / "patrons.csv"
    p.write_text("patron_id,first_name,Patron Status\n1,A,active\n", encoding="utf-8")
    with pytest.raises(ValueError, match="missing required columns"):
        load_status_csv(p)


def test_load_status_csv_handles_utf8_bom(tmp_path):
    # Excel exports often write a BOM at the start of the file.
    p = tmp_path / "patrons.csv"
    p.write_bytes(
        b"\xef\xbb\xbfpatron_id,first_name,last_name,email,barcode,Patron Status\n"
        b"1,A,B,a@b,2.02E+12,active\n"
    )
    rows = load_status_csv(p)
    assert rows[0].patron_id == "1"


# --- assign_segment ----------------------------------------------------------


def test_assign_segment_active_non_vip_returns_regulars():
    assert assign_segment(csv_status="active", barcode=SOME_BARCODE) == "regulars"


def test_assign_segment_active_vip_returns_regulars_vip():
    assert assign_segment(csv_status="active", barcode=JOSEPH_BARCODE) == "regulars_vip"


def test_assign_segment_inactive_and_new_collapse_to_reminder():
    assert assign_segment(csv_status="inactive", barcode=SOME_BARCODE) == "reminder"
    assert assign_segment(csv_status="new", barcode=SOME_BARCODE) == "reminder"


def test_assign_segment_frozen_returns_none():
    # Caller (partition) treats None as "produce a Skipped entry".
    assert assign_segment(csv_status="frozen", barcode=SOME_BARCODE) is None


# --- partition ---------------------------------------------------------------


def _csv_row(patron_id: str, status: str = "active", email: str = "x@y") -> CsvRow:
    return CsvRow(
        patron_id=patron_id, first_name="X", last_name="Y", email=email,
        csv_barcode="2.02E+12", csv_status=status,  # type: ignore[arg-type]
    )


def test_partition_active_non_vip_goes_to_regulars():
    csv_rows = [_csv_row("1")]
    patrons = {"1": _patron("1", barcode=SOME_BARCODE)}
    recipients, skipped = partition(csv_rows, patrons)
    assert skipped == []
    assert len(recipients) == 1
    assert recipients[0].segment == "regulars"
    assert recipients[0].barcode == SOME_BARCODE


def test_partition_active_vip_goes_to_regulars_vip():
    csv_rows = [_csv_row("1503")]
    patrons = {"1503": _patron("1503", barcode=JOSEPH_BARCODE)}
    recipients, _ = partition(csv_rows, patrons)
    assert recipients[0].segment == "regulars_vip"


def test_partition_inactive_and_new_go_to_reminder():
    csv_rows = [_csv_row("1", status="inactive"), _csv_row("2", status="new")]
    patrons = {
        "1": _patron("1", barcode="2020000000001"),
        "2": _patron("2", barcode="2020000000002"),
    }
    recipients, _ = partition(csv_rows, patrons)
    assert {r.segment for r in recipients} == {"reminder"}


def test_partition_frozen_status_skipped_with_reason_frozen():
    csv_rows = [_csv_row("1", status="frozen")]
    patrons = {"1": _patron("1", barcode=SOME_BARCODE)}
    recipients, skipped = partition(csv_rows, patrons)
    assert recipients == []
    assert len(skipped) == 1
    assert skipped[0].reason == "frozen"


def test_partition_no_api_match_skipped():
    csv_rows = [_csv_row("999")]
    patrons: dict[str, Patron] = {}
    _, skipped = partition(csv_rows, patrons)
    assert skipped[0].reason == "no_api_match"


def test_partition_no_email_skipped():
    csv_rows = [_csv_row("1", email="")]
    patrons = {"1": _patron("1", barcode=SOME_BARCODE)}
    _, skipped = partition(csv_rows, patrons)
    assert skipped[0].reason == "no_email"


def test_partition_no_barcode_on_api_skipped():
    # CSV has the patron but the API record has no barcode set.
    csv_rows = [_csv_row("1")]
    patrons = {"1": Patron(
        patron_id="1", first_name="X", last_name="Y", email="x@y",
        barcode=None, is_frozen=False,
    )}
    _, skipped = partition(csv_rows, patrons)
    assert skipped[0].reason == "no_barcode"


def test_partition_uses_api_barcode_not_csv_barcode():
    # The CSV's csv_barcode field is mangled; the API value is what counts.
    csv_rows = [CsvRow(
        patron_id="1", first_name="X", last_name="Y", email="x@y",
        csv_barcode="2.02E+12", csv_status="active",
    )]
    real_barcode = "2020000012345"
    patrons = {"1": _patron("1", barcode=real_barcode)}
    recipients, _ = partition(csv_rows, patrons)
    assert recipients[0].barcode == real_barcode


def test_partition_priority_no_api_match_beats_other_reasons():
    # If a row has missing email AND no API match, we report no_api_match
    # first because that's the most upstream data-quality problem.
    csv_rows = [_csv_row("999", email="")]
    _, skipped = partition(csv_rows, {})
    assert skipped[0].reason == "no_api_match"
