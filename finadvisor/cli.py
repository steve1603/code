"""Command-line interface — runs on any Python install (no Qt needed).

Useful for machines where PySide6 can't be installed (Termux on Android,
minimal servers, CI checks). The GUI and CLI share the same storage file
and analysis engine.

Usage:
    python -m finadvisor.cli report
    python -m finadvisor.cli show
    python -m finadvisor.cli add --name "Visa" --kind credit_card \\
        --balance 4000 --apr 0.2499 --min-payment 100 --credit-limit 5000
    python -m finadvisor.cli import-csv path/to/debts.csv
    python -m finadvisor.cli set-budget --income 6000 --expenses 3500 \\
        --savings 1000
    python -m finadvisor.cli remove "Visa"
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from finadvisor import storage
from finadvisor.importers import csv_importer
from finadvisor.models import Budget, Debt
from finadvisor.report import run_all, to_text


def _load(path: Path):
    return storage.load(path)


def _save(state, path: Path) -> None:
    storage.save(state, path)


def cmd_report(args: argparse.Namespace) -> int:
    state = _load(args.store)
    report = run_all(state)
    print(to_text(report))
    return 0


def cmd_show(args: argparse.Namespace) -> int:
    state = _load(args.store)
    print(f"Data file: {args.store}")
    print(f"Monthly income:   ${state.budget.monthly_income:,.2f}")
    print(f"Monthly expenses: ${state.budget.monthly_expenses:,.2f}")
    print(f"Current savings:  ${state.current_savings:,.2f}")
    print(f"Consolidation APR: {state.consolidation_apr * 100:.2f}%")
    print()
    if not state.debts:
        print("No debts on file.")
        return 0
    print(f"{'Name':<24}{'Kind':<14}{'Balance':>12}{'APR':>8}{'Min':>10}")
    print("-" * 68)
    for d in state.debts:
        print(
            f"{d.name:<24}{d.kind:<14}"
            f"${d.balance:>10,.2f} {d.apr * 100:>6.2f}% "
            f"${d.min_payment:>8,.2f}"
        )
    total = sum(d.balance for d in state.debts)
    print("-" * 68)
    print(f"{'TOTAL':<24}{'':<14}${total:>10,.2f}")
    return 0


def cmd_add(args: argparse.Namespace) -> int:
    state = _load(args.store)
    try:
        debt = Debt(
            name=args.name,
            kind=args.kind,
            balance=args.balance,
            apr=args.apr,
            min_payment=args.min_payment,
            credit_limit=args.credit_limit,
            due_day=args.due_day,
        )
    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1
    state.debts.append(debt)
    _save(state, args.store)
    print(f"Added {debt.name}.")
    return 0


def cmd_remove(args: argparse.Namespace) -> int:
    state = _load(args.store)
    before = len(state.debts)
    state.debts = [d for d in state.debts if d.name != args.name]
    if len(state.debts) == before:
        print(f"No debt named {args.name!r} found.", file=sys.stderr)
        return 1
    _save(state, args.store)
    print(f"Removed {args.name}.")
    return 0


def cmd_import_csv(args: argparse.Namespace) -> int:
    state = _load(args.store)
    try:
        new_debts = csv_importer.parse(args.path)
    except csv_importer.CSVImportError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1
    existing = {d.name: i for i, d in enumerate(state.debts)}
    added = updated = 0
    for d in new_debts:
        if d.name in existing:
            state.debts[existing[d.name]] = d
            updated += 1
        else:
            state.debts.append(d)
            added += 1
    _save(state, args.store)
    print(f"Imported {args.path}: {added} added, {updated} updated.")
    return 0


def cmd_set_budget(args: argparse.Namespace) -> int:
    state = _load(args.store)
    try:
        if args.income is not None or args.expenses is not None:
            state.budget = Budget(
                monthly_income=(
                    args.income if args.income is not None
                    else state.budget.monthly_income
                ),
                monthly_expenses=(
                    args.expenses if args.expenses is not None
                    else state.budget.monthly_expenses
                ),
            )
        if args.savings is not None:
            state.current_savings = args.savings
        if args.consolidation_apr is not None:
            state.consolidation_apr = args.consolidation_apr
    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1
    _save(state, args.store)
    print("Budget updated.")
    return 0


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="finadvisor",
        description="Local personal debt advisor (CLI).",
    )
    p.add_argument(
        "--store",
        type=Path,
        default=storage.DEFAULT_STORE,
        help="Path to the JSON data file (default: ./finances.json).",
    )
    sub = p.add_subparsers(dest="command", required=True)

    sub.add_parser("report", help="Print the full recommendation report.")
    sub.add_parser("show", help="Show current debts and budget.")

    add = sub.add_parser("add", help="Add a debt.")
    add.add_argument("--name", required=True)
    add.add_argument(
        "--kind", required=True,
        choices=["credit_card", "student_loan", "auto", "mortgage",
                 "personal", "other"],
    )
    add.add_argument("--balance", type=float, required=True)
    add.add_argument(
        "--apr", type=float, required=True,
        help="APR as a decimal, e.g. 0.2499 for 24.99%%.",
    )
    add.add_argument("--min-payment", type=float, required=True,
                     dest="min_payment")
    add.add_argument("--credit-limit", type=float, default=None,
                     dest="credit_limit")
    add.add_argument("--due-day", type=int, default=None, dest="due_day")

    rm = sub.add_parser("remove", help="Remove a debt by name.")
    rm.add_argument("name")

    imp = sub.add_parser(
        "import-csv",
        help="Import debts from a CSV file. See templates/debts_template.csv.",
    )
    imp.add_argument("path", type=Path)

    bud = sub.add_parser("set-budget", help="Set income / expenses / savings.")
    bud.add_argument("--income", type=float, default=None)
    bud.add_argument("--expenses", type=float, default=None)
    bud.add_argument("--savings", type=float, default=None)
    bud.add_argument(
        "--consolidation-apr", type=float, default=None,
        dest="consolidation_apr",
        help="APR you'd realistically qualify for, e.g. 0.09.",
    )

    return p


_COMMANDS = {
    "report": cmd_report,
    "show": cmd_show,
    "add": cmd_add,
    "remove": cmd_remove,
    "import-csv": cmd_import_csv,
    "set-budget": cmd_set_budget,
}


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    return _COMMANDS[args.command](args)


if __name__ == "__main__":
    raise SystemExit(main())
