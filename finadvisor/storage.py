"""Load and save the FinanceState to a local JSON file."""
from __future__ import annotations

import json
import os
from pathlib import Path

from finadvisor.models import FinanceState


DEFAULT_STORE = Path("finances.json")


def load(path: Path | str = DEFAULT_STORE) -> FinanceState:
    p = Path(path)
    if not p.exists():
        return FinanceState()
    with p.open("r", encoding="utf-8") as f:
        data = json.load(f)
    return FinanceState.from_dict(data)


def save(state: FinanceState, path: Path | str = DEFAULT_STORE) -> None:
    p = Path(path)
    # Atomic-ish write: write to temp then replace.
    tmp = p.with_suffix(p.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8") as f:
        json.dump(state.to_dict(), f, indent=2, sort_keys=True)
    os.replace(tmp, p)
