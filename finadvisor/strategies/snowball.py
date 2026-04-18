"""Snowball: put every extra dollar toward the smallest-balance debt."""
from __future__ import annotations

from finadvisor.models import Budget, Debt, FinanceState
from finadvisor.strategies._simulate import simulate
from finadvisor.strategies.base import Severity, StrategyResult


def _money(x: float) -> str:
    return f"${x:,.2f}"


def _years_months(months: int) -> str:
    y, m = divmod(months, 12)
    if y and m:
        return f"{y}y {m}m"
    if y:
        return f"{y}y"
    return f"{m}m"


def run(debts: list[Debt], budget: Budget, state: FinanceState) -> StrategyResult:
    if not debts:
        return StrategyResult(
            title="Snowball",
            summary="No debts on file — nothing to pay down.",
            severity=Severity.GOOD,
        )

    sim = simulate(debts, budget, target_order=lambda d: d.balance)
    target = min(debts, key=lambda d: d.balance)

    if sim.capped:
        summary = (
            "Snowball can't clear your debts with your current budget either. "
            "Revisit the Budget tab before choosing a payoff method."
        )
        severity = Severity.URGENT
    else:
        summary = (
            f"Knocking out your smallest debts first, you'd be debt-free in "
            f"{_years_months(sim.months_to_payoff)} "
            f"and pay {_money(sim.total_interest_paid)} in total interest. "
            f"Snowball usually costs more interest than Avalanche, but the "
            f"quick wins help many people stay motivated."
        )
        severity = Severity.INFO

    recs = [
        f"Focus every extra dollar on **{target.name}** "
        f"(balance {_money(target.balance)}) until it's paid off."
    ]
    payoff_order = sorted(debts, key=lambda d: d.balance)
    if len(payoff_order) > 1:
        order_str = " → ".join(d.name for d in payoff_order)
        recs.append(f"Payoff order: {order_str}.")

    if sim.first_debt_paid_off_name and sim.first_debt_paid_off_month:
        recs.append(
            f"First win: **{sim.first_debt_paid_off_name}** paid off in "
            f"{_years_months(sim.first_debt_paid_off_month)}."
        )

    return StrategyResult(
        title="Snowball (smallest balance first)",
        summary=summary,
        recommendations=recs,
        severity=severity,
        schedule=sim.schedule,
        metrics={
            "months_to_payoff": float(sim.months_to_payoff),
            "total_interest": sim.total_interest_paid,
            "total_principal": sim.total_principal_paid,
        },
    )
