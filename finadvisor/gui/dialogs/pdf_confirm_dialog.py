"""Dialog: confirm/edit fields extracted from a PDF before saving as a Debt."""
from __future__ import annotations

from PySide6.QtWidgets import QLabel, QPlainTextEdit

from finadvisor.gui.dialogs.edit_debt_dialog import EditDebtDialog
from finadvisor.importers.pdf_importer import PDFExtraction
from finadvisor.models import Debt


class PdfConfirmDialog(EditDebtDialog):
    """EditDebtDialog prefilled from a PDFExtraction + raw-text reference."""

    def __init__(self, parent=None, extraction: PDFExtraction | None = None) -> None:
        prefill = _extraction_to_debt(extraction) if extraction else None
        super().__init__(parent, debt=prefill)
        self.setWindowTitle("Confirm imported debt")
        self.setMinimumWidth(520)

        if not extraction:
            return

        layout = self.layout()  # QFormLayout

        banner = QLabel(
            "We extracted these fields from the PDF. Correct anything wrong, "
            "then click Save."
        )
        banner.setWordWrap(True)
        # Put the banner at the top by rebuilding row order via insertRow.
        layout.insertRow(0, banner)

        if extraction.raw_text:
            raw_label = QLabel("Raw text extracted from PDF (for reference):")
            raw = QPlainTextEdit(extraction.raw_text)
            raw.setReadOnly(True)
            raw.setMaximumHeight(160)
            layout.insertRow(layout.rowCount() - 1, raw_label)
            layout.insertRow(layout.rowCount() - 1, raw)


def _extraction_to_debt(ex: PDFExtraction) -> Debt | None:
    try:
        return Debt(
            name=ex.suggested_name,
            kind=ex.guessed_kind,
            balance=ex.balance or 0.0,
            apr=ex.apr or 0.0,
            min_payment=ex.min_payment or 0.0,
            credit_limit=ex.credit_limit,
        )
    except ValueError:
        return None
