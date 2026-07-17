"""Stdlib HTTP server that serves the finadvisor web UI.

Uses only the Python standard library so it runs on minimal setups like
Termux on Android. No network calls are ever made — the server only
binds locally and reads/writes the same JSON store as the GUI and CLI.
"""
from __future__ import annotations

import csv
import io
import tempfile
import traceback
from dataclasses import replace
from email.parser import BytesParser
from email.policy import default as email_default_policy
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

from finadvisor import storage
from finadvisor.importers.csv_importer import (
    REQUIRED_COLUMNS,
    _guess_kind_from_name,
)
from finadvisor.importers import bank_statement, pdf_importer, transactions_csv
from finadvisor.models import (
    Account, Budget, CategoryRule, Debt,
    Transaction as StoredTransaction,
)
from finadvisor.report import run_all
from finadvisor import scenarios as scenarios_module
from finadvisor import spending as spending_module
from finadvisor.web import templates


# A single-shot flash passed across the redirect via an in-memory slot.
# Good enough for a local single-user server; no cross-tab persistence
# needed.
_FLASH: dict[str, str] = {}


def _set_flash(kind: str, msg: str) -> None:
    _FLASH["kind"] = kind
    _FLASH["msg"] = msg


def _pop_flash() -> str:
    if not _FLASH:
        return ""
    kind = _FLASH.pop("kind", "success")
    msg = _FLASH.pop("msg", "")
    if not msg:
        return ""
    return (
        templates.flash_error(msg) if kind == "error"
        else templates.flash_success(msg)
    )


def _parse_csv_text(text: str) -> list[Debt]:
    reader = csv.DictReader(io.StringIO(text))
    if not reader.fieldnames:
        raise ValueError("CSV has no header row.")
    missing = REQUIRED_COLUMNS - set(reader.fieldnames)
    if missing:
        raise ValueError(
            f"Missing required columns: {', '.join(sorted(missing))}"
        )
    debts: list[Debt] = []
    for line_no, row in enumerate(reader, start=2):
        if not any((v or "").strip() for v in row.values()):
            continue
        if not (row.get("kind") or "").strip():
            row["kind"] = _guess_kind_from_name(row.get("name") or "")
        try:
            debts.append(Debt.from_dict(row))
        except (ValueError, KeyError) as e:
            raise ValueError(f"Row {line_no}: {e}") from e
    return debts


def _float(form: dict[str, list[str]], key: str, default: float = 0.0) -> float:
    raw = (form.get(key, [""])[0] or "").strip()
    if not raw:
        return default
    return float(raw)


def _opt_float(form: dict[str, list[str]], key: str) -> float | None:
    raw = (form.get(key, [""])[0] or "").strip()
    if not raw:
        return None
    return float(raw)


def _str(form: dict[str, list[str]], key: str, default: str = "") -> str:
    return (form.get(key, [default])[0] or default).strip()


def _candidate_debts_from_transactions(state) -> list[dict]:
    """Surface recurring debt-like transactions as candidate debts
    when the user has no debts on file yet. Skipped entirely once
    state.debts is non-empty so we don't spam the Analysis page for
    users who have already set up their debts.
    """
    if state.debts:
        return []
    recurring = spending_module.detect_recurring(
        state.transactions, min_months=1,
    )
    out: list[dict] = []
    for r in recurring:
        if r.category != "debt_payment":
            continue
        months_str = ", ".join(r.months_seen) if r.months_seen else ""
        # Very rough: treat any debt_payment recurring charge as a
        # credit_card unless the description hints at something else.
        desc_l = r.description.lower()
        if "mortgage" in desc_l:
            kind = "mortgage"
        elif "auto" in desc_l or "car" in desc_l:
            kind = "auto"
        elif "student" in desc_l or "navient" in desc_l or "nelnet" in desc_l:
            kind = "student_loan"
        elif "loan" in desc_l:
            kind = "personal"
        else:
            kind = "credit_card"
        out.append({
            "name": r.description,
            "kind": kind,
            "monthly": r.monthly_cost,
            "months_seen_str": months_str,
        })
    return out[:8]  # limit so the panel doesn't overwhelm on busy ledgers


def _rule_match_from_description(description: str) -> str:
    """Derive a durable `CategoryRule.match` substring from a raw
    transaction description. We strip store numbers / location suffixes
    via `spending._normalize_merchant`, then keep only the first few
    tokens — enough to identify the merchant ("NETFLIX COM", "OPPD
    AUTOPAY") without being so specific that small variations miss.
    """
    normalized = spending_module._normalize_merchant(description)
    if not normalized:
        return description.strip().lower()[:32]
    # Keep up to the first three tokens so "RECURRING DEB CARD PURCH
    # EXPERIAN CREDIT REPORT" collapses to "experian credit report".
    tokens = normalized.split()
    return " ".join(tokens[:3]).lower()


def _parse_multipart(content_type: str, body: bytes) -> tuple[
    dict[str, list[str]], dict[str, list[tuple[str, bytes]]]
]:
    """Parse a multipart/form-data body using stdlib email.parser.

    Returns (text fields, file fields). File field values are
    (filename, raw bytes) tuples.
    """
    # Build a synthetic email message: headers then body.
    raw = (
        f"Content-Type: {content_type}\r\n"
        f"MIME-Version: 1.0\r\n\r\n"
    ).encode() + body
    msg = BytesParser(policy=email_default_policy).parsebytes(raw)
    fields: dict[str, list[str]] = {}
    files: dict[str, list[tuple[str, bytes]]] = {}
    if not msg.is_multipart():
        return fields, files
    for part in msg.iter_parts():
        disp = part.get("Content-Disposition", "")
        if "form-data" not in disp:
            continue
        name = part.get_param("name", header="Content-Disposition")
        if not name:
            continue
        filename = part.get_param("filename", header="Content-Disposition")
        payload = part.get_payload(decode=True) or b""
        if filename:
            files.setdefault(name, []).append((filename, payload))
        else:
            fields.setdefault(name, []).append(
                payload.decode("utf-8", errors="replace")
            )
    return fields, files


def _ingest_statement(
    text: str, source_name: str, state,
) -> tuple[bank_statement.StatementMetadata, list, int]:
    """Parse a statement's text into transactions and fold them into
    `state` as Account + Transaction records.

    Returns (metadata, parsed_bank_transactions, persisted_count). The
    parsed list is kept in its original `bank_statement.Transaction`
    shape so callers can still render the debt-payment checklist UI;
    the persisted records are the spending ledger used by the /spending
    page.
    """
    md = bank_statement.extract_metadata(text)
    parsed = bank_statement.parse_transactions(text)

    account_name = md.display_name if (md.institution or md.account_name) else source_name
    state.upsert_account(Account(
        name=account_name,
        kind=md.account_kind or "checking",
        institution=md.institution,
        number_hint=md.account_last4,
    ))

    # Merchant → category map learned from prior months, so recurring
    # charges the user already labeled land right automatically.
    history = spending_module.history_category_map(state.transactions)

    ledger: list[StoredTransaction] = []
    for tx in parsed:
        iso_date, amount, category = bank_statement.transaction_to_ledger(
            tx, md, account_name, rules=state.category_rules,
        )
        needs_review = False
        if category == "other":
            inherited = history.get(
                spending_module._normalize_merchant(tx.description)
            )
            if inherited:
                category = inherited
            else:
                needs_review = True
        try:
            ledger.append(StoredTransaction(
                date=iso_date,
                account=account_name,
                description=tx.description,
                amount=amount,
                category=category,
                source=source_name,
                needs_review=needs_review,
            ))
        except ValueError:
            # Malformed date or unknown category — skip rather than
            # poison the whole import.
            continue
    persisted = state.add_transactions(ledger)

    # Tag each bank_statement.Transaction with the account name so the
    # debt-payment checklist can show it if multiple statements are
    # being reviewed at once.
    for tx in parsed:
        tx.source = source_name  # type: ignore[attr-defined]
    return md, parsed, persisted


def _whatif_summary(extra: float, baseline, boosted) -> dict:
    def _av(report):
        return next(
            (r for r in report.results if r.title.startswith("Avalanche")),
            None,
        )
    base_av = _av(baseline)
    new_av = _av(boosted)
    if not (base_av and new_av):
        return {
            "message": f"Extra ${extra:,.0f}/month — avalanche data "
                       f"unavailable.",
            "months_saved": 0, "interest_saved": 0.0,
        }
    base_months = int(base_av.metrics.get("months_to_payoff", 0))
    new_months = int(new_av.metrics.get("months_to_payoff", 0))
    base_interest = float(base_av.metrics.get("total_interest", 0.0))
    new_interest = float(new_av.metrics.get("total_interest", 0.0))
    months_saved = max(0, base_months - new_months)
    interest_saved = max(0.0, base_interest - new_interest)
    if months_saved == 0 and interest_saved < 1:
        msg = (
            f"Extra ${extra:,.0f}/month — no measurable change yet. "
            f"Try a larger amount."
        )
    else:
        word = "month" if months_saved == 1 else "months"
        msg = (
            f"Sending an extra ${extra:,.0f}/month under Avalanche "
            f"finishes {months_saved} {word} sooner and saves "
            f"${interest_saved:,.2f} in interest."
        )
    return {
        "message": msg,
        "months_saved": months_saved,
        "interest_saved": interest_saved,
    }


def make_handler(store_path: Path):
    """Build a request handler bound to a specific JSON store path."""

    class Handler(BaseHTTPRequestHandler):
        server_version = "finadvisor/1.0"

        # Silence default request logging — it's noisy on phones.
        def log_message(self, fmt: str, *args: Any) -> None:
            return

        # ---- helpers ---------------------------------------------------
        def _html(self, body: str, status: int = 200) -> None:
            data = body.encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(data)

        def _redirect(self, location: str) -> None:
            self.send_response(HTTPStatus.SEE_OTHER)
            self.send_header("Location", location)
            self.send_header("Content-Length", "0")
            self.end_headers()

        def _read_body(self) -> bytes:
            length = int(self.headers.get("Content-Length", "0") or 0)
            if length <= 0:
                return b""
            return self.rfile.read(length)

        def _read_form(self) -> dict[str, list[str]]:
            raw = self._read_body().decode("utf-8", errors="replace")
            if not raw:
                return {}
            return parse_qs(raw, keep_blank_values=True)

        def _state(self):
            return storage.load(store_path)

        def _save(self, state) -> None:
            storage.save(state, store_path)

        def _set_alarm_for(self, state) -> None:
            """Compute the negative-cashflow alarm once for this request
            and stash it on the templates module so every page renders
            the banner consistently. Cheap — pure Python over the
            already-loaded transactions."""
            try:
                alarm = spending_module.negative_cashflow_alarm(
                    state.transactions,
                    monthly_income=state.budget.monthly_income,
                )
                templates.set_alarm(alarm if alarm[0] else None)
            except Exception:  # noqa: BLE001 — never block a page render
                templates.set_alarm(None)

        # ---- GET routes ------------------------------------------------
        def do_GET(self) -> None:  # noqa: N802 (stdlib API)
            try:
                url = urlparse(self.path)
                path = url.path
                query = parse_qs(url.query)
                flash = _pop_flash()
                if path == "/" or path == "/dashboard":
                    state = self._state()
                    self._set_alarm_for(state)
                    report = run_all(state)
                    cash_plan = spending_module.monthly_cash_plan(
                        state.transactions,
                        state.debts,
                        monthly_income=state.budget.monthly_income,
                        current_savings=state.current_savings,
                        household_size=state.household_size,
                        primary_goal=state.primary_goal,
                    )
                    alarm_tuple = spending_module.negative_cashflow_alarm(
                        state.transactions,
                        monthly_income=state.budget.monthly_income,
                    )
                    stress = scenarios_module.stress_test(
                        state.transactions,
                        state.debts,
                        monthly_income=state.budget.monthly_income,
                        current_savings=state.current_savings,
                        household_size=state.household_size,
                    )
                    ladder = scenarios_module.savings_ladder(
                        state.current_savings,
                        stress.monthly_essentials,
                        household_size=state.household_size,
                    )
                    return self._html(
                        templates.render_dashboard(
                            state, report, flash=flash,
                            cash_plan=cash_plan,
                            alarm=alarm_tuple if alarm_tuple[0] else None,
                            stress=stress,
                            ladder=ladder,
                        )
                    )
                if path == "/debts":
                    state = self._state()
                    self._set_alarm_for(state)
                    edit = (query.get("edit", [""])[0] or "").strip() or None
                    return self._html(
                        templates.render_debts(
                            state.debts, edit_name=edit, flash=flash
                        )
                    )
                if path == "/budget":
                    state = self._state()
                    self._set_alarm_for(state)
                    advice = spending_module.budget_advice(
                        state.transactions,
                        monthly_income_override=state.budget.monthly_income,
                    )
                    return self._html(
                        templates.render_budget(
                            state, advice=advice, flash=flash
                        )
                    )
                if path == "/analysis":
                    state = self._state()
                    self._set_alarm_for(state)
                    try:
                        extra = float(query.get("extra", ["0"])[0] or 0)
                    except ValueError:
                        extra = 0.0
                    extra = max(0.0, extra)
                    try:
                        lump = float(query.get("lump", ["0"])[0] or 0)
                    except ValueError:
                        lump = 0.0
                    lump = max(0.0, lump)
                    windfall = scenarios_module.windfall_impact(
                        state.debts, state.budget, lump,
                    ) if lump > 0 else None
                    # Auto-populate: if the user hasn't typed an extra
                    # amount, suggest their current surplus.
                    suggested_extra = max(
                        0.0,
                        state.budget.extra_payment_capacity(state.debts),
                    )
                    candidate_debts = _candidate_debts_from_transactions(state)
                    baseline = run_all(state)
                    whatif = None
                    if extra > 0:
                        boosted = replace(
                            state,
                            budget=Budget(
                                monthly_income=state.budget.monthly_income + extra,
                                monthly_expenses=state.budget.monthly_expenses,
                            ),
                        )
                        boosted_report = run_all(boosted)
                        whatif = _whatif_summary(extra, baseline, boosted_report)
                        report = boosted_report
                    else:
                        report = baseline
                    return self._html(
                        templates.render_analysis(
                            report, flash=flash, extra=extra, whatif=whatif,
                            suggested_extra=suggested_extra,
                            candidate_debts=candidate_debts,
                            lump=lump,
                            windfall=windfall,
                        )
                    )
                if path == "/spending":
                    state = self._state()
                    self._set_alarm_for(state)
                    summaries = spending_module.monthly_summaries(
                        state.transactions
                    )
                    trends = spending_module.category_trends(
                        state.transactions
                    )
                    insights = spending_module.build_insights(
                        state.transactions, trends=trends,
                    )
                    latest_month = summaries[-1].month if summaries else ""
                    per_account = (
                        spending_module.totals_by_account(
                            state.transactions, latest_month
                        ) if summaries else {}
                    )
                    breakdown = (
                        spending_module.account_category_breakdown(
                            state.transactions, latest_month
                        ) if summaries else {}
                    )
                    merchants = (
                        spending_module.top_merchants(
                            state.transactions, latest_month
                        ) if summaries else []
                    )
                    recurring = spending_module.detect_recurring(
                        state.transactions
                    )
                    calendar = spending_module.bill_calendar(
                        state.transactions
                    )
                    return self._html(
                        templates.render_spending(
                            state, summaries, insights, per_account,
                            breakdown=breakdown,
                            merchants=merchants,
                            recurring=recurring,
                            calendar=calendar,
                            flash=flash,
                        )
                    )
                if path == "/trends":
                    state = self._state()
                    self._set_alarm_for(state)
                    trends = spending_module.category_trends(
                        state.transactions
                    )
                    months = spending_module.months_of(state.transactions)
                    projected = spending_module.projected_monthly_spending(
                        state.transactions
                    )
                    income_map = spending_module.income_by_month(
                        state.transactions
                    )
                    summaries = spending_module.monthly_summaries(
                        state.transactions
                    )
                    totals_map = spending_module.total_spending_by_month(
                        state.transactions
                    )
                    deltas = spending_module.monthly_deltas(totals_map)
                    return self._html(
                        templates.render_trends(
                            state, trends, months, projected,
                            income_by_month=income_map,
                            summaries=summaries,
                            totals_by_month=totals_map,
                            deltas=deltas,
                            flash=flash,
                        )
                    )
                if path == "/transactions":
                    state = self._state()
                    self._set_alarm_for(state)
                    active_month = (query.get("month", [""])[0] or "").strip()
                    active_category = (
                        query.get("category", [""])[0] or ""
                    ).strip()
                    active_account = (
                        query.get("account", [""])[0] or ""
                    ).strip()
                    review_only = (
                        query.get("review", [""])[0] or ""
                    ).strip() == "1"
                    months = spending_module.months_of(state.transactions)
                    filtered = []
                    for i, tx in enumerate(state.transactions):
                        if active_month and tx.month != active_month:
                            continue
                        if active_category and tx.category != active_category:
                            continue
                        if active_account and tx.account != active_account:
                            continue
                        if review_only and not tx.needs_review:
                            continue
                        filtered.append((i, tx))
                    # Most-recent first is easier to scan on a phone.
                    filtered.sort(key=lambda p: p[1].date, reverse=True)
                    return self._html(
                        templates.render_transactions_page(
                            state, filtered, months,
                            active_month, active_category, active_account,
                            review_only=review_only,
                            flash=flash,
                        )
                    )
                if path == "/import":
                    return self._html(
                        templates.render_import(flash=flash)
                    )
                if path == "/healthz":
                    return self._html("ok")
                return self._html(
                    templates.render_page(
                        "", "Not found", "<h2>404</h2><p>No such page.</p>"
                    ),
                    status=404,
                )
            except Exception as e:
                self._html(
                    templates.render_page(
                        "", "Error",
                        f"<h2>Server error</h2><pre>{templates._esc(e)}\n"
                        f"{templates._esc(traceback.format_exc())}</pre>",
                    ),
                    status=500,
                )

        # ---- POST routes -----------------------------------------------
        def do_POST(self) -> None:  # noqa: N802
            try:
                path = urlparse(self.path).path
                ctype = self.headers.get("Content-Type", "")
                # Multipart routes (file upload) read the body raw.
                if path == "/import/pdf":
                    return self._post_pdf_upload(ctype)
                if path == "/import/transactions-csv":
                    return self._post_transactions_csv_upload(ctype)
                # All other POSTs use urlencoded forms.
                form = self._read_form()
                if path == "/debts/add":
                    return self._post_add_debt(form)
                if path == "/debts/edit":
                    return self._post_edit_debt(form)
                if path == "/debts/delete":
                    return self._post_delete_debt(form)
                if path == "/budget":
                    return self._post_budget(form)
                if path == "/budget/autofill":
                    return self._post_budget_autofill()
                if path == "/settings/goal":
                    return self._post_settings_goal(form)
                if path == "/import":
                    return self._post_import(form)
                if path == "/import/statement":
                    return self._post_statement_paste(form)
                if path == "/import/pdf/save":
                    return self._post_pdf_save(form)
                if path == "/import/pdf/transactions/save":
                    return self._post_transactions_save(form)
                if path == "/transactions/save":
                    return self._post_transaction_categories(form)
                self._html(
                    templates.render_page(
                        "", "Not found", "<h2>404</h2>"
                    ),
                    status=404,
                )
            except Exception as e:
                _set_flash("error", f"{type(e).__name__}: {e}")
                self._redirect("/")

        def _post_add_debt(self, form: dict[str, list[str]]) -> None:
            state = self._state()
            try:
                debt = Debt(
                    name=_str(form, "name"),
                    kind=_str(form, "kind", "other"),
                    balance=_float(form, "balance"),
                    apr=_float(form, "apr"),
                    min_payment=_float(form, "min_payment"),
                    credit_limit=_opt_float(form, "credit_limit"),
                )
            except ValueError as e:
                _set_flash("error", str(e))
                return self._redirect("/debts")
            state.debts.append(debt)
            self._save(state)
            _set_flash("success", f"Added {debt.name}.")
            self._redirect("/debts")

        def _post_edit_debt(self, form: dict[str, list[str]]) -> None:
            orig = _str(form, "orig_name")
            state = self._state()
            idx = next(
                (i for i, d in enumerate(state.debts) if d.name == orig), -1
            )
            if idx < 0:
                _set_flash("error", f"No debt named {orig!r}.")
                return self._redirect("/debts")
            try:
                new_debt = Debt(
                    name=_str(form, "name"),
                    kind=_str(form, "kind", "other"),
                    balance=_float(form, "balance"),
                    apr=_float(form, "apr"),
                    min_payment=_float(form, "min_payment"),
                    credit_limit=_opt_float(form, "credit_limit"),
                )
            except ValueError as e:
                _set_flash("error", str(e))
                return self._redirect(f"/debts?edit={orig}")
            # Refuse to create a name collision with a *different* debt.
            if new_debt.name != orig and any(
                d.name == new_debt.name for d in state.debts
            ):
                _set_flash(
                    "error",
                    f"A debt named {new_debt.name!r} already exists.",
                )
                return self._redirect(f"/debts?edit={orig}")
            state.debts[idx] = new_debt
            self._save(state)
            _set_flash("success", f"Updated {new_debt.name}.")
            self._redirect("/debts")

        def _post_delete_debt(self, form: dict[str, list[str]]) -> None:
            name = _str(form, "name")
            state = self._state()
            before = len(state.debts)
            state.debts = [d for d in state.debts if d.name != name]
            if len(state.debts) == before:
                _set_flash("error", f"No debt named {name!r}.")
            else:
                self._save(state)
                _set_flash("success", f"Removed {name}.")
            self._redirect("/debts")

        def _post_budget_autofill(self) -> None:
            """Replace the saved budget with the 3-month transaction
            average — zero-input path so the user doesn't have to type
            income/expense numbers manually."""
            state = self._state()
            advice = spending_module.budget_advice(state.transactions)
            if advice.months_used == 0:
                _set_flash(
                    "error",
                    "Import a bank statement first — "
                    "no transactions to derive numbers from yet.",
                )
                return self._redirect("/budget")
            try:
                state.budget = Budget(
                    monthly_income=round(advice.derived_income, 2),
                    monthly_expenses=round(advice.derived_expenses, 2),
                )
            except ValueError as e:
                _set_flash("error", str(e))
                return self._redirect("/budget")
            self._save(state)
            _set_flash(
                "success",
                f"Auto-filled budget from {advice.months_used} "
                f"month(s) of transactions.",
            )
            self._redirect("/budget")

        def _post_settings_goal(self, form: dict[str, list[str]]) -> None:
            """Persist the primary goal + household size from the
            Dashboard goal picker. Validated by `FinanceState`."""
            state = self._state()
            goal = _str(form, "primary_goal", state.primary_goal)
            try:
                hh = int(_float(form, "household_size", state.household_size))
            except ValueError:
                hh = state.household_size
            try:
                state.primary_goal = goal
                state.household_size = max(1, hh)
                # Trigger __post_init__ validation by re-creating.
                from finadvisor.models import FinanceState as _FS
                _FS(**{
                    "debts": state.debts,
                    "budget": state.budget,
                    "consolidation_apr": state.consolidation_apr,
                    "current_savings": state.current_savings,
                    "accounts": state.accounts,
                    "transactions": state.transactions,
                    "category_rules": state.category_rules,
                    "household_size": state.household_size,
                    "primary_goal": state.primary_goal,
                    "guidance_style": state.guidance_style,
                })
            except ValueError as e:
                _set_flash("error", str(e))
                return self._redirect("/")
            self._save(state)
            _set_flash("success", "Goal saved — cash plan updated.")
            self._redirect("/")

        def _post_budget(self, form: dict[str, list[str]]) -> None:
            state = self._state()
            try:
                state.budget = Budget(
                    monthly_income=_float(
                        form, "income", state.budget.monthly_income
                    ),
                    monthly_expenses=_float(
                        form, "expenses", state.budget.monthly_expenses
                    ),
                )
                savings = _opt_float(form, "savings")
                if savings is not None:
                    state.current_savings = savings
                cons = _opt_float(form, "consolidation_apr")
                if cons is not None:
                    state.consolidation_apr = cons
            except ValueError as e:
                _set_flash("error", str(e))
                return self._redirect("/budget")
            self._save(state)
            _set_flash("success", "Budget updated.")
            self._redirect("/budget")

        def _post_import(self, form: dict[str, list[str]]) -> None:
            text = form.get("csv", [""])[0]
            if not text.strip():
                _set_flash("error", "No CSV content pasted.")
                return self._redirect("/import")
            # A transactions register pasted into the debts box is a
            # common mix-up (Date/Amount headers instead of
            # name/balance/apr) — point at the right section instead
            # of a cryptic missing-columns error.
            if transactions_csv.is_transactions_csv(text):
                _set_flash(
                    "error",
                    "That looks like a bank transactions CSV (Date / "
                    "Amount columns), not the debts template. Use the "
                    "'Upload a transactions CSV' section above — it "
                    "handles this format directly.",
                )
                return self._redirect("/import")
            try:
                new_debts = _parse_csv_text(text)
            except ValueError as e:
                _set_flash("error", str(e))
                return self._redirect("/import")
            state = self._state()
            existing = {d.name: i for i, d in enumerate(state.debts)}
            added = updated = 0
            for d in new_debts:
                if d.name in existing:
                    state.debts[existing[d.name]] = d
                    updated += 1
                else:
                    state.debts.append(d)
                    added += 1
            self._save(state)
            _set_flash(
                "success",
                f"Imported CSV: {added} added, {updated} updated.",
            )
            self._redirect("/debts")

        def _post_transactions_csv_upload(self, content_type: str) -> None:
            """Import a bank's transactions-CSV export (Date /
            Description / Original Description / Category / Amount /
            Status and common variants). Rows persist straight into
            the ledger — dedup makes re-uploads safe."""
            if not content_type.lower().startswith("multipart/form-data"):
                _set_flash("error", "CSV upload requires a multipart form.")
                return self._redirect("/import")
            body = self._read_body()
            try:
                fields, files = _parse_multipart(content_type, body)
            except Exception as e:
                _set_flash("error", f"Could not parse upload: {e}")
                return self._redirect("/import")
            uploads = [
                (name, payload) for name, payload in (files.get("csv") or [])
                if name and payload
            ]
            if not uploads:
                _set_flash("error", "No CSV file selected.")
                return self._redirect("/import")
            account_name = (
                (fields.get("account_name", [""])[0] or "").strip()
                or "Imported CSV"
            )
            account_kind = (
                (fields.get("account_kind", ["checking"])[0] or "checking")
                .strip()
            )
            if account_kind not in ("checking", "savings", "credit_card"):
                account_kind = "checking"

            state = self._state()
            history = spending_module.history_category_map(
                state.transactions
            )
            total_parsed = 0
            total_pending = 0
            total_unparsed = 0
            sign_flipped = False
            errors: list[str] = []
            all_rows: list[StoredTransaction] = []
            for filename, payload in uploads:
                text = payload.decode("utf-8-sig", errors="replace")
                try:
                    result = transactions_csv.parse_transactions_csv(
                        text,
                        account_name,
                        source=filename,
                        rules=state.category_rules,
                        account_kind=account_kind,
                        history=history,
                    )
                except ValueError as e:
                    errors.append(f"{filename}: {e}")
                    continue
                all_rows.extend(result.transactions)
                total_parsed += len(result.transactions)
                total_pending += result.skipped_pending
                total_unparsed += result.skipped_unparsed
                sign_flipped = sign_flipped or result.sign_flipped

            if not all_rows:
                msg = (
                    " / ".join(errors) if errors
                    else "No usable transaction rows found in the CSV."
                )
                _set_flash("error", msg)
                return self._redirect("/import")

            state.upsert_account(Account(
                name=account_name, kind=account_kind,
            ))
            persisted = state.add_transactions(all_rows)
            self._save(state)

            parts = [f"imported {persisted} transaction(s) to "
                     f"'{account_name}'"]
            duplicates = total_parsed - persisted
            if duplicates:
                parts.append(f"{duplicates} duplicate(s) skipped")
            if total_pending:
                parts.append(f"{total_pending} pending row(s) skipped")
            if total_unparsed:
                parts.append(f"{total_unparsed} unreadable row(s) skipped")
            if sign_flipped:
                parts.append(
                    "amounts were re-signed to match the ledger "
                    "(income +, spending −)"
                )
            flagged = sum(1 for t in all_rows if t.needs_review)
            if flagged:
                parts.append(
                    f"{flagged} couldn't be auto-categorized — "
                    f"flagged as to-do for your review"
                )
            if errors:
                parts.append(f"errors: {'; '.join(errors[:3])}")
            _set_flash(
                "error" if errors and persisted == 0 else "success",
                "CSV import: " + ", ".join(parts) + ".",
            )
            self._redirect("/spending" if persisted else "/import")

        def _post_pdf_upload(self, content_type: str) -> None:
            if not content_type.lower().startswith("multipart/form-data"):
                _set_flash("error", "PDF upload requires a multipart form.")
                return self._redirect("/import")
            body = self._read_body()
            try:
                _, files = _parse_multipart(content_type, body)
            except Exception as e:
                _set_flash("error", f"Could not parse upload: {e}")
                return self._redirect("/import")
            uploads = [
                (name, payload) for name, payload in (files.get("pdf") or [])
                if name and payload
            ]
            if not uploads:
                _set_flash("error", "No PDF file selected.")
                return self._redirect("/import")

            # Parse each PDF, keeping track of which file each
            # transaction came from so the user can tell them apart.
            all_transactions: list = []
            single_extractions: list = []
            errors: list[str] = []
            state = self._state()
            total_persisted = 0
            for filename, payload in uploads:
                stem = (
                    Path(filename).stem.replace("_", " ")
                    .replace("-", " ").strip()
                    or "statement"
                )
                with tempfile.NamedTemporaryFile(
                    suffix=".pdf", delete=False
                ) as tmp:
                    tmp.write(payload)
                    tmp_path = Path(tmp.name)
                try:
                    extraction = pdf_importer.parse(tmp_path)
                except pdf_importer.PDFImportError as e:
                    errors.append(f"{filename}: {e}")
                    continue
                finally:
                    try:
                        tmp_path.unlink()
                    except OSError:
                        pass
                extraction.suggested_name = stem
                if bank_statement.is_bank_statement(extraction.raw_text):
                    _md, parsed, persisted = _ingest_statement(
                        extraction.raw_text, stem, state,
                    )
                    total_persisted += persisted
                    all_transactions.extend(parsed)
                else:
                    single_extractions.append(extraction)

            # Persist the transaction ledger before we hand the UI off
            # to the debt-payment checklist — spending data is valuable
            # even if the user never confirms a debt row.
            if total_persisted or state.accounts:
                self._save(state)

            if errors and not all_transactions and not single_extractions:
                # Collapse the N-times-repeated "pypdf is required"
                # error into one actionable message pointing at the
                # paste-text alternative.
                if all("pypdf is required" in e for e in errors):
                    _set_flash(
                        "error",
                        "pypdf isn't installed, so PDF parsing is "
                        "disabled. Either run 'pip install pypdf' and "
                        "retry, or use the 'Or paste bank-statement "
                        "text' box below (works with no extra deps).",
                    )
                else:
                    _set_flash("error", " / ".join(errors))
                return self._redirect("/import")

            if all_transactions:
                # Prefix any errors as a note at the top of the page.
                source_summary = (
                    "multiple statements" if len(uploads) > 1
                    else (
                        single_extractions[0].suggested_name
                        if single_extractions
                        else all_transactions[0].source
                    )
                )
                return self._html(
                    templates.render_transactions_confirm(
                        all_transactions,
                        source_name=source_summary,
                        errors=errors,
                    )
                )

            # No bank statements — fall back to single-debt confirm for
            # the first extraction. (Multi-file single-debt imports
            # would need a confirm queue; not implemented.)
            if len(single_extractions) > 1:
                _set_flash(
                    "error",
                    f"Uploaded {len(single_extractions)} non-statement PDFs; "
                    "only the first will be shown. Upload them one at a "
                    "time to confirm each.",
                )
            return self._html(
                templates.render_pdf_confirm(single_extractions[0])
            )

        def _post_transactions_save(self, form: dict[str, list[str]]) -> None:
            # All hidden amount_<i> fields are always submitted, so we
            # can tell both which rows were selected AND which were
            # explicitly left unselected.
            all_indices = sorted({
                int(k.split("_", 1)[1])
                for k in form.keys()
                if k.startswith("amount_") and k.split("_", 1)[1].isdigit()
            })
            selected_indices = sorted({
                int(k.split("_", 1)[1])
                for k in form.keys()
                if k.startswith("select_") and k.split("_", 1)[1].isdigit()
            })
            selected_set = set(selected_indices)
            add_unselected = bool(form.get("add_unselected_to_expenses"))

            if not selected_indices and not add_unselected:
                _set_flash(
                    "error",
                    "No transactions selected and the 'add unselected to "
                    "expenses' box is unchecked — nothing to do.",
                )
                return self._redirect("/import")

            state = self._state()
            existing_names = {d.name for d in state.debts}
            added = skipped = 0
            errors: list[str] = []
            for i in selected_indices:
                name = _str(form, f"name_{i}")
                kind = _str(form, f"kind_{i}", "other")
                try:
                    amount = _float(form, f"amount_{i}")
                except ValueError:
                    amount = 0.0
                balance = _opt_float(form, f"balance_{i}") or 0.0
                if name in existing_names:
                    skipped += 1
                    continue
                try:
                    state.debts.append(Debt(
                        name=name,
                        kind=kind,
                        balance=balance,
                        apr=bank_statement.default_apr(kind),
                        min_payment=amount,
                    ))
                    existing_names.add(name)
                    added += 1
                except ValueError as e:
                    errors.append(f"{name}: {e}")

            unselected_sum = 0.0
            if add_unselected:
                for i in all_indices:
                    if i in selected_set:
                        continue
                    try:
                        unselected_sum += _float(form, f"amount_{i}")
                    except ValueError:
                        pass
                if unselected_sum > 0:
                    state.budget = Budget(
                        monthly_income=state.budget.monthly_income,
                        monthly_expenses=(
                            state.budget.monthly_expenses + unselected_sum
                        ),
                    )

            self._save(state)
            parts = []
            if added:
                parts.append(
                    f"imported {added} debt(s) with a default APR by "
                    f"kind — fill in Balance on any row you left blank"
                )
            if skipped:
                parts.append(f"{skipped} skipped (name already exists)")
            if unselected_sum > 0:
                parts.append(
                    f"added ${unselected_sum:,.2f} to monthly expenses"
                )
            if errors:
                parts.append(f"errors: {'; '.join(errors[:3])}")
            msg = "Statement import: " + ", ".join(parts) + "."
            _set_flash(
                "error" if errors and added == 0 else "success", msg,
            )
            self._redirect("/debts")

        def _post_statement_paste(
            self, form: dict[str, list[str]]
        ) -> None:
            """Parse a pasted-in bank statement exactly like an uploaded
            PDF — same checklist confirmation page."""
            text = form.get("statement", [""])[0]
            if not text.strip():
                _set_flash(
                    "error",
                    "Paste some transaction text first.",
                )
                return self._redirect("/import")
            state = self._state()
            _md, transactions, persisted = _ingest_statement(
                text, "pasted", state,
            )
            debits = [t for t in transactions if t.debit is not None]
            if not debits:
                _set_flash(
                    "error",
                    "No dated debit rows found in the pasted text — "
                    "make sure each line starts with MM/DD.",
                )
                return self._redirect("/import")
            if persisted or state.accounts:
                self._save(state)
            html = templates.render_transactions_confirm(
                transactions, source_name="pasted",
            )
            return self._html(html)

        def _post_transaction_categories(
            self, form: dict[str, list[str]]
        ) -> None:
            """Accept category overrides from the /transactions page.

            Each row the template rendered posts back `category_<idx>`
            for its state-position index. We update only rows where
            the category actually changed, so spurious resubmits don't
            churn the JSON store. Every changed row silently persists a
            `CategoryRule` so future imports of transactions with a
            similar description are auto-categorized the same way —
            the user should never have to correct a merchant twice.
            """
            state = self._state()
            changed = 0
            rules_added = 0
            reviewed = 0
            propagated = 0
            corrections: list[tuple[str, str]] = []
            existing_rules = {
                (r.match, r.category) for r in state.category_rules
            }
            # "Mark all shown as reviewed": clear the to-do flag on
            # every row the form displayed, even if untouched — the
            # user has looked at them and confirmed the guesses.
            if form.get("mark_reviewed"):
                for key in form.keys():
                    if not key.startswith("row_"):
                        continue
                    try:
                        idx = int(key.split("_", 1)[1])
                    except ValueError:
                        continue
                    if not (0 <= idx < len(state.transactions)):
                        continue
                    tx = state.transactions[idx]
                    if tx.needs_review:
                        state.transactions[idx] = replace(
                            tx, needs_review=False,
                        )
                        reviewed += 1
            for key, values in form.items():
                if not key.startswith("category_"):
                    continue
                try:
                    idx = int(key.split("_", 1)[1])
                except ValueError:
                    continue
                if not (0 <= idx < len(state.transactions)):
                    continue
                new_cat = (values[0] if values else "").strip()
                if not new_cat:
                    continue
                try:
                    tx = state.transactions[idx]
                    if tx.category == new_cat:
                        continue
                    # Use replace-style mutation since Transaction is a
                    # frozen-ish dataclass validated in __post_init__.
                    # A corrected category also resolves the to-do flag.
                    state.transactions[idx] = replace(
                        tx, category=new_cat, needs_review=False,
                    )
                    changed += 1
                    corrections.append((tx.description, new_cat))
                    match = _rule_match_from_description(tx.description)
                    if match:
                        key_pair = (match, new_cat)
                        if key_pair not in existing_rules:
                            try:
                                state.category_rules.append(
                                    CategoryRule(match=match, category=new_cat)
                                )
                                existing_rules.add(key_pair)
                                rules_added += 1
                            except ValueError:
                                pass
                except ValueError:
                    continue  # unknown category slipped through
            # Correlate: propagate each correction to OTHER still-
            # flagged rows of the same merchant (recurring charges
            # across prior months), so one fix clears the whole series.
            if corrections:
                merchant_fix = {}
                for desc, cat in corrections:
                    key = spending_module._normalize_merchant(desc)
                    if key:
                        merchant_fix[key] = cat
                for i, tx in enumerate(state.transactions):
                    if not tx.needs_review:
                        continue
                    key = spending_module._normalize_merchant(
                        tx.description
                    )
                    if key in merchant_fix:
                        state.transactions[i] = replace(
                            tx,
                            category=merchant_fix[key],
                            needs_review=False,
                        )
                        propagated += 1

            if changed or reviewed:
                self._save(state)
                bits = []
                if changed:
                    bits.append(
                        f"Updated {changed} transaction categor(y/ies)."
                    )
                if rules_added:
                    bits.append(
                        f"Saved {rules_added} rule(s) — future imports "
                        f"will apply them automatically."
                    )
                if propagated:
                    bits.append(
                        f"Applied the same fix to {propagated} matching "
                        f"recurring row(s) from other months."
                    )
                if reviewed:
                    bits.append(
                        f"Cleared the to-do flag on {reviewed} row(s)."
                    )
                _set_flash("success", " ".join(bits))
            else:
                _set_flash("error", "No category changes to save.")
            # Preserve filters if any came in via form → redirect target.
            params = []
            for key in ("month", "category", "account", "review"):
                val = (form.get(key, [""])[0] or "").strip()
                if val:
                    params.append(f"{key}={val}")
            suffix = ("?" + "&".join(params)) if params else ""
            self._redirect("/transactions" + suffix)

        def _post_pdf_save(self, form: dict[str, list[str]]) -> None:
            state = self._state()
            try:
                debt = Debt(
                    name=_str(form, "name"),
                    kind=_str(form, "kind", "other"),
                    balance=_float(form, "balance"),
                    apr=_float(form, "apr"),
                    min_payment=_float(form, "min_payment"),
                    credit_limit=_opt_float(form, "credit_limit"),
                )
            except ValueError as e:
                _set_flash("error", str(e))
                return self._redirect("/import")
            existing = {d.name: i for i, d in enumerate(state.debts)}
            if debt.name in existing:
                state.debts[existing[debt.name]] = debt
                msg = f"Updated {debt.name} from PDF."
            else:
                state.debts.append(debt)
                msg = f"Added {debt.name} from PDF."
            self._save(state)
            _set_flash("success", msg)
            self._redirect("/debts")

    return Handler


def build_server(
    host: str = "127.0.0.1",
    port: int = 8765,
    store_path: Path | str = storage.DEFAULT_STORE,
) -> ThreadingHTTPServer:
    """Construct the HTTP server without starting the request loop.

    Kept separate from serve() so unit tests can bind to an ephemeral
    port (port=0), drive it from a background thread, and shut it down
    cleanly.
    """
    handler = make_handler(Path(store_path))
    return ThreadingHTTPServer((host, port), handler)


def serve(
    host: str = "127.0.0.1",
    port: int = 8765,
    store_path: Path | str = storage.DEFAULT_STORE,
) -> None:
    """Start the web server. Blocks until Ctrl-C."""
    store_path = Path(store_path)
    httpd = build_server(host=host, port=port, store_path=store_path)
    url = f"http://{host}:{httpd.server_address[1]}"
    print(f"finadvisor web UI: {url}")
    print(f"Data file: {store_path.resolve()}")
    print("Press Ctrl+C to stop.")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down.")
    finally:
        httpd.server_close()
