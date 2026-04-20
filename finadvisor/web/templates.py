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
        ("transactions", "/transactions", "Transactions"),
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

    # Optional spending row — only rendered when the user has imported
    # at least one month of transactions. Keeps the dashboard quiet for
    # debt-only users.
    spending_cards_html = ""
    if state.transactions:
        from finadvisor import spending as _sp  # local import to keep Qt-free
        summaries = _sp.monthly_summaries(state.transactions)
        if summaries:
            latest = summaries[-1]
            biggest = sorted(
                (
                    (c, v) for c, v in latest.by_category.items()
                    if c not in ("income", "transfer") and v > 0
                ),
                key=lambda x: x[1], reverse=True,
            )
            top_cat = (
                f"{biggest[0][0].replace('_', ' ').title()} "
                f"({_money(biggest[0][1])})"
                if biggest else "—"
            )
            spending_cards = [
                (f"Spending — {latest.month}", _money(latest.spending)),
                ("Net this month", _money(latest.net)),
                ("Top category", top_cat),
            ]
            spending_cards_html = (
                '<h3 style="margin-top:24px;margin-bottom:8px">'
                'Spending snapshot</h3>'
                '<div class="cards">'
                + "".join(
                    f'<div class="card"><div class="label">{_esc(label)}</div>'
                    f'<div class="value">{_esc(value)}</div></div>'
                    for label, value in spending_cards
                )
                + '</div>'
                + '<p class="muted" style="margin-top:6px">'
                '<a href="/spending">Details</a> · '
                '<a href="/trends">Month-over-month trends</a></p>'
            )

    banner = (
        '<div class="banner"><strong>Next best action</strong>'
        f"{_esc(report.next_best_action)}</div>"
    )
    if not state.debts and not state.transactions:
        banner = (
            '<div class="banner"><strong>Welcome</strong>'
            "Head to the <a href=\"/debts\">Debts</a> page to add your first "
            "debt — manually or via CSV import — or upload a bank "
            "statement on the <a href=\"/import\">Import</a> page to "
            "start tracking spending.</div>"
        )

    content = f"""
<h2>Dashboard</h2>
{banner}
<div class="cards">{cards_html}</div>
{spending_cards_html}
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


def render_budget(
    state: FinanceState,
    advice: "object | None" = None,
    flash: str = "",
) -> str:
    b = state.budget

    # Auto-populate hints come from the transaction-derived averages.
    income_hint = ""
    expenses_hint = ""
    auto_panel = ""
    if advice is not None and advice.months_used > 0:
        d_income = advice.derived_income
        d_expenses = advice.derived_expenses
        d_debt = advice.derived_debt_payments
        if d_income > 0 and abs(d_income - b.monthly_income) > 10:
            income_hint = (
                f'<small class="muted">Last {advice.months_used} mo '
                f'actual: <strong>${d_income:,.2f}/mo</strong></small>'
            )
        if d_expenses > 0 and abs(d_expenses - b.monthly_expenses) > 10:
            expenses_hint = (
                f'<small class="muted">Last {advice.months_used} mo '
                f'actual: <strong>${d_expenses:,.2f}/mo</strong></small>'
            )
        # One-click "apply derived numbers" form.
        if d_income > 0 or d_expenses > 0:
            auto_panel = f"""
<form method="post" action="/budget/autofill"
      style="background:#eff6ff;border:1px solid #bfdbfe;border-radius:10px;
             padding:14px 16px;margin:12px 0;display:flex;
             flex-wrap:wrap;gap:12px;align-items:center;justify-content:space-between">
  <div>
    <strong style="color:#1e3a8a">Auto-fill from transactions</strong>
    <div class="muted" style="font-size:13px;margin-top:2px">
      Using the last {advice.months_used} month(s): income
      <strong>${d_income:,.2f}</strong>, expenses (excl. debt)
      <strong>${d_expenses:,.2f}</strong>, debt payments
      <strong>${d_debt:,.2f}</strong>.
    </div>
  </div>
  <button type="submit" class="btn">Use these values</button>
</form>
"""

    # Recommendations panel.
    rec_panel = ""
    if advice is not None:
        headline = _esc(advice.headline) if advice.headline else ""
        items: list[str] = []
        for s in advice.suggestions:
            sev_cls = f"severity-{s.severity}"
            icon = "✂️" if s.is_cut else ("⚠️" if s.severity == "urgent" else "🛡")
            target = (
                f' <span class="muted">→ target '
                f'<strong>${s.target_monthly:,.0f}/mo</strong></span>'
                if s.target_monthly is not None else ""
            )
            items.append(
                f'<li style="margin-bottom:10px">'
                f'<span class="banner {sev_cls}" '
                f'style="display:inline-block;margin:0;padding:2px 8px;'
                f'font-size:12px;border-radius:999px">'
                f'{icon} {_esc(s.label)}{target}</span>'
                f'<div class="muted" style="font-size:13px;margin-top:4px">'
                f'{_esc(s.note)}</div>'
                f'</li>'
            )
        body = (
            f'<ul style="list-style:none;padding-left:0">{"".join(items)}</ul>'
            if items else
            '<p class="muted">Import a couple months of statements and '
            'the advisor will tell you exactly which categories to trim.</p>'
        )
        rec_panel = f"""
<section style="background:white;border:1px solid #e5e7eb;
                border-radius:10px;padding:16px;margin:16px 0">
  <h3 style="margin-top:0">Budget coach</h3>
  <p style="color:#374151">{headline}</p>
  {body}
</section>
"""

    content = f"""
<h2>Budget</h2>
<p class="muted">All figures are monthly. The advisor computes how much
is left over after expenses and minimum debt payments. Import a bank
statement to auto-fill these from your actual cashflow.</p>
{auto_panel}
<form method="post" action="/budget">
  <div class="row">
    <div><label>Monthly income (take-home)</label>
      <input name="income" type="number" step="0.01" min="0"
             value="{b.monthly_income}">
      {income_hint}
    </div>
    <div><label>Monthly expenses (excl. debt)</label>
      <input name="expenses" type="number" step="0.01" min="0"
             value="{b.monthly_expenses}">
      {expenses_hint}
    </div>
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
{rec_panel}
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
    suggested_extra: float = 0.0,
    candidate_debts: list | None = None,
) -> str:
    # If the caller derived a surplus from the budget but the user
    # hasn't typed a number into the what-if field yet, pre-fill it —
    # that's the "auto-populate" ask.
    displayed_extra = extra if extra > 0 else round(suggested_extra, 0)
    hint = ""
    if suggested_extra > 0 and extra <= 0:
        hint = (
            f'<small class="muted" style="display:block;margin-top:4px">'
            f'Auto-filled from your budget surplus '
            f'(${suggested_extra:,.0f}/mo available after expenses + '
            f'minimums).</small>'
        )
    whatif_form = f"""
<form method="get" action="/analysis" style="display:flex;gap:12px;align-items:end;flex-wrap:wrap">
  <div style="flex:1 1 200px">
    <label>What-if: extra $/month</label>
    <input name="extra" type="number" step="10" min="0" value="{displayed_extra:.0f}">
    {hint}
  </div>
  <div><button type="submit">Recalculate</button></div>
</form>
"""

    # Candidate-debts panel: if there are no debts on file but we've
    # detected recurring debt-like payments (credit-card, loan) in the
    # transaction ledger, surface them so the user isn't stuck on
    # "No debts on file".
    candidate_panel = ""
    if candidate_debts:
        rows = "".join(
            f'<tr><td><strong>{_esc(c["name"])}</strong></td>'
            f'<td>{_esc(c["kind"].replace("_", " ").title())}</td>'
            f'<td style="text-align:right">${c["monthly"]:,.2f}/mo</td>'
            f'<td>{_esc(c["months_seen_str"])}</td></tr>'
            for c in candidate_debts
        )
        candidate_panel = f"""
<section style="background:white;border:1px solid #e5e7eb;
                border-radius:10px;padding:16px;margin:16px 0">
  <h3 style="margin-top:0">Likely debts from your statements</h3>
  <p class="muted">The advisor spotted these recurring payments in
  your transactions. Add them as debts (with balance + APR) to unlock
  the payoff strategies below.</p>
  <div style="overflow-x:auto"><table>
    <thead><tr><th>Name</th><th>Kind</th><th>Monthly</th>
    <th>Seen in</th></tr></thead>
    <tbody>{rows}</tbody>
  </table></div>
  <p style="margin-top:10px"><a class="btn" href="/debts">Add a debt</a></p>
</section>
"""

    if not report.results:
        return render_page(
            "analysis", "Analysis",
            f"<h2>Analysis</h2>{whatif_form}{candidate_panel}"
            "<p>Add a debt first — then we can show payoff strategies.</p>",
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
{candidate_panel}
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
    breakdown=None,
    merchants=None,
    recurring=None,
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

    # Per-account-per-category breakdown: for each account, render a
    # small bars section showing where that account's money went this
    # month. Only shown when multiple accounts exist.
    breakdown_html = ""
    if breakdown and len(breakdown) >= 2:
        sections = []
        for acct in sorted(breakdown.keys()):
            cats = sorted(
                ((c, v) for c, v in breakdown[acct].items() if v > 0),
                key=lambda x: x[1], reverse=True,
            )
            if not cats:
                continue
            acct_total = sum(v for _, v in cats)
            acct_max = cats[0][1] if cats else 1.0
            bars = []
            for cat, v in cats:
                pct = min(100.0, v / acct_max * 100)
                bars.append(
                    f'<div style="margin-bottom:6px">'
                    f'<div style="display:flex;justify-content:space-between;'
                    f'font-size:12px;margin-bottom:2px">'
                    f'<span>{_esc(cat.replace("_", " ").title())}</span>'
                    f'<span class="muted">{_money(v)}</span></div>'
                    f'<div class="bar bar-info"><span '
                    f'style="width:{pct:.1f}%"></span></div></div>'
                )
            sections.append(
                '<section style="margin-bottom:18px">'
                f'<div style="display:flex;justify-content:space-between;'
                f'align-items:baseline"><strong>{_esc(acct)}</strong>'
                f'<span class="muted">{_money(acct_total)}</span></div>'
                + "".join(bars)
                + '</section>'
            )
        if sections:
            breakdown_html = (
                '<h3 style="margin-top:24px">By account — '
                f'{_esc(latest.month)}</h3>' + "".join(sections)
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

    # ---- Top merchants (this month) -----------------------------
    merchants_html = ""
    if merchants:
        rows_html = "".join(
            f'<tr><td>{_esc(name.title())}</td>'
            f'<td style="text-align:right">{_money(amount)}</td></tr>'
            for name, amount in merchants
        )
        merchants_html = (
            f'<h3 style="margin-top:24px">Top merchants — '
            f'{_esc(latest.month)}</h3>'
            f'<table style="max-width:560px"><thead><tr>'
            f'<th>Merchant</th><th style="text-align:right">Spent</th>'
            f'</tr></thead><tbody>{rows_html}</tbody></table>'
            f'<p class="muted" style="margin-top:6px">'
            f'Biggest single-merchant outflows this month. Store '
            f'numbers and locations are merged into one row.</p>'
        )

    # ---- Recurring charges --------------------------------------
    recurring_html = ""
    if recurring:
        yearly_total = sum(r.yearly_cost for r in recurring)
        monthly_total = sum(r.monthly_cost for r in recurring)
        rows_html = "".join(
            f'<tr><td>{_esc(r.description)}</td>'
            f'<td class="muted" style="font-size:12px">{_esc(r.account)}</td>'
            f'<td>{_esc(r.category.replace("_", " ").title())}</td>'
            f'<td style="text-align:right">{_money(r.typical_amount)}</td>'
            f'<td style="text-align:right">{_money(r.monthly_cost)}</td>'
            f'<td style="text-align:right"><strong>{_money(r.yearly_cost)}</strong></td>'
            f'</tr>'
            for r in recurring
        )
        recurring_html = (
            f'<h3 style="margin-top:24px">Recurring charges</h3>'
            f'<div class="banner severity-info">'
            f'<strong>{len(recurring)} recurring merchant(s) detected</strong>'
            f'Together they cost about <strong>{_money(monthly_total)}'
            f'/mo</strong> — roughly <strong>{_money(yearly_total)}'
            f'/yr</strong> at the current cadence. Cancel whatever you '
            f"haven't used this month for an easy win.</div>"
            f'<div style="overflow-x:auto"><table>'
            f'<thead><tr><th>Merchant</th><th>Account</th>'
            f'<th>Category</th>'
            f'<th style="text-align:right">Typical $</th>'
            f'<th style="text-align:right">$/mo</th>'
            f'<th style="text-align:right">$/yr</th>'
            f'</tr></thead>'
            f'<tbody>{rows_html}</tbody></table></div>'
        )

    content = f"""
<h2>Spending</h2>
<div class="cards">{cards_html}</div>
{insights_html}
{cat_html}
{merchants_html}
{recurring_html}
{breakdown_html}
{acct_html}
{history_html}
<p class="muted" style="margin-top:16px">
  Something miscategorized? Fix it on the
  <a href="/transactions">Transactions</a> page.
</p>
"""
    return render_page("spending", "Spending", content, flash=flash)


def _pct_span(pct: float | None) -> str:
    """Render a '(+18%)' badge tinted green (down = good) or amber
    (up = spent more). Returns "" for None (no prior month or zero
    base), so first-month cells stay quiet."""
    if pct is None:
        return ""
    color = "#059669" if pct < 0 else ("#b45309" if pct > 0 else "#6b7280")
    sign = "+" if pct > 0 else ""
    return (
        f'<div style="font-size:11px;color:{color};font-weight:600">'
        f"{sign}{pct * 100:.0f}%</div>"
    )


def render_trends(
    state: FinanceState,
    trends,
    months,
    projected: float,
    income_by_month=None,
    summaries=None,
    totals_by_month=None,
    deltas=None,
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

    # ------ Chart + MoM delta cards --------------------------------
    from finadvisor.web import charts as _charts

    chart_html = ""
    totals_by_month = totals_by_month or {}
    deltas = deltas or []
    if totals_by_month:
        # Build the chart series: Total on top + top 3 categories by
        # latest-month spend so the biggest drivers of the Total line
        # are visible alongside it.
        series: dict[str, list[tuple[str, float]]] = {
            "Total": [(m, totals_by_month.get(m, 0.0)) for m in shown_months]
        }
        for t in [
            t for t in trends
            if t.latest > 0 and t.category not in ("income", "transfer")
        ][:3]:
            label = t.category.replace("_", " ").title()
            series[label] = [
                (m, t.by_month.get(m, 0.0)) for m in shown_months
            ]

        chart_svg = _charts.render_line_chart(
            series, width=680, height=240,
            title="Monthly spending trajectory",
        )

        # Side-panel MoM delta cards.
        delta_cards = []
        for prev, nxt, dollar_delta, pct_delta in deltas:
            arrow = "▲" if dollar_delta > 0 else (
                "▼" if dollar_delta < 0 else "•"
            )
            # Spending more = warning; spending less = good.
            color = "#b45309" if dollar_delta > 0 else (
                "#059669" if dollar_delta < 0 else "#6b7280"
            )
            bg = "#fffbeb" if dollar_delta > 0 else (
                "#ecfdf5" if dollar_delta < 0 else "#f3f4f6"
            )
            pct_str = (
                f"{('+' if pct_delta > 0 else '')}{pct_delta * 100:.0f}%"
                if pct_delta is not None else "—"
            )
            delta_cards.append(
                f'<div style="background:{bg};border:1px solid #e5e7eb;'
                f'border-radius:10px;padding:10px 12px">'
                f'<div style="font-size:11px;color:#6b7280;font-weight:700;'
                f'letter-spacing:0.5px;text-transform:uppercase">'
                f"{_esc(prev)} → {_esc(nxt)}</div>"
                f'<div style="font-size:18px;font-weight:700;color:{color}">'
                f"{arrow} {_fmt_delta(dollar_delta)}</div>"
                f'<div style="font-size:12px;color:#374151">'
                f"{_esc(pct_str)} vs prev</div></div>"
            )
        deltas_html = (
            '<div style="display:flex;flex-direction:column;gap:8px">'
            + "".join(delta_cards)
            + "</div>"
        ) if delta_cards else ""

        chart_html = (
            '<div style="background:white;border:1px solid #e5e7eb;'
            'border-radius:10px;padding:16px;margin:12px 0">'
            '<div style="display:flex;gap:18px;flex-wrap:wrap;'
            'align-items:flex-start">'
            f'<div style="flex:1 1 420px;min-width:280px">{chart_svg}</div>'
            f'<div style="flex:0 1 220px">{deltas_html}</div>'
            '</div></div>'
        )

    # Top rows: income and net cashflow, so the reader sees the
    # earning side of the ledger before diving into categories.
    income_by_month = income_by_month or {}
    summaries_map = {s.month: s for s in (summaries or [])}
    summary_rows = []
    if income_by_month:
        incomes = [income_by_month.get(m, 0.0) for m in shown_months]
        avg_income = (sum(incomes) / len(incomes)) if incomes else 0.0
        prev_income = incomes[-2] if len(incomes) >= 2 else 0.0
        income_delta = incomes[-1] - prev_income if incomes else 0.0
        arrow = "▲" if income_delta > 0 else ("▼" if income_delta < 0 else "•")
        delta_sev = (
            "good" if income_delta > 0 else
            "warn" if income_delta < 0 else "info"
        )
        income_cells = "".join(
            f"<td>{_money(v)}</td>" for v in incomes
        )
        summary_rows.append(
            f'<tr style="background:#ecfdf5">'
            f'<td><strong>Income</strong></td>'
            f"{income_cells}"
            f"<td>{_money(avg_income)}</td>"
            f'<td><span class="banner severity-{delta_sev}" '
            f'style="display:inline-block;margin:0;padding:2px 8px;'
            f'font-size:12px;border-radius:999px">'
            f'{arrow} {_fmt_delta(income_delta)}</span></td>'
            f'</tr>'
        )
    if summaries:
        net_values = [
            (summaries_map[m].net if m in summaries_map else 0.0)
            for m in shown_months
        ]
        avg_net = sum(net_values) / len(net_values) if net_values else 0.0
        prev_net = net_values[-2] if len(net_values) >= 2 else 0.0
        net_delta = net_values[-1] - prev_net if net_values else 0.0
        arrow = "▲" if net_delta > 0 else ("▼" if net_delta < 0 else "•")
        net_sev = (
            "good" if net_delta > 0 else
            "warn" if net_delta < 0 else "info"
        )
        net_cells = "".join(f"<td>{_money(v)}</td>" for v in net_values)
        summary_rows.append(
            f'<tr style="background:#eff6ff">'
            f'<td><strong>Net cashflow</strong></td>'
            f"{net_cells}"
            f"<td>{_money(avg_net)}</td>"
            f'<td><span class="banner severity-{net_sev}" '
            f'style="display:inline-block;margin:0;padding:2px 8px;'
            f'font-size:12px;border-radius:999px">'
            f'{arrow} {_fmt_delta(net_delta)}</span></td>'
            f'</tr>'
        )
    rows = list(summary_rows)
    for t in trends:
        if t.latest == 0 and t.rolling_3mo == 0 and t.previous == 0:
            continue
        # Each category cell is $amount on line 1 plus the inline
        # "+18%" / "-4%" MoM delta on line 2 (hidden for the leftmost
        # column since there's no predecessor).
        month_cells_parts = []
        for m in shown_months:
            amt = t.by_month.get(m, 0.0)
            pct = (t.pct_by_month or {}).get(m)
            month_cells_parts.append(
                f"<td>{_money(amt)}{_pct_span(pct)}</td>"
            )
        month_cells = "".join(month_cells_parts)
        spark_values = [t.by_month.get(m, 0.0) for m in shown_months]
        spark = _charts.render_sparkline(spark_values, width=110, height=26)
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
            f'<tr><td><strong>{_esc(t.category.replace("_", " ").title())}</strong>'
            f'<div style="margin-top:2px">{spark}</div></td>'
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
{chart_html}
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
more. The small inline percentage under each cell is that month's
change vs the month before it. The 3-month average smooths out
one-off bills.
</p>
"""
    return render_page("trends", "Trends", content, flash=flash)


def _category_select(name: str, selected: str) -> str:
    from finadvisor.models import SPENDING_CATEGORIES
    opts = "".join(
        f'<option value="{v}"{" selected" if v == selected else ""}>'
        f"{_esc(v.replace('_', ' ').title())}</option>"
        for v in SPENDING_CATEGORIES
    )
    return f'<select name="{name}" style="min-width:140px">{opts}</select>'


def render_transactions_page(
    state: FinanceState,
    indices_and_tx,  # list[tuple[int, Transaction]] — preserves state indices
    months: list[str],
    active_month: str,
    active_category: str,
    active_account: str,
    flash: str = "",
) -> str:
    """All-transactions ledger with per-row category override.

    The caller pre-filters the rows by (month, category, account) and
    passes in (state_index, Transaction) pairs so the form can post
    back the original transaction positions.
    """
    from finadvisor.models import SPENDING_CATEGORIES

    # Filter controls.
    month_opts = (
        '<option value="">All months</option>'
        + "".join(
            f'<option value="{_esc(m)}"'
            f'{" selected" if m == active_month else ""}>{_esc(m)}</option>'
            for m in months
        )
    )
    cat_opts = (
        '<option value="">All categories</option>'
        + "".join(
            f'<option value="{v}"'
            f'{" selected" if v == active_category else ""}>'
            f"{_esc(v.replace('_', ' ').title())}</option>"
            for v in SPENDING_CATEGORIES
        )
    )
    account_names = sorted({a.name for a in state.accounts})
    acct_opts = (
        '<option value="">All accounts</option>'
        + "".join(
            f'<option value="{_esc(n)}"'
            f'{" selected" if n == active_account else ""}>{_esc(n)}</option>'
            for n in account_names
        )
    )

    filters = f"""
<form method="get" action="/transactions"
      style="display:flex;gap:12px;align-items:end;flex-wrap:wrap">
  <div style="flex:1 1 140px"><label>Month</label>
    <select name="month">{month_opts}</select></div>
  <div style="flex:1 1 140px"><label>Category</label>
    <select name="category">{cat_opts}</select></div>
  <div style="flex:1 1 140px"><label>Account</label>
    <select name="account">{acct_opts}</select></div>
  <div><button type="submit">Filter</button></div>
</form>
"""

    if not indices_and_tx:
        return render_page(
            "transactions", "Transactions",
            f"<h2>Transactions</h2>{filters}"
            '<p class="muted" style="margin-top:16px">No transactions '
            "match these filters. Import a bank statement on the "
            '<a href="/import">Import</a> page, or widen the filter '
            "above.</p>",
            flash=flash,
        )

    rows = []
    for idx, tx in indices_and_tx:
        amount_cls = "color:#059669" if tx.amount > 0 else "color:#1f2937"
        rows.append(
            "<tr>"
            f"<td>{_esc(tx.date)}</td>"
            f'<td class="muted" style="font-size:12px">{_esc(tx.account)}</td>'
            f"<td>{_esc(tx.description[:80])}</td>"
            f'<td style="text-align:right;{amount_cls}">'
            f"{_money(tx.amount)}</td>"
            f"<td>{_category_select(f'category_{idx}', tx.category)}</td>"
            f'<td style="text-align:center">'
            f'<label style="font-size:11px;color:#6b7280;font-weight:500">'
            f'<input type="checkbox" name="save_rule_{idx}" value="1" '
            f'style="width:auto;margin-right:4px"> save rule</label></td>'
            f'<input type="hidden" name="row_{idx}" value="1">'
            "</tr>"
        )

    total_spend = sum(-t.amount for _, t in indices_and_tx if t.amount < 0)
    total_income = sum(t.amount for _, t in indices_and_tx if t.amount > 0)
    content = f"""
<h2>Transactions</h2>
{filters}
<div class="banner severity-info" style="margin-top:12px">
  <strong>{len(indices_and_tx)} row(s)</strong>
  Income {_money(total_income)} · Spending {_money(total_spend)}.
  Change a category in the dropdown and click Save to re-label
  transactions the auto-classifier got wrong.
</div>
<form method="post" action="/transactions/save">
  <div style="overflow-x:auto">
  <table>
    <thead><tr>
      <th>Date</th><th>Account</th><th>Description</th>
      <th style="text-align:right">Amount</th><th>Category</th>
      <th style="text-align:center">Rule</th>
    </tr></thead>
    <tbody>{''.join(rows)}</tbody>
  </table>
  </div>
  <p class="muted" style="margin-top:10px">
    Tick <strong>save rule</strong> on a row to remember the override
    — future imports of transactions with a matching description will
    be auto-categorized the same way.
  </p>
  <p style="margin-top:12px">
    <button type="submit">Save category changes</button>
    <a class="btn secondary" href="/spending">Back to spending</a>
  </p>
</form>
"""
    return render_page(
        "transactions", "Transactions", content, flash=flash,
    )


def flash_success(msg: str) -> str:
    return f'<div class="flash">{_esc(msg)}</div>'


def flash_error(msg: str) -> str:
    return f'<div class="flash error">{_esc(msg)}</div>'
