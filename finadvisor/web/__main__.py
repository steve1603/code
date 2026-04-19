"""Entry point: `python -m finadvisor.web` launches the local web UI."""
from __future__ import annotations

import argparse
from pathlib import Path

from finadvisor import storage
from finadvisor.web.server import serve


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        prog="finadvisor.web",
        description="Local web UI for finadvisor (stdlib-only).",
    )
    p.add_argument("--host", default="127.0.0.1",
                   help="Bind address (default: 127.0.0.1). Use 0.0.0.0 "
                        "to expose to your LAN — only do so on a trusted "
                        "network; the server has no authentication.")
    p.add_argument("--port", type=int, default=8765,
                   help="Port to listen on (default: 8765).")
    p.add_argument("--store", type=Path, default=storage.DEFAULT_STORE,
                   help="Path to the JSON data file (default: ./finances.json).")
    args = p.parse_args(argv)
    serve(host=args.host, port=args.port, store_path=args.store)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
