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
    re.compile(r"unpaid\s+principal(?:\s+balance)?[:\s]+" + _MONEY, re.IGNORECASE),
    re.compile(r"principal\s+balance[:\s]+" + _MONEY, re.IGNORECASE),
    re.compile(r"remaining\s+balance[:\s]+" + _MONEY, re.IGNORECASE),
    re.compile(r"payoff\s+amount[:\s]+" + _MONEY, re.IGNORECASE),
    re.compile(r"\bbalance[:\s]+" + _MONEY, re.IGNORECASE),
]
APR_PATTERNS = [
    re.compile(r"purchase\s+apr[:\s]+" + _PERCENT, re.IGNORECASE),
    re.compile(r"\bapr[:\s]+" + _PERCENT, re.IGNORECASE),
    re.compile(r"annual\s+percentage\s+rate[:\s]+" + _PERCENT, re.IGNORECASE),
    re.compile(r"interest\s+rate[:\s]+" + _PERCENT, re.IGNORECASE),
    re.compile(r"note\s+rate[:\s]+" + _PERCENT, re.IGNORECASE),
]
MIN_PAYMENT_PATTERNS = [
    re.compile(r"minimum\s+payment(?:\s+due)?[:\s]+" + _MONEY, re.IGNORECASE),
    re.compile(r"minimum\s+due[:\s]+" + _MONEY, re.IGNORECASE),
    re.compile(r"monthly\s+payment(?:\s+amount)?[:\s]+" + _MONEY, re.IGNORECASE),
    re.compile(r"regular\s+payment[:\s]+" + _MONEY, re.IGNORECASE),
    re.compile(r"amount\s+due[:\s]+" + _MONEY, re.IGNORECASE),
]
CREDIT_LIMIT_PATTERNS = [
    re.compile(r"credit\s+limit[:\s]+" + _MONEY, re.IGNORECASE),
    re.compile(r"total\s+credit\s+line[:\s]+" + _MONEY, re.IGNORECASE),
    re.compile(r"credit\s+line[:\s]+" + _MONEY, re.IGNORECASE),
]

# Text signals used to classify the debt kind. Checked in order; the first
# matching kind wins. "credit_card" is the default when we find credit-card
# signals, "other" when we find nothing at all.
_KIND_SIGNALS = [
    ("mortgage", re.compile(
        r"\b(mortgage|escrow|home\s+loan|heloc)\b", re.IGNORECASE)),
    ("auto", re.compile(
        r"\b(auto\s+loan|vehicle\s+loan|car\s+loan|vin|odometer)\b",
        re.IGNORECASE)),
    ("student_loan", re.compile(
        r"\b(student\s+loan|federal\s+loan|stafford|sallie\s+mae|"
        r"nelnet|great\s+lakes|loan\s+servicer|direct\s+loan)\b",
        re.IGNORECASE)),
    ("personal", re.compile(
        r"\b(personal\s+loan|installment\s+loan|unsecured\s+loan)\b",
        re.IGNORECASE)),
    ("credit_card", re.compile(
        r"\b(credit\s+card|statement\s+balance|credit\s+limit|"
        r"minimum\s+payment\s+due|purchase\s+apr|cash\s+advance\s+apr)\b",
        re.IGNORECASE)),
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


def _guess_kind(text: str) -> str:
    for kind, pattern in _KIND_SIGNALS:
        if pattern.search(text):
            return kind
    return "other"


def extract_from_text(text: str, suggested_name: str) -> PDFExtraction:
    """Run heuristics against already-extracted text. Exposed for tests."""
    kind = _guess_kind(text)
    credit_limit = (
        _money(_first(CREDIT_LIMIT_PATTERNS, text))
        if kind == "credit_card"
        else None
    )
    return PDFExtraction(
        suggested_name=suggested_name,
        raw_text=text,
        balance=_money(_first(BALANCE_PATTERNS, text)),
        apr=_percent_to_decimal(_first(APR_PATTERNS, text)),
        min_payment=_money(_first(MIN_PAYMENT_PATTERNS, text)),
        credit_limit=credit_limit,
        guessed_kind=kind,
    )


def parse(path: Path | str) -> PDFExtraction:
    p = Path(path)
    if not p.exists():
        raise PDFImportError(f"File not found: {p}")

    text = _extract_text(p)
    suggested_name = (
        p.stem.replace("_", " ").replace("-", " ").strip() or "Imported debt"
    )
    return extract_from_text(text, suggested_name)
