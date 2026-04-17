#!/usr/bin/env python3
"""Convenience launcher — equivalent to `python -m finadvisor`."""
from finadvisor.gui.app import main

if __name__ == "__main__":
    raise SystemExit(main())
