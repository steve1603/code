"""Avalanche: put every extra dollar toward the highest-APR debt."""
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
            title="Avalanche",
            summary="No debts on file — nothing to pay down.",
            severity=Severity.GOOD,
        )

    sim = simulate(debts, budget, target_order=lambda d: -d.apr)
    target = max(debts, key=lambda d: d.apr)
    extra = budget.extra_payment_capacity(debts)

    if sim.capped:
        summary = (
            "Avalanche can't clear your debts with your current budget — your "
            "minimums outpace what you can pay each month. Lower expenses or "
            "increase income to make progress."
        )
        severity = Severity.URGENT
    else:
        summary = (
            f"By targeting the highest-APR debt first, you'd be debt-free in "
            f"{_years_months(sim.months_to_payoff)} "
            f"(~{sim.months_to_payoff} months) and pay "
            f"{_money(sim.total_interest_paid)} in total interest."
        )
        severity = Severity.INFO

    recs = [
        f"Focus every extra dollar on **{target.name}** "
        f"(APR {target.apr * 100:.2f}%) until it's paid off.",
    ]
    if extra > 0:
        recs.append(
            f"Apply ~{_money(extra)}/month above the minimums to the target debt."
        )
    else:
        recs.append(
            "You have no surplus above minimums right now — see the Budget tab."
        )
    # Order the rest.
    payoff_order = sorted(debts, key=lambda d: -d.apr)
    if len(payoff_order) > 1:
        order_str = " → ".join(d.name for d in payoff_order)
        recs.append(f"Payoff order: {order_str}.")

    if sim.first_debt_paid_off_name and sim.first_debt_paid_off_month:
        recs.append(
            f"First win: **{sim.first_debt_paid_off_name}** paid off in "
            f"{_years_months(sim.first_debt_paid_off_month)}."
        )

    return StrategyResult(
        title="Avalanche (highest interest first)",
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
