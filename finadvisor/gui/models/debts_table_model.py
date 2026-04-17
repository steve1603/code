"""QAbstractTableModel wrapping a list[Debt]."""
from __future__ import annotations

from PySide6.QtCore import QAbstractTableModel, QModelIndex, Qt

from finadvisor.models import Debt


COLUMNS = [
    "Name",
    "Type",
    "Balance",
    "APR",
    "Min Payment",
    "Credit Limit",
    "Utilization",
]


class DebtsTableModel(QAbstractTableModel):
    def __init__(self, debts: list[Debt]) -> None:
        super().__init__()
        self._debts = debts

    def set_debts(self, debts: list[Debt]) -> None:
        self.beginResetModel()
        self._debts = debts
        self.endResetModel()

    # --- required overrides --------------------------------------------
    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:
        return 0 if parent.isValid() else len(self._debts)

    def columnCount(self, parent: QModelIndex = QModelIndex()) -> int:
        return 0 if parent.isValid() else len(COLUMNS)

    def headerData(self, section, orientation, role=Qt.DisplayRole):
        if role != Qt.DisplayRole:
            return None
        if orientation == Qt.Horizontal:
            return COLUMNS[section]
        return section + 1

    def data(self, index: QModelIndex, role: int = Qt.DisplayRole):
        if not index.isValid():
            return None
        d = self._debts[index.row()]
        col = index.column()

        if role == Qt.DisplayRole:
            if col == 0: return d.name
            if col == 1: return d.kind.replace("_", " ").title()
            if col == 2: return f"${d.balance:,.2f}"
            if col == 3: return f"{d.apr * 100:.2f}%"
            if col == 4: return f"${d.min_payment:,.2f}"
            if col == 5:
                return f"${d.credit_limit:,.2f}" if d.credit_limit else "—"
            if col == 6:
                u = d.utilization
                return f"{u * 100:.1f}%" if u is not None else "—"

        if role == Qt.TextAlignmentRole and col >= 2:
            return int(Qt.AlignRight | Qt.AlignVCenter)

        return None
