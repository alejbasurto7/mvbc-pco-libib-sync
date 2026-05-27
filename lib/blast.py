"""Pure logic for the one-shot blast email send path.

Reads a `Patrons-Status-YYYYMMDD.csv` export from Libib, hydrates real
barcodes via the Libib API (the CSV's `barcode` column is Excel-mangled
and discarded), and partitions patrons into one of three send segments
plus a skip bucket.

All persistent state downstream of this module keys on Libib **barcode**,
not patron_id, because patron_id can be remapped during migrations while
barcodes are immutable.
"""
from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Literal, Optional

from lib.types import Patron
from lib.web_card import is_vip_patron


PatronStatus = Literal["active", "inactive", "new", "frozen"]
BlastSegment = Literal["regulars", "regulars_vip", "reminder"]
SkipReason = Literal["frozen", "no_api_match", "no_email", "no_barcode", "non_active_pco"]


@dataclass(frozen=True)
class CsvRow:
    """A raw row from a Patrons-Status export. ``csv_barcode`` is informational
    only — downstream code must use the API-hydrated barcode (the CSV's value
    is typically Excel-mangled to scientific notation)."""
    patron_id: str
    first_name: str
    last_name: str
    email: str
    csv_barcode: str
    csv_status: PatronStatus


@dataclass(frozen=True)
class Recipient:
    """A patron who will receive an email in the upcoming blast."""
    patron_id: str
    first_name: str
    last_name: str
    email: str
    barcode: str  # API-hydrated, immutable
    csv_status: PatronStatus
    segment: BlastSegment


@dataclass(frozen=True)
class Skipped:
    """A patron we explicitly chose not to email. Keyed by patron_id (since
    skip reasons include cases where no barcode exists)."""
    patron_id: str
    first_name: str
    last_name: str
    email: str
    csv_status: PatronStatus
    reason: SkipReason


_VALID_STATUSES: frozenset[str] = frozenset({"active", "inactive", "new", "frozen"})


def load_status_csv(path: Path) -> list[CsvRow]:
    """Read a Patrons-Status-YYYYMMDD.csv export.

    Expected schema (header row, comma-separated):
        patron_id,first_name,last_name,email,barcode,Patron Status

    Raises ValueError if the header is missing required columns or if
    any row carries an unknown Patron Status value.
    """
    rows: list[CsvRow] = []
    with Path(path).open(encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        required = {"patron_id", "first_name", "last_name", "email", "barcode", "Patron Status"}
        missing = required - set(reader.fieldnames or [])
        if missing:
            raise ValueError(f"CSV missing required columns: {sorted(missing)}")
        for raw in reader:
            status = (raw["Patron Status"] or "").strip().lower()
            if status not in _VALID_STATUSES:
                raise ValueError(
                    f"unknown Patron Status {status!r} for patron_id={raw['patron_id']!r}"
                )
            rows.append(CsvRow(
                patron_id=(raw["patron_id"] or "").strip(),
                first_name=(raw["first_name"] or "").strip(),
                last_name=(raw["last_name"] or "").strip(),
                email=(raw["email"] or "").strip(),
                csv_barcode=(raw["barcode"] or "").strip(),
                csv_status=status,  # type: ignore[arg-type]
            ))
    return rows


def assign_segment(*, csv_status: PatronStatus, barcode: str) -> Optional[BlastSegment]:
    """Map a (status, barcode) pair to a send segment.

    Returns None for ``frozen`` (the caller should produce a Skipped). For
    ``active`` the segment is VIP if the barcode is in VIP_BARCODES,
    otherwise the standard regulars segment. ``inactive`` and ``new``
    both collapse to ``reminder``.
    """
    if csv_status == "frozen":
        return None
    if csv_status == "active":
        return "regulars_vip" if is_vip_patron(barcode=barcode) else "regulars"
    # inactive + new
    return "reminder"


def partition(
    csv_rows: Iterable[CsvRow],
    patrons_by_patron_id: dict[str, Patron],
    *,
    non_active_pco_patron_ids: frozenset[str] | set[str] = frozenset(),
) -> tuple[list[Recipient], list[Skipped]]:
    """Split CSV rows into sendable Recipients and Skipped entries.

    For each row we look up the patron in ``patrons_by_patron_id`` to
    get the real (immutable) barcode. Rows are skipped — in priority
    order — for: no API match, missing email, missing barcode on the
    API side, csv_status='frozen', or PCO Member Status != Active.

    Libib's ``frozen`` takes precedence over PCO non-Active for the skip
    label, so the existing freeze workflow stays the audit source of
    truth when both signals agree.
    """
    recipients: list[Recipient] = []
    skipped: list[Skipped] = []
    for row in csv_rows:
        patron = patrons_by_patron_id.get(row.patron_id)
        if patron is None:
            skipped.append(_skip(row, "no_api_match"))
            continue
        if not row.email:
            skipped.append(_skip(row, "no_email"))
            continue
        if not patron.barcode:
            skipped.append(_skip(row, "no_barcode"))
            continue
        if row.csv_status == "frozen":
            skipped.append(_skip(row, "frozen"))
            continue
        if row.patron_id in non_active_pco_patron_ids:
            skipped.append(_skip(row, "non_active_pco"))
            continue
        segment = assign_segment(csv_status=row.csv_status, barcode=patron.barcode)
        assert segment is not None  # frozen was filtered above
        recipients.append(Recipient(
            patron_id=row.patron_id,
            first_name=row.first_name,
            last_name=row.last_name,
            email=row.email,
            barcode=patron.barcode,
            csv_status=row.csv_status,
            segment=segment,
        ))
    return recipients, skipped


def _skip(row: CsvRow, reason: SkipReason) -> Skipped:
    return Skipped(
        patron_id=row.patron_id,
        first_name=row.first_name,
        last_name=row.last_name,
        email=row.email,
        csv_status=row.csv_status,
        reason=reason,
    )
