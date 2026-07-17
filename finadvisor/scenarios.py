"""What-if scenarios beyond the monthly strategies.

Three coach-style questions get concrete answers here:

- `stress_test`     — "What if I (or my partner) lost a job tomorrow?"
- `windfall_impact` — "What happens if I throw a lump sum at my debt?"
- `savings_ladder`  — "How far along the emergency-fund ladder am I?"

Everything is pure and Qt-free like the rest of the engine.
"""
from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Iterable

from finadvisor.models import Budget, Debt, Transaction
from finadvisor.spending import STARTER_EMERGENCY, derived_budget
from finadvisor.strategies._simulate import simulate


@dataclass
class StressTestResult:
    """Runway estimates if income stops."""

    monthly_essentials: float       # 3-mo avg non-debt spending
    total_minimums: float           # required debt payments
    monthly_burn: float             # essentials + minimums
    savings: float
    runway_months_full_loss: float  # savings / burn (all income gone)
    # Dual-income households: months sustainable if ONE income stops.
    # None means the remaining income still covers the burn (no runway
    # limit) — or the household has a single earner (scenario n/a).
    runway_months_one_income: float | None
    one_income_applicable: bool     # household_size >= 2 and income > 0
    headline: str
    notes: list[str] = field(default_factory=list)


def stress_test(
    transactions: Iterable[Transaction],
    debts: list[Debt],
    monthly_income: float = 0.0,
    current_savings: float = 0.0,
    household_size: int = 1,
) -> StressTestResult:
    """Estimate how long savings last if income stops.

    Burn rate = 3-month average essentials + every debt minimum.
    Full-loss runway divides savings by that burn. For households with
    two earners we also model losing one income: if half the income
    still covers the burn, the household is resilient; otherwise the
    monthly deficit eats savings at a slower (but nonzero) rate.
    """
    txs = list(transactions)
    income_avg, essentials, _debt_avg, n_months = derived_budget(txs)
    income = monthly_income if monthly_income > 0 else income_avg
    minimums = sum(d.min_payment for d in debts)
    burn = essentials + minimums

    notes: list[str] = []
    if n_months == 0:
        notes.append(
            "No transaction history yet — burn rate assumes only debt "
            "minimums. Import a statement for a real estimate."
        )

    runway_full = (current_savings / burn) if burn > 0 else float("inf")

    one_income_applicable = household_size >= 2 and income > 0
    runway_one: float | None = None
    if one_income_applicable:
        remaining = income / 2  # assume roughly equal earners
        deficit = burn - remaining
        if deficit > 0:
            runway_one = current_savings / deficit
            notes.append(
                f"If one income stopped, the household would run a "
                f"${deficit:,.0f}/mo deficit — savings cover about "
                f"{runway_one:.1f} month(s) of that gap."
            )
        else:
            notes.append(
                "One income alone still covers essentials and minimums "
                "— losing a single job would sting but not sink you."
            )

    if burn <= 0:
        headline = (
            "No burn rate on file yet — import a statement so the "
            "stress test can measure your monthly obligations."
        )
    elif runway_full >= 6:
        headline = (
            f"Solid: savings cover {runway_full:.1f} months of "
            f"essentials + minimums (${burn:,.0f}/mo) with zero income."
        )
    elif runway_full >= 3:
        headline = (
            f"OK: {runway_full:.1f} months of runway at "
            f"${burn:,.0f}/mo burn. Aim for 6 months for a two-person "
            f"household."
        )
    elif runway_full >= 1:
        headline = (
            f"Thin: only {runway_full:.1f} month(s) of runway at "
            f"${burn:,.0f}/mo burn. A single missed paycheck would "
            f"hurt — prioritize the emergency fund."
        )
    else:
        headline = (
            f"Critical: savings cover less than a month of the "
            f"${burn:,.0f}/mo burn. Build the ${STARTER_EMERGENCY:,.0f} "
            f"starter fund before any extra debt payments."
        )

    return StressTestResult(
        monthly_essentials=round(essentials, 2),
        total_minimums=round(minimums, 2),
        monthly_burn=round(burn, 2),
        savings=round(current_savings, 2),
        runway_months_full_loss=(
            round(runway_full, 1) if burn > 0 else float("inf")
        ),
        runway_months_one_income=(
            round(runway_one, 1) if runway_one is not None else None
        ),
        one_income_applicable=one_income_applicable,
        headline=headline,
        notes=notes,
    )


@dataclass
class WindfallResult:
    """Effect of applying a one-time lump sum to debt (avalanche order)."""

    lump: float
    baseline_months: int
    boosted_months: int
    months_saved: int
    baseline_interest: float
    boosted_interest: float
    interest_saved: float
    debts_cleared: list[str]        # debts the lump wipes out instantly
    headline: str


def windfall_impact(
    debts: list[Debt],
    budget: Budget,
    lump: float,
) -> WindfallResult | None:
    """Simulate a tax refund / bonus applied to debt immediately.

    The lump pays down balances in avalanche order (highest APR first,
    cascading to the next debt when one hits zero), then the normal
    avalanche payoff runs on what remains. Returns None when there's
    nothing to compare (no debts, or non-positive lump).
    """
    if lump <= 0 or not any(d.balance > 0 for d in debts):
        return None

    avalanche_order = lambda d: -d.apr  # noqa: E731 — matches strategies
    baseline = simulate(debts, budget, avalanche_order)

    remaining = lump
    cleared: list[str] = []
    boosted_debts: list[Debt] = []
    for d in sorted(debts, key=lambda d: d.apr, reverse=True):
        pay = min(remaining, d.balance)
        remaining -= pay
        new_balance = d.balance - pay
        if d.balance > 0 and new_balance <= 0.005:
            cleared.append(d.name)
        boosted_debts.append(replace(d, balance=max(0.0, new_balance)))

    if any(d.balance > 0.005 for d in boosted_debts):
        boosted = simulate(boosted_debts, budget, avalanche_order)
        boosted_months = boosted.months_to_payoff
        boosted_interest = boosted.total_interest_paid
    else:
        # Lump wipes everything — simulate() treats an already-empty
        # debt list as "capped", so short-circuit to zero here.
        boosted_months = 0
        boosted_interest = 0.0
    months_saved = max(0, baseline.months_to_payoff - boosted_months)
    interest_saved = max(
        0.0, baseline.total_interest_paid - boosted_interest
    )

    if boosted_months == 0:
        headline = (
            f"${lump:,.0f} wipes out every debt on the spot and saves "
            f"${interest_saved:,.0f} in interest."
        )
    else:
        cleared_phrase = (
            f" and immediately clears {', '.join(cleared)}"
            if cleared else ""
        )
        headline = (
            f"${lump:,.0f} toward your highest-APR debt saves "
            f"${interest_saved:,.0f} in interest and brings debt-free "
            f"day {months_saved} month(s) closer{cleared_phrase}."
        )

    return WindfallResult(
        lump=round(lump, 2),
        baseline_months=baseline.months_to_payoff,
        boosted_months=boosted_months,
        months_saved=months_saved,
        baseline_interest=round(baseline.total_interest_paid, 2),
        boosted_interest=round(boosted_interest, 2),
        interest_saved=round(interest_saved, 2),
        debts_cleared=cleared,
        headline=headline,
    )


@dataclass
class LadderRung:
    label: str
    target: float
    filled: float           # dollars counted toward this rung
    fraction: float         # 0..1 progress on this rung
    reached: bool


def savings_ladder(
    current_savings: float,
    monthly_essentials: float,
    household_size: int = 1,
) -> list[LadderRung]:
    """Progress along the emergency-fund ladder.

    Rungs: $1k starter → 3 months of essentials → the household target
    (6 months for 2+ people, 3 for a single earner — matching
    `_emergency_target`). Each rung's `filled` counts total savings
    against that rung's cumulative target, so a $5k balance shows the
    starter rung full and partial progress on the next.
    """
    rungs_spec: list[tuple[str, float]] = [
        ("Starter fund", STARTER_EMERGENCY),
    ]
    if monthly_essentials > 0:
        three_mo = monthly_essentials * 3
        rungs_spec.append(("3 months of essentials", three_mo))
        if household_size >= 2:
            rungs_spec.append(
                ("6 months (household target)", monthly_essentials * 6)
            )
    out: list[LadderRung] = []
    for label, target in rungs_spec:
        filled = min(current_savings, target)
        out.append(LadderRung(
            label=label,
            target=round(target, 2),
            filled=round(filled, 2),
            fraction=(filled / target) if target > 0 else 1.0,
            reached=current_savings >= target,
        ))
    return out
