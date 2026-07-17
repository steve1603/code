"""Emergency fund strategy: advise on liquid savings vs. aggressive payoff.

The usual ordering: a small starter buffer first (so a flat tire doesn't
force you back onto a credit card), then attack high-APR debt, then build
the full 3-6 month fund once debt is under control.
"""
from __future__ import annotations

from finadvisor.models import Budget, Debt, FinanceState
from finadvisor.strategies.base import Severity, StrategyResult


STARTER_FUND = 1_000.0
HIGH_APR_THRESHOLD = 0.10


def _money(x: float) -> str:
    return f"${x:,.2f}"


def run(debts: list[Debt], budget: Budget, state: FinanceState) -> StrategyResult:
    savings = state.current_savings
    monthly_need = budget.monthly_expenses + sum(d.min_payment for d in debts)
    has_high_apr = any(d.apr >= HIGH_APR_THRESHOLD and d.balance > 0 for d in debts)

    # Without a meaningful monthly-need figure we can still advise on the
    # starter fund.
    if monthly_need <= 0:
        if savings >= STARTER_FUND:
            return StrategyResult(
                title="Emergency fund",
                summary=(
                    f"You have {_money(savings)} in savings. Add your monthly "
                    f"expenses on the Budget tab so we can size your full "
                    f"emergency fund target (3–6 months of essentials)."
                ),
                recommendations=[
                    "Enter monthly income and expenses on the Budget tab.",
                ],
                severity=Severity.INFO,
                metrics={"savings": savings, "starter_target": STARTER_FUND},
            )
        return StrategyResult(
            title="Emergency fund",
            summary=(
                f"You have {_money(savings)} set aside. Aim for a "
                f"{_money(STARTER_FUND)} starter emergency fund before "
                f"accelerating debt payoff — it keeps a surprise expense "
                f"from landing on a credit card."
            ),
            recommendations=[
                f"Build a {_money(STARTER_FUND)} starter fund in a separate "
                f"high-yield savings account.",
                "Fill in your monthly expenses on the Budget tab so we can "
                "size the full 3–6 month target.",
            ],
            severity=Severity.WARN,
            metrics={"savings": savings, "starter_target": STARTER_FUND},
        )

    three_month_target = 3 * monthly_need
    six_month_target = 6 * monthly_need
    months_covered = savings / monthly_need if monthly_need else 0.0

    if savings < STARTER_FUND:
        shortfall = STARTER_FUND - savings
        summary = (
            f"You have {_money(savings)} in savings — below the "
            f"{_money(STARTER_FUND)} starter fund that protects you from "
            f"taking on new debt for small emergencies."
        )
        recs = [
            f"Save {_money(shortfall)} to hit the starter fund before paying "
            f"extra on debt.",
        ]
        if has_high_apr:
            recs.append(
                "Once the starter fund is in place, pause additional savings "
                "and pour the surplus into high-APR debt — the interest saved "
                "beats the interest earned in savings."
            )
        else:
            recs.append(
                "After the starter fund, split surplus roughly 50/50 between "
                "savings and debt until you reach 3 months of expenses."
            )
        severity = Severity.URGENT if has_high_apr else Severity.WARN
    elif savings < three_month_target:
        shortfall = three_month_target - savings
        summary = (
            f"Starter fund secured ({_money(savings)}, about "
            f"{months_covered:.1f} months of essentials). Keep building toward "
            f"a full 3-month cushion of {_money(three_month_target)}."
        )
        recs: list[str] = []
        if has_high_apr:
            recs.append(
                "With high-APR debt outstanding, keep the starter fund but "
                "route surplus to debt until those balances are gone."
            )
            recs.append(
                f"Once high-APR debt is paid, resume savings to reach "
                f"{_money(three_month_target)} (3 months of essentials)."
            )
            severity = Severity.WARN
        else:
            recs.append(
                f"Save the remaining {_money(shortfall)} to reach 3 months of "
                f"essentials before accelerating lower-APR debt."
            )
            recs.append(
                "A rough split: 60% to savings, 40% to extra debt payments "
                "until you hit 3 months."
            )
            severity = Severity.INFO
    elif savings < six_month_target:
        shortfall = six_month_target - savings
        summary = (
            f"Solid 3-month cushion ({_money(savings)}, about "
            f"{months_covered:.1f} months of essentials). The next milestone "
            f"is a 6-month fund of {_money(six_month_target)}."
        )
        recs = [
            f"Add {_money(shortfall)} to reach a full 6-month emergency fund.",
            "Prioritize any remaining high-APR debt alongside savings.",
        ]
        severity = Severity.GOOD
    else:
        summary = (
            f"Excellent: {_money(savings)} in savings — roughly "
            f"{months_covered:.1f} months of expenses covered. Your emergency "
            f"fund is fully funded."
        )
        recs = [
            "Redirect surplus to extra debt payments, then to retirement "
            "or long-term investing.",
            "Keep the fund in a high-yield savings account, not checking.",
        ]
        severity = Severity.GOOD

    return StrategyResult(
        title="Emergency fund",
        summary=summary,
        recommendations=recs,
        severity=severity,
        metrics={
            "savings": savings,
            "starter_target": STARTER_FUND,
            "three_month_target": three_month_target,
            "six_month_target": six_month_target,
            "months_covered": months_covered,
        },
    )
