"""Dashboard: at-a-glance totals + 'Next best action'."""
from __future__ import annotations

from datetime import date

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFrame,
    QGridLayout,
    QLabel,
    QVBoxLayout,
    QWidget,
)

from finadvisor.report import run_all
from finadvisor.strategies._simulate import MAX_MONTHS


class _Card(QFrame):
    def __init__(self, title: str) -> None:
        super().__init__()
        self.setObjectName("card")
        layout = QVBoxLayout(self)
        self.title = QLabel(title.upper())
        self.title.setObjectName("cardTitle")
        self.value = QLabel("—")
        self.value.setObjectName("cardValue")
        self.value.setWordWrap(True)
        layout.addWidget(self.title)
        layout.addWidget(self.value)
        layout.addStretch(1)

    def set_value(self, text: str) -> None:
        self.value.setText(text)


class DashboardPage(QWidget):
    def __init__(self, window) -> None:
        super().__init__()
        self.window_ = window

        root = QVBoxLayout(self)
        root.setContentsMargins(24, 24, 24, 24)
        root.setSpacing(16)

        title = QLabel("Dashboard")
        title.setObjectName("pageTitle")
        root.addWidget(title)

        self.next_action = QLabel()
        self.next_action.setObjectName("nextAction")
        self.next_action.setWordWrap(True)
        root.addWidget(self.next_action)

        grid = QGridLayout()
        grid.setSpacing(16)
        self.card_total = _Card("Total debt")
        self.card_apr = _Card("Weighted APR")
        self.card_dti = _Card("Debt-to-income")
        self.card_payoff = _Card("Avalanche payoff")
        self.card_emergency = _Card("Emergency fund")
        self.card_savings = _Card("Interest saved vs. Snowball")
        grid.addWidget(self.card_total, 0, 0)
        grid.addWidget(self.card_apr, 0, 1)
        grid.addWidget(self.card_dti, 0, 2)
        grid.addWidget(self.card_payoff, 1, 0)
        grid.addWidget(self.card_emergency, 1, 1)
        grid.addWidget(self.card_savings, 1, 2)
        root.addLayout(grid)

        tip = QLabel(
            "💡 All data is stored locally on your computer. This app does "
            "not send anything over the network."
        )
        tip.setWordWrap(True)
        tip.setAlignment(Qt.AlignLeft)
        root.addStretch(1)
        root.addWidget(tip)

        self.refresh()

    def refresh(self) -> None:
        state = self.window_.state
        if not state.debts:
            self.next_action.setText(
                "Welcome! Head to the Debts tab to add your first debt — via "
                "the Add button, a CSV file, or a PDF statement."
            )
            self.card_total.set_value("$0.00")
            self.card_apr.set_value("—")
            self.card_dti.set_value("—")
            self.card_payoff.set_value("—")
            self.card_emergency.set_value(f"${state.current_savings:,.0f}")
            self.card_savings.set_value("—")
            return

        report = run_all(state)
        self.next_action.setText(f"Next best action:  {report.next_best_action}")

        self.card_total.set_value(f"${state.total_debt():,.2f}")
        self.card_apr.set_value(f"{state.weighted_average_apr() * 100:.2f}%")

        total_minimums = sum(d.min_payment for d in state.debts)
        if state.budget.monthly_income > 0:
            dti = total_minimums / state.budget.monthly_income
            self.card_dti.set_value(f"{dti * 100:.1f}%")
        else:
            self.card_dti.set_value("set budget")

        avalanche_r = next(
            (r for r in report.results if r.title.startswith("Avalanche")),
            None,
        )
        if avalanche_r and avalanche_r.metrics.get("months_to_payoff"):
            months = int(avalanche_r.metrics["months_to_payoff"])
            if months >= MAX_MONTHS:
                self.card_payoff.set_value("never at current rate")
            else:
                y, m = divmod(months, 12)
                duration = (
                    f"{y}y {m}m" if y and m else f"{y}y" if y else f"{m}m"
                )
                today = date.today()
                # Approximate calendar math: add months exactly.
                year = today.year + (today.month - 1 + months) // 12
                month = (today.month - 1 + months) % 12 + 1
                free_by = date(year, month, 1).strftime("%b %Y")
                self.card_payoff.set_value(f"{duration}  (by {free_by})")
        else:
            self.card_payoff.set_value("—")

        emergency_r = next(
            (r for r in report.results if r.title == "Emergency fund"), None,
        )
        if emergency_r:
            months_covered = emergency_r.metrics.get("months_covered", 0.0)
            label = f"${state.current_savings:,.0f}"
            if months_covered > 0:
                label += f"  ({months_covered:.1f} mo)"
            self.card_emergency.set_value(label)
        else:
            self.card_emergency.set_value(f"${state.current_savings:,.0f}")

        snowball_r = next(
            (r for r in report.results if r.title.startswith("Snowball")), None,
        )
        if (
            avalanche_r and snowball_r
            and "total_interest" in avalanche_r.metrics
            and "total_interest" in snowball_r.metrics
        ):
            delta = (
                snowball_r.metrics["total_interest"]
                - avalanche_r.metrics["total_interest"]
            )
            self.card_savings.set_value(f"${max(delta, 0):,.0f}")
        else:
            self.card_savings.set_value("—")
