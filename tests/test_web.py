"""End-to-end tests for the local web UI.

These tests spin up the real HTTP server in a background thread on an
ephemeral port and drive it with urllib, so they exercise the actual
request/response path (routing, form parsing, multipart upload,
redirects, flash messages, storage round-trip).

pypdf is not available in every environment (and its dependency
`cryptography` is known to be broken on some minimal images), so the
PDF upload test monkeypatches `pdf_importer.parse` with a stub that
returns a canned extraction — we're testing the web glue here, not
pypdf itself (that's covered in test_importers.py).
"""
from __future__ import annotations

import tempfile
import threading
import unittest
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from finadvisor import storage
from finadvisor.importers import pdf_importer
from finadvisor.models import Budget, Debt, FinanceState
from finadvisor.web.server import build_server


class WebTestBase(unittest.TestCase):
    """Starts the server on a random port with a per-test temp store."""

    def setUp(self) -> None:
        self.tmpdir = tempfile.TemporaryDirectory()
        self.store = Path(self.tmpdir.name) / "finances.json"
        storage.save(self._initial_state(), self.store)
        self.server = build_server(host="127.0.0.1", port=0,
                                    store_path=self.store)
        self.port = self.server.server_address[1]
        self.thread = threading.Thread(
            target=self.server.serve_forever, daemon=True,
        )
        self.thread.start()

    def tearDown(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)
        self.tmpdir.cleanup()

    def _initial_state(self) -> FinanceState:
        return FinanceState()

    def url(self, path: str) -> str:
        return f"http://127.0.0.1:{self.port}{path}"

    def get(self, path: str) -> tuple[int, str]:
        try:
            with urllib.request.urlopen(self.url(path), timeout=5) as r:
                return r.status, r.read().decode("utf-8", errors="replace")
        except urllib.error.HTTPError as e:
            return e.code, e.read().decode("utf-8", errors="replace")

    def post(
        self, path: str, data: dict | bytes,
        content_type: str | None = None,
    ) -> tuple[int, str]:
        if isinstance(data, dict):
            body = urllib.parse.urlencode(data).encode()
            ctype = content_type or "application/x-www-form-urlencoded"
        else:
            body = data
            ctype = content_type or "application/octet-stream"
        req = urllib.request.Request(
            self.url(path), data=body, method="POST",
            headers={"Content-Type": ctype},
        )
        try:
            with urllib.request.urlopen(req, timeout=5) as r:
                return r.status, r.read().decode("utf-8", errors="replace")
        except urllib.error.HTTPError as e:
            return e.code, e.read().decode("utf-8", errors="replace")

    def state(self) -> FinanceState:
        return storage.load(self.store)


class GETRouteTests(WebTestBase):
    def _initial_state(self) -> FinanceState:
        return FinanceState(
            debts=[Debt(name="Visa", kind="credit_card", balance=1000,
                         apr=0.2, min_payment=25, credit_limit=5000)],
            budget=Budget(monthly_income=5000, monthly_expenses=3000),
        )

    def test_dashboard_loads(self):
        code, body = self.get("/")
        self.assertEqual(code, 200)
        self.assertIn("Dashboard", body)
        self.assertIn("Total debt", body)

    def test_dashboard_alias(self):
        code, _ = self.get("/dashboard")
        self.assertEqual(code, 200)

    def test_debts_lists_existing(self):
        code, body = self.get("/debts")
        self.assertEqual(code, 200)
        self.assertIn("Visa", body)
        self.assertIn("Add a debt", body)

    def test_debts_edit_mode(self):
        code, body = self.get("/debts?edit=Visa")
        self.assertEqual(code, 200)
        self.assertIn('name="orig_name"', body)
        self.assertIn('value="Visa"', body)

    def test_budget_loads(self):
        code, body = self.get("/budget")
        self.assertEqual(code, 200)
        self.assertIn("Monthly income", body)

    def test_analysis_loads_and_runs_strategies(self):
        code, body = self.get("/analysis")
        self.assertEqual(code, 200)
        self.assertIn("Avalanche", body)
        self.assertIn("Snowball", body)
        # what-if form is always rendered
        self.assertIn('name="extra"', body)

    def test_analysis_whatif(self):
        code, body = self.get("/analysis?extra=200")
        self.assertEqual(code, 200)
        self.assertIn("What-if", body)

    def test_analysis_ignores_bad_extra(self):
        code, body = self.get("/analysis?extra=abc")
        self.assertEqual(code, 200)

    def test_import_shows_both_forms(self):
        code, body = self.get("/import")
        self.assertEqual(code, 200)
        self.assertIn('enctype="multipart/form-data"', body)
        self.assertIn('name="pdf"', body)
        self.assertIn('name="csv"', body)
        self.assertIn("multiple", body)  # multi-file upload enabled

    def test_healthz(self):
        code, body = self.get("/healthz")
        self.assertEqual(code, 200)
        self.assertEqual(body, "ok")

    def test_unknown_route_404(self):
        code, _ = self.get("/does-not-exist")
        self.assertEqual(code, 404)


class DebtMutationTests(WebTestBase):
    def test_add_then_delete(self):
        code, body = self.post("/debts/add", {
            "name": "Test", "kind": "credit_card", "balance": "500",
            "apr": "0.15", "min_payment": "20", "credit_limit": "1000",
        })
        self.assertEqual(code, 200)
        self.assertIn("Added Test", body)
        self.assertEqual([d.name for d in self.state().debts], ["Test"])

        code, body = self.post("/debts/delete", {"name": "Test"})
        self.assertEqual(code, 200)
        self.assertIn("Removed Test", body)
        self.assertEqual(self.state().debts, [])

    def test_add_rejects_negative_balance(self):
        _, body = self.post("/debts/add", {
            "name": "Bad", "kind": "credit_card", "balance": "-1",
            "apr": "0.1", "min_payment": "10",
        })
        self.assertIn("Balance cannot be negative", body)
        self.assertEqual(self.state().debts, [])

    def test_edit_updates_in_place(self):
        self.post("/debts/add", {
            "name": "OldName", "kind": "credit_card", "balance": "100",
            "apr": "0.1", "min_payment": "10",
        })
        code, body = self.post("/debts/edit", {
            "orig_name": "OldName", "name": "NewName", "kind": "credit_card",
            "balance": "200", "apr": "0.12", "min_payment": "15",
        })
        self.assertEqual(code, 200)
        self.assertIn("Updated NewName", body)
        debts = self.state().debts
        self.assertEqual(len(debts), 1)
        self.assertEqual(debts[0].name, "NewName")
        self.assertEqual(debts[0].balance, 200)

    def test_edit_rejects_name_collision(self):
        for name in ("A", "B"):
            self.post("/debts/add", {
                "name": name, "kind": "other", "balance": "10",
                "apr": "0.1", "min_payment": "1",
            })
        _, body = self.post("/debts/edit", {
            "orig_name": "A", "name": "B", "kind": "other",
            "balance": "10", "apr": "0.1", "min_payment": "1",
        })
        self.assertIn("already exists", body)


class BudgetTests(WebTestBase):
    def test_budget_updates(self):
        code, body = self.post("/budget", {
            "income": "6000", "expenses": "3500",
            "savings": "1200", "consolidation_apr": "0.08",
        })
        self.assertEqual(code, 200)
        self.assertIn("Budget updated", body)
        s = self.state()
        self.assertEqual(s.budget.monthly_income, 6000)
        self.assertEqual(s.budget.monthly_expenses, 3500)
        self.assertEqual(s.current_savings, 1200)
        self.assertAlmostEqual(s.consolidation_apr, 0.08)


class CSVImportTests(WebTestBase):
    def test_csv_paste_imports(self):
        csv = (
            "name,balance,apr,min_payment\n"
            "Paste Card,3000,0.18,80\n"
            "Paste Loan,9000,0.06,150\n"
        )
        code, body = self.post("/import", {"csv": csv})
        self.assertEqual(code, 200)
        self.assertIn("Imported CSV", body)
        names = [d.name for d in self.state().debts]
        self.assertEqual(names, ["Paste Card", "Paste Loan"])

    def test_empty_csv_flashes_error(self):
        _, body = self.post("/import", {"csv": ""})
        self.assertIn("No CSV content", body)

    def test_bad_csv_shows_error(self):
        _, body = self.post("/import", {"csv": "not,a,valid,csv\n"})
        self.assertIn("Missing required columns", body)


class SpendingRoutesTests(WebTestBase):
    """Verify the /spending and /trends pages render with empty and
    populated transaction ledgers, and that pasted statements flow into
    the persisted spending data."""

    SAMPLE = (
        "Statement Period 02/01/2026 to 02/28/2026\n"
        "USAA Federal Savings Bank\n"
        "USAA CLASSIC CHECKING\n"
        "Account Number: 123456789\n"
        "Date Description Debits Credits Balance\n"
        "02/02 PAYROLL DIRECT DEP $2500.00 $3000.00\n"
        "02/05 DEBIT CARD PURCHASE TACO BELL $8.07 $2991.93\n"
        "02/12 KROGER GROCERIES $124.33 $2867.60\n"
        "02/17 USAA CREDIT CARD PAYMENT $45.00 $2822.60\n"
        "CREDIT CARD ENDING IN 6421\n"
        "02/20 NETFLIX SUBSCRIPTION $15.99 $2806.61\n"
    )

    def test_spending_empty_shows_welcome(self):
        code, body = self.get("/spending")
        self.assertEqual(code, 200)
        self.assertIn("No transactions yet", body)

    def test_trends_empty_shows_hint(self):
        code, body = self.get("/trends")
        self.assertEqual(code, 200)
        self.assertIn("Not enough data", body)

    def test_statement_paste_populates_spending(self):
        # First, feed a statement through the paste route.
        code, _ = self.post(
            "/import/statement", {"statement": self.SAMPLE},
        )
        self.assertEqual(code, 200)
        s = self.state()
        self.assertGreater(len(s.transactions), 0)
        self.assertGreaterEqual(len(s.accounts), 1)

        code, body = self.get("/spending")
        self.assertEqual(code, 200)
        self.assertIn("Spending", body)
        # Coach-notes block is always rendered once there's data.
        self.assertIn("Coach notes", body)
        # The latest-month by-category section should mention at least
        # one of the canonical categories we seeded.
        self.assertTrue(
            "Groceries" in body
            or "Subscriptions" in body
            or "Dining" in body
        )

    def test_trends_renders_with_data(self):
        self.post("/import/statement", {"statement": self.SAMPLE})
        code, body = self.get("/trends")
        self.assertEqual(code, 200)
        self.assertIn("Trends", body)
        self.assertIn("3-month projection", body)


class StatementPasteTests(WebTestBase):
    """The /import/statement route parses transaction text and shows
    the same checklist as a PDF upload — without needing pypdf."""

    SAMPLE = (
        "Date Description Debits Credits Balance\n"
        "02/17 DEBIT CARD PURCHASE 021426 TACO BELL $8.07 $2,707.18\n"
        "02/17 USAA CREDIT CARD PAYMENT $45.00 $2,495.62\n"
        "CREDIT CARD ENDING IN 6421\n"
        "02/17 USAA LOAN PAYMENT $542.12 $357.75\n"
        "LOAN NUMBER ENDING IN 3351\n"
    )

    def test_paste_renders_checklist(self):
        code, body = self.post("/import/statement", {"statement": self.SAMPLE})
        self.assertEqual(code, 200)
        self.assertIn("Confirm transactions", body)
        self.assertIn("Found 3 debit transactions", body)
        self.assertIn("Usaa Card 6421", body)

    def test_paste_empty_text_flashes_error(self):
        _, body = self.post("/import/statement", {"statement": "   "})
        self.assertIn("Paste some transaction text", body)

    def test_paste_no_debits_flashes_error(self):
        _, body = self.post(
            "/import/statement",
            {"statement": "no dates here\njust some text\n"},
        )
        self.assertIn("No dated debit rows", body)


class PDFUploadTests(WebTestBase):
    """Exercise the multipart upload flow with a stubbed pdf_importer."""

    SAMPLE_STATEMENT = (
        "Transactions (continued)\n"
        "Date Description Debits Credits Balance\n"
        "02/17 DEBIT CARD PURCHASE 021426 TACO BELL $8.07 $2,707.18\n"
        "02/17 USAA CREDIT CARD PAYMENT $45.00 $2,495.62\n"
        "CREDIT CARD ENDING IN 6421\n"
        "02/17 USAA LOAN PAYMENT $542.12 $357.75\n"
        "LOAN NUMBER ENDING IN 3351\n"
    )

    def setUp(self) -> None:
        super().setUp()
        self._real_parse = pdf_importer.parse

    def tearDown(self) -> None:
        pdf_importer.parse = self._real_parse
        super().tearDown()

    def _install_stub(self, text: str) -> None:
        def fake_parse(path):
            return pdf_importer.PDFExtraction(
                suggested_name="statement",
                raw_text=text,
                balance=None, apr=None, min_payment=None, credit_limit=None,
                guessed_kind="other",
            )
        pdf_importer.parse = fake_parse

    @staticmethod
    def _multipart_body(
        files: list[tuple[str, str, bytes]], boundary: bytes = b"----testbnd"
    ) -> tuple[bytes, str]:
        """Build a multipart/form-data body.

        files: list of (field_name, filename, content) tuples.
        """
        parts = []
        for name, filename, content in files:
            parts.append(
                b"--" + boundary + b"\r\n"
                + f'Content-Disposition: form-data; name="{name}"; '
                  f'filename="{filename}"\r\n'.encode()
                + b"Content-Type: application/pdf\r\n\r\n"
                + content + b"\r\n"
            )
        body = b"".join(parts) + b"--" + boundary + b"--\r\n"
        return body, f"multipart/form-data; boundary={boundary.decode()}"

    def test_upload_bank_statement_shows_checklist(self):
        self._install_stub(self.SAMPLE_STATEMENT)
        body, ctype = self._multipart_body(
            [("pdf", "feb.pdf", b"%PDF-1.4\nstub\n%%EOF\n")]
        )
        code, html = self.post("/import/pdf", body, content_type=ctype)
        self.assertEqual(code, 200)
        self.assertIn("Confirm transactions", html)
        self.assertIn("Found 3 debit transactions", html)
        # Credit-card + loan payment pre-checked; taco bell not.
        self.assertIn("Usaa Card 6421", html)
        self.assertIn("Usaa Loan 3351", html)

    def test_upload_no_file_flashes_error(self):
        self._install_stub(self.SAMPLE_STATEMENT)
        body, ctype = self._multipart_body(
            [("pdf", "", b"")]
        )
        code, html = self.post("/import/pdf", body, content_type=ctype)
        self.assertEqual(code, 200)
        self.assertIn("No PDF file selected", html)

    def test_upload_multiple_statements_merges(self):
        self._install_stub(self.SAMPLE_STATEMENT)
        body, ctype = self._multipart_body([
            ("pdf", "feb.pdf", b"%PDF-1.4\na\n%%EOF\n"),
            ("pdf", "mar.pdf", b"%PDF-1.4\nb\n%%EOF\n"),
        ])
        code, html = self.post("/import/pdf", body, content_type=ctype)
        self.assertEqual(code, 200)
        # Both statements should contribute 3 debit rows each = 6 total.
        self.assertIn("Found 6 debit transactions", html)
        # Source column appears when >1 upload.
        self.assertIn("<th>Source</th>", html)
        self.assertIn("feb", html)
        self.assertIn("mar", html)

    def test_upload_non_statement_falls_back_to_single_debt_confirm(self):
        self._install_stub("Chase Freedom\nNew Balance: $1,234.56\n"
                            "Purchase APR: 19.99%\n"
                            "Minimum Payment Due: $25.00\n"
                            "Credit Limit: $5,000\n")
        body, ctype = self._multipart_body(
            [("pdf", "card.pdf", b"%PDF-1.4\nx\n%%EOF\n")]
        )
        code, html = self.post("/import/pdf", body, content_type=ctype)
        self.assertEqual(code, 200)
        self.assertIn("Confirm imported debt", html)


class TransactionsSaveTests(WebTestBase):
    def test_save_creates_debts_and_adds_expenses(self):
        # Simulate what the confirm form would POST:
        # 3 rows, user checks rows 0 and 2, leaves row 1 unchecked,
        # and checks "add unselected to expenses".
        form = {
            "amount_0": "45.00",
            "name_0": "USAA Card 6421",
            "kind_0": "credit_card",
            "balance_0": "2500.00",   # user filled in balance on the row
            "select_0": "on",

            "amount_1": "8.07",       # Taco Bell — unchecked
            "name_1": "Taco Bell",
            "kind_1": "other",

            "amount_2": "542.12",
            "name_2": "USAA Loan 3351",
            "kind_2": "personal",
            "select_2": "on",

            "add_unselected_to_expenses": "1",
        }
        code, body = self.post(
            "/import/pdf/transactions/save", form,
        )
        self.assertEqual(code, 200)
        self.assertIn("imported 2 debt(s)", body)
        self.assertIn("added $8.07 to monthly expenses", body)

        state = self.state()
        names = {d.name for d in state.debts}
        self.assertEqual(names, {"USAA Card 6421", "USAA Loan 3351"})
        card = next(d for d in state.debts if d.name == "USAA Card 6421")
        self.assertAlmostEqual(card.min_payment, 45.0)
        # Balance filled in by user on the row flows through.
        self.assertAlmostEqual(card.balance, 2500.0)
        # APR defaults to the per-kind default (credit_card → 22%).
        self.assertAlmostEqual(card.apr, 0.22)
        loan = next(d for d in state.debts if d.name == "USAA Loan 3351")
        # Balance left blank on the row → stays 0 (user will fill later).
        self.assertEqual(loan.balance, 0.0)
        # Personal loans default to 12%.
        self.assertAlmostEqual(loan.apr, 0.12)
        self.assertEqual(state.budget.monthly_expenses, 8.07)

    def test_nothing_selected_and_no_expense_bump_flashes_error(self):
        code, body = self.post("/import/pdf/transactions/save", {
            "amount_0": "10.00", "name_0": "X", "kind_0": "other",
        })
        self.assertEqual(code, 200)
        self.assertIn("nothing to do", body)

    def test_duplicate_name_is_skipped(self):
        self.post("/debts/add", {
            "name": "X", "kind": "other", "balance": "5",
            "apr": "0.1", "min_payment": "1",
        })
        form = {
            "amount_0": "99.00",
            "name_0": "X",
            "kind_0": "other",
            "select_0": "on",
        }
        _, body = self.post("/import/pdf/transactions/save", form)
        self.assertIn("1 skipped", body)
        # Original debt unchanged.
        debt = next(d for d in self.state().debts if d.name == "X")
        self.assertEqual(debt.balance, 5)


if __name__ == "__main__":
    unittest.main()
