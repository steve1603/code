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


class BankStatementTests(unittest.TestCase):
    """Parser smoke tests based on the checking-account format used by
    USAA — Date / Description / Debits / Credits / Balance columns."""

    SAMPLE = (
        "Transactions (continued)\n"
        "Date Description Debits Credits Balance\n"
        "02/17 DEBIT CARD PURCHASE 021426 5814021426 $8.07 $2,707.18\n"
        "TACO BELL 037203 SUGAR LAND TX\n"
        "02/17 DEBIT CARD PURCHASE 021526 5462021526 $18.89 $2,688.29\n"
        "CRUMBL OMAHA NORTHWEST 180-14101313 UT\n"
        "02/17 POS DEBIT 021726 6051021726 $30.00 $2,607.33\n"
        "VENMO* Steven Davis Visa Direct NY\n"
        "02/17 USAA CREDIT CARD PAYMENT $45.00 $2,495.62\n"
        "CREDIT CARD ENDING IN 6421\n"
        "02/17 USAA LOAN PAYMENT $542.12 $357.75\n"
        "LOAN NUMBER ENDING IN 3351\n"
    )

    def setUp(self):
        from finadvisor.importers import bank_statement
        self.bs = bank_statement

    def test_detection(self):
        self.assertTrue(self.bs.is_bank_statement(self.SAMPLE))
        self.assertFalse(self.bs.is_bank_statement(
            "Chase Freedom\nNew Balance: $100.00\n"
        ))

    def test_parses_every_debit_row(self):
        txs = self.bs.parse_transactions(self.SAMPLE)
        # Expect 5 rows (matching the 5 dated lines above).
        self.assertEqual(len(txs), 5)
        # Every row is a debit (no credits in this sample).
        self.assertTrue(all(t.debit is not None for t in txs))
        self.assertTrue(all(t.credit is None for t in txs))

    def test_debit_and_balance_amounts(self):
        txs = self.bs.parse_transactions(self.SAMPLE)
        self.assertAlmostEqual(txs[0].debit, 8.07)
        self.assertAlmostEqual(txs[0].balance, 2707.18)
        self.assertAlmostEqual(txs[3].debit, 45.00)
        self.assertAlmostEqual(txs[3].balance, 2495.62)
        self.assertAlmostEqual(txs[4].debit, 542.12)

    def test_classifies_debt_related_payments(self):
        txs = self.bs.parse_transactions(self.SAMPLE)
        card = next(t for t in txs if "CREDIT CARD PAYMENT" in t.description)
        self.assertEqual(card.kind_guess, "credit_card")
        self.assertEqual(card.account_hint, "6421")
        loan = next(t for t in txs if "LOAN PAYMENT" in t.description)
        self.assertEqual(loan.kind_guess, "personal")
        self.assertEqual(loan.account_hint, "3351")
        taco = next(t for t in txs if "TACO BELL" in t.description)
        self.assertEqual(taco.kind_guess, "other")

    def test_suggest_debt_name(self):
        txs = self.bs.parse_transactions(self.SAMPLE)
        card = next(t for t in txs if "CREDIT CARD PAYMENT" in t.description)
        self.assertEqual(self.bs.suggest_debt_name(card), "Usaa Card 6421")
        loan = next(t for t in txs if "LOAN PAYMENT" in t.description)
        self.assertEqual(self.bs.suggest_debt_name(loan), "Usaa Loan 3351")

    def test_looks_like_debt_payment(self):
        txs = self.bs.parse_transactions(self.SAMPLE)
        preselected = [t for t in txs if self.bs.looks_like_debt_payment(t)]
        # Only the credit-card and loan payments should pre-select.
        self.assertEqual(len(preselected), 2)
        descs = {t.description for t in preselected}
        self.assertTrue(any("CREDIT CARD PAYMENT" in d for d in descs))
        self.assertTrue(any("LOAN PAYMENT" in d for d in descs))

    def test_deposits_classified_as_credit(self):
        text = (
            "Transactions\n"
            "Date Description Debits Credits Balance\n"
            "02/15 DIRECT DEPOSIT PAYROLL $1,500.00 $5,000.00\n"
        )
        txs = self.bs.parse_transactions(text)
        self.assertEqual(len(txs), 1)
        self.assertIsNone(txs[0].debit)
        self.assertAlmostEqual(txs[0].credit, 1500.0)

    def test_empty_text(self):
        self.assertEqual(self.bs.parse_transactions(""), [])


if __name__ == "__main__":
    unittest.main()
