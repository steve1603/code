"""Core data model for debts and budget."""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from datetime import date
from typing import Any


DEBT_KINDS = (
    "credit_card",
    "student_loan",
    "auto",
    "mortgage",
    "personal",
    "other",
)


# Spending categories are a closed set so the UI can render consistent
# colors and the trend view can diff them across months.
SPENDING_CATEGORIES = (
    "income",
    "transfer",
    "debt_payment",
    "groceries",
    "dining",
    "gas",
    "auto",
    "shopping",
    "home",
    "utilities",
    "phone_internet",
    "insurance",
    "healthcare",
    "entertainment",
    "subscriptions",
    "travel",
    "fees",
    "cash",
    "other",
)


@dataclass
class Debt:
    name: str
    kind: str
    balance: float
    apr: float
    min_payment: float
    credit_limit: float | None = None
    due_day: int | None = None

    def __post_init__(self) -> None:
        if not self.name or not self.name.strip():
            raise ValueError("Debt name cannot be empty.")
        if self.kind not in DEBT_KINDS:
            raise ValueError(
                f"Unknown debt kind {self.kind!r}. "
                f"Must be one of: {', '.join(DEBT_KINDS)}."
            )
        if self.balance < 0:
            raise ValueError(f"Balance cannot be negative (got {self.balance}).")
        if not (0 <= self.apr < 1):
            raise ValueError(
                f"APR must be a decimal in [0, 1), e.g. 0.2499 for 24.99% "
                f"(got {self.apr})."
            )
        if self.min_payment < 0:
            raise ValueError(
                f"Minimum payment cannot be negative (got {self.min_payment})."
            )
        if self.credit_limit is not None and self.credit_limit < 0:
            raise ValueError(
                f"Credit limit cannot be negative (got {self.credit_limit})."
            )
        if self.due_day is not None and not (1 <= self.due_day <= 31):
            raise ValueError(f"Due day must be 1..31 (got {self.due_day}).")

    @property
    def utilization(self) -> float | None:
        """Credit utilization as a fraction (e.g. 0.42) for credit cards."""
        if self.kind != "credit_card" or not self.credit_limit:
            return None
        return self.balance / self.credit_limit

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "Debt":
        return cls(
            name=d["name"],
            kind=d.get("kind", "other"),
            balance=float(d["balance"]),
            apr=float(d["apr"]),
            min_payment=float(d.get("min_payment", 0.0)),
            credit_limit=(
                float(d["credit_limit"])
                if d.get("credit_limit") not in (None, "")
                else None
            ),
            due_day=(
                int(d["due_day"])
                if d.get("due_day") not in (None, "")
                else None
            ),
        )


@dataclass
class Budget:
    monthly_income: float = 0.0
    monthly_expenses: float = 0.0

    def __post_init__(self) -> None:
        if self.monthly_income < 0:
            raise ValueError("Monthly income cannot be negative.")
        if self.monthly_expenses < 0:
            raise ValueError("Monthly expenses cannot be negative.")

    def extra_payment_capacity(self, debts: list[Debt]) -> float:
        """Cash left over after living expenses AND every minimum payment."""
        total_minimums = sum(d.min_payment for d in debts)
        return self.monthly_income - self.monthly_expenses - total_minimums

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "Budget":
        return cls(
            monthly_income=float(d.get("monthly_income", 0.0)),
            monthly_expenses=float(d.get("monthly_expenses", 0.0)),
        )


@dataclass
class Account:
    """A bank / credit-card account that transactions are posted to.

    `name` is what the user sees (e.g. "USAA Checking 3904"). `kind`
    drives sign interpretation: for checking/savings a positive amount
    is a deposit, for credit_card a positive amount is a payment.
    """

    name: str
    kind: str = "checking"  # "checking" | "savings" | "credit_card"
    institution: str = ""
    number_hint: str = ""   # last-4 or truncated number for display only

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "Account":
        return cls(
            name=d["name"],
            kind=d.get("kind", "checking"),
            institution=d.get("institution", ""),
            number_hint=d.get("number_hint", ""),
        )


@dataclass
class Transaction:
    """A single posted line from a statement.

    `amount` follows an income-positive convention: deposits and
    credits are positive, debits/purchases are negative. `date` is
    stored as ISO YYYY-MM-DD so month grouping is trivial.
    """

    date: str          # ISO "YYYY-MM-DD"
    account: str       # matches Account.name
    description: str
    amount: float      # signed: + = money in, - = money out
    category: str = "other"
    source: str = ""   # filename or "pasted"
    note: str = ""     # optional user annotation

    def __post_init__(self) -> None:
        if self.category not in SPENDING_CATEGORIES:
            raise ValueError(
                f"Unknown category {self.category!r}. "
                f"Must be one of: {', '.join(SPENDING_CATEGORIES)}."
            )
        # Sanity-check the date but don't mutate — callers pass ISO.
        try:
            date.fromisoformat(self.date)
        except ValueError as e:
            raise ValueError(f"Transaction date must be ISO YYYY-MM-DD: {e}")

    @property
    def month(self) -> str:
        """e.g. '2026-02' — useful for grouping."""
        return self.date[:7]

    @property
    def is_expense(self) -> bool:
        return self.amount < 0

    @property
    def is_income(self) -> bool:
        return self.amount > 0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "Transaction":
        return cls(
            date=d["date"],
            account=d["account"],
            description=d.get("description", ""),
            amount=float(d["amount"]),
            category=d.get("category", "other"),
            source=d.get("source", ""),
            note=d.get("note", ""),
        )


@dataclass
class FinanceState:
    """The complete persisted state: debts, budget, accounts, transactions."""

    debts: list[Debt] = field(default_factory=list)
    budget: Budget = field(default_factory=Budget)
    consolidation_apr: float = 0.09  # configurable assumption for recommendations
    current_savings: float = 0.0  # liquid emergency fund balance
    accounts: list[Account] = field(default_factory=list)
    transactions: list[Transaction] = field(default_factory=list)

    def __post_init__(self) -> None:
        if self.current_savings < 0:
            raise ValueError(
                f"current_savings cannot be negative (got {self.current_savings})."
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "debts": [d.to_dict() for d in self.debts],
            "budget": self.budget.to_dict(),
            "consolidation_apr": self.consolidation_apr,
            "current_savings": self.current_savings,
            "accounts": [a.to_dict() for a in self.accounts],
            "transactions": [t.to_dict() for t in self.transactions],
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "FinanceState":
        return cls(
            debts=[Debt.from_dict(x) for x in d.get("debts", [])],
            budget=Budget.from_dict(d.get("budget", {})),
            consolidation_apr=float(d.get("consolidation_apr", 0.09)),
            current_savings=float(d.get("current_savings", 0.0)),
            accounts=[Account.from_dict(x) for x in d.get("accounts", [])],
            transactions=[
                Transaction.from_dict(x) for x in d.get("transactions", [])
            ],
        )

    def total_debt(self) -> float:
        return sum(d.balance for d in self.debts)

    def weighted_average_apr(self) -> float:
        total = self.total_debt()
        if total <= 0:
            return 0.0
        return sum(d.balance * d.apr for d in self.debts) / total

    def upsert_account(self, account: Account) -> None:
        """Add an account, or update the record if one by the same name
        already exists. Idempotent so repeated imports don't duplicate."""
        for i, existing in enumerate(self.accounts):
            if existing.name == account.name:
                self.accounts[i] = account
                return
        self.accounts.append(account)

    def add_transactions(self, txs: list[Transaction]) -> int:
        """Append transactions, skipping any (date, account, amount,
        description) duplicates of rows already on file. Returns the
        number newly inserted."""
        seen = {
            (t.date, t.account, round(t.amount, 2), t.description)
            for t in self.transactions
        }
        added = 0
        for t in txs:
            key = (t.date, t.account, round(t.amount, 2), t.description)
            if key in seen:
                continue
            self.transactions.append(t)
            seen.add(key)
            added += 1
        return added
