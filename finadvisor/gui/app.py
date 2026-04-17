"""QApplication bootstrap."""
from __future__ import annotations

import sys

APP_STYLESHEET = """
QMainWindow, QWidget { background-color: #f5f6f8; color: #1f2937; }
QListWidget#sidebar {
    background-color: #1f2937;
    color: #e5e7eb;
    border: none;
    padding: 8px 0;
    font-size: 14px;
}
QListWidget#sidebar::item { padding: 12px 20px; }
QListWidget#sidebar::item:selected {
    background-color: #2563eb;
    color: white;
}
QFrame#card {
    background-color: white;
    border: 1px solid #e5e7eb;
    border-radius: 8px;
    padding: 16px;
}
QLabel#cardTitle { color: #6b7280; font-size: 12px; font-weight: 600; }
QLabel#cardValue { color: #111827; font-size: 22px; font-weight: 700; }
QLabel#pageTitle { font-size: 22px; font-weight: 700; color: #111827; }
QLabel#sectionTitle { font-size: 14px; font-weight: 600; color: #374151; }
QLabel#nextAction {
    background-color: #eff6ff;
    border: 1px solid #bfdbfe;
    border-radius: 8px;
    padding: 14px;
    font-size: 14px;
    color: #1e3a8a;
}
QLabel[severity="urgent"] {
    background-color: #fef2f2;
    border: 1px solid #fecaca;
    color: #991b1b;
    border-radius: 6px; padding: 8px;
}
QLabel[severity="warn"] {
    background-color: #fffbeb;
    border: 1px solid #fde68a;
    color: #92400e;
    border-radius: 6px; padding: 8px;
}
QLabel[severity="good"] {
    background-color: #ecfdf5;
    border: 1px solid #a7f3d0;
    color: #065f46;
    border-radius: 6px; padding: 8px;
}
QLabel[severity="info"] {
    background-color: #eff6ff;
    border: 1px solid #bfdbfe;
    color: #1e3a8a;
    border-radius: 6px; padding: 8px;
}
QPushButton {
    background-color: #2563eb; color: white;
    border: none; border-radius: 6px; padding: 8px 14px;
    font-weight: 600;
}
QPushButton:hover  { background-color: #1d4ed8; }
QPushButton:disabled { background-color: #9ca3af; }
QPushButton#secondary { background-color: #e5e7eb; color: #111827; }
QPushButton#secondary:hover { background-color: #d1d5db; }
QPushButton#danger { background-color: #dc2626; }
QPushButton#danger:hover { background-color: #b91c1c; }
QTableView {
    background-color: white; border: 1px solid #e5e7eb;
    border-radius: 6px; gridline-color: #f3f4f6;
    selection-background-color: #dbeafe; selection-color: #1e3a8a;
}
QHeaderView::section {
    background-color: #f9fafb; border: none;
    border-bottom: 1px solid #e5e7eb;
    padding: 8px; font-weight: 600; color: #374151;
}
QLineEdit, QComboBox, QDoubleSpinBox, QSpinBox {
    background-color: white; border: 1px solid #d1d5db;
    border-radius: 6px; padding: 6px 10px;
}
QLineEdit:focus, QComboBox:focus,
QDoubleSpinBox:focus, QSpinBox:focus { border-color: #2563eb; }
QTabWidget::pane {
    border: 1px solid #e5e7eb; border-radius: 6px;
    background-color: white; top: -1px;
}
QTabBar::tab {
    background-color: #f3f4f6; border: 1px solid #e5e7eb;
    padding: 8px 16px; border-top-left-radius: 6px; border-top-right-radius: 6px;
}
QTabBar::tab:selected {
    background-color: white; color: #2563eb;
    border-bottom-color: white; font-weight: 600;
}
QScrollArea { border: none; background-color: transparent; }
"""


def main() -> int:
    from PySide6.QtWidgets import QApplication
    from finadvisor.gui.main_window import MainWindow

    app = QApplication.instance() or QApplication(sys.argv)
    app.setApplicationName("finadvisor")
    app.setStyle("Fusion")
    app.setStyleSheet(APP_STYLESHEET)

    window = MainWindow()
    window.show()
    return app.exec()
