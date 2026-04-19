"""Long-term savings / retirement guidance.

Follows the canonical personal-finance ordering:
  1. Starter emergency fund ($1k)
  2. 401(k) up to the employer match (free money)
  3. High-APR debt (>10%)
  4. Full 3-6 month emergency fund
  5. Max out Roth IRA
  6. Max 401(k) and taxable investing

The advisor doesn't know the user's employer match or current retirement
contributions, so this tab is intentionally advisory — it tells the user
which stage they're in and what their next dollar should fund.
"""
from __future__ import annotations

from finadvisor.models import Budget, Debt, FinanceState
from finadvisor.strategies.base import Severity, StrategyResult
from finadvisor.strategies.emergency_fund import STARTER_FUND, HIGH_APR_THRESHOLD


def _money(x: float) -> str:
    return f"${x:,.2f}"


def run(debts: list[Debt], budget: Budget, state: FinanceState) -> StrategyResult:
    savings = state.current_savings
    monthly_need = budget.monthly_expenses + sum(d.min_payment for d in debts)
    has_high_apr = any(
        d.apr >= HIGH_APR_THRESHOLD and d.balance > 0 for d in debts
    )
    three_month = 3 * monthly_need if monthly_need > 0 else float("inf")

    if savings < STARTER_FUND:
        stage = 1
        summary = (
            f"You're at stage 1 of the savings ladder: build the "
            f"{_money(STARTER_FUND)} starter emergency fund before any "
            f"long-term investing. Losing a paycheck or a car repair at "
            f"this stage will land on a credit card."
        )
        recs = [
            f"Focus all surplus on reaching {_money(STARTER_FUND)} in "
            f"liquid savings.",
            "Exception: if your employer matches 401(k) contributions, "
            "contribute at least enough to capture the full match — that's "
            "an instant 50-100% return no debt strategy can beat.",
        ]
        severity = Severity.WARN
    elif has_high_apr:
        stage = 2
        summary = (
            "Stage 2: starter fund is in place, but high-APR debt still "
            "beats most investment returns. Clear it before investing extra, "
            "while continuing to capture any employer 401(k) match."
        )
        recs = [
            "Contribute to 401(k) up to the employer match, no more.",
            f"Route every other spare dollar to debt with APR above "
            f"{HIGH_APR_THRESHOLD * 100:.0f}% (see Avalanche tab).",
            "Re-evaluate long-term investing once high-APR debt is gone.",
        ]
        severity = Severity.INFO
    elif savings < three_month:
        stage = 3
        shortfall = three_month - savings
        summary = (
            f"Stage 3: high-APR debt cleared (nice work). Build savings to "
            f"3 months of essentials ({_money(three_month)}) before "
            f"ramping retirement past the match. Shortfall: {_money(shortfall)}."
        )
        recs = [
            "Keep contributing to the employer 401(k) match.",
            f"Direct the rest to cash savings until you hit "
            f"{_money(three_month)}.",
            "Then redirect to Roth IRA (tax-advantaged).",
        ]
        severity = Severity.INFO
    else:
        stage = 4
        summary = (
            f"Stage 4+: strong safety net ({_money(savings)} in savings, "
            f"about {savings / monthly_need:.1f} months covered) and no "
            f"high-APR debt. Time to optimize long-term wealth."
        )
        recs = [
            "Max out a Roth IRA each year (2026 limit: $7,000, or $8,000 "
            "if age 50+).",
            "Increase 401(k) contributions past the match toward the "
            "annual limit.",
            "Any lower-APR debt (mortgage, student loans below 5%) is "
            "generally okay to carry alongside investing.",
            "Consider a taxable brokerage account for goals that don't "
            "fit retirement buckets.",
        ]
        severity = Severity.GOOD

    return StrategyResult(
        title="Long-term savings",
        summary=summary,
        recommendations=recs,
        severity=severity,
        metrics={
            "stage": float(stage),
            "savings": savings,
            "has_high_apr_debt": 1.0 if has_high_apr else 0.0,
        },
    )
