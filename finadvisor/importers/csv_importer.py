"""Import debts from a CSV file matching templates/debts_template.csv."""
from __future__ import annotations

import csv
import re
from pathlib import Path

from finadvisor.models import Debt


# The kind column is recommended but optional — we'll infer from the name
# when it's missing or blank.
REQUIRED_COLUMNS = {"name", "balance", "apr", "min_payment"}


class CSVImportError(Exception):
    """Raised when a CSV file cannot be imported."""


_NAME_KIND_HINTS: list[tuple[re.Pattern, str]] = [
    (re.compile(r"mortgage|heloc|home\s+loan", re.IGNORECASE), "mortgage"),
    (re.compile(r"auto|car|vehicle|truck", re.IGNORECASE), "auto"),
    (re.compile(r"student|federal\s+loan|stafford|nelnet|sallie", re.IGNORECASE),
     "student_loan"),
    (re.compile(r"credit\s+card|visa|mastercard|amex|discover|card", re.IGNORECASE),
     "credit_card"),
    (re.compile(r"personal\s+loan|installment", re.IGNORECASE), "personal"),
]


def _guess_kind_from_name(name: str) -> str:
    for pattern, kind in _NAME_KIND_HINTS:
        if pattern.search(name):
            return kind
    return "other"


def parse(path: Path | str) -> list[Debt]:
    p = Path(path)
    if not p.exists():
        raise CSVImportError(f"File not found: {p}")

    with p.open("r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        if not reader.fieldnames:
            raise CSVImportError("CSV file has no header row.")
        missing = REQUIRED_COLUMNS - set(reader.fieldnames)
        if missing:
            raise CSVImportError(
                f"Missing required columns: {', '.join(sorted(missing))}"
            )

        debts: list[Debt] = []
        for line_no, row in enumerate(reader, start=2):  # 1 is header
            if not any((v or "").strip() for v in row.values()):
                continue  # skip blank rows
            if not (row.get("kind") or "").strip():
                row["kind"] = _guess_kind_from_name(row.get("name") or "")
            try:
                debts.append(Debt.from_dict(row))
            except (ValueError, KeyError) as e:
                raise CSVImportError(f"Row {line_no}: {e}") from e
    return debts
