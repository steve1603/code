"""Main window: sidebar + stacked pages."""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QAction, QKeySequence
from PySide6.QtWidgets import (
    QFileDialog,
    QHBoxLayout,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
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
        self._build_menu()

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

    def _build_menu(self) -> None:
        menu = self.menuBar()
        file_menu = menu.addMenu("&File")

        open_act = QAction("&Open data file…", self)
        open_act.setShortcut(QKeySequence.Open)
        open_act.triggered.connect(self._on_menu_open)
        file_menu.addAction(open_act)

        save_as_act = QAction("&Save a copy as…", self)
        save_as_act.setShortcut(QKeySequence("Ctrl+Shift+S"))
        save_as_act.triggered.connect(self._on_menu_save_as)
        file_menu.addAction(save_as_act)

        file_menu.addSeparator()
        quit_act = QAction("&Quit", self)
        quit_act.setShortcut(QKeySequence.Quit)
        quit_act.triggered.connect(self.close)
        file_menu.addAction(quit_act)

        help_menu = menu.addMenu("&Help")
        about_act = QAction("&About finadvisor", self)
        about_act.triggered.connect(self._on_menu_about)
        help_menu.addAction(about_act)

    def _on_menu_open(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Open finadvisor data file",
            str(Path(self.store_path).parent),
            "JSON (*.json);;All files (*)",
        )
        if not path:
            return
        try:
            new_state = storage.load(Path(path))
        except Exception as e:
            QMessageBox.warning(self, "Could not open", str(e))
            return
        self.store_path = Path(path)
        self.state = new_state
        self._update_statusbar()
        for i in range(self.pages.count()):
            widget = self.pages.widget(i)
            if hasattr(widget, "refresh"):
                widget.refresh()

    def _on_menu_save_as(self) -> None:
        path, _ = QFileDialog.getSaveFileName(
            self, "Save a copy",
            str(Path.cwd() / "finances-copy.json"),
            "JSON (*.json)",
        )
        if not path:
            return
        try:
            storage.save(self.state, Path(path))
            QMessageBox.information(self, "Saved", f"Copy written to {path}")
        except Exception as e:
            QMessageBox.warning(self, "Could not save", str(e))

    def _on_menu_about(self) -> None:
        QMessageBox.about(
            self, "About finadvisor",
            "<h3>finadvisor</h3>"
            "<p>A local personal debt-advisor. All data stays on your "
            "computer; no network calls.</p>"
            "<p><i>Educational tool only — not licensed financial advice.</i></p>",
        )

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
