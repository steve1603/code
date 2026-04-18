"""Core data model for debts and budget."""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Any


DEBT_KINDS = (
    "credit_card",
    "student_loan",
    "auto",
    "mortgage",
    "personal",
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
class FinanceState:
    """The complete persisted state: all debts plus a single budget."""

    debts: list[Debt] = field(default_factory=list)
    budget: Budget = field(default_factory=Budget)
    consolidation_apr: float = 0.09  # configurable assumption for recommendations
    current_savings: float = 0.0  # liquid emergency fund balance

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
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "FinanceState":
        return cls(
            debts=[Debt.from_dict(x) for x in d.get("debts", [])],
            budget=Budget.from_dict(d.get("budget", {})),
            consolidation_apr=float(d.get("consolidation_apr", 0.09)),
            current_savings=float(d.get("current_savings", 0.0)),
        )

    def total_debt(self) -> float:
        return sum(d.balance for d in self.debts)

    def weighted_average_apr(self) -> float:
        total = self.total_debt()
        if total <= 0:
            return 0.0
        return sum(d.balance * d.apr for d in self.debts) / total
