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
from finadvisor.importers import bank_statement, pdf_importer
from finadvisor.models import Budget, Debt
from finadvisor.report import run_all
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

        # ---- GET routes ------------------------------------------------
        def do_GET(self) -> None:  # noqa: N802 (stdlib API)
            try:
                url = urlparse(self.path)
                path = url.path
                query = parse_qs(url.query)
                flash = _pop_flash()
                if path == "/" or path == "/dashboard":
                    state = self._state()
                    report = run_all(state)
                    return self._html(
                        templates.render_dashboard(state, report, flash=flash)
                    )
                if path == "/debts":
                    state = self._state()
                    edit = (query.get("edit", [""])[0] or "").strip() or None
                    return self._html(
                        templates.render_debts(
                            state.debts, edit_name=edit, flash=flash
                        )
                    )
                if path == "/budget":
                    state = self._state()
                    return self._html(
                        templates.render_budget(state, flash=flash)
                    )
                if path == "/analysis":
                    state = self._state()
                    try:
                        extra = float(query.get("extra", ["0"])[0] or 0)
                    except ValueError:
                        extra = 0.0
                    extra = max(0.0, extra)
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
                if path == "/import":
                    return self._post_import(form)
                if path == "/import/pdf/save":
                    return self._post_pdf_save(form)
                if path == "/import/pdf/transactions/save":
                    return self._post_transactions_save(form)
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
                    for tx in bank_statement.parse_transactions(
                        extraction.raw_text
                    ):
                        # Attach source so the confirm page can show it.
                        tx.source = stem  # type: ignore[attr-defined]
                        all_transactions.append(tx)
                else:
                    single_extractions.append(extraction)

            if errors and not all_transactions and not single_extractions:
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
