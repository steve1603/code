"""Stdlib HTTP server that serves the finadvisor web UI.

Uses only the Python standard library so it runs on minimal setups like
Termux on Android. No network calls are ever made — the server only
binds locally and reads/writes the same JSON store as the GUI and CLI.
"""
from __future__ import annotations

import csv
import io
import traceback
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

        def _read_form(self) -> dict[str, list[str]]:
            length = int(self.headers.get("Content-Length", "0") or 0)
            if length <= 0:
                return {}
            raw = self.rfile.read(length).decode("utf-8", errors="replace")
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
                    report = run_all(state)
                    return self._html(
                        templates.render_analysis(report, flash=flash)
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

    return Handler


def serve(
    host: str = "127.0.0.1",
    port: int = 8765,
    store_path: Path | str = storage.DEFAULT_STORE,
) -> None:
    """Start the web server. Blocks until Ctrl-C."""
    store_path = Path(store_path)
    handler = make_handler(store_path)
    httpd = ThreadingHTTPServer((host, port), handler)
    url = f"http://{host}:{port}"
    print(f"finadvisor web UI: {url}")
    print(f"Data file: {store_path.resolve()}")
    print("Press Ctrl+C to stop.")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down.")
    finally:
        httpd.server_close()
