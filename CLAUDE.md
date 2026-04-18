# Repo guidance for Claude Code

## Project: finadvisor

A local PySide6 desktop app that analyzes debts and produces payoff
recommendations. See `README.md` for user-facing docs.

## Verifying changes

**Always run the unit test suite before reporting a task complete.** The
core engine is Qt-free and fast (<1s for all 26 tests):

```bash
python -m unittest discover tests/ -v
```

For any change that touches `finadvisor/gui/**`, also run a headless
import/instantiation smoke check to catch Qt errors:

```bash
QT_QPA_PLATFORM=offscreen python -c "
from PySide6.QtWidgets import QApplication
from finadvisor.gui.main_window import MainWindow
app = QApplication([])
MainWindow()
print('GUI instantiates cleanly.')
"
```

The `SessionStart` hook in `.claude/hooks/session-start.sh` installs
every dependency these commands need on Claude Code on the web.

## Architecture notes

- `finadvisor/models.py` — `Debt`, `Budget`, `FinanceState` dataclasses
  with validation in `__post_init__`. Raise `ValueError` for bad input;
  the GUI catches these and shows a `QMessageBox`.
- `finadvisor/strategies/` — each module exposes
  `run(debts, budget, state) -> StrategyResult`. Keep the signature
  stable; `report.run_all` iterates over `STRATEGY_MODULES`.
- `finadvisor/strategies/_simulate.py` — shared month-by-month payoff
  simulator used by avalanche and snowball. If you change amortization
  logic, update both strategies' tests together.
- `finadvisor/gui/` — purely a view on top of the engine. Anything that
  mutates `self.state` must call `self.window_.mark_dirty()` so the
  change is persisted and other pages refresh.

## Things to avoid

- Do not add network calls. Privacy is a core property — all data stays
  on disk.
- Do not commit `finances.json` (it's in `.gitignore`); it contains real
  user debt data.
- Do not couple the strategies to Qt. Tests import the engine without
  PySide6 available.
