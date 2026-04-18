"""Main window: sidebar + stacked pages."""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QHBoxLayout,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QStackedWidget,
    QStatusBar,
    QWidget,
)

from finadvisor import storage
from finadvisor.gui.pages.analysis_page import AnalysisPage
from finadvisor.gui.pages.budget_page import BudgetPage
from finadvisor.gui.pages.dashboard_page import DashboardPage
from finadvisor.gui.pages.debts_page import DebtsPage
from finadvisor.models import FinanceState


class MainWindow(QMainWindow):
    state_changed = Signal()

    def __init__(self, store_path: Path | None = None) -> None:
        super().__init__()
        self.setWindowTitle("finadvisor — Personal Debt Advisor")
        self.resize(1100, 720)

        self.store_path = store_path or storage.DEFAULT_STORE
        self.state: FinanceState = storage.load(self.store_path)

        self._build_ui()

        # Whenever any page mutates self.state, it emits state_changed; we
        # persist and ask every page to refresh.
        self.state_changed.connect(self._on_state_changed)

    # --- layout ---------------------------------------------------------
    def _build_ui(self) -> None:
        central = QWidget()
        layout = QHBoxLayout(central)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self.sidebar = QListWidget()
        self.sidebar.setObjectName("sidebar")
        self.sidebar.setFixedWidth(200)
        for label in ("Dashboard", "Debts", "Budget", "Analysis"):
            item = QListWidgetItem(label)
            item.setTextAlignment(Qt.AlignLeft | Qt.AlignVCenter)
            self.sidebar.addItem(item)

        self.pages = QStackedWidget()
        self.dashboard_page = DashboardPage(self)
        self.debts_page = DebtsPage(self)
        self.budget_page = BudgetPage(self)
        self.analysis_page = AnalysisPage(self)
        self.pages.addWidget(self.dashboard_page)
        self.pages.addWidget(self.debts_page)
        self.pages.addWidget(self.budget_page)
        self.pages.addWidget(self.analysis_page)

        self.sidebar.currentRowChanged.connect(self._on_nav)
        self.sidebar.setCurrentRow(0)

        layout.addWidget(self.sidebar)
        layout.addWidget(self.pages, 1)
        self.setCentralWidget(central)

        status = QStatusBar()
        self.setStatusBar(status)
        self._update_statusbar()

    def _on_nav(self, row: int) -> None:
        self.pages.setCurrentIndex(row)
        # Re-render the page whenever the user navigates to it — cheap.
        widget = self.pages.currentWidget()
        if hasattr(widget, "refresh"):
            widget.refresh()

    def _update_statusbar(self) -> None:
        self.statusBar().showMessage(f"Data file: {Path(self.store_path).resolve()}")

    # --- state mutation helpers (called by pages) -----------------------
    def mark_dirty(self) -> None:
        """Pages call this after mutating self.state."""
        self.state_changed.emit()

    def _on_state_changed(self) -> None:
        storage.save(self.state, self.store_path)
        for i in range(self.pages.count()):
            widget = self.pages.widget(i)
            if hasattr(widget, "refresh"):
                widget.refresh()
