"""Budget page: income / expenses + live surplus display."""
from __future__ import annotations

from PySide6.QtWidgets import (
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from finadvisor.gui.widgets.money_line_edit import MoneyLineEdit, PercentLineEdit
from finadvisor.models import Budget


class BudgetPage(QWidget):
    def __init__(self, window) -> None:
        super().__init__()
        self.window_ = window

        root = QVBoxLayout(self)
        root.setContentsMargins(24, 24, 24, 24)
        root.setSpacing(12)

        title = QLabel("Budget")
        title.setObjectName("pageTitle")
        root.addWidget(title)

        subtitle = QLabel(
            "Tell us your monthly income and your non-debt expenses (rent, "
            "food, utilities, etc.). We'll figure out how much is left to "
            "throw at debt."
        )
        subtitle.setWordWrap(True)
        root.addWidget(subtitle)

        form = QFormLayout()
        self.income = MoneyLineEdit()
        self.expenses = MoneyLineEdit()
        self.savings = MoneyLineEdit()
        self.consolidation = PercentLineEdit()
        self.consolidation.setMaximum(40.0)
        form.addRow("Monthly income (take-home)", self.income)
        form.addRow("Monthly expenses (excl. debt)", self.expenses)
        form.addRow("Current emergency savings", self.savings)
        form.addRow("Assumed consolidation APR", self.consolidation)
        root.addLayout(form)

        self.surplus_label = QLabel()
        self.surplus_label.setObjectName("sectionTitle")
        root.addWidget(self.surplus_label)

        buttons = QHBoxLayout()
        buttons.addStretch(1)
        self.save_btn = QPushButton("Save")
        buttons.addWidget(self.save_btn)
        root.addLayout(buttons)
        root.addStretch(1)

        # Wiring
        self.income.valueChanged.connect(self._update_surplus)
        self.expenses.valueChanged.connect(self._update_surplus)
        self.save_btn.clicked.connect(self._on_save)

        self.refresh()

    def refresh(self) -> None:
        b = self.window_.state.budget
        self.income.setValue(b.monthly_income)
        self.expenses.setValue(b.monthly_expenses)
        self.savings.setValue(self.window_.state.current_savings)
        self.consolidation.setDecimalValue(self.window_.state.consolidation_apr)
        self._update_surplus()

    def _update_surplus(self) -> None:
        total_minimums = sum(d.min_payment for d in self.window_.state.debts)
        surplus = self.income.value() - self.expenses.value() - total_minimums
        if surplus >= 0:
            self.surplus_label.setText(
                f"After expenses and minimum debt payments "
                f"(${total_minimums:,.2f}/mo), you have roughly "
                f"${surplus:,.2f}/mo to apply toward extra debt payoff."
            )
        else:
            self.surplus_label.setText(
                f"⚠️ You're ${-surplus:,.2f}/mo short after expenses and "
                f"minimum debt payments. See the Analysis → Budget tab."
            )

    def _on_save(self) -> None:
        self.window_.state.budget = Budget(
            monthly_income=self.income.value(),
            monthly_expenses=self.expenses.value(),
        )
        self.window_.state.current_savings = self.savings.value()
        self.window_.state.consolidation_apr = self.consolidation.decimalValue()
        self.window_.mark_dirty()
