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
from dataclasses import dataclass, field
from datetime import date

from finadvisor.models import DEBT_KINDS, SPENDING_CATEGORIES


@dataclass
class StatementMetadata:
    """What we can scrape from a statement's header page.

    Every field is best-effort. The UI falls back on the filename if
    we can't identify the account, and on "today" if we can't find a
    statement period.
    """

    institution: str = ""          # e.g. "USAA Federal Savings Bank"
    account_name: str = ""         # e.g. "USAA CLASSIC CHECKING"
    account_number: str = ""       # full number if we found one
    account_last4: str = ""        # last 4 digits for display
    account_kind: str = "checking"  # checking / savings / credit_card
    period_start: date | None = None
    period_end: date | None = None
    holder: str = ""

    @property
    def display_name(self) -> str:
        """Short label combining institution + last-4 for the UI."""
        bits = []
        if self.institution:
            # Drop trailing words like "Bank" / "Federal Savings" —
            # "USAA Federal Savings Bank" → "USAA"
            bits.append(self.institution.split()[0])
        if self.account_kind == "credit_card":
            bits.append("Card")
        elif self.account_kind == "savings":
            bits.append("Savings")
        else:
            bits.append("Checking")
        if self.account_last4:
            bits.append(self.account_last4)
        return " ".join(bits) or "Account"


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


# ---------------------------------------------------------------------
# Statement metadata extraction
# ---------------------------------------------------------------------

_INSTITUTION_PATTERNS = [
    re.compile(r"(USAA\s+Federal\s+Savings\s+Bank)", re.IGNORECASE),
    re.compile(r"(Chase\s+Bank[^\n]*)", re.IGNORECASE),
    re.compile(r"(Wells\s+Fargo[^\n]*)", re.IGNORECASE),
    re.compile(r"(Bank\s+of\s+America[^\n]*)", re.IGNORECASE),
    re.compile(r"(Capital\s+One[^\n]*)", re.IGNORECASE),
    re.compile(r"(Citibank|Citi\b[^\n]*)", re.IGNORECASE),
    re.compile(r"(Discover\s+Bank[^\n]*)", re.IGNORECASE),
    re.compile(r"(Ally\s+Bank[^\n]*)", re.IGNORECASE),
]

_ACCOUNT_NAME = re.compile(
    r"\b([A-Z][A-Z &'/-]{2,40}?(?:CHECKING|SAVINGS|CARD|CREDIT\s+CARD))\b"
)

_ACCOUNT_NUMBER = re.compile(
    r"(?:Account\s+Number|Account\s*#|Acct\s*#?)\s*:?\s*"
    r"([\d\*x]{4,20})",
    re.IGNORECASE,
)

_PERIOD = re.compile(
    r"(?:Statement\s+Period|Period|From)\s*:?\s*"
    r"(\d{1,2}/\d{1,2}/\d{2,4})\s*(?:to|-|through|–|—)\s*"
    r"(\d{1,2}/\d{1,2}/\d{2,4})",
    re.IGNORECASE,
)


def _parse_us_date(s: str) -> date | None:
    """Accept M/D/YY or M/D/YYYY, return a date or None."""
    parts = s.split("/")
    if len(parts) != 3:
        return None
    try:
        m, d_, y = (int(p) for p in parts)
    except ValueError:
        return None
    if y < 100:
        # 2-digit year: assume 20xx.
        y += 2000
    try:
        return date(y, m, d_)
    except ValueError:
        return None


def extract_metadata(text: str) -> StatementMetadata:
    """Scrape the header of a bank-statement PDF text.

    Intentionally lenient: pypdf's extracted text varies hugely across
    issuers. Any field we can't confidently find is left blank and
    callers can fall back on the filename.
    """
    md = StatementMetadata()
    if not text:
        return md

    for p in _INSTITUTION_PATTERNS:
        m = p.search(text)
        if m:
            md.institution = m.group(1).strip()
            break

    m = _ACCOUNT_NAME.search(text)
    if m:
        md.account_name = m.group(1).strip().title()
        up = md.account_name.upper()
        if "SAVINGS" in up:
            md.account_kind = "savings"
        elif "CARD" in up or "CREDIT" in up:
            md.account_kind = "credit_card"
        else:
            md.account_kind = "checking"

    m = _ACCOUNT_NUMBER.search(text)
    if m:
        raw = m.group(1)
        md.account_number = raw
        digits = re.sub(r"\D", "", raw)
        if len(digits) >= 4:
            md.account_last4 = digits[-4:]

    m = _PERIOD.search(text)
    if m:
        md.period_start = _parse_us_date(m.group(1))
        md.period_end = _parse_us_date(m.group(2))

    return md


def assign_year(
    md: StatementMetadata, mmdd: str,
) -> str:
    """Promote a 'MM/DD' transaction date to ISO 'YYYY-MM-DD' using
    the statement's period as context. When the period spans a year
    boundary (Dec→Jan) we pick whichever year actually contains the
    MM/DD — so 12/28 stays in the old year and 01/05 bumps forward.
    """
    try:
        m, d_ = (int(x) for x in mmdd.split("/")[:2])
    except ValueError:
        return mmdd  # malformed — hand back untouched

    # No metadata → fall back on today's year so grouping still works.
    today = date.today()
    start = md.period_start or today.replace(day=1)
    end = md.period_end or today

    for candidate_year in (start.year, end.year):
        try:
            cand = date(candidate_year, m, d_)
        except ValueError:
            continue
        if start <= cand <= end:
            return cand.isoformat()

    # Date falls outside the stated period (rare, e.g. pending fees).
    # Default to the period-start year; worst case the user reassigns.
    try:
        return date(start.year, m, d_).isoformat()
    except ValueError:
        return mmdd


# ---------------------------------------------------------------------
# Spending-category classifier
# ---------------------------------------------------------------------

# Rule format: (category, regex). First match wins, so ordering matters
# — more specific patterns (debt_payment, transfer) come before broad
# merchant matches.
_CATEGORY_RULES: list[tuple[str, re.Pattern]] = [
    ("income", re.compile(
        r"\b(payroll|direct\s+dep(?:osit)?|salary|ACH\s+CREDIT|"
        r"interest\s+paid|refund|reimbursement|tax\s+refund|"
        r"(?:dep|deposit)\s+from)\b", re.IGNORECASE)),
    ("debt_payment", re.compile(
        r"\b(credit\s*card\s*payment|loan\s*payment|mortgage\s*payment|"
        r"auto\s*loan|student\s*loan|autopay|card\s*payment|"
        r"citi\s*autopay|chase\s*card|amex\s*payment)\b", re.IGNORECASE)),
    ("transfer", re.compile(
        r"\b(funds\s*transfer|transfer\s*(?:to|from)|zelle|venmo|cashapp|"
        r"cash\s*app|paypal|wire\s*transfer|ATM\s*transfer|"
        r"account\s*transfer|ACH\s*(?:TRANSFER|WITHDRAWAL))\b",
        re.IGNORECASE)),
    ("groceries", re.compile(
        r"\b(kroger|hy-?vee|costco\s*whse|costco\s*wholesale|whole\s*foods|"
        r"trader\s*joe|walmart\s*groc|walmart\s*super|aldi|publix|"
        r"safeway|wegmans|heb\b|sprouts|fresh\s*market|food\s*lion)\b",
        re.IGNORECASE)),
    ("dining", re.compile(
        r"\b(taco\s*bell|mcdonald|starbucks|chipotle|sonic\s*drive|"
        r"dominos|pizza|subway|chick[- ]?fil[- ]?a|panera|wendy|"
        r"dunkin|burger\s*king|crumbl|tst\*?|doordash|ubereats|"
        r"uber\s*eats|grubhub|restaurant|cafe|coffee|lounge|diner|"
        r"sushi|bbq|brewery|brewing)\b", re.IGNORECASE)),
    ("gas", re.compile(
        r"\b(costco\s*gas|shell|chevron|exxon|mobil|bp\b|speedway|"
        r"valero|76\b|circle\s*k|kum\s*&\s*go|love'?s|buc[- ]?ee'?s|"
        r"7[- ]?eleven|gas\s*station)\b", re.IGNORECASE)),
    ("auto", re.compile(
        r"\b(jiffy\s*lube|oil\s*change|autozone|auto\s*zone|o'?reilly|"
        r"napa\s*auto|car\s*wash|tire|dmv\b|registration|"
        r"geico|progressive|state\s*farm\s*auto)\b", re.IGNORECASE)),
    ("home", re.compile(
        r"\b(home\s*depot|lowe'?s|menards|ikea|ace\s*hardware|"
        r"harbor\s*freight|wayfair|at\s*home|best\s*buy)\b",
        re.IGNORECASE)),
    ("utilities", re.compile(
        r"\b(electric|power\s*co|power\s*company|utility|utilities|"
        r"water\s*dept|water\s*bill|gas\s*bill|waste\s*mgmt|"
        r"sewer|trash|disposal)\b", re.IGNORECASE)),
    ("phone_internet", re.compile(
        r"\b(at\s*&\s*t|verizon|t[- ]?mobile|sprint|comcast|xfinity|"
        r"spectrum|cox\s*comm|centurylink|google\s*fi|"
        r"mint\s*mobile)\b", re.IGNORECASE)),
    ("insurance", re.compile(
        r"\b(insurance|allstate|metlife|progressive\s*ins|"
        r"usaa\s*ins|state\s*farm\s*ins|liberty\s*mut|farmers\s*ins)\b",
        re.IGNORECASE)),
    ("healthcare", re.compile(
        r"\b(pharmacy|cvs\s*pharmacy|walgreens|rite\s*aid|medical|"
        r"dental|doctor|clinic|hospital|urgent\s*care|"
        r"lab\s*corp|quest\s*diag)\b", re.IGNORECASE)),
    ("subscriptions", re.compile(
        r"\b(netflix|spotify|hulu|disney\s*plus|disney\+|apple\.com/bill|"
        r"prime\s*video|amazon\s*prime|youtube\s*(?:tv|premium)|"
        r"hbo|paramount|peacock|audible|patreon|substack|"
        r"icloud|onedrive|dropbox|github|adobe|microsoft\s*365|"
        r"office\s*365)\b", re.IGNORECASE)),
    ("entertainment", re.compile(
        r"\b(cinema|movie|theater|theatre|ticketmaster|stubhub|"
        r"steam\s*games|playstation|xbox|nintendo|arcade|bowling|"
        r"concert|festival)\b", re.IGNORECASE)),
    ("travel", re.compile(
        r"\b(airline|airlines|delta\s*air|united\s*air|southwest\s*air|"
        r"american\s*air|jetblue|alaska\s*air|hotel|marriott|hilton|"
        r"airbnb|expedia|kayak|uber\b|lyft|rental\s*car|hertz|"
        r"enterprise\s*r|budget\s*rental)\b", re.IGNORECASE)),
    ("fees", re.compile(
        r"\b(overdraft|nsf\s*fee|late\s*fee|service\s*charge|"
        r"atm\s*fee|foreign\s*trans|maintenance\s*fee|annual\s*fee|"
        r"returned\s*item)\b", re.IGNORECASE)),
    ("cash", re.compile(
        r"\b(atm\s*withdrawal|cash\s*withdrawal|atm\s*cash)\b",
        re.IGNORECASE)),
    ("shopping", re.compile(
        r"\b(amazon|amzn|target|walmart|ebay|etsy|nordstrom|macy|"
        r"kohl|costco\s*#|best\s*buy|gap\b|old\s*navy|tj\s*maxx)\b",
        re.IGNORECASE)),
]


def categorize(description: str) -> str:
    """Return one of SPENDING_CATEGORIES for a transaction description."""
    if not description:
        return "other"
    for cat, pattern in _CATEGORY_RULES:
        if pattern.search(description):
            return cat
    return "other"


def transaction_to_ledger(
    tx: Transaction, md: StatementMetadata, account_name: str,
) -> "tuple[str, float, str]":
    """Collapse a parsed Transaction into the fields needed for
    models.Transaction — an ISO date, a signed amount, and a category.

    Sign convention: amount > 0 means money into the account
    (credits/deposits/payments received), amount < 0 means money out
    (debits/purchases). Matches models.Transaction's contract.
    """
    iso_date = assign_year(md, tx.date)
    if tx.credit is not None:
        amount = float(tx.credit)
    elif tx.debit is not None:
        amount = -float(tx.debit)
    else:
        amount = 0.0
    category = categorize(tx.description)
    return iso_date, amount, category


# Re-exported: useful for UI category pickers.
ALL_CATEGORIES = SPENDING_CATEGORIES
