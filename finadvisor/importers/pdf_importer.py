"""Best-effort extraction of debt fields from a PDF statement.

PDFs vary wildly, so this is heuristic. Always show results to the user
for confirmation before persisting — see gui/dialogs/pdf_confirm_dialog.py.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path


class PDFImportError(Exception):
    """Raised when a PDF cannot be read or parsed at all."""


@dataclass
class PDFExtraction:
    """Result of a best-effort parse. Any field may be None."""

    suggested_name: str
    raw_text: str
    balance: float | None = None
    apr: float | None = None
    min_payment: float | None = None
    credit_limit: float | None = None
    guessed_kind: str = "credit_card"


_MONEY = r"\$?([\d,]+(?:\.\d{1,2})?)"
_PERCENT = r"(\d{1,2}(?:\.\d{1,4})?)\s*%"

# Ordered patterns — we pick the first match.
BALANCE_PATTERNS = [
    re.compile(r"new\s+balance[:\s]+" + _MONEY, re.IGNORECASE),
    re.compile(r"statement\s+balance[:\s]+" + _MONEY, re.IGNORECASE),
    re.compile(r"current\s+balance[:\s]+" + _MONEY, re.IGNORECASE),
    re.compile(r"outstanding\s+balance[:\s]+" + _MONEY, re.IGNORECASE),
    re.compile(r"principal\s+balance[:\s]+" + _MONEY, re.IGNORECASE),
    re.compile(r"\bbalance[:\s]+" + _MONEY, re.IGNORECASE),
]
APR_PATTERNS = [
    re.compile(r"purchase\s+apr[:\s]+" + _PERCENT, re.IGNORECASE),
    re.compile(r"\bapr[:\s]+" + _PERCENT, re.IGNORECASE),
    re.compile(r"interest\s+rate[:\s]+" + _PERCENT, re.IGNORECASE),
]
MIN_PAYMENT_PATTERNS = [
    re.compile(r"minimum\s+payment(?:\s+due)?[:\s]+" + _MONEY, re.IGNORECASE),
    re.compile(r"minimum\s+due[:\s]+" + _MONEY, re.IGNORECASE),
    re.compile(r"amount\s+due[:\s]+" + _MONEY, re.IGNORECASE),
]
CREDIT_LIMIT_PATTERNS = [
    re.compile(r"credit\s+limit[:\s]+" + _MONEY, re.IGNORECASE),
    re.compile(r"total\s+credit\s+line[:\s]+" + _MONEY, re.IGNORECASE),
]


def _first(patterns: list[re.Pattern], text: str) -> str | None:
    for p in patterns:
        m = p.search(text)
        if m:
            return m.group(1)
    return None


def _money(value: str | None) -> float | None:
    if value is None:
        return None
    try:
        return float(value.replace(",", ""))
    except ValueError:
        return None


def _percent_to_decimal(value: str | None) -> float | None:
    if value is None:
        return None
    try:
        return float(value) / 100.0
    except ValueError:
        return None


def _extract_text(path: Path) -> str:
    try:
        from pypdf import PdfReader
    except ImportError as e:
        raise PDFImportError(
            "pypdf is required for PDF import. Run: pip install pypdf"
        ) from e

    try:
        reader = PdfReader(str(path))
    except Exception as e:  # pypdf raises various errors
        raise PDFImportError(f"Could not open PDF: {e}") from e

    pages = []
    for page in reader.pages:
        try:
            pages.append(page.extract_text() or "")
        except Exception:
            pages.append("")
    return "\n".join(pages)


def parse(path: Path | str) -> PDFExtraction:
    p = Path(path)
    if not p.exists():
        raise PDFImportError(f"File not found: {p}")

    text = _extract_text(p)
    return PDFExtraction(
        suggested_name=p.stem.replace("_", " ").replace("-", " ").strip() or "Imported debt",
        raw_text=text,
        balance=_money(_first(BALANCE_PATTERNS, text)),
        apr=_percent_to_decimal(_first(APR_PATTERNS, text)),
        min_payment=_money(_first(MIN_PAYMENT_PATTERNS, text)),
        credit_limit=_money(_first(CREDIT_LIMIT_PATTERNS, text)),
        guessed_kind="credit_card",
    )
