import tempfile
import unittest
from pathlib import Path

from finadvisor.importers import csv_importer, pdf_importer


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

    def test_kind_inferred_when_missing(self):
        # kind column present but blank → inferred from name
        path = self._write(
            "name,kind,balance,apr,min_payment,credit_limit,due_day\n"
            "Chase Visa,,4500,0.20,100,5000,15\n"
            "Toyota Auto Loan,,12000,0.045,300,,20\n"
            "My Student Loan,,18000,0.065,220,,1\n"
            "Random Thing,,500,0.1,25,,1\n"
        )
        debts = csv_importer.parse(path)
        self.assertEqual(debts[0].kind, "credit_card")
        self.assertEqual(debts[1].kind, "auto")
        self.assertEqual(debts[2].kind, "student_loan")
        self.assertEqual(debts[3].kind, "other")

    def test_kind_column_optional(self):
        # Users can omit the column entirely
        path = self._write(
            "name,balance,apr,min_payment\n"
            "My Mortgage,250000,0.035,1600\n"
        )
        debts = csv_importer.parse(path)
        self.assertEqual(debts[0].kind, "mortgage")

    def test_bad_row_reports_line_number(self):
        path = self._write(
            "name,kind,balance,apr,min_payment,credit_limit,due_day\n"
            "Card,credit_card,-50,0.24,25,5000,15\n"
        )
        with self.assertRaises(csv_importer.CSVImportError) as ctx:
            csv_importer.parse(path)
        self.assertIn("Row 2", str(ctx.exception))


class PDFExtractFromTextTests(unittest.TestCase):
    """PDF parsing is tested on synthetic text so no real PDFs are needed."""

    def test_credit_card_statement(self):
        text = (
            "Your Credit Card Statement\n"
            "New Balance: $2,483.17\n"
            "Minimum Payment Due: $45.00\n"
            "Credit Limit: $10,000.00\n"
            "Purchase APR: 24.99%\n"
        )
        result = pdf_importer.extract_from_text(text, "chase-card")
        self.assertEqual(result.guessed_kind, "credit_card")
        self.assertAlmostEqual(result.balance, 2483.17)
        self.assertAlmostEqual(result.apr, 0.2499)
        self.assertAlmostEqual(result.min_payment, 45.0)
        self.assertAlmostEqual(result.credit_limit, 10000.0)

    def test_student_loan_statement(self):
        text = (
            "Nelnet Loan Servicer — Monthly Statement\n"
            "Unpaid Principal Balance: $18,452.10\n"
            "Monthly Payment Amount: $215.00\n"
            "Interest Rate: 6.50%\n"
            "Direct Loan, Subsidized\n"
        )
        result = pdf_importer.extract_from_text(text, "nelnet")
        self.assertEqual(result.guessed_kind, "student_loan")
        self.assertAlmostEqual(result.balance, 18452.10)
        self.assertAlmostEqual(result.apr, 0.065)
        self.assertAlmostEqual(result.min_payment, 215.0)
        # Student loans don't carry a credit limit.
        self.assertIsNone(result.credit_limit)

    def test_auto_loan_statement(self):
        text = (
            "Auto Loan Payoff Statement\n"
            "VIN: 1HGBH41JXMN109186\n"
            "Principal Balance: $12,003.22\n"
            "Regular Payment: $310.45\n"
            "Note Rate: 4.49%\n"
        )
        result = pdf_importer.extract_from_text(text, "auto")
        self.assertEqual(result.guessed_kind, "auto")
        self.assertAlmostEqual(result.balance, 12003.22)
        self.assertAlmostEqual(result.apr, 0.0449)
        self.assertAlmostEqual(result.min_payment, 310.45)

    def test_mortgage_statement(self):
        text = (
            "Home Mortgage Statement\n"
            "Principal Balance: $258,400.00\n"
            "Interest Rate: 3.25%\n"
            "Monthly Payment: $1,722.00\n"
        )
        result = pdf_importer.extract_from_text(text, "mortgage")
        self.assertEqual(result.guessed_kind, "mortgage")
        self.assertAlmostEqual(result.balance, 258400.0)
        self.assertAlmostEqual(result.apr, 0.0325)

    def test_unknown_text_defaults_to_other(self):
        result = pdf_importer.extract_from_text("nothing useful here", "x")
        self.assertEqual(result.guessed_kind, "other")
        self.assertIsNone(result.balance)
        self.assertIsNone(result.apr)


if __name__ == "__main__":
    unittest.main()
