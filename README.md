# finadvisor

A **local**, offline desktop app that helps you understand your debts and
get recommendations on how to pay them off. Built with Python + PySide6.

> Educational tool only. Not licensed financial advice. All data stays
> on your machine — no network calls, no accounts, no cloud.

## Features

- Import debts from a **CSV template** or a **PDF statement**.
- All data normalized into a local `finances.json` file you own.
- Track a simple monthly budget (income / expenses).
- Get side-by-side recommendations from five strategies:
  1. **Avalanche** — pay the highest interest rate first (saves the most money).
  2. **Snowball** — pay the smallest balance first (fastest first win).
  3. **Consolidation / refinance** — flags debts where a lower-rate loan would help.
  4. **Budget / cashflow** — warns about over-extension, suggests how much extra to put toward debt.
  5. **Credit utilization** — for credit cards, warns when balances are too high vs. limits.

## Install & run

Requires Python 3.10 or newer.

```bash
pip install -r requirements.txt
python -m finadvisor
```

The main window opens. Your data is saved to `./finances.json` in the
directory you launched from.

## Importing debts

### CSV

A blank template lives in `templates/debts_template.csv`. Fill in rows
with these columns:

| column | meaning | example |
|---|---|---|
| `name` | your nickname for the debt | `Chase Freedom` |
| `kind` | `credit_card`, `student_loan`, `auto`, `mortgage`, `personal`, or `other` | `credit_card` |
| `balance` | current balance owed, in dollars | `4250.00` |
| `apr` | annual rate as a decimal (e.g. `0.2499` for 24.99%) | `0.2499` |
| `min_payment` | monthly minimum payment | `105.00` |
| `credit_limit` | only for credit cards (blank otherwise) | `10000` |
| `due_day` | day of month due (optional) | `15` |

Then: **Debts → Import CSV…** in the app.

### PDF

**Debts → Import PDF…** extracts balance / APR / minimum / credit limit
from a statement PDF (best-effort — always shows a confirmation dialog
you can correct before saving).

## Testing

The core analysis engine has no Qt dependency and can be tested headless:

```bash
python -m unittest discover tests/
```

## Disclaimer

This program is for personal budgeting and educational purposes only. It
does not constitute financial, tax, or legal advice. Always consult a
qualified professional before making major financial decisions.
