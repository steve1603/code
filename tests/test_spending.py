"""Tests for transaction storage, metadata extraction, categorization,
and the monthly/trend aggregations."""
from __future__ import annotations

import unittest
from datetime import date

from finadvisor.importers import bank_statement as bs
from finadvisor.models import (
    Account, FinanceState, Transaction, SPENDING_CATEGORIES,
)
from finadvisor import spending


# --------------------------------------------------------------------
# Models
# --------------------------------------------------------------------


class TransactionModelTests(unittest.TestCase):
    def test_rejects_bad_iso_date(self):
        with self.assertRaises(ValueError):
            Transaction(
                date="02/17", account="USAA", description="x", amount=-1,
            )

    def test_rejects_unknown_category(self):
        with self.assertRaises(ValueError):
            Transaction(
                date="2026-02-17", account="USAA", description="x",
                amount=-1, category="vibes",
            )

    def test_month_property(self):
        t = Transaction(
            date="2026-02-17", account="USAA", description="x",
            amount=-1, category="other",
        )
        self.assertEqual(t.month, "2026-02")

    def test_income_expense_helpers(self):
        exp = Transaction(
            date="2026-02-17", account="A", description="x",
            amount=-50, category="other",
        )
        inc = Transaction(
            date="2026-02-17", account="A", description="x",
            amount=1500, category="income",
        )
        self.assertTrue(exp.is_expense)
        self.assertFalse(exp.is_income)
        self.assertTrue(inc.is_income)
        self.assertFalse(inc.is_expense)


class FinanceStatePersistenceTests(unittest.TestCase):
    def test_accounts_and_transactions_roundtrip(self):
        st = FinanceState()
        st.upsert_account(Account(
            name="USAA Checking 3904",
            kind="checking", institution="USAA", number_hint="3904",
        ))
        st.add_transactions([
            Transaction(
                date="2026-02-17", account="USAA Checking 3904",
                description="TACO BELL", amount=-8.07, category="dining",
            ),
        ])
        data = st.to_dict()
        restored = FinanceState.from_dict(data)
        self.assertEqual(len(restored.accounts), 1)
        self.assertEqual(restored.accounts[0].name, "USAA Checking 3904")
        self.assertEqual(len(restored.transactions), 1)
        self.assertEqual(restored.transactions[0].category, "dining")

    def test_upsert_account_is_idempotent(self):
        st = FinanceState()
        st.upsert_account(Account(name="A", kind="checking"))
        st.upsert_account(Account(name="A", kind="savings"))
        self.assertEqual(len(st.accounts), 1)
        self.assertEqual(st.accounts[0].kind, "savings")

    def test_add_transactions_deduplicates(self):
        st = FinanceState()
        tx = Transaction(
            date="2026-02-17", account="A", description="TACO",
            amount=-8.07, category="dining",
        )
        added1 = st.add_transactions([tx])
        added2 = st.add_transactions([tx])
        self.assertEqual(added1, 1)
        self.assertEqual(added2, 0)
        self.assertEqual(len(st.transactions), 1)


# --------------------------------------------------------------------
# Statement metadata
# --------------------------------------------------------------------


USAA_HEADER = """
USAA Federal Savings Bank
10750 McDermott Freeway
San Antonio, Texas 78288-0544
USAA CLASSIC CHECKING
for Account Number: 0274373904
Statement Period: 02/12/2026 to 03/11/2026
ROXANNE TRIBELL DAVIS
TEVEN BRADLY DAVIS
16475 VANE ST
BENNINGTON NE  68007-1669
Activity Summary
Beginning Balance $1.42
"""


class MetadataExtractionTests(unittest.TestCase):
    def test_parses_usaa_checking_header(self):
        md = bs.extract_metadata(USAA_HEADER)
        self.assertIn("USAA", md.institution)
        self.assertEqual(md.account_name, "Usaa Classic Checking")
        self.assertEqual(md.account_number, "0274373904")
        self.assertEqual(md.account_last4, "3904")
        self.assertEqual(md.account_kind, "checking")
        self.assertEqual(md.period_start, date(2026, 2, 12))
        self.assertEqual(md.period_end, date(2026, 3, 11))

    def test_display_name_format(self):
        md = bs.extract_metadata(USAA_HEADER)
        self.assertEqual(md.display_name, "USAA Checking 3904")

    def test_credit_card_statement_detected(self):
        text = (
            "Chase Bank Statement\n"
            "CHASE FREEDOM UNLIMITED CARD\n"
            "Account Number: ************4321\n"
            "Statement Period: 01/15/2026 to 02/14/2026\n"
        )
        md = bs.extract_metadata(text)
        self.assertEqual(md.account_kind, "credit_card")
        self.assertEqual(md.account_last4, "4321")

    def test_missing_metadata_returns_blank_fields(self):
        md = bs.extract_metadata("just some gibberish\n")
        self.assertEqual(md.institution, "")
        self.assertIsNone(md.period_start)


class AssignYearTests(unittest.TestCase):
    def test_picks_year_from_statement_period(self):
        md = bs.StatementMetadata(
            period_start=date(2026, 2, 12),
            period_end=date(2026, 3, 11),
        )
        self.assertEqual(bs.assign_year(md, "02/17"), "2026-02-17")
        self.assertEqual(bs.assign_year(md, "03/05"), "2026-03-05")

    def test_handles_year_boundary(self):
        md = bs.StatementMetadata(
            period_start=date(2025, 12, 15),
            period_end=date(2026, 1, 14),
        )
        # 12/28 should land in 2025, 01/05 should land in 2026.
        self.assertEqual(bs.assign_year(md, "12/28"), "2025-12-28")
        self.assertEqual(bs.assign_year(md, "01/05"), "2026-01-05")

    def test_malformed_input_pass_through(self):
        md = bs.StatementMetadata()
        self.assertEqual(bs.assign_year(md, "garbage"), "garbage")


# --------------------------------------------------------------------
# Categorization
# --------------------------------------------------------------------


class CategorizeTests(unittest.TestCase):
    CASES = [
        ("TACO BELL 037203 SUGAR LAND TX", "dining"),
        ("CRUMBL OMAHA NORTHWEST 180-14101313 UT", "dining"),
        ("COSTCO GAS #1690 OMAHA NE", "gas"),
        ("COSTCO WHSE #1690 OMAHA NE", "groceries"),
        ("HY-VEE OMAHA 147 HY VEE OMAHA NE", "groceries"),
        ("SHELL OIL 12345", "gas"),
        ("USAA CREDIT CARD PAYMENT CREDIT CARD ENDING IN 6421",
         "debt_payment"),
        ("USAA LOAN PAYMENT LOAN NUMBER ENDING IN 3351", "debt_payment"),
        ("ACH WITHDRAWAL 030226 CITI AUTOPAY RETRY PYMT ***0078",
         "debt_payment"),
        ("USAA FUNDS TRANSFER CR FROM Steven Davis", "transfer"),
        ("VENMO* Steven Davis Visa Direct NY", "transfer"),
        ("DIRECT DEPOSIT PAYROLL", "income"),
        ("Netflix.com CA", "subscriptions"),
        ("Amazon.com Seattle WA", "shopping"),
        ("THE HOME DEPOT #3201 OMAHA NE", "home"),
        ("Harbor Freight Tools USA Omaha NE", "home"),
        ("Prime Video Channels amzn.com/billWA", "subscriptions"),
        ("SONIC DRIVE IN #4587 402-431-1593 NE", "dining"),
        ("VERIZON WIRELESS", "phone_internet"),
        ("OVERDRAFT FEE", "fees"),
        ("ATM WITHDRAWAL 400.00", "cash"),
        ("Random mystery merchant", "other"),
        # User-reported merchants (USAA statement walkthrough):
        ("RECURRING DEB CARD PURCH Experian* Credit Report",
         "subscriptions"),
        ("RECURRING DEB CARD PURCH WWW.COURSEHERO.COM",
         "subscriptions"),
        ("MUD AUTOPAY 402", "utilities"),
        ("OPPD AUTOPAY", "utilities"),
        ("METROPOLITAN UTILITIES DISTRICT", "utilities"),
        ("FREEDOM MORTGAGE AUTOPAY", "utilities"),
    ]

    def test_each_case(self):
        for desc, expected in self.CASES:
            with self.subTest(desc=desc):
                self.assertEqual(
                    bs.categorize(desc), expected,
                    f"{desc!r} → got {bs.categorize(desc)!r}, "
                    f"expected {expected!r}",
                )

    def test_every_category_is_valid(self):
        for _, cat in self.CASES:
            self.assertIn(cat, SPENDING_CATEGORIES)


# --------------------------------------------------------------------
# Spending aggregations
# --------------------------------------------------------------------


def _tx(date_: str, amount: float, category: str = "other",
        account: str = "A", desc: str = "x") -> Transaction:
    return Transaction(
        date=date_, account=account, description=desc,
        amount=amount, category=category,
    )


class MonthlySummaryTests(unittest.TestCase):
    def test_groups_by_month(self):
        txs = [
            _tx("2026-01-05", -100, "dining"),
            _tx("2026-01-20", -50, "groceries"),
            _tx("2026-01-31", 2000, "income"),
            _tx("2026-02-03", -80, "dining"),
            _tx("2026-02-15", 2000, "income"),
        ]
        sums = spending.monthly_summaries(txs)
        self.assertEqual([s.month for s in sums], ["2026-01", "2026-02"])
        self.assertAlmostEqual(sums[0].income, 2000)
        self.assertAlmostEqual(sums[0].spending, 150)
        self.assertAlmostEqual(sums[0].net, 1850)
        self.assertAlmostEqual(sums[0].by_category["dining"], 100)
        self.assertAlmostEqual(sums[0].by_category["groceries"], 50)
        self.assertEqual(sums[0].transaction_count, 3)

    def test_empty_input(self):
        self.assertEqual(spending.monthly_summaries([]), [])


class CategoryTrendsTests(unittest.TestCase):
    def setUp(self):
        # 3 months of data so rolling averages mean something.
        self.txs = [
            # Jan
            _tx("2026-01-05", -200, "dining"),
            _tx("2026-01-10", -300, "groceries"),
            _tx("2026-01-15", -80, "subscriptions"),
            _tx("2026-01-20", 3000, "income"),
            # Feb
            _tx("2026-02-05", -220, "dining"),
            _tx("2026-02-10", -280, "groceries"),
            _tx("2026-02-15", -80, "subscriptions"),
            _tx("2026-02-20", 3000, "income"),
            # Mar (dining jumps)
            _tx("2026-03-05", -500, "dining"),
            _tx("2026-03-10", -300, "groceries"),
            _tx("2026-03-15", -80, "subscriptions"),
            _tx("2026-03-20", 3000, "income"),
        ]

    def test_latest_and_rolling(self):
        trends = spending.category_trends(self.txs)
        dining = next(t for t in trends if t.category == "dining")
        self.assertAlmostEqual(dining.latest, 500)
        self.assertAlmostEqual(dining.previous, 220)
        # Rolling average of prior two months (jan 200, feb 220) = 210.
        self.assertAlmostEqual(dining.rolling_3mo, 210)
        self.assertAlmostEqual(dining.delta_vs_prev, 280)
        self.assertAlmostEqual(dining.delta_vs_3mo, 290)

    def test_sorted_by_latest_desc(self):
        trends = spending.category_trends(self.txs)
        self.assertEqual(
            [t.category for t in trends][:3],
            ["dining", "groceries", "subscriptions"],
        )

    def test_excludes_non_spending_by_default(self):
        trends = spending.category_trends(self.txs)
        cats = {t.category for t in trends}
        self.assertNotIn("income", cats)
        self.assertNotIn("transfer", cats)


class InsightsTests(unittest.TestCase):
    def test_flags_dining_jump_and_surplus(self):
        txs = [
            # Feb baseline.
            _tx("2026-02-05", -100, "dining"),
            _tx("2026-02-15", 3000, "income"),
            # Mar — dining triples, still in surplus.
            _tx("2026-03-05", -400, "dining"),
            _tx("2026-03-15", 3000, "income"),
        ]
        insights = spending.build_insights(txs)
        titles = " ".join(i.title for i in insights)
        self.assertIn("Net surplus", titles)
        self.assertIn("Dining up", titles)

    def test_flags_negative_net(self):
        txs = [
            _tx("2026-03-05", -3000, "dining"),
            _tx("2026-03-15", 2000, "income"),
        ]
        insights = spending.build_insights(txs)
        titles = " ".join(i.title for i in insights)
        self.assertIn("Spent", titles)
        self.assertTrue(
            any(i.severity == "urgent" for i in insights),
            "Overspend should be flagged urgent.",
        )

    def test_no_insights_on_empty(self):
        self.assertEqual(spending.build_insights([]), [])


class TotalsByAccountTests(unittest.TestCase):
    def test_splits_per_account(self):
        txs = [
            _tx("2026-03-05", -100, "dining", account="Checking"),
            _tx("2026-03-08", -200, "groceries", account="Checking"),
            _tx("2026-03-12", -50, "gas", account="Savings"),
            _tx("2026-03-15", 2000, "income", account="Checking"),
        ]
        per = spending.totals_by_account(txs, "2026-03")
        self.assertAlmostEqual(per["Checking"].spending, 300)
        self.assertAlmostEqual(per["Checking"].income, 2000)
        self.assertAlmostEqual(per["Savings"].spending, 50)


class IncomeByMonthTests(unittest.TestCase):
    def test_sums_positive_non_transfer_amounts(self):
        txs = [
            _tx("2026-01-05", 2500, "income"),
            _tx("2026-01-12", 400, "other"),  # positive non-transfer
            _tx("2026-01-20", -100, "dining"),
            _tx("2026-02-01", 2500, "income"),
            _tx("2026-02-10", 300, "transfer"),  # excluded: self-move
        ]
        by_month = spending.income_by_month(txs)
        self.assertAlmostEqual(by_month["2026-01"], 2900)
        self.assertAlmostEqual(by_month["2026-02"], 2500)


class AccountCategoryBreakdownTests(unittest.TestCase):
    def test_only_spending_shows_up(self):
        txs = [
            _tx("2026-03-05", -120, "dining", account="Checking"),
            _tx("2026-03-08", -250, "groceries", account="Checking"),
            _tx("2026-03-12", -50, "gas", account="Savings"),
            _tx("2026-03-15", 2000, "income", account="Checking"),
            _tx("2026-03-18", -100, "transfer", account="Checking"),
        ]
        breakdown = spending.account_category_breakdown(txs, "2026-03")
        self.assertIn("Checking", breakdown)
        self.assertIn("Savings", breakdown)
        self.assertAlmostEqual(breakdown["Checking"]["dining"], 120)
        self.assertAlmostEqual(breakdown["Checking"]["groceries"], 250)
        self.assertAlmostEqual(breakdown["Savings"]["gas"], 50)
        # income/transfer categories excluded
        self.assertNotIn("income", breakdown["Checking"])
        self.assertNotIn("transfer", breakdown["Checking"])


class ProjectionTests(unittest.TestCase):
    def test_projects_last_three_months_average(self):
        txs = [
            _tx("2026-01-05", -1000, "other"),
            _tx("2026-02-05", -1500, "other"),
            _tx("2026-03-05", -2000, "other"),
        ]
        self.assertAlmostEqual(
            spending.projected_monthly_spending(txs), 1500.0,
        )


class TotalSpendingByMonthTests(unittest.TestCase):
    def test_sums_outflows_excluding_transfers(self):
        txs = [
            _tx("2026-01-05", -300, "dining"),
            _tx("2026-01-10", -200, "groceries"),
            _tx("2026-01-15", -100, "transfer"),   # excluded
            _tx("2026-01-20", 2500, "income"),     # excluded (positive)
            _tx("2026-02-05", -400, "dining"),
        ]
        totals = spending.total_spending_by_month(txs)
        self.assertAlmostEqual(totals["2026-01"], 500)
        self.assertAlmostEqual(totals["2026-02"], 400)


class MonthlyDeltasTests(unittest.TestCase):
    def test_computes_dollar_and_pct_deltas(self):
        totals = {"2026-01": 1000.0, "2026-02": 1200.0, "2026-03": 900.0}
        deltas = spending.monthly_deltas(totals)
        self.assertEqual(len(deltas), 2)
        (a1, b1, d1, p1) = deltas[0]
        self.assertEqual((a1, b1), ("2026-01", "2026-02"))
        self.assertAlmostEqual(d1, 200)
        self.assertAlmostEqual(p1, 0.20, places=4)
        (a2, b2, d2, p2) = deltas[1]
        self.assertEqual((a2, b2), ("2026-02", "2026-03"))
        self.assertAlmostEqual(d2, -300)
        self.assertAlmostEqual(p2, -0.25, places=4)

    def test_empty_totals(self):
        self.assertEqual(spending.monthly_deltas({}), [])


class CategoryTrendPctByMonthTests(unittest.TestCase):
    def test_first_month_is_none_and_subsequent_have_pct(self):
        txs = [
            _tx("2026-01-05", -100, "dining"),
            _tx("2026-02-05", -150, "dining"),  # +50%
            _tx("2026-03-05", -120, "dining"),  # -20%
        ]
        trends = spending.category_trends(txs)
        dining = next(t for t in trends if t.category == "dining")
        self.assertIsNone(dining.pct_by_month["2026-01"])
        self.assertAlmostEqual(dining.pct_by_month["2026-02"], 0.5)
        self.assertAlmostEqual(dining.pct_by_month["2026-03"], -0.2)


class TopMerchantsTests(unittest.TestCase):
    def test_ranks_merchants_and_merges_noise(self):
        txs = [
            _tx("2026-03-05", -25.0, "dining", desc="TACO BELL #037203 SUGAR LAND TX"),
            _tx("2026-03-10", -18.0, "dining", desc="TACO BELL #5622 OMAHA NE"),
            _tx("2026-03-15", -120.0, "groceries", desc="KROGER #147 OMAHA NE"),
            _tx("2026-03-20", -3000, "transfer", desc="FUNDS TRANSFER"),
            _tx("2026-03-25", 2500, "income", desc="DIRECT DEPOSIT"),
        ]
        top = spending.top_merchants(txs, "2026-03", n=5)
        labels = [name for name, _ in top]
        # Kroger spends $120, Taco Bell combines to $43
        self.assertEqual(top[0][0].upper().startswith("KROGER"), True)
        self.assertAlmostEqual(top[0][1], 120.0)
        self.assertTrue(any("TACO" in l.upper() for l in labels))
        # Transfer + income are skipped
        self.assertFalse(any("TRANSFER" in l.upper() for l in labels))
        self.assertFalse(any("DIRECT DEPOSIT" in l.upper() for l in labels))


class DetectRecurringTests(unittest.TestCase):
    def test_detects_multi_month_consistent_charge(self):
        txs = [
            _tx("2026-01-05", -15.99, "subscriptions", desc="NETFLIX.COM CA"),
            _tx("2026-02-05", -15.99, "subscriptions", desc="NETFLIX.COM CA"),
            _tx("2026-03-05", -15.99, "subscriptions", desc="NETFLIX.COM CA"),
        ]
        result = spending.detect_recurring(txs)
        self.assertTrue(result, "Netflix should be flagged as recurring.")
        r = result[0]
        self.assertIn("NETFLIX", r.description.upper())
        self.assertAlmostEqual(r.typical_amount, 15.99)
        self.assertEqual(len(r.months_seen), 3)
        self.assertAlmostEqual(r.yearly_cost, round(15.99 * 12, 2))

    def test_skips_single_month_items(self):
        txs = [
            _tx("2026-01-05", -15.99, "subscriptions", desc="NETFLIX.COM CA"),
        ]
        self.assertEqual(spending.detect_recurring(txs), [])

    def test_skips_highly_variable_amounts(self):
        # Groceries vary by month → not a subscription.
        txs = [
            _tx("2026-01-05", -120, "groceries", desc="KROGER GROCERIES"),
            _tx("2026-02-05", -420, "groceries", desc="KROGER GROCERIES"),
            _tx("2026-03-05", -180, "groceries", desc="KROGER GROCERIES"),
        ]
        self.assertEqual(spending.detect_recurring(txs), [])


class CategorizeWithRulesTests(unittest.TestCase):
    def test_user_rule_overrides_builtin(self):
        from finadvisor.models import CategoryRule
        rules = [CategoryRule(match="netflix", category="entertainment")]
        # Default rule says subscriptions; user override wins.
        self.assertEqual(
            bs.categorize("NETFLIX.COM CA", rules=rules), "entertainment",
        )

    def test_rule_that_does_not_match_is_ignored(self):
        from finadvisor.models import CategoryRule
        rules = [CategoryRule(match="nomatch", category="entertainment")]
        self.assertEqual(
            bs.categorize("NETFLIX.COM CA", rules=rules), "subscriptions",
        )


class CategoryRuleModelTests(unittest.TestCase):
    def test_roundtrip_through_finance_state(self):
        from finadvisor.models import CategoryRule
        st = FinanceState(
            category_rules=[CategoryRule(match="netflix", category="entertainment")]
        )
        restored = FinanceState.from_dict(st.to_dict())
        self.assertEqual(len(restored.category_rules), 1)
        self.assertEqual(restored.category_rules[0].match, "netflix")
        self.assertEqual(restored.category_rules[0].category, "entertainment")

    def test_rejects_blank_match(self):
        from finadvisor.models import CategoryRule
        with self.assertRaises(ValueError):
            CategoryRule(match="", category="other")

    def test_rejects_unknown_category(self):
        from finadvisor.models import CategoryRule
        with self.assertRaises(ValueError):
            CategoryRule(match="x", category="vibes")


class BudgetAdviceTests(unittest.TestCase):
    """Derives income/expense averages and concrete cut suggestions
    from the transaction ledger — the engine powering the zero-input
    /budget experience."""

    def _make_txs(self) -> list[Transaction]:
        # Two months with a clear "wants-heavy" pattern: $3000 income,
        # $400 groceries (need), $600 dining out (want over threshold),
        # $200 subscriptions (want over threshold).
        txs: list[Transaction] = []
        for month in ("2026-01", "2026-02"):
            txs.extend([
                Transaction(
                    date=f"{month}-05", account="Checking",
                    description="PAYROLL", amount=3000.0, category="income",
                ),
                Transaction(
                    date=f"{month}-10", account="Checking",
                    description="KROGER", amount=-400.0, category="groceries",
                ),
                Transaction(
                    date=f"{month}-15", account="Checking",
                    description="DINING OUT", amount=-600.0, category="dining",
                ),
                Transaction(
                    date=f"{month}-20", account="Checking",
                    description="NETFLIX", amount=-200.0,
                    category="subscriptions",
                ),
                Transaction(
                    date=f"{month}-22", account="Checking",
                    description="CC PAYMENT", amount=-150.0,
                    category="debt_payment",
                ),
            ])
        return txs

    def test_derived_budget_averages_last_3_months(self):
        from finadvisor.spending import derived_budget
        income, expenses, debt, n = derived_budget(self._make_txs())
        self.assertEqual(n, 2)
        self.assertAlmostEqual(income, 3000.0)
        self.assertAlmostEqual(expenses, 1200.0)  # 400+600+200
        self.assertAlmostEqual(debt, 150.0)

    def test_budget_advice_suggests_cuts_for_wants_over_30pct(self):
        from finadvisor.spending import budget_advice
        advice = budget_advice(self._make_txs())
        # Wants total = 600 + 200 = 800 / 3000 ≈ 27%. Still under the
        # 30% cap — but both wants are >$50 so we suggest trims anyway.
        cut_cats = {s.category for s in advice.suggestions if s.is_cut}
        self.assertIn("dining", cut_cats)
        self.assertIn("subscriptions", cut_cats)
        # Each cut suggestion carries a target cap.
        for s in advice.suggestions:
            if s.is_cut:
                self.assertIsNotNone(s.target_monthly)
                self.assertLess(s.target_monthly, s.avg_monthly)

    def test_budget_advice_protects_needs(self):
        from finadvisor.spending import budget_advice
        advice = budget_advice(self._make_txs())
        # Groceries is a "need" — must appear as a NON-cut suggestion.
        groceries = next(
            (s for s in advice.suggestions if s.category == "groceries"),
            None,
        )
        self.assertIsNotNone(groceries)
        self.assertFalse(groceries.is_cut)
        self.assertEqual(groceries.severity, "good")

    def test_budget_advice_empty_transactions(self):
        from finadvisor.spending import budget_advice
        advice = budget_advice([])
        self.assertEqual(advice.months_used, 0)
        self.assertEqual(advice.suggestions, [])
        self.assertIn("Import", advice.headline)


if __name__ == "__main__":
    unittest.main()
