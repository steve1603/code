"""Parse a bank-statement PDF into a list of transactions.

Most checking-account statements share a table with Date / Description /
Debits / Credits / Balance columns. We extract every debit line and
classify it so the web UI can offer them as debt candidates — e.g. a
"USAA CREDIT CARD PAYMENT" line becomes a suggested credit_card debt.

This is entirely text-based (regex against pypdf's extracted text) so
it's testable without any PDF library or Qt.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from finadvisor.models import DEBT_KINDS


@dataclass
class Transaction:
    date: str            # e.g. "02/17"
    description: str     # cleaned, possibly multi-line
    debit: float | None  # money out
    credit: float | None # money in (deposits)
    balance: float | None  # running balance after the transaction
    kind_guess: str      # one of DEBT_KINDS; best-effort
    account_hint: str = ""  # e.g. "6421" (last 4 of a card/loan number)


# Header / structural phrases that strongly indicate a checking-account
# statement rather than a single-debt statement.
_BANK_STATEMENT_SIGNALS = [
    re.compile(r"\bTransactions\b.*\bDebits\b.*\bCredits\b.*\bBalance\b",
               re.IGNORECASE | re.DOTALL),
    re.compile(r"\bDate\b\s*\bDescription\b\s*\bDebits\b", re.IGNORECASE),
    re.compile(r"\bPOS\s+DEBIT\b", re.IGNORECASE),
    re.compile(r"\bDEBIT\s+CARD\s+PURCHASE\b", re.IGNORECASE),
]


def is_bank_statement(text: str) -> bool:
    """True if the raw PDF text looks like a transaction ledger."""
    if not text:
        return False
    # Any one strong signal plus at least 3 date-prefixed lines.
    signal = any(p.search(text) for p in _BANK_STATEMENT_SIGNALS)
    date_lines = len(re.findall(r"^\s*\d{2}/\d{2}\b", text, re.MULTILINE))
    return signal and date_lines >= 3


# A dollar amount like "$1,234.56" or "1234.56" — the decimal part is
# required so we don't match arbitrary integers in the description.
_AMOUNT = re.compile(r"\$?(-?[\d,]+\.\d{2})")
_DATE_PREFIX = re.compile(r"^\s*(\d{2}/\d{2})\s+(.*)$")


# Description classifiers — first match wins. Patterns are intentionally
# narrow so random words don't trigger a miscategorization.
_KIND_RULES: list[tuple[str, re.Pattern]] = [
    ("mortgage", re.compile(
        r"\b(mortgage|escrow|heloc|home\s*loan)\b", re.IGNORECASE)),
    ("auto", re.compile(
        r"\b(auto\s*loan|car\s*loan|vehicle\s*loan)\b", re.IGNORECASE)),
    ("student_loan", re.compile(
        r"\b(student\s*loan|sallie\s*mae|nelnet|great\s*lakes|"
        r"navient|stafford|fedloan)\b", re.IGNORECASE)),
    ("credit_card", re.compile(
        r"\b(credit\s*card\s*payment|credit\s*card\s*ending|"
        r"card\s*payment)\b", re.IGNORECASE)),
    ("personal", re.compile(
        r"\b(loan\s*payment|installment\s*loan|personal\s*loan|"
        r"loan\s*number\s*ending)\b", re.IGNORECASE)),
]


_ACCOUNT_HINT = re.compile(
    r"ending\s+in\s+(\d{3,6})", re.IGNORECASE
)


def _classify(description: str) -> str:
    for kind, pattern in _KIND_RULES:
        if pattern.search(description):
            return kind
    return "other"


def _extract_account_hint(description: str) -> str:
    m = _ACCOUNT_HINT.search(description)
    return m.group(1) if m else ""


def _is_credit_line(description: str) -> bool:
    """Heuristic: does the wording sound like money coming IN?"""
    return bool(re.search(
        r"\b(deposit|credit\s+memo|refund|payroll|interest\s+paid|"
        r"reversal|direct\s+dep)\b", description, re.IGNORECASE))


def _clean_description(raw: str) -> str:
    # Collapse whitespace and drop PDF-glyph artifacts.
    text = re.sub(r"\s+", " ", raw).strip()
    # Remove trailing commas / stray punctuation.
    return text.strip(" ,;")


def parse_transactions(text: str) -> list[Transaction]:
    """Extract every dated line from the ledger.

    Returns one Transaction per row. Multi-line descriptions (the
    second line carrying a merchant name under the debit-card header)
    are folded into the preceding transaction.
    """
    if not text:
        return []

    raw_lines = text.splitlines()
    # First pass: group wrap-around description continuation lines onto
    # whichever transaction row they belong to.
    rows: list[str] = []
    for line in raw_lines:
        if _DATE_PREFIX.match(line):
            rows.append(line.rstrip())
        elif rows and line.strip():
            # Only treat as continuation if the previous row hasn't yet
            # had a balance attached — simple heuristic: if the row
            # already contains 2+ money amounts, it's probably closed.
            if len(_AMOUNT.findall(rows[-1])) >= 2:
                # Still append — some statements spread descriptions
                # below the amount line.
                rows[-1] += " " + line.strip()
            else:
                rows[-1] += " " + line.strip()

    transactions: list[Transaction] = []
    for row in rows:
        m = _DATE_PREFIX.match(row)
        if not m:
            continue
        date = m.group(1)
        body = m.group(2)

        amounts = _AMOUNT.findall(body)
        amount_floats = [float(a.replace(",", "")) for a in amounts]

        # Strip every dollar amount from the text to get a clean description.
        desc = _AMOUNT.sub("", body)
        desc = _clean_description(desc)

        debit = credit = balance = None
        is_credit = _is_credit_line(desc)
        if len(amount_floats) >= 2:
            # Last amount is the running balance.
            balance = amount_floats[-1]
            # First amount is the transaction value; wording tells us
            # which column it belongs to.
            if is_credit:
                credit = amount_floats[0]
            else:
                debit = amount_floats[0]
            # A third amount means both columns had a value — rare but
            # handle it.
            if len(amount_floats) >= 3:
                credit = amount_floats[1]
        elif len(amount_floats) == 1:
            # Just a balance row (opening/closing); skip.
            continue
        else:
            continue

        transactions.append(Transaction(
            date=date,
            description=desc,
            debit=debit,
            credit=credit,
            balance=balance,
            kind_guess=_classify(desc),
            account_hint=_extract_account_hint(desc),
        ))
    return transactions


def suggest_debt_name(tx: Transaction) -> str:
    """Pick a reasonable Debt name from a transaction description."""
    desc = tx.description
    hint = tx.account_hint
    # Debt-payment transactions: "USAA CREDIT CARD PAYMENT … ENDING IN 6421"
    # → "USAA Card 6421"
    lower = desc.lower()
    if "credit card" in lower and hint:
        issuer = desc.split()[0].title() if desc.split() else "Card"
        return f"{issuer} Card {hint}"
    if "loan" in lower and hint:
        issuer = desc.split()[0].title() if desc.split() else "Loan"
        return f"{issuer} Loan {hint}"
    # Fall back to a tidy version of the description.
    words = desc.split()
    return " ".join(words[:6]).title() or f"Transaction {tx.date}"


def looks_like_debt_payment(tx: Transaction) -> bool:
    """Pre-select rows that clearly pay down an existing debt."""
    return tx.kind_guess in {
        "credit_card", "mortgage", "auto", "student_loan", "personal",
    } and tx.debit is not None


# Re-exported for callers that want to validate a guessed kind.
ALLOWED_KINDS = DEBT_KINDS
