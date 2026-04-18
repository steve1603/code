"""Monthly amortization simulator shared by avalanche and snowball."""
from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any, Callable

from finadvisor.models import Budget, Debt

# Safety cap so a bad input can't produce an infinite loop.
MAX_MONTHS = 12 * 60  # 60 years


@dataclass
class SimulationResult:
    months_to_payoff: int  # 0 if already debt-free; MAX_MONTHS if capped
    total_interest_paid: float
    total_principal_paid: float
    schedule: list[dict[str, Any]]
    first_debt_paid_off_name: str | None
    first_debt_paid_off_month: int | None
    capped: bool


def _choose_target(order: Callable[[Debt], float], debts: list[Debt]) -> Debt | None:
    active = [d for d in debts if d.balance > 0.005]
    if not active:
        return None
    return min(active, key=order)


def simulate(
    debts: list[Debt],
    budget: Budget,
    target_order: Callable[[Debt], float],
) -> SimulationResult:
    """Simulate monthly payments.

    - Each debt accrues interest at apr/12 per month.
    - Minimum payments are applied to every debt.
    - Any extra capacity (budget minus expenses minus active minimums)
      is applied to the debt selected by `target_order` (smallest key wins).
    - target_order examples:
        * Avalanche:  lambda d: -d.apr
        * Snowball:   lambda d:  d.balance
    """
    # Work on copies so the caller's data is untouched.
    working = [replace(d) for d in debts]

    total_interest = 0.0
    total_principal = 0.0
    schedule: list[dict[str, Any]] = []
    first_paid_name: str | None = None
    first_paid_month: int | None = None

    for month in range(1, MAX_MONTHS + 1):
        active_before = [d for d in working if d.balance > 0.005]
        if not active_before:
            break

        # 1) Interest accrues.
        month_interest = 0.0
        for d in active_before:
            interest = d.balance * (d.apr / 12.0)
            d.balance += interest
            month_interest += interest
        total_interest += month_interest

        # 2) Each active debt pays its minimum (or its balance, whichever
        #    is smaller). Leftover min capacity is freed for the target.
        pool = 0.0  # cash recovered from already-paid-off debts' minimums
        for d in working:
            if d.balance <= 0.005:
                # Debt is paid off — its minimum is freed to the pool.
                pool += d.min_payment
                continue
            pay = min(d.min_payment, d.balance)
            d.balance -= pay
            total_principal += pay
            # If the minimum exceeded the balance, refund the leftover to pool.
            pool += max(0.0, d.min_payment - pay)

        # 3) Any remaining extra capacity plus the pool goes to the target.
        extra = budget.extra_payment_capacity(debts) + pool
        # Guard: extra may be negative if income doesn't cover minimums.
        if extra > 0:
            target = _choose_target(target_order, working)
            if target is not None:
                pay = min(extra, target.balance)
                target.balance -= pay
                total_principal += pay

        # 4) Record first-debt-paid-off milestone.
        if first_paid_name is None:
            newly_paid = [
                d for d in working
                if d.balance <= 0.005 and any(
                    orig.name == d.name and orig.balance > 0.005 for orig in debts
                )
            ]
            if newly_paid:
                # Pick the one with the smallest original balance to be deterministic.
                newly_paid.sort(key=lambda d: next(
                    o.balance for o in debts if o.name == d.name
                ))
                first_paid_name = newly_paid[0].name
                first_paid_month = month

        # 5) Log snapshot every 6 months (plus first + last).
        if month == 1 or month % 6 == 0:
            schedule.append({
                "month": month,
                "total_balance": sum(max(0.0, d.balance) for d in working),
                "interest_paid_this_month": month_interest,
                "per_debt": {d.name: max(0.0, d.balance) for d in working},
            })

        if all(d.balance <= 0.005 for d in working):
            schedule.append({
                "month": month,
                "total_balance": 0.0,
                "interest_paid_this_month": month_interest,
                "per_debt": {d.name: 0.0 for d in working},
            })
            return SimulationResult(
                months_to_payoff=month,
                total_interest_paid=total_interest,
                total_principal_paid=total_principal,
                schedule=schedule,
                first_debt_paid_off_name=first_paid_name,
                first_debt_paid_off_month=first_paid_month,
                capped=False,
            )

    # Hit cap — either negative cashflow or interest > minimums.
    return SimulationResult(
        months_to_payoff=MAX_MONTHS,
        total_interest_paid=total_interest,
        total_principal_paid=total_principal,
        schedule=schedule,
        first_debt_paid_off_name=first_paid_name,
        first_debt_paid_off_month=first_paid_month,
        capped=True,
    )
