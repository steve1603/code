"""Flag debts that a lower-rate consolidation/refinance loan could beat."""
from __future__ import annotations

from finadvisor.models import Budget, Debt, FinanceState
from finadvisor.strategies.base import Severity, StrategyResult


def _money(x: float) -> str:
    return f"${x:,.2f}"


def run(debts: list[Debt], budget: Budget, state: FinanceState) -> StrategyResult:
    if not debts:
        return StrategyResult(
            title="Consolidation / refinance",
            summary="No debts on file — nothing to consolidate.",
            severity=Severity.GOOD,
        )

    target_apr = state.consolidation_apr
    candidates = [d for d in debts if d.apr > target_apr + 0.005]

    if not candidates:
        return StrategyResult(
            title="Consolidation / refinance",
            summary=(
                f"None of your debts carry an APR above the assumed "
                f"consolidation rate of {target_apr * 100:.2f}%. No refinance "
                f"opportunity jumps out."
            ),
            severity=Severity.GOOD,
            recommendations=[
                "Still worth shopping rates every ~12 months as your credit improves."
            ],
        )

    # Rough savings estimate: assume the user keeps paying the same
    # monthly amount, so the savings ≈ (rate diff) × balance × 1 year
    # for a simple one-year snapshot. This is a conservative back-of-the-
    # envelope number, not an exact amortization.
    flagged = []
    total_annual_saving = 0.0
    for d in sorted(candidates, key=lambda d: -d.apr):
        rate_diff = d.apr - target_apr
        annual_saving = rate_diff * d.balance
        total_annual_saving += annual_saving
        flagged.append(
            f"**{d.name}** at {d.apr * 100:.2f}% → could save roughly "
            f"{_money(annual_saving)}/yr at {target_apr * 100:.2f}%."
        )

    summary = (
        f"{len(candidates)} debt(s) carry interest well above the assumed "
        f"consolidation rate of {target_apr * 100:.2f}%. Refinancing or "
        f"consolidating them could save ~{_money(total_annual_saving)} per "
        f"year in interest."
    )
    severity = Severity.WARN if total_annual_saving > 200 else Severity.INFO

    recs = flagged + [
        "Check balance-transfer credit cards (0% intro APR) for high-rate cards.",
        "Shop personal-loan rates from your bank, credit union, and online lenders.",
        "Watch for origination fees and prepayment penalties — they can erase the savings.",
    ]

    return StrategyResult(
        title="Consolidation / refinance",
        summary=summary,
        recommendations=recs,
        severity=severity,
        metrics={
            "candidate_count": float(len(candidates)),
            "estimated_annual_saving": total_annual_saving,
        },
    )
