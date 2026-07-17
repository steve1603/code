"""Tests for the transactions-CSV importer — the exact export format
the user's bank produces (Date, Description, Original Description,
Category, Amount, Status) plus common variants."""
from __future__ import annotations

import unittest

from finadvisor.importers.transactions_csv import (
    is_transactions_csv,
    parse_transactions_csv,
)
from finadvisor.models import CategoryRule


# The user's real header layout.
MINT_STYLE = """\
Date,Description,Original Description,Category,Amount,Status
07/01/2026,Freedom Mortgage,FREEDOM MORTGAGE CORP AUTOPAY,Mortgage & Rent,-1850.00,Posted
07/02/2026,Paycheck,ACME CORP PAYROLL DIRECT DEP,Paycheck,4200.00,Posted
07/03/2026,Hy-Vee,HYVEE 1234 OMAHA NE,Groceries,-142.87,Posted
07/05/2026,Netflix,NETFLIX.COM SUBSCRIPTION,Subscriptions,-15.99,Posted
07/06/2026,Taco Bell,TACO BELL 037203,Fast Food,-8.07,Posted
07/07/2026,Amazon,AMZN MKTP US,Shopping,-63.20,Pending
"""


class HeaderDetectionTests(unittest.TestCase):
    def test_detects_mint_style_header(self):
        self.assertTrue(is_transactions_csv(MINT_STYLE))

    def test_rejects_debts_template(self):
        debts = "name,kind,balance,apr,min_payment\nVisa,credit_card,100,0.2,25\n"
        self.assertFalse(is_transactions_csv(debts))

    def test_rejects_garbage(self):
        self.assertFalse(is_transactions_csv(""))
        self.assertFalse(is_transactions_csv("hello world"))

    def test_detects_debit_credit_variant(self):
        text = "Posted Date,Description,Debit,Credit\n"
        self.assertTrue(is_transactions_csv(text))


class MintStyleParseTests(unittest.TestCase):
    def _parse(self, rules=None):
        return parse_transactions_csv(
            MINT_STYLE, "Checking", source="export.csv", rules=rules,
        )

    def test_row_count_and_pending_skip(self):
        result = self._parse()
        # 6 data rows, 1 pending skipped → 5 imported.
        self.assertEqual(len(result.transactions), 5)
        self.assertEqual(result.skipped_pending, 1)
        self.assertEqual(result.skipped_unparsed, 0)
        self.assertFalse(result.sign_flipped)

    def test_dates_normalized_to_iso(self):
        result = self._parse()
        self.assertEqual(result.transactions[0].date, "2026-07-01")

    def test_signed_amounts_trusted(self):
        result = self._parse()
        mortgage = result.transactions[0]
        paycheck = result.transactions[1]
        self.assertAlmostEqual(mortgage.amount, -1850.00)
        self.assertAlmostEqual(paycheck.amount, 4200.00)

    def test_bank_categories_mapped(self):
        result = self._parse()
        by_desc = {t.description: t.category for t in result.transactions}
        self.assertEqual(by_desc["Freedom Mortgage"], "home")
        self.assertEqual(by_desc["Paycheck"], "income")
        self.assertEqual(by_desc["Hy-Vee"], "groceries")
        self.assertEqual(by_desc["Netflix"], "subscriptions")
        self.assertEqual(by_desc["Taco Bell"], "dining")

    def test_user_rule_beats_bank_category(self):
        rules = [CategoryRule(match="netflix", category="entertainment")]
        result = self._parse(rules=rules)
        netflix = next(
            t for t in result.transactions if t.description == "Netflix"
        )
        self.assertEqual(netflix.category, "entertainment")

    def test_account_and_source_stamped(self):
        result = self._parse()
        self.assertTrue(all(
            t.account == "Checking" and t.source == "export.csv"
            for t in result.transactions
        ))


class SignConventionTests(unittest.TestCase):
    def test_all_positive_export_is_resigned(self):
        text = (
            "Date,Description,Category,Amount\n"
            "07/01/2026,ACME PAYROLL,Paycheck,4200.00\n"
            "07/03/2026,HYVEE,Groceries,142.87\n"
        )
        result = parse_transactions_csv(text, "Checking")
        self.assertTrue(result.sign_flipped)
        by_desc = {t.description: t.amount for t in result.transactions}
        self.assertGreater(by_desc["ACME PAYROLL"], 0)   # income stays +
        self.assertLess(by_desc["HYVEE"], 0)             # spending goes −

    def test_credit_card_charge_positive_export_inverted(self):
        # Card exports: purchases +, payment −. Ledger wants opposite.
        text = (
            "Date,Description,Category,Amount\n"
            "07/03/2026,HYVEE,Groceries,142.87\n"
            "07/06/2026,TACO BELL,Fast Food,8.07\n"
            "07/15/2026,PAYMENT THANK YOU,Credit Card Payment,-450.00\n"
        )
        result = parse_transactions_csv(
            text, "Visa", account_kind="credit_card",
        )
        self.assertTrue(result.sign_flipped)
        by_desc = {t.description: t.amount for t in result.transactions}
        self.assertLess(by_desc["HYVEE"], 0)
        self.assertGreater(by_desc["PAYMENT THANK YOU"], 0)

    def test_checking_signed_export_not_inverted(self):
        text = (
            "Date,Description,Category,Amount\n"
            "07/03/2026,HYVEE,Groceries,-142.87\n"
            "07/02/2026,PAYROLL,Paycheck,4200.00\n"
        )
        result = parse_transactions_csv(text, "Checking")
        self.assertFalse(result.sign_flipped)


class VariantFormatTests(unittest.TestCase):
    def test_debit_credit_columns(self):
        text = (
            "Posted Date,Description,Debit,Credit\n"
            "2026-07-03,HYVEE OMAHA,142.87,\n"
            "2026-07-02,ACME PAYROLL,,4200.00\n"
        )
        result = parse_transactions_csv(text, "Checking")
        by_desc = {t.description: t.amount for t in result.transactions}
        self.assertAlmostEqual(by_desc["HYVEE OMAHA"], -142.87)
        self.assertAlmostEqual(by_desc["ACME PAYROLL"], 4200.00)

    def test_money_formats(self):
        text = (
            "Date,Description,Category,Amount\n"
            '07/01/2026,RENT,Mortgage & Rent,"-$1,850.00"\n'
            "07/02/2026,FEE REFUND,Refund,(25.00)\n"
        )
        result = parse_transactions_csv(text, "Checking")
        by_desc = {t.description: t.amount for t in result.transactions}
        self.assertAlmostEqual(by_desc["RENT"], -1850.00)
        self.assertAlmostEqual(by_desc["FEE REFUND"], -25.00)

    def test_transaction_type_column_sets_sign(self):
        text = (
            "Date,Description,Category,Amount,Transaction Type\n"
            "07/03/2026,HYVEE,Groceries,142.87,debit\n"
            "07/02/2026,PAYROLL,Paycheck,4200.00,credit\n"
        )
        result = parse_transactions_csv(text, "Checking")
        by_desc = {t.description: t.amount for t in result.transactions}
        self.assertAlmostEqual(by_desc["HYVEE"], -142.87)
        self.assertAlmostEqual(by_desc["PAYROLL"], 4200.00)

    def test_bom_and_unknown_category_falls_back_to_classifier(self):
        text = (
            "﻿Date,Description,Original Description,Category,Amount,Status\n"
            "07/05/2026,Mystery,SHELL OIL 5551234,Uncategorized,-45.00,Posted\n"
        )
        result = parse_transactions_csv(text, "Checking")
        self.assertEqual(len(result.transactions), 1)
        # "Uncategorized" bank label → built-in classifier sees SHELL → gas.
        self.assertEqual(result.transactions[0].category, "gas")

    def test_unreadable_rows_counted_not_fatal(self):
        text = (
            "Date,Description,Category,Amount\n"
            "not-a-date,HYVEE,Groceries,-10.00\n"
            "07/03/2026,HYVEE,Groceries,-142.87\n"
            "07/04/2026,EMPTY AMOUNT,Groceries,\n"
        )
        result = parse_transactions_csv(text, "Checking")
        self.assertEqual(len(result.transactions), 1)
        self.assertEqual(result.skipped_unparsed, 2)

    def test_missing_date_column_raises(self):
        with self.assertRaises(ValueError):
            parse_transactions_csv(
                "Description,Amount\nHYVEE,-10\n", "Checking",
            )

    def test_missing_amount_column_raises(self):
        with self.assertRaises(ValueError):
            parse_transactions_csv(
                "Date,Description\n07/01/2026,HYVEE\n", "Checking",
            )


class AutoCategorizationTests(unittest.TestCase):
    """History correlation + needs_review to-do flagging. Uses the
    user's real bank categories (Credit Card, Business Services)."""

    USER_BANK_CSV = (
        "Date,Description,Original Description,Category,Amount,Status\n"
        "2026-07-01,Nebraska Furnitur,NEFURNMART NFMCARDPI,"
        "Credit Card,-50,Posted\n"
        "2026-07-02,LinkedIn,LinkedIn*P3043818790 855-,"
        "Business Services,-32.09,Posted\n"
        "2026-07-03,Paramount+,PARAMOUNT+ 888-274,"
        "Entertainment,-14.97,Posted\n"
        "2026-06-28,USAA Transfer,USAA FUNDS TRANSFER CR,"
        "Transfer,50,Posted\n"
    )

    def test_credit_card_bank_category_maps_to_debt_payment(self):
        result = parse_transactions_csv(self.USER_BANK_CSV, "Checking")
        nf = next(t for t in result.transactions
                  if "Nebraska" in t.description)
        self.assertEqual(nf.category, "debt_payment")
        self.assertFalse(nf.needs_review)

    def test_unknown_bank_category_flags_todo(self):
        # "Business Services" isn't mapped and LinkedIn* isn't in the
        # built-in classifier → to-do.
        result = parse_transactions_csv(self.USER_BANK_CSV, "Checking")
        li = next(t for t in result.transactions
                  if t.description == "LinkedIn")
        self.assertEqual(li.category, "other")
        self.assertTrue(li.needs_review)

    def test_history_correlation_inherits_prior_month_category(self):
        # Same charge categorized in a prior month → inherited, no todo.
        from finadvisor.models import Transaction
        from finadvisor.spending import history_category_map
        prior = [Transaction(
            date="2026-06-02", account="Checking",
            description="LinkedIn",
            amount=-32.09, category="subscriptions",
        )]
        history = history_category_map(prior)
        result = parse_transactions_csv(
            self.USER_BANK_CSV, "Checking", history=history,
        )
        li = next(t for t in result.transactions
                  if t.description == "LinkedIn")
        self.assertEqual(li.category, "subscriptions")
        self.assertFalse(li.needs_review)

    def test_flagged_rows_do_not_teach_history(self):
        from finadvisor.models import Transaction
        from finadvisor.spending import history_category_map
        unreviewed = [Transaction(
            date="2026-06-02", account="Checking",
            description="LinkedIn", amount=-32.09,
            category="shopping", needs_review=True,
        )]
        self.assertEqual(history_category_map(unreviewed), {})

    def test_transfer_and_entertainment_mapped(self):
        result = parse_transactions_csv(self.USER_BANK_CSV, "Checking")
        by_desc = {t.description: t.category for t in result.transactions}
        self.assertEqual(by_desc["USAA Transfer"], "transfer")
        self.assertEqual(by_desc["Paramount+"], "entertainment")


if __name__ == "__main__":
    unittest.main()
