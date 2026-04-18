"""Analysis page: one tab per strategy, runs live against current state."""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCharts import QChart, QChartView, QLineSeries, QValueAxis
from PySide6.QtCore import Qt
from PySide6.QtGui import QPainter
from PySide6.QtWidgets import (
    QAbstractItemView,
    QFileDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QListWidget,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from finadvisor.report import run_all, to_text
from finadvisor.strategies.base import StrategyResult


class AnalysisPage(QWidget):
    def __init__(self, window) -> None:
        super().__init__()
        self.window_ = window

        root = QVBoxLayout(self)
        root.setContentsMargins(24, 24, 24, 24)
        root.setSpacing(12)

        title_row = QHBoxLayout()
        title = QLabel("Recommendations")
        title.setObjectName("pageTitle")
        title_row.addWidget(title)
        title_row.addStretch(1)
        self.refresh_btn = QPushButton("Refresh")
        self.refresh_btn.setObjectName("secondary")
        self.export_btn = QPushButton("Export Report…")
        self.export_btn.setObjectName("secondary")
        title_row.addWidget(self.refresh_btn)
        title_row.addWidget(self.export_btn)
        root.addLayout(title_row)

        disclaimer = QLabel(
            "Educational tool only — not licensed financial advice. "
            "Recommendations are based only on the data you entered."
        )
        disclaimer.setProperty("severity", "info")
        disclaimer.setWordWrap(True)
        root.addWidget(disclaimer)

        self.tabs = QTabWidget()
        root.addWidget(self.tabs, 1)

        self.refresh_btn.clicked.connect(self.refresh)
        self.export_btn.clicked.connect(self._on_export)

        self.refresh()

    def refresh(self) -> None:
        # Rebuild every tab from scratch for simplicity.
        self.tabs.clear()
        state = self.window_.state
        if not state.debts:
            empty = QLabel(
                "Add at least one debt on the Debts tab to see recommendations."
            )
            empty.setAlignment(Qt.AlignCenter)
            empty.setWordWrap(True)
            self.tabs.addTab(empty, "Start here")
            return

        self._report = run_all(state)
        for result in self._report.results:
            self.tabs.addTab(_build_strategy_tab(result), result.title)

    def _on_export(self) -> None:
        if not hasattr(self, "_report"):
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "Export report",
            str(Path.cwd() / "finadvisor-report.txt"),
            "Text files (*.txt)",
        )
        if not path:
            return
        Path(path).write_text(to_text(self._report), encoding="utf-8")
        QMessageBox.information(self, "Exported", f"Report saved to {path}")


def _build_strategy_tab(r: StrategyResult) -> QWidget:
    tab = QWidget()
    layout = QVBoxLayout(tab)
    layout.setContentsMargins(16, 16, 16, 16)
    layout.setSpacing(12)

    summary = QLabel(r.summary)
    summary.setWordWrap(True)
    summary.setProperty("severity", r.severity.value)
    layout.addWidget(summary)

    if r.recommendations:
        recs_title = QLabel("Recommendations")
        recs_title.setObjectName("sectionTitle")
        layout.addWidget(recs_title)

        recs = QListWidget()
        for rec in r.recommendations:
            recs.addItem("• " + rec)
        recs.setSelectionMode(QAbstractItemView.NoSelection)
        recs.setWordWrap(True)
        layout.addWidget(recs, 1)

    if r.schedule:
        chart_title = QLabel("Payoff curve")
        chart_title.setObjectName("sectionTitle")
        layout.addWidget(chart_title)
        layout.addWidget(_build_payoff_chart(r.schedule), 1)

        sched_title = QLabel("Projected balances over time")
        sched_title.setObjectName("sectionTitle")
        layout.addWidget(sched_title)
        layout.addWidget(_build_schedule_table(r.schedule))

    return tab


def _build_payoff_chart(schedule: list[dict]) -> QChartView:
    """Line chart of total balance over time, plus one line per debt."""
    chart = QChart()
    chart.setTitle("Projected total balance (and per-debt breakdown)")
    chart.legend().setVisible(True)
    chart.legend().setAlignment(Qt.AlignBottom)

    months = [row["month"] for row in schedule]
    max_month = max(months) if months else 1

    total_series = QLineSeries()
    total_series.setName("Total balance")
    max_balance = 0.0
    for row in schedule:
        total = float(row.get("total_balance", 0.0))
        total_series.append(row["month"], total)
        if total > max_balance:
            max_balance = total
    chart.addSeries(total_series)

    debt_names = sorted({
        name for row in schedule for name in row.get("per_debt", {}).keys()
    })
    for name in debt_names:
        s = QLineSeries()
        s.setName(name)
        for row in schedule:
            s.append(row["month"], float(row.get("per_debt", {}).get(name, 0.0)))
        chart.addSeries(s)

    axis_x = QValueAxis()
    axis_x.setTitleText("Month")
    axis_x.setRange(0, max(max_month, 1))
    axis_x.setLabelFormat("%d")
    chart.addAxis(axis_x, Qt.AlignBottom)

    axis_y = QValueAxis()
    axis_y.setTitleText("Balance ($)")
    axis_y.setRange(0, max(max_balance * 1.05, 1.0))
    axis_y.setLabelFormat("$%,.0f")
    chart.addAxis(axis_y, Qt.AlignLeft)

    for series in chart.series():
        series.attachAxis(axis_x)
        series.attachAxis(axis_y)

    view = QChartView(chart)
    view.setRenderHint(QPainter.Antialiasing)
    view.setMinimumHeight(260)
    return view


def _build_schedule_table(schedule: list[dict]) -> QTableWidget:
    all_debt_names = sorted({
        name for row in schedule for name in row.get("per_debt", {}).keys()
    })
    headers = ["Month", "Total balance", "Interest this month", *all_debt_names]
    t = QTableWidget(len(schedule), len(headers))
    t.setHorizontalHeaderLabels(headers)
    t.verticalHeader().setVisible(False)
    t.setEditTriggers(QAbstractItemView.NoEditTriggers)
    t.setAlternatingRowColors(True)

    for row_idx, entry in enumerate(schedule):
        t.setItem(row_idx, 0, QTableWidgetItem(str(entry["month"])))
        t.setItem(row_idx, 1, QTableWidgetItem(f"${entry['total_balance']:,.2f}"))
        t.setItem(
            row_idx, 2,
            QTableWidgetItem(f"${entry.get('interest_paid_this_month', 0.0):,.2f}"),
        )
        per = entry.get("per_debt", {})
        for j, name in enumerate(all_debt_names):
            t.setItem(
                row_idx, 3 + j,
                QTableWidgetItem(f"${per.get(name, 0.0):,.2f}"),
            )
    t.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
    t.horizontalHeader().setStretchLastSection(True)
    return t
