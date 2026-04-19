"""Local web UI — stdlib only, so it runs on Termux and other minimal setups.

Usage:
    python -m finadvisor.web              # serves on http://127.0.0.1:8765
    python -m finadvisor.web --port 9000
    python -m finadvisor.web --host 0.0.0.0  # expose to LAN (use with care)
"""
