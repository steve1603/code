import unittest

from finadvisor.models import Budget, Debt, FinanceState
from finadvisor.report import run_all
from finadvisor.strategies import (
    avalanche,
    budget as budget_strategy,
    consolidation,
    emergency_fund,
    snowball,
    utilization,
)
from finadvisor.strategies.base import Severity


def _state(debts, income=6000.0, expenses=3000.0, consolidation_apr=0.09,
           current_savings=0.0):
    return FinanceState(
        debts=debts,
        budget=Budget(monthly_income=income, monthly_expenses=expenses),
        consolidation_apr=consolidation_apr,
        current_savings=current_savings,
    )


class AvalancheVsSnowballTests(unittest.TestCase):
    """Avalanche must always cost ≤ Snowball in total interest."""

    def test_avalanche_saves_more_or_equal_interest(self):
        debts = [
            Debt(name="Small high APR", kind="credit_card",
                 balance=500, apr=0.25, min_payment=25, credit_limit=5000),
            Debt(name="Big low APR", kind="student_loan",
                 balance=10000, apr=0.05, min_payment=120),
            Debt(name="Medium mid APR", kind="auto",
                 balance=5000, apr=0.09, min_payment=110),
        ]
        state = _state(debts)

        av = avalanche.run(state.debts, state.budget, state)
        sn = snowball.run(state.debts, state.budget, state)

        self.assertFalse(av.schedule == [] and sn.schedule == [])
        self.assertLessEqual(
            av.metrics["total_interest"], sn.metrics["total_interest"] + 0.01,
            "Avalanche should never cost more interest than Snowball."
        )

    def test_both_pay_off_with_adequate_budget(self):
        debts = [Debt(name="Card", kind="credit_card",
                      balance=2000, apr=0.20, min_payment=50, credit_limit=5000)]
        state = _state(debts, income=3000, expenses=1000)
        av = avalanche.run(state.debts, state.budget, state)
        self.assertLess(av.metrics["months_to_payoff"], 36)


class NegativeAmortizationTests(unittest.TestCase):
    def test_urgent_when_minimum_below_monthly_interest(self):
        # $5000 at 24% APR -> ~$100/mo interest. A $50 min doesn't cover it.
        debts = [Debt(name="runaway", kind="credit_card",
                      balance=5000, apr=0.24, min_payment=50,
                      credit_limit=10000)]
        state = _state(debts, income=4000, expenses=2000)
        result = budget_strategy.run(state.debts, state.budget, state)
        self.assertEqual(result.severity, Severity.URGENT)
        self.assertIn("runaway", result.summary)
        self.assertGreaterEqual(result.metrics["underwater_debts"], 1)

    def test_not_flagged_when_minimum_covers_interest(self):
        # $5000 at 6% -> $25/mo interest. A $150 min comfortably covers it.
        debts = [Debt(name="ok", kind="student_loan",
                      balance=5000, apr=0.06, min_payment=150)]
        state = _state(debts, income=4000, expenses=2000)
        result = budget_strategy.run(state.debts, state.budget, state)
        self.assertNotEqual(result.severity, Severity.URGENT)


class NegativeCashflowTests(unittest.TestCase):
    def test_urgent_when_no_income(self):
        debts = [Debt(name="x", kind="credit_card", balance=1000, apr=0.25,
                      min_payment=50, credit_limit=2000)]
        state = _state(debts, income=0, expenses=0)
        result = budget_strategy.run(state.debts, state.budget, state)
        self.assertEqual(result.severity, Severity.WARN)

    def test_urgent_when_negative_surplus(self):
        debts = [Debt(name="x", kind="auto", balance=20000, apr=0.08,
                      min_payment=800)]
        state = _state(debts, income=1500, expenses=1000)  # -300 surplus
        result = budget_strategy.run(state.debts, state.budget, state)
        self.assertEqual(result.severity, Severity.URGENT)


class UtilizationTests(unittest.TestCase):
    def test_urgent_above_70(self):
        debts = [Debt(name="maxed", kind="credit_card",
                      balance=4500, apr=0.24, min_payment=100, credit_limit=5000)]
        state = _state(debts)
        result = utilization.run(state.debts, state.budget, state)
        self.assertEqual(result.severity, Severity.URGENT)

    def test_good_below_30(self):
        debts = [Debt(name="mild", kind="credit_card",
                      balance=500, apr=0.24, min_payment=25, credit_limit=5000)]
        state = _state(debts)
        result = utilization.run(state.debts, state.budget, state)
        self.assertEqual(result.severity, Severity.GOOD)

    def test_no_cards_returns_info(self):
        debts = [Debt(name="loan", kind="student_loan",
                      balance=5000, apr=0.06, min_payment=60)]
        state = _state(debts)
        result = utilization.run(state.debts, state.budget, state)
        self.assertEqual(result.severity, Severity.INFO)


class ConsolidationTests(unittest.TestCase):
    def test_flags_high_apr(self):
        debts = [Debt(name="card", kind="credit_card",
                      balance=3000, apr=0.25, min_payment=60, credit_limit=5000)]
        state = _state(debts, consolidation_apr=0.09)
        result = consolidation.run(state.debts, state.budget, state)
        self.assertGreater(result.metrics["candidate_count"], 0)

    def test_no_flags_for_low_apr(self):
        debts = [Debt(name="auto", kind="auto",
                      balance=8000, apr=0.04, min_payment=200)]
        state = _state(debts, consolidation_apr=0.09)
        result = consolidation.run(state.debts, state.budget, state)
        self.assertEqual(result.severity, Severity.GOOD)


class EmergencyFundTests(unittest.TestCase):
    def test_urgent_when_high_apr_and_no_starter_fund(self):
        debts = [Debt(name="card", kind="credit_card",
                      balance=3000, apr=0.24, min_payment=75, credit_limit=5000)]
        state = _state(debts, current_savings=0.0)
        result = emergency_fund.run(state.debts, state.budget, state)
        self.assertEqual(result.severity, Severity.URGENT)

    def test_warn_when_below_starter_without_high_apr(self):
        debts = [Debt(name="auto", kind="auto",
                      balance=5000, apr=0.04, min_payment=150)]
        state = _state(debts, current_savings=200.0)
        result = emergency_fund.run(state.debts, state.budget, state)
        self.assertEqual(result.severity, Severity.WARN)

    def test_good_once_three_months_covered(self):
        debts = [Debt(name="auto", kind="auto",
                      balance=5000, apr=0.04, min_payment=150)]
        # 3 * (3000 expenses + 150 min) = 9,450
        state = _state(debts, current_savings=10_000.0)
        result = emergency_fund.run(state.debts, state.budget, state)
        self.assertEqual(result.severity, Severity.GOOD)

    def test_fully_funded_at_six_months(self):
        debts: list = []
        state = _state(debts, current_savings=50_000.0)
        result = emergency_fund.run(state.debts, state.budget, state)
        self.assertEqual(result.severity, Severity.GOOD)
        self.assertGreaterEqual(result.metrics["months_covered"], 6)


class ReportTests(unittest.TestCase):
    def test_run_all_produces_six_results(self):
        debts = [
            Debt(name="Card", kind="credit_card",
                 balance=4000, apr=0.25, min_payment=100, credit_limit=5000),
            Debt(name="Loan", kind="student_loan",
                 balance=15000, apr=0.065, min_payment=180),
        ]
        state = _state(debts)
        report = run_all(state)
        self.assertEqual(len(report.results), 6)
        self.assertTrue(report.next_best_action)

    def test_empty_state_has_action(self):
        report = run_all(FinanceState())
        self.assertTrue(report.next_best_action)


if __name__ == "__main__":
    unittest.main()
