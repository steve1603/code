"""Dialog for adding / editing a single Debt."""
from __future__ import annotations

from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLineEdit,
    QMessageBox,
    QSpinBox,
)

from finadvisor.gui.widgets.money_line_edit import MoneyLineEdit, PercentLineEdit
from finadvisor.models import DEBT_KINDS, Debt


class EditDebtDialog(QDialog):
    def __init__(self, parent=None, debt: Debt | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Edit Debt" if debt else "Add Debt")
        self.setMinimumWidth(420)

        self.name_edit = QLineEdit()
        self.kind_combo = QComboBox()
        for k in DEBT_KINDS:
            self.kind_combo.addItem(k.replace("_", " ").title(), k)
        self.balance_edit = MoneyLineEdit()
        self.apr_edit = PercentLineEdit()
        self.min_payment_edit = MoneyLineEdit()
        self.credit_limit_edit = MoneyLineEdit()
        self.due_day_edit = QSpinBox()
        self.due_day_edit.setRange(0, 31)  # 0 means "not set"
        self.due_day_edit.setSpecialValueText("—")

        form = QFormLayout(self)
        form.addRow("Name", self.name_edit)
        form.addRow("Type", self.kind_combo)
        form.addRow("Current balance", self.balance_edit)
        form.addRow("APR", self.apr_edit)
        form.addRow("Minimum payment (monthly)", self.min_payment_edit)
        form.addRow("Credit limit (cards only)", self.credit_limit_edit)
        form.addRow("Due day (1–31)", self.due_day_edit)

        self.buttons = QDialogButtonBox(
            QDialogButtonBox.Save | QDialogButtonBox.Cancel
        )
        self.buttons.accepted.connect(self._on_accept)
        self.buttons.rejected.connect(self.reject)
        form.addRow(self.buttons)

        if debt is not None:
            self._load_debt(debt)

        self._result_debt: Debt | None = None
        self.kind_combo.currentTextChanged.connect(self._update_limit_enabled)
        self._update_limit_enabled()

    def _load_debt(self, debt: Debt) -> None:
        self.name_edit.setText(debt.name)
        idx = self.kind_combo.findData(debt.kind)
        if idx >= 0:
            self.kind_combo.setCurrentIndex(idx)
        self.balance_edit.setValue(debt.balance)
        self.apr_edit.setDecimalValue(debt.apr)
        self.min_payment_edit.setValue(debt.min_payment)
        self.credit_limit_edit.setValue(debt.credit_limit or 0.0)
        self.due_day_edit.setValue(debt.due_day or 0)

    def _update_limit_enabled(self) -> None:
        kind = self.kind_combo.currentData()
        is_card = kind == "credit_card"
        self.credit_limit_edit.setEnabled(is_card)
        if not is_card:
            self.credit_limit_edit.setValue(0.0)

    def _on_accept(self) -> None:
        try:
            name = self.name_edit.text().strip()
            credit_limit = self.credit_limit_edit.value()
            due_day = self.due_day_edit.value()
            self._result_debt = Debt(
                name=name,
                kind=self.kind_combo.currentData(),
                balance=self.balance_edit.value(),
                apr=self.apr_edit.decimalValue(),
                min_payment=self.min_payment_edit.value(),
                credit_limit=credit_limit if credit_limit > 0 else None,
                due_day=due_day if due_day > 0 else None,
            )
        except ValueError as e:
            QMessageBox.warning(self, "Invalid input", str(e))
            return
        self.accept()

    def debt(self) -> Debt | None:
        return self._result_debt
