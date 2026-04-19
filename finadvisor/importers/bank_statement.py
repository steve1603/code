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


# Header / structural phrases that hint at a checking-account ledger
# rather than a single-debt statement. pypdf's text extraction can
# flatten columns into one long line, so these intentionally match
# anywhere in the text.
_BANK_STATEMENT_SIGNALS = [
    re.compile(r"\bTransactions?\b", re.IGNORECASE),
    re.compile(r"\bDebits?\s+Credits?\b", re.IGNORECASE),
    re.compile(r"\bPOS\s+DEBIT\b", re.IGNORECASE),
    re.compile(r"\bDEBIT\s+CARD\s+PURCHASE\b", re.IGNORECASE),
    re.compile(r"\b(previous|beginning|ending|available)\s+balance\b",
               re.IGNORECASE),
    re.compile(r"\bstatement\s+period\b", re.IGNORECASE),
    re.compile(r"\b(deposit|withdrawal|transfer)\b", re.IGNORECASE),
    re.compile(r"\bACH\s+(credit|debit)\b", re.IGNORECASE),
]

# A date like "02/17" or "2/17/2024" — we only need month/day, so the
# year (if present) is an optional suffix captured and discarded.
_DATE = re.compile(r"\b(\d{1,2}/\d{1,2})(?:/\d{2,4})?\b")
# Single-debt-statement disqualifiers: if these are present, the file
# is almost certainly a card/loan statement, not a bank ledger.
_SINGLE_DEBT_SIGNALS = [
    re.compile(r"\bNew\s+Balance\b", re.IGNORECASE),
    re.compile(r"\bMinimum\s+Payment\s+Due\b", re.IGNORECASE),
    re.compile(r"\bCredit\s+Limit\b", re.IGNORECASE),
    re.compile(r"\bPurchase\s+APR\b", re.IGNORECASE),
    re.compile(r"\bPrincipal\s+Balance\b", re.IGNORECASE),
]


def is_bank_statement(text: str) -> bool:
    """True if the raw PDF text looks like a transaction ledger.

    Deliberately permissive: pypdf's extraction often reflows columns
    into one long line, losing the tidy "Date Description Debits
    Credits Balance" header. We take any structural signal OR enough
    date+amount density as evidence, and disqualify single-debt
    statements (cards/loans) that happen to list a few dates.
    """
    if not text:
        return False
    # If the text shouts that it's a single-debt statement, bail out
    # early so we don't mis-route a credit-card bill through the
    # checklist flow.
    single_debt_hits = sum(
        1 for p in _SINGLE_DEBT_SIGNALS if p.search(text)
    )
    if single_debt_hits >= 2:
        return False

    signal_hits = sum(
        1 for p in _BANK_STATEMENT_SIGNALS if p.search(text)
    )
    dates = len(_DATE.findall(text))
    amounts = len(_AMOUNT.findall(text))
    # Either (a) we see an explicit signal and a few dated rows, or
    # (b) the text is dense with dates and dollar amounts — typical
    # of a checking-account transaction list.
    return (
        (signal_hits >= 1 and dates >= 3 and amounts >= 3)
        or (dates >= 5 and amounts >= 6)
    )


# A dollar amount like "$1,234.56" or "1234.56" — the decimal part is
# required so we don't match arbitrary integers in the description.
_AMOUNT = re.compile(r"\$?(-?[\d,]+\.\d{2})")


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
    """Extract every dated transaction from the ledger text.

    pypdf often flattens a statement's rows into one long line with
    every column value run together, so a line-anchored parser misses
    everything. Instead we find every date token (MM/DD or MM/DD/YYYY)
    and treat the span between one date and the next as a single
    transaction — that's robust to line breaks, reordered columns,
    and inline continuation text.
    """
    if not text:
        return []

    matches = list(_DATE.finditer(text))
    if not matches:
        return []

    transactions: list[Transaction] = []
    for i, m in enumerate(matches):
        start = m.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        body = text[start:end]

        amounts = _AMOUNT.findall(body)
        if not amounts:
            continue
        amount_floats = [float(a.replace(",", "")) for a in amounts]

        # Drop every dollar amount to recover a clean description.
        desc = _AMOUNT.sub("", body)
        desc = _clean_description(desc)
        if not desc:
            # Probably an opening/closing-balance row with only amounts.
            continue

        debit = credit = balance = None
        is_credit = _is_credit_line(desc)
        if len(amount_floats) >= 2:
            balance = amount_floats[-1]
            if is_credit:
                credit = amount_floats[0]
            else:
                debit = amount_floats[0]
            if len(amount_floats) >= 3:
                # Some formats put both debit and credit columns on the
                # same row; whichever is non-zero is what we want.
                credit = amount_floats[1]
        else:
            # Single amount — no running-balance column. Still useful:
            # the amount IS the transaction value; assume debit unless
            # description sounds like a deposit.
            value = amount_floats[0]
            if is_credit:
                credit = value
            else:
                debit = value

        transactions.append(Transaction(
            date=m.group(1),
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


# Reasonable rate-of-the-day defaults for each debt kind. These are
# only used when a transaction gets imported as a new Debt — the user
# can always edit afterwards. Keeping them here (not magic numbers in
# the web handler) makes them easy to tune in one place.
DEFAULT_APR_BY_KIND: dict[str, float] = {
    "credit_card": 0.22,
    "auto": 0.07,
    "mortgage": 0.065,
    "student_loan": 0.06,
    "personal": 0.12,
    "other": 0.10,
}


def default_apr(kind: str) -> float:
    return DEFAULT_APR_BY_KIND.get(kind, DEFAULT_APR_BY_KIND["other"])
