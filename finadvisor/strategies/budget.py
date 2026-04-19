"""Budget / cashflow check: ensure debt service is sustainable."""
from __future__ import annotations

from finadvisor.models import Budget, Debt, FinanceState
from finadvisor.strategies.base import Severity, StrategyResult


def _money(x: float) -> str:
    return f"${x:,.2f}"


def run(debts: list[Debt], budget: Budget, state: FinanceState) -> StrategyResult:
    recs: list[str] = []
    if budget.monthly_income <= 0:
        return StrategyResult(
            title="Budget / cashflow",
            summary=(
                "You haven't set a monthly income yet. Head to the Budget tab "
                "so the advisor can tell you how much extra to put toward debt."
            ),
            recommendations=["Enter your monthly income and expenses."],
            severity=Severity.WARN,
        )

    total_minimums = sum(d.min_payment for d in debts)
    surplus = budget.extra_payment_capacity(debts)
    dti = total_minimums / budget.monthly_income if budget.monthly_income else 0.0

    # Negative amortization: if a debt's minimum payment doesn't even cover
    # its monthly interest, the balance grows forever at that payment level.
    # This is the single most destructive pattern a consumer can be in, so we
    # escalate to URGENT regardless of other cashflow signals.
    underwater = [
        d for d in debts
        if d.balance > 0 and d.min_payment < d.balance * d.apr / 12.0
    ]
    if underwater:
        names = ", ".join(d.name for d in underwater)
        monthly_interest_owed = sum(
            d.balance * d.apr / 12.0 for d in underwater
        )
        summary = (
            f"Negative amortization on {len(underwater)} debt(s): {names}. "
            f"Their minimum payments don't cover {_money(monthly_interest_owed)} "
            f"in monthly interest, so the balances grow every month even if "
            f"you pay exactly the minimum."
        )
        recs = [
            f"Treat {names} as emergencies — any extra dollar above the "
            f"minimum reduces the balance, nothing below does.",
            "Call the lender to request a hardship reduction or switch to "
            "a fixed payoff plan.",
            "Consider a lower-APR consolidation loan for these balances "
            "specifically (see the Consolidation tab).",
        ]
        return StrategyResult(
            title="Budget / cashflow",
            summary=summary,
            recommendations=recs,
            severity=Severity.URGENT,
            metrics={
                "dti": dti,
                "surplus": surplus,
                "total_minimums": total_minimums,
                "underwater_debts": float(len(underwater)),
            },
        )

    if surplus < 0:
        summary = (
            f"You're short {_money(-surplus)} per month — even paying just "
            f"the minimums on your debts would leave you in the red. This is "
            f"the single most important thing to fix."
        )
        recs = [
            "Trim non-essential expenses (subscriptions, dining out, delivery).",
            "Call each lender and ask about hardship or forbearance programs.",
            "Look into a balance-transfer card or consolidation loan to lower minimums.",
            "Consider a short-term side income to close the gap.",
        ]
        severity = Severity.URGENT
    elif dti > 0.40:
        summary = (
            f"Your minimum payments consume {dti * 100:.1f}% of your income — "
            f"above the 40% debt-to-income threshold lenders watch for. "
            f"You have ~{_money(surplus)}/month in surplus."
        )
        recs = [
            f"Direct your {_money(surplus)} surplus to the Avalanche target.",
            "Avoid adding new debt until your DTI drops below 35%.",
            "Consider consolidation to lower monthly minimums.",
        ]
        severity = Severity.WARN
    elif surplus < 50:
        summary = (
            f"Cashflow is tight — only {_money(surplus)}/month above minimums. "
            f"Debt-to-income is {dti * 100:.1f}%, which is manageable but "
            f"leaves no buffer for surprises."
        )
        recs = [
            "Aim for $500–$1,000 in an emergency buffer before accelerating payoff.",
            f"Put the {_money(surplus)} surplus toward the highest-APR debt.",
        ]
        severity = Severity.WARN
    else:
        summary = (
            f"Healthy cashflow: {_money(surplus)}/month above minimums, and "
            f"debt payments are {dti * 100:.1f}% of income. You can safely "
            f"accelerate debt payoff."
        )
        recs = [
            f"Send {_money(surplus)}/month extra to the Avalanche target debt.",
            "Maintain a 3–6 month emergency fund alongside debt payoff.",
        ]
        severity = Severity.GOOD

    return StrategyResult(
        title="Budget / cashflow",
        summary=summary,
        recommendations=recs,
        severity=severity,
        metrics={
            "dti": dti,
            "surplus": surplus,
            "total_minimums": total_minimums,
        },
    )
