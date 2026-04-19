import unittest

from finadvisor.models import Budget, Debt, FinanceState


class DebtTests(unittest.TestCase):
    def test_valid_credit_card(self):
        d = Debt(
            name="Card A", kind="credit_card",
            balance=1000.0, apr=0.24, min_payment=25.0, credit_limit=5000.0,
        )
        self.assertAlmostEqual(d.utilization, 0.2)

    def test_rejects_bad_apr(self):
        with self.assertRaises(ValueError):
            Debt(name="x", kind="other", balance=0, apr=1.5, min_payment=0)

    def test_rejects_negative_balance(self):
        with self.assertRaises(ValueError):
            Debt(name="x", kind="other", balance=-1, apr=0.1, min_payment=0)

    def test_rejects_unknown_kind(self):
        with self.assertRaises(ValueError):
            Debt(name="x", kind="weird", balance=0, apr=0.1, min_payment=0)

    def test_utilization_none_for_non_cards(self):
        d = Debt(name="Loan", kind="student_loan", balance=1000, apr=0.05, min_payment=50)
        self.assertIsNone(d.utilization)

    def test_roundtrip_dict(self):
        d = Debt(name="Card", kind="credit_card", balance=100, apr=0.2,
                 min_payment=10, credit_limit=1000, due_day=15)
        d2 = Debt.from_dict(d.to_dict())
        self.assertEqual(d, d2)


class BudgetTests(unittest.TestCase):
    def test_extra_capacity(self):
        b = Budget(monthly_income=5000, monthly_expenses=3000)
        debts = [Debt(name="x", kind="other", balance=1000, apr=0.1, min_payment=100)]
        self.assertEqual(b.extra_payment_capacity(debts), 1900)

    def test_rejects_negative(self):
        with self.assertRaises(ValueError):
            Budget(monthly_income=-1, monthly_expenses=0)


class FinanceStateTests(unittest.TestCase):
    def test_weighted_apr(self):
        state = FinanceState(
            debts=[
                Debt(name="A", kind="other", balance=1000, apr=0.10, min_payment=10),
                Debt(name="B", kind="other", balance=1000, apr=0.20, min_payment=10),
            ],
        )
        self.assertAlmostEqual(state.weighted_average_apr(), 0.15)

    def test_empty_state_apr_is_zero(self):
        self.assertEqual(FinanceState().weighted_average_apr(), 0.0)

    def test_state_roundtrip(self):
        state = FinanceState(
            debts=[Debt(name="x", kind="other", balance=100, apr=0.1, min_payment=5)],
            budget=Budget(monthly_income=1000, monthly_expenses=500),
            consolidation_apr=0.08,
            current_savings=750.0,
        )
        reloaded = FinanceState.from_dict(state.to_dict())
        self.assertEqual(len(reloaded.debts), 1)
        self.assertEqual(reloaded.budget.monthly_income, 1000)
        self.assertAlmostEqual(reloaded.consolidation_apr, 0.08)
        self.assertAlmostEqual(reloaded.current_savings, 750.0)

    def test_rejects_negative_savings(self):
        with self.assertRaises(ValueError):
            FinanceState(current_savings=-1.0)


if __name__ == "__main__":
    unittest.main()
