"""Credit-card utilization analyzer."""
from __future__ import annotations

from finadvisor.models import Budget, Debt, FinanceState
from finadvisor.strategies.base import Severity, StrategyResult


def _money(x: float) -> str:
    return f"${x:,.2f}"


def run(debts: list[Debt], budget: Budget, state: FinanceState) -> StrategyResult:
    cards = [
        d for d in debts
        if d.kind == "credit_card" and d.credit_limit and d.credit_limit > 0
    ]

    if not cards:
        return StrategyResult(
            title="Credit utilization",
            summary=(
                "No credit cards with a known credit limit on file. Add the "
                "credit limit to each card in the Debts tab to get utilization "
                "insights."
            ),
            severity=Severity.INFO,
        )

    total_balance = sum(c.balance for c in cards)
    total_limit = sum(c.credit_limit or 0.0 for c in cards)
    overall = total_balance / total_limit if total_limit else 0.0

    urgent = [c for c in cards if c.utilization and c.utilization > 0.70]
    warn = [
        c for c in cards
        if c.utilization and 0.30 < c.utilization <= 0.70
    ]
    healthy = [c for c in cards if c.utilization and c.utilization <= 0.30]

    recs: list[str] = []
    for c in sorted(urgent + warn, key=lambda d: -(d.utilization or 0)):
        target_balance = 0.30 * (c.credit_limit or 0.0)
        paydown = max(0.0, c.balance - target_balance)
        recs.append(
            f"**{c.name}** is at {c.utilization * 100:.1f}% utilization. "
            f"Pay down {_money(paydown)} to reach the 30% threshold."
        )
    for c in healthy:
        recs.append(
            f"{c.name}: {c.utilization * 100:.1f}% — healthy. Keep it there."
        )
    recs.append(
        "Credit scores weigh per-card AND overall utilization. Below 30% is "
        "the common rule of thumb; below 10% is best."
    )

    if urgent:
        severity = Severity.URGENT
        summary = (
            f"{len(urgent)} card(s) above 70% utilization — a major drag on "
            f"your credit score and a sign of over-reliance on revolving "
            f"credit. Overall utilization is {overall * 100:.1f}%."
        )
    elif warn:
        severity = Severity.WARN
        summary = (
            f"{len(warn)} card(s) between 30% and 70% utilization. Paying "
            f"these under 30% will help your credit score. Overall "
            f"utilization is {overall * 100:.1f}%."
        )
    else:
        severity = Severity.GOOD
        summary = (
            f"All credit cards are under 30% utilization. Overall utilization "
            f"is {overall * 100:.1f}%. Nicely done."
        )

    breakdown = []
    for c in sorted(cards, key=lambda d: -(d.utilization or 0)):
        util = c.utilization or 0.0
        if util > 0.70:
            bar_sev = "urgent"
        elif util > 0.30:
            bar_sev = "warn"
        else:
            bar_sev = "good"
        breakdown.append({
            "label": c.name,
            "value": util * 100,
            "max": 100.0,
            "severity": bar_sev,
            "caption": (
                f"{_money(c.balance)} / {_money(c.credit_limit or 0)} "
                f"({util * 100:.1f}%)"
            ),
        })

    return StrategyResult(
        title="Credit utilization",
        summary=summary,
        recommendations=recs,
        severity=severity,
        metrics={
            "overall_utilization": overall,
            "cards_urgent": float(len(urgent)),
            "cards_warn": float(len(warn)),
        },
        breakdown=breakdown,
    )
