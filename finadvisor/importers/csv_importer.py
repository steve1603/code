"""Import debts from a CSV file matching templates/debts_template.csv."""
from __future__ import annotations

import csv
from pathlib import Path

from finadvisor.models import Debt


REQUIRED_COLUMNS = {"name", "kind", "balance", "apr", "min_payment"}


class CSVImportError(Exception):
    """Raised when a CSV file cannot be imported."""


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
            try:
                debts.append(Debt.from_dict(row))
            except (ValueError, KeyError) as e:
                raise CSVImportError(f"Row {line_no}: {e}") from e
    return debts
