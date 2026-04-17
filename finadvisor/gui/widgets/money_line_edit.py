"""Money-entry widget built on QDoubleSpinBox."""
from __future__ import annotations

from PySide6.QtWidgets import QDoubleSpinBox


class MoneyLineEdit(QDoubleSpinBox):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setPrefix("$ ")
        self.setDecimals(2)
        self.setMaximum(1_000_000_000.0)
        self.setMinimum(0.0)
        self.setSingleStep(10.0)
        self.setGroupSeparatorShown(True)


class PercentLineEdit(QDoubleSpinBox):
    """Percent entry: user types 24.99, we store 0.2499."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setSuffix(" %")
        self.setDecimals(4)
        self.setMaximum(99.9999)
        self.setMinimum(0.0)
        self.setSingleStep(0.25)

    def setDecimalValue(self, v: float) -> None:
        self.setValue(v * 100.0)

    def decimalValue(self) -> float:
        return self.value() / 100.0
