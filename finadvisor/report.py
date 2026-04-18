"""Aggregate all strategies into a single report."""
from __future__ import annotations

from dataclasses import dataclass

from finadvisor.models import FinanceState
from finadvisor.strategies import (
    avalanche,
    budget,
    consolidation,
    emergency_fund,
    snowball,
    utilization,
)
from finadvisor.strategies.base import Severity, StrategyResult


STRATEGY_MODULES = [
    avalanche,
    snowball,
    consolidation,
    budget,
    utilization,
    emergency_fund,
]

_SEVERITY_RANK = {
    Severity.URGENT: 3,
    Severity.WARN: 2,
    Severity.INFO: 1,
    Severity.GOOD: 0,
}


@dataclass
class Report:
    results: list[StrategyResult]
    next_best_action: str


def run_all(state: FinanceState) -> Report:
    """Run every strategy and return a combined Report."""
    results = [
        mod.run(state.debts, state.budget, state)
        for mod in STRATEGY_MODULES
    ]
    return Report(results=results, next_best_action=_pick_next_action(results))


def _pick_next_action(results: list[StrategyResult]) -> str:
    """Prioritize: utilization > budget > emergency fund > avalanche > consolidation > snowball."""
    priority = ["Credit utilization", "Budget / cashflow", "Emergency fund"]
    # Take the highest-severity result from the priority list; fall back to
    # highest-severity overall.
    by_title = {r.title: r for r in results}
    for title in priority:
        r = by_title.get(title)
        if r and _SEVERITY_RANK[r.severity] >= 2:  # WARN or URGENT
            return f"{r.title}: {r.summary}"

    avalanche_r = next(
        (r for r in results if r.title.startswith("Avalanche")), None
    )
    if avalanche_r and avalanche_r.recommendations:
        return f"{avalanche_r.title}: {avalanche_r.recommendations[0]}"

    # Fall back to the most severe message.
    ranked = sorted(results, key=lambda r: -_SEVERITY_RANK[r.severity])
    if ranked:
        return f"{ranked[0].title}: {ranked[0].summary}"
    return "Add some debts to get your first recommendation."


def to_text(report: Report) -> str:
    """Render the report as plain text (for Export Report…)."""
    lines: list[str] = []
    lines.append("=" * 72)
    lines.append("finadvisor — Personal Debt Report")
    lines.append("=" * 72)
    lines.append("")
    lines.append("Next best action:")
    lines.append(f"  → {report.next_best_action}")
    lines.append("")

    for r in report.results:
        lines.append("-" * 72)
        lines.append(f"{r.title}   [{r.severity.value.upper()}]")
        lines.append("-" * 72)
        lines.append(_wrap(r.summary, 72))
        if r.recommendations:
            lines.append("")
            for rec in r.recommendations:
                lines.append(f"  • {rec}")
        lines.append("")

    lines.append("-" * 72)
    lines.append(
        "Disclaimer: Educational tool only. Not licensed financial advice."
    )
    return "\n".join(lines)


def _wrap(text: str, width: int) -> str:
    import textwrap
    return "\n".join(textwrap.fill(p, width=width) for p in text.split("\n"))
