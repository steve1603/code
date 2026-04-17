import tempfile
import unittest
from pathlib import Path

from finadvisor.importers import csv_importer


class CSVImporterTests(unittest.TestCase):
    def _write(self, content: str) -> Path:
        tmp = tempfile.NamedTemporaryFile("w", delete=False, suffix=".csv")
        tmp.write(content)
        tmp.close()
        return Path(tmp.name)

    def test_parses_template_shape(self):
        path = self._write(
            "name,kind,balance,apr,min_payment,credit_limit,due_day\n"
            "Card,credit_card,1000,0.24,25,5000,15\n"
            "Loan,student_loan,20000,0.06,220,,1\n"
        )
        debts = csv_importer.parse(path)
        self.assertEqual(len(debts), 2)
        self.assertEqual(debts[0].name, "Card")
        self.assertAlmostEqual(debts[0].apr, 0.24)
        self.assertIsNone(debts[1].credit_limit)

    def test_skips_blank_rows(self):
        path = self._write(
            "name,kind,balance,apr,min_payment,credit_limit,due_day\n"
            "\n"
            "Card,credit_card,1000,0.24,25,5000,15\n"
        )
        self.assertEqual(len(csv_importer.parse(path)), 1)

    def test_missing_columns(self):
        path = self._write("name,balance\nCard,1000\n")
        with self.assertRaises(csv_importer.CSVImportError):
            csv_importer.parse(path)

    def test_bad_row_reports_line_number(self):
        path = self._write(
            "name,kind,balance,apr,min_payment,credit_limit,due_day\n"
            "Card,credit_card,-50,0.24,25,5000,15\n"
        )
        with self.assertRaises(csv_importer.CSVImportError) as ctx:
            csv_importer.parse(path)
        self.assertIn("Row 2", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
