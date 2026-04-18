"""Debts page: table + add/edit/delete + import buttons."""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFileDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMessageBox,
    QPushButton,
    QTableView,
    QVBoxLayout,
    QWidget,
)

from finadvisor import storage
from finadvisor.gui.dialogs.edit_debt_dialog import EditDebtDialog
from finadvisor.gui.dialogs.pdf_confirm_dialog import PdfConfirmDialog
from finadvisor.gui.models.debts_table_model import DebtsTableModel
from finadvisor.importers import csv_importer, pdf_importer


class DebtsPage(QWidget):
    def __init__(self, window) -> None:
        super().__init__()
        self.window_ = window

        root = QVBoxLayout(self)
        root.setContentsMargins(24, 24, 24, 24)
        root.setSpacing(12)

        title = QLabel("Your debts")
        title.setObjectName("pageTitle")
        root.addWidget(title)

        subtitle = QLabel(
            "Add each of your debts below. Use Import CSV for a batch, or "
            "Import PDF to pull fields from a statement."
        )
        subtitle.setWordWrap(True)
        root.addWidget(subtitle)

        # Toolbar
        toolbar = QHBoxLayout()
        self.btn_add = QPushButton("Add")
        self.btn_edit = QPushButton("Edit")
        self.btn_edit.setObjectName("secondary")
        self.btn_delete = QPushButton("Delete")
        self.btn_delete.setObjectName("danger")
        self.btn_import_csv = QPushButton("Import CSV…")
        self.btn_import_csv.setObjectName("secondary")
        self.btn_import_pdf = QPushButton("Import PDF…")
        self.btn_import_pdf.setObjectName("secondary")
        self.btn_export = QPushButton("Export JSON…")
        self.btn_export.setObjectName("secondary")

        toolbar.addWidget(self.btn_add)
        toolbar.addWidget(self.btn_edit)
        toolbar.addWidget(self.btn_delete)
        toolbar.addSpacing(16)
        toolbar.addWidget(self.btn_import_csv)
        toolbar.addWidget(self.btn_import_pdf)
        toolbar.addStretch(1)
        toolbar.addWidget(self.btn_export)
        root.addLayout(toolbar)

        # Table
        self.table = QTableView()
        self.model = DebtsTableModel(self.window_.state.debts)
        self.table.setModel(self.model)
        self.table.setSelectionBehavior(QTableView.SelectRows)
        self.table.setSelectionMode(QTableView.SingleSelection)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.verticalHeader().setVisible(False)
        self.table.doubleClicked.connect(lambda _ix: self._on_edit())
        root.addWidget(self.table, 1)

        # Summary footer
        self.summary = QLabel()
        self.summary.setObjectName("sectionTitle")
        self.summary.setWordWrap(True)
        root.addWidget(self.summary)

        # Wiring
        self.btn_add.clicked.connect(self._on_add)
        self.btn_edit.clicked.connect(self._on_edit)
        self.btn_delete.clicked.connect(self._on_delete)
        self.btn_import_csv.clicked.connect(self._on_import_csv)
        self.btn_import_pdf.clicked.connect(self._on_import_pdf)
        self.btn_export.clicked.connect(self._on_export)

        self._update_summary()

    # --- helpers --------------------------------------------------------
    def refresh(self) -> None:
        self.model.set_debts(self.window_.state.debts)
        self._update_summary()

    def _update_summary(self) -> None:
        debts = self.window_.state.debts
        if not debts:
            self.summary.setText("")
            return
        total_balance = sum(d.balance for d in debts)
        total_minimums = sum(d.min_payment for d in debts)
        total_monthly_interest = sum(
            d.balance * d.apr / 12.0 for d in debts
        )
        self.summary.setText(
            f"{len(debts)} debt(s) • balance ${total_balance:,.2f} • "
            f"minimums ${total_minimums:,.2f}/mo • "
            f"accrued interest ${total_monthly_interest:,.2f}/mo"
        )

    def _selected_row(self) -> int:
        idx = self.table.currentIndex()
        return idx.row() if idx.isValid() else -1

    # --- actions --------------------------------------------------------
    def _on_add(self) -> None:
        dlg = EditDebtDialog(self)
        if dlg.exec() == dlg.Accepted and dlg.debt():
            self.window_.state.debts.append(dlg.debt())
            self.window_.mark_dirty()

    def _on_edit(self) -> None:
        row = self._selected_row()
        if row < 0:
            QMessageBox.information(self, "No selection", "Select a debt first.")
            return
        dlg = EditDebtDialog(self, debt=self.window_.state.debts[row])
        if dlg.exec() == dlg.Accepted and dlg.debt():
            self.window_.state.debts[row] = dlg.debt()
            self.window_.mark_dirty()

    def _on_delete(self) -> None:
        row = self._selected_row()
        if row < 0:
            return
        name = self.window_.state.debts[row].name
        if QMessageBox.question(
            self, "Delete debt",
            f"Remove '{name}' from your debts?",
        ) != QMessageBox.Yes:
            return
        del self.window_.state.debts[row]
        self.window_.mark_dirty()

    def _on_import_csv(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Import debts CSV",
            str(Path.cwd()),
            "CSV files (*.csv);;All files (*)",
        )
        if not path:
            return
        try:
            new_debts = csv_importer.parse(path)
        except csv_importer.CSVImportError as e:
            QMessageBox.warning(self, "CSV import failed", str(e))
            return

        # De-dup by name: replace existing, append new.
        existing_by_name = {d.name: i for i, d in enumerate(self.window_.state.debts)}
        added = 0
        updated = 0
        for d in new_debts:
            if d.name in existing_by_name:
                self.window_.state.debts[existing_by_name[d.name]] = d
                updated += 1
            else:
                self.window_.state.debts.append(d)
                added += 1
        self.window_.mark_dirty()
        QMessageBox.information(
            self, "Import complete",
            f"Added {added} new debts, updated {updated} existing by name.",
        )

    def _on_import_pdf(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Import statement PDF",
            str(Path.cwd()),
            "PDF files (*.pdf);;All files (*)",
        )
        if not path:
            return
        try:
            extraction = pdf_importer.parse(path)
        except pdf_importer.PDFImportError as e:
            QMessageBox.warning(self, "PDF import failed", str(e))
            return

        dlg = PdfConfirmDialog(self, extraction=extraction)
        if dlg.exec() == dlg.Accepted and dlg.debt():
            self.window_.state.debts.append(dlg.debt())
            self.window_.mark_dirty()

    def _on_export(self) -> None:
        path, _ = QFileDialog.getSaveFileName(
            self, "Export finances.json",
            str(Path.cwd() / "finances-export.json"),
            "JSON (*.json)",
        )
        if not path:
            return
        storage.save(self.window_.state, path)
        QMessageBox.information(self, "Exported", f"Saved to {path}")
