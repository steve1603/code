"""Tests for the what-if scenarios engine (stress test, windfall,
savings ladder) — pure functions, no Qt, no I/O."""
from __future__ import annotations

import unittest

from finadvisor.models import Budget, Debt, Transaction
from finadvisor.scenarios import (
    savings_ladder,
    stress_test,
    windfall_impact,
)


def _txs(income_per_month: float, essentials_per_month: float):
    out = []
    for month in ("2026-01", "2026-02"):
        out.append(Transaction(
            date=f"{month}-03", account="Checking",
            description="PAYROLL", amount=income_per_month,
            category="income",
        ))
        out.append(Transaction(
            date=f"{month}-10", account="Checking",
            description="RENT", amount=-essentials_per_month,
            category="home",
        ))
    return out


class StressTestTests(unittest.TestCase):
    def test_runway_full_loss(self):
        debts = [Debt(name="Visa", kind="credit_card", balance=1000,
                      apr=0.20, min_payment=100)]
        result = stress_test(
            _txs(5000, 2000), debts,
            current_savings=6300, household_size=1,
        )
        # Burn = 2000 essentials + 100 minimums = 2100/mo.
        self.assertAlmostEqual(result.monthly_burn, 2100.0)
        self.assertAlmostEqual(result.runway_months_full_loss, 3.0)
        self.assertFalse(result.one_income_applicable)

    def test_dual_income_resilient_when_half_covers_burn(self):
        result = stress_test(
            _txs(6000, 2000), [],
            monthly_income=6000, current_savings=1000, household_size=2,
        )
        # Half income = 3000 > 2000 burn → one-income loss is covered.
        self.assertTrue(result.one_income_applicable)
        self.assertIsNone(result.runway_months_one_income)

    def test_dual_income_deficit_runway(self):
        debts = [Debt(name="Visa", kind="credit_card", balance=1000,
                      apr=0.20, min_payment=500)]
        result = stress_test(
            _txs(4000, 2500), debts,
            monthly_income=4000, current_savings=2000, household_size=2,
        )
        # Burn = 3000; half income = 2000; deficit = 1000/mo → 2 months.
        self.assertAlmostEqual(result.runway_months_one_income, 2.0)

    def test_no_history_flags_note(self):
        result = stress_test([], [], current_savings=500, household_size=1)
        self.assertTrue(any("No transaction history" in n
                            for n in result.notes))


class WindfallTests(unittest.TestCase):
    def _debts(self):
        return [
            Debt(name="Visa", kind="credit_card", balance=3000,
                 apr=0.2499, min_payment=90),
            Debt(name="Car", kind="auto", balance=8000,
                 apr=0.06, min_payment=250),
        ]

    def test_windfall_saves_months_and_interest(self):
        budget = Budget(monthly_income=4000, monthly_expenses=3000)
        result = windfall_impact(self._debts(), budget, 2000)
        self.assertIsNotNone(result)
        self.assertGreater(result.months_saved, 0)
        self.assertGreater(result.interest_saved, 0)
        self.assertLess(result.boosted_months, result.baseline_months)

    def test_lump_clears_highest_apr_debt_first(self):
        budget = Budget(monthly_income=4000, monthly_expenses=3000)
        result = windfall_impact(self._debts(), budget, 3000)
        self.assertIn("Visa", result.debts_cleared)
        self.assertNotIn("Car", result.debts_cleared)

    def test_lump_covering_everything(self):
        budget = Budget(monthly_income=4000, monthly_expenses=3000)
        result = windfall_impact(self._debts(), budget, 20000)
        self.assertEqual(result.boosted_months, 0)
        self.assertIn("wipes out every debt", result.headline)

    def test_zero_lump_or_no_debts_returns_none(self):
        budget = Budget(monthly_income=4000, monthly_expenses=3000)
        self.assertIsNone(windfall_impact(self._debts(), budget, 0))
        self.assertIsNone(windfall_impact([], budget, 500))


class SavingsLadderTests(unittest.TestCase):
    def test_rungs_for_dual_income_household(self):
        rungs = savings_ladder(5000, 2000, household_size=2)
        labels = [r.label for r in rungs]
        self.assertEqual(len(rungs), 3)
        self.assertIn("Starter fund", labels[0])
        # $5k: starter ($1k) reached, 3-mo ($6k) partial, 6-mo not.
        self.assertTrue(rungs[0].reached)
        self.assertFalse(rungs[1].reached)
        self.assertAlmostEqual(rungs[1].fraction, 5000 / 6000)
        self.assertFalse(rungs[2].reached)

    def test_single_earner_omits_six_month_rung(self):
        rungs = savings_ladder(500, 2000, household_size=1)
        self.assertEqual(len(rungs), 2)
        self.assertFalse(rungs[0].reached)  # $500 < $1k starter

    def test_no_essentials_yields_starter_only(self):
        rungs = savings_ladder(1500, 0.0, household_size=2)
        self.assertEqual(len(rungs), 1)
        self.assertTrue(rungs[0].reached)


if __name__ == "__main__":
    unittest.main()
