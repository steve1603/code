"""Recommendation strategies. Each module exposes run(debts, budget, state)."""
from finadvisor.strategies.base import StrategyResult, Severity

__all__ = ["StrategyResult", "Severity"]
