"""Importer for bank-exported transaction CSVs.

Banks and aggregators (Mint, USAA, Chase, Capital One…) export a
transaction register as CSV with headers like:

    Date, Description, Original Description, Category, Amount, Status

This module turns that text into `finadvisor.models.Transaction`
records. It is deliberately forgiving: header names are matched
case-insensitively against a set of aliases, several date and money
formats are accepted, pending rows are skipped, and the amount sign
convention is auto-detected (some exports use signed amounts, others
list everything positive).

Category resolution order (first hit wins):
  1. A user `CategoryRule` matching the description — an explicit
     override always beats everything.
  2. The bank's own Category column, mapped onto SPENDING_CATEGORIES.
  3. The built-in description classifier from `bank_statement`.

Pure text-in / dataclasses-out — no I/O, no Qt.
"""
from __future__ import annotations

import csv
import io
import re
from dataclasses import dataclass, field
from datetime import datetime

from finadvisor.importers.bank_statement import categorize
from finadvisor.models import Transaction
from finadvisor.spending import _normalize_merchant


# ---- header detection -------------------------------------------------------

# Canonical field → accepted header spellings (lowercased, stripped).
_HEADER_ALIASES: dict[str, tuple[str, ...]] = {
    "date": (
        "date", "transaction date", "posted date", "post date",
        "posting date", "trans date",
    ),
    "description": (
        "description", "payee", "merchant", "name", "transaction",
    ),
    "original_description": (
        "original description", "original_description", "memo",
        "original name", "extended description", "full description",
    ),
    "category": ("category", "transaction category"),
    "amount": ("amount", "transaction amount"),
    "debit": ("debit", "withdrawal", "withdrawals", "money out"),
    "credit": ("credit", "deposit", "deposits", "money in"),
    "type": ("transaction type", "type", "debit/credit"),
    "status": ("status", "state"),
}


def _map_headers(fieldnames: list[str]) -> dict[str, str]:
    """Map canonical field names to the CSV's actual header strings."""
    normalized = {
        (name or "").strip().lower().lstrip("﻿"): name
        for name in fieldnames
    }
    out: dict[str, str] = {}
    for canonical, aliases in _HEADER_ALIASES.items():
        for alias in aliases:
            if alias in normalized:
                out[canonical] = normalized[alias]
                break
    return out


def is_transactions_csv(text: str) -> bool:
    """True when the first CSV row looks like a transaction register
    (a date column plus an amount or debit/credit column). Used to
    tell transaction exports apart from the debts CSV template."""
    try:
        reader = csv.reader(io.StringIO(text.lstrip("﻿")))
        header = next(reader)
    except (StopIteration, csv.Error):
        return False
    mapped = _map_headers(header)
    has_amount = "amount" in mapped or (
        "debit" in mapped or "credit" in mapped
    )
    return "date" in mapped and has_amount


# ---- value parsing ----------------------------------------------------------

_DATE_FORMATS = (
    "%m/%d/%Y", "%m/%d/%y", "%Y-%m-%d", "%m-%d-%Y", "%m-%d-%y",
    "%b %d, %Y", "%B %d, %Y", "%d %b %Y", "%Y/%m/%d",
)


def _parse_date(raw: str) -> str | None:
    """Parse common bank date spellings into ISO YYYY-MM-DD."""
    s = (raw or "").strip()
    if not s:
        return None
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(s, fmt).date().isoformat()
        except ValueError:
            continue
    return None


_MONEY_JUNK = re.compile(r"[$,\s]")


def _parse_money(raw: str) -> float | None:
    """Parse '$1,234.56', '-1234.56', '(45.00)' → float. None if blank
    or unparseable. Parentheses mean negative (accounting style)."""
    s = (raw or "").strip()
    if not s:
        return None
    negative = s.startswith("(") and s.endswith(")")
    if negative:
        s = s[1:-1]
    s = _MONEY_JUNK.sub("", s)
    if not s:
        return None
    try:
        value = float(s)
    except ValueError:
        return None
    return -value if negative else value


# ---- bank-category mapping --------------------------------------------------

# Ordered (ours, keywords) pairs — the first keyword found in the
# bank's lowercased category string wins, so more specific phrases
# ("credit card payment") come before generic ones ("credit").
_BANK_CATEGORY_MAP: list[tuple[str, tuple[str, ...]]] = [
    ("debt_payment", (
        "credit card payment", "credit card", "loan payment",
        "student loan", "auto payment", "loan",
    )),
    ("income", (
        "paycheck", "payroll", "salary", "income", "interest earned",
        "reimbursement", "refund",
    )),
    ("transfer", ("transfer", "venmo", "zelle", "paypal")),
    ("home", ("mortgage", "rent", "home improvement", "home services")),
    ("phone_internet", (
        "mobile phone", "cell phone", "internet", "cable", "telephone",
        "phone",
    )),
    ("utilities", ("utilities", "utility", "electric", "water", "sewer",
                   "bills")),
    ("groceries", ("groceries", "grocery", "supermarket")),
    ("dining", (
        "restaurants", "restaurant", "fast food", "dining", "coffee",
        "food & dining", "food and dining", "bars", "alcohol",
    )),
    ("gas", ("gas & fuel", "gas and fuel", "fuel", "gas station", "gas")),
    ("auto", (
        "auto & transport", "auto and transport", "auto insurance",
        "car", "vehicle", "parking", "auto", "service & parts",
        "public transportation", "ride share",
    )),
    ("insurance", ("insurance",)),
    ("healthcare", (
        "health", "medical", "doctor", "pharmacy", "dentist",
        "eyecare", "gym", "fitness",
    )),
    ("subscriptions", ("subscription", "streaming", "membership",
                       "software")),
    ("entertainment", (
        "entertainment", "movies", "music", "arts", "games", "hobbies",
    )),
    ("travel", ("travel", "hotel", "airfare", "air travel", "vacation",
                "rental car")),
    ("fees", ("fee", "fees", "bank charge", "finance charge",
              "service charge", "taxes", "tax")),
    ("cash", ("atm", "cash",)),
    ("shopping", (
        "shopping", "clothing", "electronics", "merchandise", "amazon",
        "sporting goods", "books", "gift", "pets", "pet",
        "personal care", "kids", "baby",
    )),
    ("education", ()),  # placeholder: not in SPENDING_CATEGORIES; unused
]


def _map_bank_category(bank_category: str) -> str | None:
    """Map the bank's category label to one of ours, or None."""
    s = (bank_category or "").strip().lower()
    if not s or s in ("uncategorized", "other", "misc", "miscellaneous"):
        return None
    for ours, keywords in _BANK_CATEGORY_MAP:
        for kw in keywords:
            if kw in s:
                # Guard against the placeholder row.
                return ours if ours != "education" else None
    return None


def _resolve_category(
    display_desc: str,
    original_desc: str,
    bank_category: str,
    rules,
) -> str:
    """Apply the resolution order documented in the module docstring."""
    # 1) User rules win outright — check both description spellings.
    if rules:
        for rule in rules:
            try:
                if rule.matches(original_desc) or rule.matches(display_desc):
                    return rule.category
            except AttributeError:
                continue
    # 2) The bank's own category, mapped to our closed set.
    mapped = _map_bank_category(bank_category)
    if mapped:
        return mapped
    # 3) Built-in description classifier (original text first — it
    #    carries the merchant signals the cleaned name may have lost).
    cat = categorize(original_desc or display_desc)
    if cat == "other" and display_desc and original_desc:
        cat = categorize(display_desc)
    return cat


# ---- main entry point -------------------------------------------------------

@dataclass
class CSVImportResult:
    """Outcome of parsing one transactions CSV."""

    transactions: list[Transaction] = field(default_factory=list)
    skipped_pending: int = 0
    skipped_unparsed: int = 0
    sign_flipped: bool = False   # True when an all-positive export was
    #                              re-signed (income +, spending -)
    total_rows: int = 0


def parse_transactions_csv(
    text: str,
    account_name: str,
    source: str = "csv",
    rules=None,
    account_kind: str = "checking",
    history: dict[str, str] | None = None,
) -> CSVImportResult:
    """Parse a transaction-register CSV into models.Transaction rows.

    `account_kind` refines sign handling: credit-card exports usually
    list charges as positive and payments as negative, the opposite of
    our money-in-positive ledger convention — when most signed rows in
    a credit-card file are positive, the whole file is inverted.

    `history` is a merchant → category map learned from prior months
    (see `spending.history_category_map`). When neither a user rule,
    the bank's category, nor the built-in classifier can place a row,
    the same merchant's historical category is inherited; rows that
    still come up empty are marked `needs_review=True` — the app
    surfaces those as a to-do list for the user.

    Raises ValueError when the text has no usable header (callers show
    the message to the user). Individual bad rows are skipped and
    counted rather than failing the whole file.
    """
    reader = csv.DictReader(io.StringIO(text.lstrip("﻿")))
    if not reader.fieldnames:
        raise ValueError("CSV has no header row.")
    headers = _map_headers(list(reader.fieldnames))
    if "date" not in headers:
        raise ValueError(
            "Couldn't find a Date column. Expected headers like: "
            "Date, Description, Original Description, Category, "
            "Amount, Status."
        )
    if "amount" not in headers and not (
        "debit" in headers or "credit" in headers
    ):
        raise ValueError(
            "Couldn't find an Amount (or Debit/Credit) column in the CSV."
        )

    result = CSVImportResult()

    # First pass: collect raw parsed rows so the sign convention can be
    # decided from the whole file, not row by row.
    parsed_rows: list[tuple[str, str, str, str, float]] = []
    for row in reader:
        if not row or not any((v or "").strip() for v in row.values()):
            continue
        result.total_rows += 1

        status = (row.get(headers.get("status", ""), "") or "").strip().lower()
        if "pending" in status:
            result.skipped_pending += 1
            continue

        iso_date = _parse_date(row.get(headers["date"], "") or "")
        if not iso_date:
            result.skipped_unparsed += 1
            continue

        display_desc = (
            (row.get(headers.get("description", ""), "") or "").strip()
        )
        original_desc = (
            (row.get(headers.get("original_description", ""), "") or "")
            .strip()
        )
        if not display_desc:
            display_desc = original_desc
        if not display_desc:
            result.skipped_unparsed += 1
            continue

        # Amount: single signed column, or separate debit/credit pair.
        amount: float | None = None
        if "amount" in headers:
            amount = _parse_money(row.get(headers["amount"], "") or "")
            # Optional debit/credit *type* column overrides the sign.
            tx_type = (
                (row.get(headers.get("type", ""), "") or "").strip().lower()
            )
            if amount is not None and tx_type:
                if tx_type.startswith("debit") and amount > 0:
                    amount = -amount
                elif tx_type.startswith("credit") and amount < 0:
                    amount = -amount
        else:
            debit = _parse_money(row.get(headers.get("debit", ""), "") or "")
            credit = _parse_money(row.get(headers.get("credit", ""), "") or "")
            if debit is not None and debit != 0:
                amount = -abs(debit)
            elif credit is not None and credit != 0:
                amount = abs(credit)
        if amount is None or amount == 0:
            result.skipped_unparsed += 1
            continue

        bank_category = (
            (row.get(headers.get("category", ""), "") or "").strip()
        )
        parsed_rows.append(
            (iso_date, display_desc, original_desc, bank_category, amount)
        )

    # Sign convention: if the file never goes negative, it's listing
    # magnitudes — flip everything to "money out" except income rows.
    all_positive = bool(parsed_rows) and all(a > 0 for *_x, a in parsed_rows)

    # Credit-card exports commonly use charge-positive signs (purchases
    # +, payments −) — the inverse of our money-in-positive ledger.
    # When a signed credit-card file is mostly positive, spending is
    # what's positive, so invert everything.
    invert_signs = False
    if account_kind == "credit_card" and parsed_rows and not all_positive:
        positives = sum(1 for *_x, a in parsed_rows if a > 0)
        if positives > len(parsed_rows) - positives:
            invert_signs = True

    for iso_date, display_desc, original_desc, bank_category, amount \
            in parsed_rows:
        category = _resolve_category(
            display_desc, original_desc, bank_category, rules,
        )
        needs_review = False
        if category == "other":
            # Correlate with prior months: if this merchant has shown
            # up before with a known category, inherit it.
            inherited = None
            if history:
                inherited = (
                    history.get(_normalize_merchant(original_desc))
                    or history.get(_normalize_merchant(display_desc))
                )
            if inherited:
                category = inherited
            else:
                needs_review = True
        if all_positive and category != "income":
            amount = -amount
            result.sign_flipped = True
        elif invert_signs:
            amount = -amount
            result.sign_flipped = True
        try:
            result.transactions.append(Transaction(
                date=iso_date,
                account=account_name,
                description=display_desc,
                amount=round(amount, 2),
                category=category,
                source=source,
                needs_review=needs_review,
            ))
        except ValueError:
            result.skipped_unparsed += 1

    return result
