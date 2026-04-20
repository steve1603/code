"""Aggregate spending transactions into monthly/category views.

The analysis engine in `strategies/` focuses on debts. This module is
its spending-side twin: given a list of `Transaction`s it produces the
month-by-month category totals, deltas, and insight bullets that power
the /spending and /trends pages.

Everything here is pure — no I/O, no Qt — so it's cheap to test.
"""
from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date
from statistics import mean
from typing import Iterable

from finadvisor.models import SPENDING_CATEGORIES, Transaction


# Categories that represent money flowing within the user's own
# accounts or back to them — these shouldn't show up as "spending" in
# summaries or trend diffs.
NON_SPENDING_CATEGORIES = frozenset({"income", "transfer"})


@dataclass
class MonthlySummary:
    """Totals for a single calendar month."""

    month: str  # "YYYY-MM"
    income: float = 0.0
    spending: float = 0.0            # sum of expense magnitudes
    net: float = 0.0                 # income - spending
    by_category: dict[str, float] = field(default_factory=dict)  # magnitudes
    transaction_count: int = 0


@dataclass
class CategoryTrend:
    """How one category has moved across months."""

    category: str
    by_month: dict[str, float]      # month → magnitude
    latest: float                    # most-recent month's total
    previous: float                  # prior month's total
    rolling_3mo: float               # avg of up-to-3 prior months
    delta_vs_prev: float             # latest - previous
    delta_vs_3mo: float              # latest - rolling_3mo
    # month → % change vs the previous month in this category.
    # First month (and any month with a 0 base) is None.
    pct_by_month: dict[str, float | None] = field(default_factory=dict)


@dataclass
class Recurring:
    """A merchant/amount combo that shows up in ≥2 months.

    Powers the 'Recurring charges' card: lets the user see their
    subscription footprint and the dollars those commitments will eat
    over a year at the current cadence.
    """

    description: str             # cleaned/normalized merchant key
    account: str
    category: str
    typical_amount: float        # median magnitude seen
    months_seen: list[str]       # e.g. ["2026-01", "2026-02", "2026-03"]
    monthly_cost: float          # typical_amount * avg occurrences/mo
    yearly_cost: float           # monthly_cost * 12


@dataclass
class Insight:
    severity: str   # "good" | "info" | "warn" | "urgent"
    title: str
    detail: str


def months_of(transactions: Iterable[Transaction]) -> list[str]:
    """Sorted list of distinct YYYY-MM months represented in the data."""
    return sorted({t.month for t in transactions if t.date})


def monthly_summaries(
    transactions: Iterable[Transaction],
) -> list[MonthlySummary]:
    """Group transactions by month, returning summaries in chronological
    order. Income and spending are split so the caller can show both
    without second-guessing sign conventions."""
    buckets: dict[str, MonthlySummary] = {}
    for tx in transactions:
        if not tx.date:
            continue
        s = buckets.setdefault(tx.month, MonthlySummary(month=tx.month))
        s.transaction_count += 1
        if tx.amount >= 0:
            s.income += tx.amount
        else:
            amt = -tx.amount
            s.spending += amt
            s.by_category[tx.category] = (
                s.by_category.get(tx.category, 0.0) + amt
            )
    # Derive net once totals are in.
    for s in buckets.values():
        s.net = s.income - s.spending
    return [buckets[m] for m in sorted(buckets)]


def category_trends(
    transactions: Iterable[Transaction],
    categories: Iterable[str] | None = None,
) -> list[CategoryTrend]:
    """Per-category month-over-month view.

    `categories` filters the output; default is every non-
    income/transfer spending category that appears in the data.
    Results are sorted by most recent month total, descending — the
    biggest items in your current-month spending come first.
    """
    txs = list(transactions)
    months = months_of(txs)
    if not months:
        return []

    # Build a dense table of (month × category) magnitudes so missing
    # months show as 0 rather than KeyError.
    table: dict[str, dict[str, float]] = defaultdict(
        lambda: {m: 0.0 for m in months}
    )
    for tx in txs:
        if tx.amount >= 0:
            continue
        table[tx.category][tx.month] = (
            table[tx.category].get(tx.month, 0.0) + (-tx.amount)
        )

    latest = months[-1]
    prev = months[-2] if len(months) >= 2 else None
    prior_months = months[:-1][-3:]  # up to 3 months before latest

    selected = (
        list(categories) if categories is not None
        else sorted(
            c for c in table.keys() if c not in NON_SPENDING_CATEGORIES
        )
    )

    out: list[CategoryTrend] = []
    for cat in selected:
        row = table.get(cat, {m: 0.0 for m in months})
        latest_v = row.get(latest, 0.0)
        prev_v = row.get(prev, 0.0) if prev else 0.0
        prior_vs = [row.get(m, 0.0) for m in prior_months] or [0.0]
        rolling = mean(prior_vs)

        # Percent change vs the previous month in this category, per
        # month. The first month has no predecessor; months where the
        # base is 0 get None (can't divide).
        pct_by_month: dict[str, float | None] = {}
        for i, m in enumerate(months):
            if i == 0:
                pct_by_month[m] = None
                continue
            pct_by_month[m] = _pct_change(
                row.get(m, 0.0), row.get(months[i - 1], 0.0),
            )

        out.append(CategoryTrend(
            category=cat,
            by_month=dict(row),
            latest=latest_v,
            previous=prev_v,
            rolling_3mo=rolling,
            delta_vs_prev=latest_v - prev_v,
            delta_vs_3mo=latest_v - rolling,
            pct_by_month=pct_by_month,
        ))

    out.sort(key=lambda t: t.latest, reverse=True)
    return out


def totals_by_account(
    transactions: Iterable[Transaction], month: str,
) -> dict[str, MonthlySummary]:
    """Per-account summary for a single month."""
    buckets: dict[str, MonthlySummary] = {}
    for tx in transactions:
        if tx.month != month:
            continue
        key = tx.account or "(unassigned)"
        s = buckets.setdefault(key, MonthlySummary(month=month))
        s.transaction_count += 1
        if tx.amount >= 0:
            s.income += tx.amount
        else:
            amt = -tx.amount
            s.spending += amt
            s.by_category[tx.category] = (
                s.by_category.get(tx.category, 0.0) + amt
            )
    for s in buckets.values():
        s.net = s.income - s.spending
    return buckets


def income_by_month(
    transactions: Iterable[Transaction],
) -> dict[str, float]:
    """Month → total income (across every account). Transfer rows are
    excluded so self-transfers between a user's own accounts don't
    double-count. Feeds the month-over-month income row on /trends."""
    out: dict[str, float] = {}
    for tx in transactions:
        if tx.amount <= 0 or tx.category == "transfer":
            continue
        out[tx.month] = out.get(tx.month, 0.0) + tx.amount
    return out


def account_category_breakdown(
    transactions: Iterable[Transaction], month: str,
) -> dict[str, dict[str, float]]:
    """{account: {category: magnitude}} for a single month's spending.

    Income/transfer categories are excluded so the matrix reflects
    real outflows — which is what /spending needs to show where money
    went per account."""
    out: dict[str, dict[str, float]] = {}
    for tx in transactions:
        if tx.month != month or tx.amount >= 0:
            continue
        if tx.category in NON_SPENDING_CATEGORIES:
            continue
        acct = tx.account or "(unassigned)"
        bucket = out.setdefault(acct, {})
        bucket[tx.category] = bucket.get(tx.category, 0.0) + (-tx.amount)
    return out


def _pct_change(a: float, b: float) -> float | None:
    """(a - b) / b, handling the b=0 case gracefully."""
    if b == 0:
        return None
    return (a - b) / b


def build_insights(
    transactions: Iterable[Transaction],
    trends: list[CategoryTrend] | None = None,
) -> list[Insight]:
    """Hand-written rules that flag the most actionable movements.

    Kept simple and explainable — each rule maps to a short bullet
    that reads like a coach's note, not a dashboard metric. Callers
    render them as bullets on the spending page.
    """
    txs = list(transactions)
    summaries = monthly_summaries(txs)
    if not summaries:
        return []

    insights: list[Insight] = []
    latest = summaries[-1]

    # 1) Net cashflow.
    if latest.net < 0:
        insights.append(Insight(
            "urgent",
            f"Spent ${abs(latest.net):,.0f} more than you earned in "
            f"{latest.month}",
            "Income minus all spending for the month is negative. "
            "Either cut a category (see the list below) or pause any "
            "extra debt payments until this is in the black.",
        ))
    elif latest.net > 0:
        insights.append(Insight(
            "good",
            f"Net surplus of ${latest.net:,.0f} in {latest.month}",
            "That's the cash available this month for extra debt "
            "paydown, savings, or investment. Redirecting it to your "
            "highest-APR debt gives the biggest payoff win.",
        ))

    # 2) Month-over-month spending jumps in any category > $100 or 25%.
    trends = trends or category_trends(txs)
    for t in trends:
        if t.previous <= 0 and t.latest <= 0:
            continue
        jump_pct = _pct_change(t.latest, t.previous)
        if (
            t.delta_vs_prev >= 100
            or (jump_pct is not None and jump_pct >= 0.25 and t.latest >= 50)
        ):
            pct_phrase = (
                f" ({jump_pct * 100:+.0f}% vs last month)"
                if jump_pct is not None else ""
            )
            insights.append(Insight(
                "warn",
                f"{t.category.replace('_', ' ').title()} up "
                f"${t.delta_vs_prev:,.0f}{pct_phrase}",
                f"Went from ${t.previous:,.0f} to ${t.latest:,.0f}. "
                "Skim the transactions list for one-off charges you "
                "don't want to repeat.",
            ))

    # 3) Subscriptions total — easy cut target.
    sub = next((t for t in trends if t.category == "subscriptions"), None)
    if sub and sub.latest >= 50:
        insights.append(Insight(
            "info",
            f"${sub.latest:,.0f}/mo in subscriptions",
            "List every recurring service and cancel the ones you "
            "haven't used this month — an easy win that compounds.",
        ))

    # 4) Dining vs. groceries ratio.
    groc = next((t for t in trends if t.category == "groceries"), None)
    din = next((t for t in trends if t.category == "dining"), None)
    if groc and din and din.latest > groc.latest and din.latest >= 150:
        insights.append(Insight(
            "warn",
            f"Dining out (${din.latest:,.0f}) exceeds groceries "
            f"(${groc.latest:,.0f})",
            "Cooking two extra dinners a week typically saves $150-250 "
            "a month at current restaurant prices.",
        ))

    # 5) Savings rate (if income > 0).
    if latest.income > 0:
        rate = latest.net / latest.income
        if rate >= 0.20:
            insights.append(Insight(
                "good",
                f"Saving {rate * 100:.0f}% of income this month",
                "Solid margin. Lock it in by scheduling an automatic "
                "transfer of your surplus on payday.",
            ))
        elif rate < 0 or rate < 0.05:
            insights.append(Insight(
                "warn",
                f"Savings rate is {rate * 100:.0f}% of income",
                "Pros target 20%+. The fastest lever is usually the "
                "largest category above — trim it first.",
            ))

    return insights


def projected_monthly_spending(transactions: Iterable[Transaction]) -> float:
    """Simple projection: average of the last 3 months' spending.
    Feeds the budget/analysis pages with a forward estimate without
    needing the user to guess."""
    sums = monthly_summaries(transactions)
    if not sums:
        return 0.0
    tail = sums[-3:]
    return mean(s.spending for s in tail)


def total_spending_by_month(
    transactions: Iterable[Transaction],
) -> dict[str, float]:
    """Month → total non-transfer/non-income spending magnitude.

    Feeds the /trends line chart's primary series. Mirrors the logic
    used by `monthly_summaries(...).spending` but returns a flat
    dict keyed by month string for easy chart consumption.
    """
    out: dict[str, float] = {}
    for tx in transactions:
        if tx.amount >= 0:
            continue
        if tx.category in NON_SPENDING_CATEGORIES:
            continue
        out[tx.month] = out.get(tx.month, 0.0) + (-tx.amount)
    return out


def monthly_deltas(
    totals: dict[str, float],
) -> list[tuple[str, str, float, float | None]]:
    """Produce (prev, next, $ delta, % delta) pairs across consecutive
    months. Useful for rendering side-panel "Jan → Feb +$340 +12%"
    cards beside the line chart.
    """
    months = sorted(totals)
    out: list[tuple[str, str, float, float | None]] = []
    for a, b in zip(months, months[1:]):
        av = totals.get(a, 0.0)
        bv = totals.get(b, 0.0)
        out.append((a, b, bv - av, _pct_change(bv, av)))
    return out


# Merchant name cleanup — strip store/location numbers, city/state
# suffixes, dates, and transaction-id gunk so that "TACO BELL 037203
# SUGAR LAND TX" collapses to the same key as "TACO BELL 012345 OMAHA
# NE". Used by both top_merchants() and detect_recurring().
_MERCHANT_NOISE = [
    re.compile(r"#\s*\d+", re.IGNORECASE),           # store numbers
    re.compile(r"\b\d{4,}\b"),                       # long digit runs
    re.compile(r"\b\d{1,2}/\d{1,2}(?:/\d{2,4})?\b"),  # dates
    re.compile(r"\b[A-Z]{2}\b$"),                    # trailing US state
    re.compile(
        r"\b(debit\s+card\s+purchase|recurring\s+deb\s+card\s+purch|"
        r"pos\s+debit|ach\s+(?:debit|withdrawal|credit)|"
        r"check\s+card|card\s+purchase|purchase)\b",
        re.IGNORECASE,
    ),
]
_MERCHANT_WS = re.compile(r"\s+")


def _normalize_merchant(description: str) -> str:
    """Collapse a raw description to a stable merchant key."""
    if not description:
        return ""
    s = description
    for p in _MERCHANT_NOISE:
        s = p.sub(" ", s)
    # Drop any non-alphanumeric-or-space fluff.
    s = re.sub(r"[^A-Za-z0-9 &'/-]+", " ", s)
    s = _MERCHANT_WS.sub(" ", s).strip()
    # Trim trailing single-letter tokens (usually state halves after
    # the 2-letter state regex ran).
    while s and len(s.rsplit(" ", 1)[-1]) <= 1:
        parts = s.rsplit(" ", 1)
        if len(parts) == 1:
            break
        s = parts[0].strip()
    return s.upper()


def top_merchants(
    transactions: Iterable[Transaction],
    month: str,
    n: int = 10,
) -> list[tuple[str, float]]:
    """Biggest single-merchant outflows for `month`.

    Returns (merchant_label, total_magnitude) pairs, sorted desc.
    Income/transfer categories are skipped so the list reflects real
    outflows. Merchants are normalized so the same store with different
    branch numbers rolls up into one row.
    """
    totals: dict[str, float] = {}
    for tx in transactions:
        if tx.month != month:
            continue
        if tx.amount >= 0:
            continue
        if tx.category in NON_SPENDING_CATEGORIES:
            continue
        key = _normalize_merchant(tx.description) or tx.description.strip()
        if not key:
            continue
        totals[key] = totals.get(key, 0.0) + (-tx.amount)
    ranked = sorted(totals.items(), key=lambda kv: kv[1], reverse=True)
    return ranked[:n]


def detect_recurring(
    transactions: Iterable[Transaction],
    min_months: int = 2,
) -> list[Recurring]:
    """Find merchants billing the same amount (±10%) in ≥ `min_months`
    distinct months. Each group becomes one `Recurring`.

    This is a rule-light heuristic — it handles the ~60-80% of
    subscriptions that hit on a monthly-ish cadence with a stable
    amount (Netflix, Experian, OPPD). Irregular or variable-amount
    charges (utilities that fluctuate, annual memberships) are
    intentionally skipped.
    """
    # Bucket transactions by (merchant_key, account) and by rounded
    # amount-tier so "Netflix $15.99" doesn't cluster with "Netflix
    # $22.99". Tolerance is ±10% so slight promo/tax changes don't
    # split a group.
    groups: dict[tuple[str, str, int], list[Transaction]] = {}
    for tx in transactions:
        if tx.amount >= 0:
            continue
        if tx.category in NON_SPENDING_CATEGORIES:
            continue
        key = _normalize_merchant(tx.description)
        if not key:
            continue
        amt = -tx.amount
        if amt < 1.0:
            continue
        # Tier by 10%-wide buckets so ±10% stays in the same group.
        from math import log10, floor
        if amt <= 0:
            tier = 0
        else:
            tier = int(floor(log10(amt) * 10))  # coarse logarithmic bucket
        groups.setdefault((key, tx.account or "", tier), []).append(tx)

    recurring: list[Recurring] = []
    for (merchant, account, _tier), items in groups.items():
        months_seen = sorted({t.month for t in items})
        if len(months_seen) < min_months:
            continue
        amounts = sorted(-t.amount for t in items)
        median_amt = amounts[len(amounts) // 2]
        # Filter out groups where the spread is wider than ±25% — that
        # signals a variable-amount merchant rather than a subscription.
        if amounts and amounts[0] > 0:
            spread = (amounts[-1] - amounts[0]) / amounts[0]
            if spread > 0.25:
                continue
        # Pick the most common category for this merchant.
        cats = [t.category for t in items]
        category = max(set(cats), key=cats.count)
        monthly = median_amt * (len(items) / max(1, len(months_seen)))
        recurring.append(Recurring(
            description=merchant.title(),
            account=account,
            category=category,
            typical_amount=round(median_amt, 2),
            months_seen=months_seen,
            monthly_cost=round(monthly, 2),
            yearly_cost=round(monthly * 12, 2),
        ))
    recurring.sort(key=lambda r: r.yearly_cost, reverse=True)
    return recurring
