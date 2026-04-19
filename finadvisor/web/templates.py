"""HTML rendering for the local web UI.

Templates are plain Python f-strings with percent-substitution blocks for
content (`{content}`) and a flash message (`{flash}`). All user-supplied
values pass through html.escape() before interpolation.
"""
from __future__ import annotations

import html
from typing import Iterable

from finadvisor.models import Debt, FinanceState
from finadvisor.report import Report
from finadvisor.strategies.base import Severity, StrategyResult


BASE_CSS = """
* { box-sizing: border-box; }
body {
  margin: 0; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI",
    Roboto, sans-serif;
  background: #f5f6f8; color: #1f2937; -webkit-text-size-adjust: 100%;
}
header {
  background: #1f2937; color: white; padding: 14px 20px;
  display: flex; flex-wrap: wrap; gap: 12px; align-items: center;
}
header h1 { margin: 0; font-size: 18px; font-weight: 700; }
nav { display: flex; gap: 16px; margin-left: auto; flex-wrap: wrap; }
nav a { color: #cbd5e1; text-decoration: none; font-weight: 600; }
nav a.active, nav a:hover { color: white; }
main { max-width: 980px; margin: 0 auto; padding: 20px 16px 60px; }
h2 { margin-top: 0; color: #111827; }
.cards {
  display: grid; gap: 16px;
  grid-template-columns: repeat(auto-fit, minmax(170px, 1fr));
}
.card {
  background: white; border: 1px solid #e5e7eb; border-radius: 10px;
  padding: 14px 16px;
}
.card .label { color: #6b7280; font-size: 11px; font-weight: 700;
  letter-spacing: 0.5px; text-transform: uppercase; }
.card .value { color: #111827; font-size: 20px; font-weight: 700;
  margin-top: 4px; word-wrap: break-word; }
.banner {
  background: #eff6ff; border: 1px solid #bfdbfe; color: #1e3a8a;
  border-radius: 10px; padding: 14px 16px; margin: 12px 0;
}
.banner strong { display: block; margin-bottom: 4px; }
.severity-urgent { background: #fef2f2; border-color: #fecaca; color: #991b1b; }
.severity-warn   { background: #fffbeb; border-color: #fde68a; color: #92400e; }
.severity-good   { background: #ecfdf5; border-color: #a7f3d0; color: #065f46; }
.severity-info   { background: #eff6ff; border-color: #bfdbfe; color: #1e3a8a; }
table { width: 100%; border-collapse: collapse; background: white;
  border: 1px solid #e5e7eb; border-radius: 10px; overflow: hidden;
  margin: 12px 0; }
th, td { padding: 10px 12px; text-align: left; border-bottom: 1px solid #f3f4f6;
  font-size: 14px; }
th { background: #f9fafb; color: #374151; font-weight: 700;
  text-transform: uppercase; font-size: 11px; letter-spacing: 0.5px; }
tr:last-child td { border-bottom: none; }
form { background: white; border: 1px solid #e5e7eb; border-radius: 10px;
  padding: 16px; margin: 12px 0; }
label { display: block; margin: 8px 0 4px; font-weight: 600; color: #374151;
  font-size: 13px; }
input, select, textarea {
  width: 100%; padding: 8px 10px; border: 1px solid #d1d5db;
  border-radius: 6px; font-size: 14px; font-family: inherit;
  background: white;
}
input:focus, select:focus, textarea:focus {
  outline: none; border-color: #2563eb;
}
textarea { min-height: 140px; font-family: ui-monospace, monospace;
  font-size: 12px; }
button, .btn {
  background: #2563eb; color: white; border: none; border-radius: 6px;
  padding: 9px 16px; font-weight: 700; cursor: pointer; font-size: 14px;
  text-decoration: none; display: inline-block;
}
button:hover, .btn:hover { background: #1d4ed8; }
button.secondary, .btn.secondary { background: #e5e7eb; color: #111827; }
button.danger, .btn.danger { background: #dc2626; }
.row { display: flex; gap: 12px; flex-wrap: wrap; }
.row > * { flex: 1 1 180px; }
.bar { background: #e5e7eb; border-radius: 4px; height: 10px; overflow: hidden; }
.bar > span { display: block; height: 100%; border-radius: 4px; }
.bar-urgent > span { background: #dc2626; }
.bar-warn > span { background: #d97706; }
.bar-good > span { background: #059669; }
.bar-info > span { background: #2563eb; }
ul.recs { padding-left: 18px; }
ul.recs li { margin-bottom: 6px; }
.muted { color: #6b7280; font-size: 13px; }
.flash { margin: 12px 0; padding: 10px 14px; border-radius: 6px;
  background: #ecfdf5; color: #065f46; border: 1px solid #a7f3d0; }
.flash.error { background: #fef2f2; color: #991b1b; border-color: #fecaca; }
"""


def _esc(s) -> str:
    return html.escape(str(s), quote=True)


def _money(x: float) -> str:
    return f"${x:,.2f}"


def _nav(active: str) -> str:
    links = [
        ("dashboard", "/", "Dashboard"),
        ("debts", "/debts", "Debts"),
        ("budget", "/budget", "Budget"),
        ("spending", "/spending", "Spending"),
        ("trends", "/trends", "Trends"),
        ("analysis", "/analysis", "Analysis"),
        ("import", "/import", "Import"),
    ]
    parts = []
    for key, url, label in links:
        cls = "active" if key == active else ""
        parts.append(f'<a class="{cls}" href="{url}">{label}</a>')
    return f"<nav>{''.join(parts)}</nav>"


def render_page(active: str, title: str, content: str, flash: str = "") -> str:
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>finadvisor — {_esc(title)}</title>
<style>{BASE_CSS}</style>
</head>
<body>
<header>
  <h1>finadvisor</h1>
  {_nav(active)}
</header>
<main>
  {flash}
  {content}
  <p class="muted" style="margin-top:32px">
    Educational tool only — not licensed financial advice.
    All data stays on your device.
  </p>
</main>
</body>
</html>"""


def render_dashboard(state: FinanceState, report: Report, flash: str = "") -> str:
    def _find(prefix: str) -> StrategyResult | None:
        return next(
            (r for r in report.results if r.title.startswith(prefix)), None
        )

    av = _find("Avalanche")
    sn = _find("Snowball")
    ef = next(
        (r for r in report.results if r.title == "Emergency fund"), None
    )
    total = state.total_debt()
    apr = state.weighted_average_apr() * 100
    total_min = sum(d.min_payment for d in state.debts)
    dti = (
        f"{total_min / state.budget.monthly_income * 100:.1f}%"
        if state.budget.monthly_income > 0 else "set budget"
    )
    payoff = "—"
    if av and av.metrics.get("months_to_payoff"):
        months = int(av.metrics["months_to_payoff"])
        y, m = divmod(months, 12)
        payoff = f"{y}y {m}m" if y and m else f"{y}y" if y else f"{m}m"
    saved = "—"
    if av and sn and "total_interest" in av.metrics and "total_interest" in sn.metrics:
        delta = sn.metrics["total_interest"] - av.metrics["total_interest"]
        saved = _money(max(0, delta))
    em_value = _money(state.current_savings)
    if ef:
        months_covered = ef.metrics.get("months_covered", 0.0)
        if months_covered:
            em_value += f" ({months_covered:.1f} mo)"

    cards_html = "".join(
        f'<div class="card"><div class="label">{_esc(label)}</div>'
        f'<div class="value">{_esc(value)}</div></div>'
        for label, value in [
            ("Total debt", _money(total)),
            ("Weighted APR", f"{apr:.2f}%"),
            ("Debt-to-income", dti),
            ("Avalanche payoff", payoff),
            ("Emergency fund", em_value),
            ("Saved vs. Snowball", saved),
        ]
    )

    banner = (
        '<div class="banner"><strong>Next best action</strong>'
        f"{_esc(report.next_best_action)}</div>"
    )
    if not state.debts:
        banner = (
            '<div class="banner"><strong>Welcome</strong>'
            "Head to the <a href=\"/debts\">Debts</a> page to add your first "
            "debt — manually or via CSV import.</div>"
        )

    content = f"""
<h2>Dashboard</h2>
{banner}
<div class="cards">{cards_html}</div>
"""
    return render_page("dashboard", "Dashboard", content, flash=flash)


_KIND_OPTIONS = [
    ("credit_card", "Credit card"),
    ("student_loan", "Student loan"),
    ("auto", "Auto"),
    ("mortgage", "Mortgage"),
    ("personal", "Personal"),
    ("other", "Other"),
]


def _kind_select(name: str = "kind", selected: str = "") -> str:
    opts = "".join(
        f'<option value="{v}"{" selected" if v == selected else ""}>'
        f"{_esc(label)}</option>"
        for v, label in _KIND_OPTIONS
    )
    return f'<select name="{name}">{opts}</select>'


def _edit_row(d: Debt) -> str:
    cl = "" if d.credit_limit is None else f"{d.credit_limit}"
    return (
        '<tr><td colspan="7" style="background:#eff6ff">'
        '<form method="post" action="/debts/edit">'
        f'<input type="hidden" name="orig_name" value="{_esc(d.name)}">'
        '<div class="row">'
        f'<div><label>Name</label><input name="name" value="{_esc(d.name)}" required></div>'
        f'<div><label>Kind</label>{_kind_select("kind", d.kind)}</div>'
        '</div>'
        '<div class="row">'
        f'<div><label>Balance ($)</label><input name="balance" type="number" step="0.01" min="0" value="{d.balance}" required></div>'
        f'<div><label>APR (decimal)</label><input name="apr" type="number" step="0.0001" min="0" max="0.9999" value="{d.apr}" required></div>'
        '</div>'
        '<div class="row">'
        f'<div><label>Minimum ($/mo)</label><input name="min_payment" type="number" step="0.01" min="0" value="{d.min_payment}" required></div>'
        f'<div><label>Credit limit ($)</label><input name="credit_limit" type="number" step="0.01" min="0" value="{cl}"></div>'
        '</div>'
        '<p style="margin-top:12px">'
        '<button type="submit">Save</button> '
        '<a class="btn secondary" href="/debts">Cancel</a>'
        '</p>'
        '</form></td></tr>'
    )


def _display_row(d: Debt) -> str:
    edit_url = f"/debts?edit={_esc(d.name)}"
    # Flag debts that were created from a bank-statement import where
    # only the monthly payment is known — balance and APR still need
    # filling in for the analysis to be meaningful.
    incomplete = d.balance == 0 or d.apr == 0
    name_cell = _esc(d.name)
    if incomplete:
        name_cell += (
            ' <span title="Balance or APR is zero — open to complete."'
            ' style="background:#fef3c7;color:#92400e;border-radius:4px;'
            'padding:1px 6px;font-size:11px;font-weight:700;'
            'margin-left:6px">needs info</span>'
        )
    return (
        "<tr>"
        f"<td>{name_cell}</td>"
        f"<td>{_esc(d.kind)}</td>"
        f"<td>{_money(d.balance)}</td>"
        f"<td>{d.apr * 100:.2f}%</td>"
        f"<td>{_money(d.min_payment)}</td>"
        f"<td>{_money(d.credit_limit) if d.credit_limit else '—'}</td>"
        "<td>"
        f'<a class="btn secondary" href="{edit_url}">Edit</a> '
        '<form method="post" action="/debts/delete" '
        'style="display:inline;background:none;border:none;padding:0;margin:0;" '
        f'onsubmit="return confirm(\'Delete {_esc(d.name)}?\');">'
        f'<input type="hidden" name="name" value="{_esc(d.name)}">'
        '<button type="submit" class="danger">Delete</button>'
        "</form>"
        "</td>"
        "</tr>"
    )


def render_debts(
    debts: list[Debt], edit_name: str | None = None, flash: str = ""
) -> str:
    if debts:
        rows = "".join(
            _edit_row(d) if d.name == edit_name else _display_row(d)
            for d in debts
        )
        table = f"""
<table>
<thead><tr>
<th>Name</th><th>Kind</th><th>Balance</th><th>APR</th>
<th>Min payment</th><th>Credit limit</th><th></th>
</tr></thead>
<tbody>{rows}</tbody>
</table>
"""
        total = sum(d.balance for d in debts)
        summary = (
            f'<p class="muted">{len(debts)} debt(s) • '
            f"total {_money(total)} • minimums "
            f"{_money(sum(d.min_payment for d in debts))}/mo</p>"
        )
    else:
        table = '<p class="muted">No debts yet. Add one below or import a CSV.</p>'
        summary = ""

    add_form = f"""
<h3>Add a debt</h3>
<form method="post" action="/debts/add">
  <div class="row">
    <div><label>Name</label><input name="name" required></div>
    <div><label>Kind</label>{_kind_select("kind", "credit_card")}</div>
  </div>
  <div class="row">
    <div><label>Balance ($)</label>
      <input name="balance" type="number" step="0.01" min="0" required></div>
    <div><label>APR (decimal, e.g. 0.2499)</label>
      <input name="apr" type="number" step="0.0001" min="0" max="0.9999" required></div>
  </div>
  <div class="row">
    <div><label>Minimum payment ($/mo)</label>
      <input name="min_payment" type="number" step="0.01" min="0" required></div>
    <div><label>Credit limit ($ — cards only)</label>
      <input name="credit_limit" type="number" step="0.01" min="0"></div>
  </div>
  <p style="margin-top:12px"><button type="submit">Add debt</button></p>
</form>
"""

    content = f"<h2>Debts</h2>{summary}{table}{add_form}"
    return render_page("debts", "Debts", content, flash=flash)


def render_budget(state: FinanceState, flash: str = "") -> str:
    b = state.budget
    content = f"""
<h2>Budget</h2>
<p class="muted">All figures are monthly. The advisor computes how much
is left over after expenses and minimum debt payments.</p>
<form method="post" action="/budget">
  <div class="row">
    <div><label>Monthly income (take-home)</label>
      <input name="income" type="number" step="0.01" min="0"
             value="{b.monthly_income}"></div>
    <div><label>Monthly expenses (excl. debt)</label>
      <input name="expenses" type="number" step="0.01" min="0"
             value="{b.monthly_expenses}"></div>
  </div>
  <div class="row">
    <div><label>Current emergency savings ($)</label>
      <input name="savings" type="number" step="0.01" min="0"
             value="{state.current_savings}"></div>
    <div><label>Assumed consolidation APR (decimal)</label>
      <input name="consolidation_apr" type="number" step="0.0001" min="0" max="0.40"
             value="{state.consolidation_apr}"></div>
  </div>
  <p style="margin-top:12px"><button type="submit">Save</button></p>
</form>
"""
    return render_page("budget", "Budget", content, flash=flash)


def _strip_md(text: str) -> str:
    import re
    return re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", text)


def render_analysis(
    report: Report,
    flash: str = "",
    extra: float = 0.0,
    whatif: dict | None = None,
) -> str:
    whatif_form = f"""
<form method="get" action="/analysis" style="display:flex;gap:12px;align-items:end;flex-wrap:wrap">
  <div style="flex:1 1 200px">
    <label>What-if: extra $/month</label>
    <input name="extra" type="number" step="10" min="0" value="{extra:.0f}">
  </div>
  <div><button type="submit">Recalculate</button></div>
</form>
"""
    if not report.results:
        return render_page(
            "analysis", "Analysis",
            f"<h2>Analysis</h2>{whatif_form}"
            "<p>Add a debt first.</p>",
            flash=flash,
        )

    sections = []
    for r in report.results:
        sev = r.severity.value
        recs_html = ""
        if r.recommendations:
            items = "".join(
                f"<li>{_strip_md(_esc(rec))}</li>" for rec in r.recommendations
            )
            recs_html = f'<ul class="recs">{items}</ul>'

        breakdown_html = ""
        if r.breakdown:
            bars = []
            for item in r.breakdown:
                pct = min(100.0, item["value"] / max(item.get("max", 100), 1) * 100)
                bars.append(
                    f'<div style="margin-bottom:10px">'
                    f'<div style="display:flex;justify-content:space-between;'
                    f'font-size:13px;margin-bottom:3px">'
                    f'<strong>{_esc(item["label"])}</strong>'
                    f'<span class="muted">{_esc(item.get("caption", ""))}</span>'
                    f'</div>'
                    f'<div class="bar bar-{_esc(item.get("severity", "info"))}">'
                    f'<span style="width:{pct:.1f}%"></span></div>'
                    f'</div>'
                )
            breakdown_html = "".join(bars)

        schedule_html = _render_schedule(r.schedule) if r.schedule else ""

        sections.append(
            f'<section>'
            f'<h3>{_esc(r.title)}</h3>'
            f'<div class="banner severity-{sev}">{_strip_md(_esc(r.summary))}</div>'
            f'{recs_html}'
            f'{breakdown_html}'
            f'{schedule_html}'
            f'</section>'
        )

    whatif_banner = ""
    if whatif:
        sev_cls = "severity-good" if whatif.get("months_saved", 0) or whatif.get("interest_saved", 0) > 1 else "severity-info"
        whatif_banner = (
            f'<div class="banner {sev_cls}"><strong>What-if</strong>'
            f'{_esc(whatif["message"])}</div>'
        )

    content = f"""
<h2>Analysis</h2>
{whatif_form}
{whatif_banner}
<div class="banner"><strong>Next best action</strong>
{_esc(report.next_best_action)}</div>
{''.join(sections)}
"""
    return render_page("analysis", "Analysis", content, flash=flash)


def _render_schedule(schedule: list[dict]) -> str:
    # Show at most the first 18 snapshots so phones aren't overwhelmed.
    rows_data = schedule[:18]
    debt_names = sorted({
        name for row in rows_data for name in row.get("per_debt", {}).keys()
    })
    headers = "".join(
        f"<th>{_esc(h)}</th>"
        for h in ["Month", "Total"] + debt_names
    )
    body = []
    for row in rows_data:
        per = row.get("per_debt", {})
        cells = (
            f"<td>{row['month']}</td>"
            f"<td>{_money(row.get('total_balance', 0.0))}</td>"
        )
        cells += "".join(
            f"<td>{_money(per.get(n, 0.0))}</td>" for n in debt_names
        )
        body.append(f"<tr>{cells}</tr>")
    more = (
        f'<p class="muted">(Showing first {len(rows_data)} of '
        f"{len(schedule)} snapshots.)</p>"
        if len(schedule) > len(rows_data) else ""
    )
    return (
        f"<table><thead><tr>{headers}</tr></thead>"
        f"<tbody>{''.join(body)}</tbody></table>{more}"
    )


def render_import(preview: str = "", flash: str = "") -> str:
    content = f"""
<h2>Import</h2>

<h3>Upload a PDF statement</h3>
<p class="muted">Pick a credit-card or loan statement PDF. We'll extract
balance, APR, minimum payment, and credit limit (best effort). You'll
get a confirmation screen to correct anything before saving.</p>
<form method="post" action="/import/pdf" enctype="multipart/form-data">
  <label>PDF files (you can select several at once)</label>
  <input type="file" name="pdf" accept="application/pdf,.pdf" multiple required>
  <p style="margin-top:12px"><button type="submit">Upload &amp; parse</button></p>
</form>

<h3 style="margin-top:24px">Or paste bank-statement text</h3>
<p class="muted">If PDF parsing fails for your bank, open the statement
in any reader, copy the transaction table, and paste it here. Same
checklist flow as the upload path.</p>
<form method="post" action="/import/statement">
  <label>Transaction text</label>
  <textarea name="statement" placeholder="Date Description Debits Credits Balance
02/17 DEBIT CARD PURCHASE TACO BELL $8.07 $2,707.18
02/17 USAA CREDIT CARD PAYMENT $45.00 $2,495.62
CREDIT CARD ENDING IN 6421"></textarea>
  <p style="margin-top:12px"><button type="submit">Parse transactions</button></p>
</form>

<h3 style="margin-top:24px">Or paste CSV</h3>
<p class="muted">Required columns: <code>name, balance, apr, min_payment</code>.
The <code>kind</code> column is optional — if omitted, it's inferred from the name.</p>
<form method="post" action="/import">
  <label>CSV content</label>
  <textarea name="csv" placeholder="name,kind,balance,apr,min_payment,credit_limit
Visa,credit_card,4000,0.2499,100,5000
Auto Loan,auto,12000,0.045,300,"></textarea>
  <p style="margin-top:12px"><button type="submit">Import CSV</button></p>
</form>
{preview}
"""
    return render_page("import", "Import", content, flash=flash)


def render_transactions_confirm(
    transactions,
    source_name: str = "",
    errors: list[str] | None = None,
) -> str:
    """Checklist of bank-statement transactions to import as debts.

    Each row has a checkbox, an editable name + kind dropdown, and a
    hidden amount field. Debt-payment-looking rows (credit card / loan
    payments) are pre-selected; all others default to unchecked so the
    user isn't surprised by dozens of Taco Bell charges on the Debts
    page.

    If multiple files were uploaded, a Source column is added so the
    user can tell which statement each row came from.
    """
    from finadvisor.importers.bank_statement import (
        suggest_debt_name, looks_like_debt_payment,
    )

    debits = [t for t in transactions if t.debit is not None]
    total_debit = sum(t.debit or 0 for t in debits)
    credits = [t for t in transactions if t.credit is not None]
    total_credit = sum(t.credit or 0 for t in credits)
    sources = {getattr(t, "source", "") for t in debits}
    show_source = len(sources) > 1

    if not debits:
        return render_page(
            "import", "Confirm transactions",
            "<h2>Confirm transactions</h2>"
            "<p class=\"muted\">No debit transactions were found in "
            "this statement.</p>",
        )

    rows = []
    for i, tx in enumerate(debits):
        preselect = "checked" if looks_like_debt_payment(tx) else ""
        name = suggest_debt_name(tx)
        kind_select = _kind_select(f"kind_{i}", tx.kind_guess)
        source_cell = (
            f'<td class="muted" style="font-size:12px">'
            f'{_esc(getattr(tx, "source", ""))}</td>'
            if show_source else ""
        )
        rows.append(
            "<tr>"
            f'<td><input type="checkbox" name="select_{i}" {preselect}></td>'
            f"<td>{_esc(tx.date)}</td>"
            f"{source_cell}"
            f'<td><input name="name_{i}" value="{_esc(name)}"></td>'
            f"<td>{kind_select}</td>"
            f'<td><input name="balance_{i}" type="number" step="0.01" min="0"'
            f' placeholder="e.g. 2500" style="width:110px"></td>'
            f"<td style=\"text-align:right\">{_money(tx.debit or 0)}</td>"
            f'<td class="muted" style="font-size:12px">{_esc(tx.description[:80])}</td>'
            f'<input type="hidden" name="amount_{i}" value="{tx.debit or 0}">'
            "</tr>"
        )

    source_header = "<th>Source</th>" if show_source else ""

    credits_note = ""
    if credits:
        credits_note = (
            f'<p class="muted">{len(credits)} credit (deposit) '
            f"transaction(s) totaling {_money(total_credit)} were also "
            "detected and are not shown (deposits aren't debts).</p>"
        )

    errors_note = ""
    if errors:
        items = "".join(f"<li>{_esc(e)}</li>" for e in errors)
        errors_note = (
            f'<div class="banner severity-warn">'
            f"<strong>Some files couldn't be parsed</strong>"
            f"<ul>{items}</ul></div>"
        )

    expense_total_hint = _money(total_debit)
    content = f"""
<h2>Confirm transactions</h2>
{errors_note}
<div class="banner severity-info">
  <strong>Found {len(debits)} debit transactions</strong>
  totaling {_money(total_debit)} in {_esc(source_name or "this statement")}.
  Credit-card and loan payments are pre-selected. Review the list,
  then import the ones you want as debts.
</div>
{credits_note}
<form method="post" action="/import/pdf/transactions/save">
  <p style="margin:12px 0">
    <button type="button" class="secondary" onclick="
      for(const c of document.querySelectorAll('input[type=checkbox][name^=select_]')) c.checked = true;
      return false;
    ">Select all</button>
    <button type="button" class="secondary" onclick="
      for(const c of document.querySelectorAll('input[type=checkbox][name^=select_]')) c.checked = false;
      return false;
    ">Clear all</button>
  </p>
  <div style="overflow-x:auto">
  <table>
    <thead><tr>
      <th></th><th>Date</th>{source_header}<th>Debt name</th><th>Kind</th>
      <th>Balance&nbsp;$</th>
      <th style="text-align:right">Amount</th><th>From description</th>
    </tr></thead>
    <tbody>{''.join(rows)}</tbody>
  </table>
  </div>
  <div style="background:white;border:1px solid #e5e7eb;border-radius:10px;
       padding:12px 16px;margin-top:12px">
    <label style="font-weight:600">
      <input type="checkbox" name="add_unselected_to_expenses" value="1"
             style="width:auto;margin-right:8px">
      Also add the <em>unselected</em> debits to monthly expenses
    </label>
    <p class="muted" style="margin:6px 0 0">
      Total debits on this page: {expense_total_hint}. Whatever you
      leave unchecked above will be summed and added to your Budget's
      monthly expenses — useful for capturing groceries, gas, and
      other spending that isn't a tracked debt.
    </p>
  </div>
  <p class="muted" style="margin-top:8px">
    Each imported transaction becomes a Debt with
    <code>min_payment</code> set to the amount shown, and a default
    APR chosen by kind (e.g. 22% for credit cards). Fill in Balance
    now for accurate payoff math, or leave blank and edit later on
    the Debts page.
  </p>
  <p style="margin-top:12px">
    <button type="submit">Import selected as debts</button>
    <a class="btn secondary" href="/import">Cancel</a>
  </p>
</form>
"""
    return render_page("import", "Confirm transactions", content)


def render_pdf_confirm(extraction) -> str:
    """Show a prefilled form after a PDF upload so the user can edit
    fields before they're persisted as a Debt."""
    name = extraction.suggested_name or "Imported debt"
    kind = extraction.guessed_kind or "credit_card"
    balance = extraction.balance if extraction.balance is not None else ""
    apr = extraction.apr if extraction.apr is not None else ""
    min_pmt = extraction.min_payment if extraction.min_payment is not None else ""
    cl = extraction.credit_limit if extraction.credit_limit is not None else ""

    found = []
    if extraction.balance is not None:
        found.append("balance")
    if extraction.apr is not None:
        found.append("APR")
    if extraction.min_payment is not None:
        found.append("minimum payment")
    if extraction.credit_limit is not None:
        found.append("credit limit")
    if found:
        banner_text = "Extracted: " + ", ".join(found) + ". Verify and edit below."
        sev = "severity-good"
    else:
        banner_text = (
            "No fields extracted automatically. Fill them in below using "
            "the raw text as reference."
        )
        sev = "severity-warn"

    raw_section = ""
    if extraction.raw_text:
        raw_section = (
            '<details style="margin-top:16px"><summary class="muted">'
            'Show raw text from PDF</summary>'
            f'<pre style="white-space:pre-wrap;font-size:12px;'
            f'background:#f3f4f6;padding:12px;border-radius:6px">'
            f'{_esc(extraction.raw_text)}</pre></details>'
        )

    content = f"""
<h2>Confirm imported debt</h2>
<div class="banner {sev}">{_esc(banner_text)}</div>
<form method="post" action="/import/pdf/save">
  <div class="row">
    <div><label>Name</label>
      <input name="name" value="{_esc(name)}" required></div>
    <div><label>Kind</label>{_kind_select("kind", kind)}</div>
  </div>
  <div class="row">
    <div><label>Balance ($)</label>
      <input name="balance" type="number" step="0.01" min="0"
             value="{balance}" required></div>
    <div><label>APR (decimal)</label>
      <input name="apr" type="number" step="0.0001" min="0" max="0.9999"
             value="{apr}" required></div>
  </div>
  <div class="row">
    <div><label>Minimum payment ($/mo)</label>
      <input name="min_payment" type="number" step="0.01" min="0"
             value="{min_pmt}" required></div>
    <div><label>Credit limit ($)</label>
      <input name="credit_limit" type="number" step="0.01" min="0"
             value="{cl}"></div>
  </div>
  <p style="margin-top:12px">
    <button type="submit">Save debt</button>
    <a class="btn secondary" href="/import">Cancel</a>
  </p>
</form>
{raw_section}
"""
    return render_page("import", "Confirm PDF", content)


def _fmt_delta(value: float) -> str:
    sign = "+" if value > 0 else ""
    return f"{sign}{_money(value)}"


def _severity_for(insight_severity: str) -> str:
    return {
        "good": "good",
        "warn": "warn",
        "urgent": "urgent",
        "info": "info",
    }.get(insight_severity, "info")


def render_spending(
    state: FinanceState,
    summaries,
    insights,
    per_account,
    flash: str = "",
) -> str:
    """Monthly cashflow view: headline cards + insight list + the most
    recent month's by-category and by-account breakdowns."""
    if not summaries:
        content = (
            "<h2>Spending</h2>"
            '<div class="banner"><strong>No transactions yet</strong>'
            'Import a bank statement on the '
            '<a href="/import">Import</a> page and monthly spending '
            'summaries will appear here.</div>'
        )
        return render_page("spending", "Spending", content, flash=flash)

    latest = summaries[-1]
    prev = summaries[-2] if len(summaries) >= 2 else None
    income_delta = latest.income - prev.income if prev else 0.0
    spend_delta = latest.spending - prev.spending if prev else 0.0

    cards = [
        ("Month", latest.month),
        ("Income", _money(latest.income)),
        ("Spending", _money(latest.spending)),
        ("Net",
         f"{_money(latest.net)}"
         + ("" if not prev else f" ({_fmt_delta(latest.net - prev.net)} vs prev)")),
        ("Transactions", str(latest.transaction_count)),
        ("Accounts tracked", str(len(state.accounts))),
    ]
    if prev:
        cards.insert(3, ("Income Δ", _fmt_delta(income_delta)))
        cards.insert(5, ("Spending Δ", _fmt_delta(spend_delta)))
    cards_html = "".join(
        f'<div class="card"><div class="label">{_esc(label)}</div>'
        f'<div class="value">{_esc(value)}</div></div>'
        for label, value in cards
    )

    # Insights list, rendered as themed banners.
    insights_html = ""
    if insights:
        banners = []
        for ins in insights:
            sev = _severity_for(ins.severity)
            banners.append(
                f'<div class="banner severity-{sev}">'
                f'<strong>{_esc(ins.title)}</strong>'
                f'{_esc(ins.detail)}</div>'
            )
        insights_html = (
            '<h3 style="margin-top:24px">Coach notes</h3>' + "".join(banners)
        )
    else:
        insights_html = (
            '<h3 style="margin-top:24px">Coach notes</h3>'
            '<p class="muted">Nothing urgent — add another month of '
            'transactions for richer suggestions.</p>'
        )

    # This month's biggest spending categories.
    by_cat = sorted(
        (
            (cat, v) for cat, v in latest.by_category.items()
            if v > 0 and cat not in ("income", "transfer")
        ),
        key=lambda x: x[1], reverse=True,
    )
    max_v = by_cat[0][1] if by_cat else 1.0
    cat_rows = []
    for cat, v in by_cat:
        pct = min(100.0, v / max_v * 100)
        label = cat.replace("_", " ").title()
        cat_rows.append(
            f'<div style="margin-bottom:10px">'
            f'<div style="display:flex;justify-content:space-between;'
            f'font-size:13px;margin-bottom:3px">'
            f'<strong>{_esc(label)}</strong>'
            f'<span class="muted">{_money(v)}</span></div>'
            f'<div class="bar bar-info"><span style="width:{pct:.1f}%"></span>'
            f'</div></div>'
        )
    cat_html = (
        f'<h3 style="margin-top:24px">This month by category — '
        f'{_esc(latest.month)}</h3>'
        + ("".join(cat_rows) if cat_rows
           else '<p class="muted">No expense rows this month.</p>')
    )

    # Per-account summary for the current month (if there's more than one
    # account, it's useful to see where the money's flowing).
    acct_html = ""
    if per_account and len(per_account) >= 2:
        rows = "".join(
            f"<tr><td>{_esc(name)}</td>"
            f"<td>{_money(s.income)}</td>"
            f"<td>{_money(s.spending)}</td>"
            f"<td>{_money(s.net)}</td>"
            f"<td>{s.transaction_count}</td></tr>"
            for name, s in sorted(per_account.items())
        )
        acct_html = (
            '<h3 style="margin-top:24px">By account</h3>'
            "<table><thead><tr>"
            "<th>Account</th><th>Income</th><th>Spending</th>"
            "<th>Net</th><th>Txns</th>"
            "</tr></thead>"
            f"<tbody>{rows}</tbody></table>"
        )

    # Recent months roll-up.
    history_rows = []
    for s in summaries[-6:][::-1]:
        history_rows.append(
            f"<tr><td>{_esc(s.month)}</td>"
            f"<td>{_money(s.income)}</td>"
            f"<td>{_money(s.spending)}</td>"
            f"<td>{_money(s.net)}</td>"
            f"<td>{s.transaction_count}</td></tr>"
        )
    history_html = (
        '<h3 style="margin-top:24px">Last few months</h3>'
        "<table><thead><tr>"
        "<th>Month</th><th>Income</th><th>Spending</th>"
        "<th>Net</th><th>Txns</th>"
        "</tr></thead>"
        f"<tbody>{''.join(history_rows)}</tbody></table>"
    )

    content = f"""
<h2>Spending</h2>
<div class="cards">{cards_html}</div>
{insights_html}
{cat_html}
{acct_html}
{history_html}
"""
    return render_page("spending", "Spending", content, flash=flash)


def render_trends(
    state: FinanceState,
    trends,
    months,
    projected: float,
    flash: str = "",
) -> str:
    """Category-by-category movement across every month on file."""
    if not trends or not months:
        content = (
            "<h2>Trends</h2>"
            '<div class="banner"><strong>Not enough data</strong>'
            "Import at least one bank statement (two months is better) "
            "and this page will show how each spending category is "
            "moving month over month.</div>"
        )
        return render_page("trends", "Trends", content, flash=flash)

    shown_months = months[-6:]
    header_cells = "".join(f"<th>{_esc(m)}</th>" for m in shown_months)
    rows = []
    for t in trends:
        if t.latest == 0 and t.rolling_3mo == 0 and t.previous == 0:
            continue
        month_cells = "".join(
            f"<td>{_money(t.by_month.get(m, 0.0))}</td>" for m in shown_months
        )
        delta = t.delta_vs_prev
        if delta > 0:
            delta_cls = "severity-warn"
            delta_arrow = "▲"
        elif delta < 0:
            delta_cls = "severity-good"
            delta_arrow = "▼"
        else:
            delta_cls = "severity-info"
            delta_arrow = "•"
        delta_badge = (
            f'<span class="banner {delta_cls}" '
            f'style="display:inline-block;margin:0;padding:2px 8px;'
            f'font-size:12px;border-radius:999px">'
            f'{delta_arrow} {_fmt_delta(delta)}</span>'
        )
        rows.append(
            f'<tr><td><strong>{_esc(t.category.replace("_", " ").title())}</strong></td>'
            f"{month_cells}"
            f"<td>{_money(t.rolling_3mo)}</td>"
            f"<td>{delta_badge}</td>"
            f"</tr>"
        )

    projection_banner = (
        f'<div class="banner"><strong>3-month projection</strong>'
        f'Average of your last three months of spending is '
        f'{_money(projected)}/mo. Use this as a forward estimate when '
        f'sizing extra debt payments or an emergency fund target.</div>'
    )

    content = f"""
<h2>Trends</h2>
{projection_banner}
<div style="overflow-x:auto">
<table>
<thead><tr>
<th>Category</th>{header_cells}<th>3-mo avg</th><th>Δ vs prev</th>
</tr></thead>
<tbody>{''.join(rows) if rows else '<tr><td colspan="9" class="muted">No category activity to show.</td></tr>'}</tbody>
</table>
</div>
<p class="muted" style="margin-top:12px">
Green ▼ means you spent less than last month; amber ▲ means you spent
more. The 3-month average smooths out one-off bills.
</p>
"""
    return render_page("trends", "Trends", content, flash=flash)


def flash_success(msg: str) -> str:
    return f'<div class="flash">{_esc(msg)}</div>'


def flash_error(msg: str) -> str:
    return f'<div class="flash error">{_esc(msg)}</div>'
