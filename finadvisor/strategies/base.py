"""Shared data structures for strategy output."""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class Severity(str, Enum):
    INFO = "info"
    GOOD = "good"
    WARN = "warn"
    URGENT = "urgent"


@dataclass
class StrategyResult:
    title: str
    summary: str
    recommendations: list[str] = field(default_factory=list)
    severity: Severity = Severity.INFO
    # Optional monthly schedule: list of {"month": int, "total_balance": float,
    # "interest_paid": float, "per_debt": {debt_name: balance}}
    schedule: list[dict[str, Any]] = field(default_factory=list)
    # Summary numbers for dashboard display
    metrics: dict[str, float] = field(default_factory=dict)
