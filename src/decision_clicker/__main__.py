# SPDX-License-Identifier: MIT
"""Einstieg: python -m decision_clicker [--port N] [--chain DIR] [--check]"""
from __future__ import annotations

import argparse
import sys
import webbrowser
from dataclasses import replace
from pathlib import Path

from . import chain
from .config import load
from .server import serve


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="decision-clicker", description=__doc__)
    parser.add_argument("--port", type=int, help="Port (Default 8096)")
    parser.add_argument("--chain", type=Path, help="Ordner der Entscheidungskette")
    parser.add_argument("--open", action="store_true", help="Browser mit oeffnen")
    parser.add_argument("--check", action="store_true", help="nur Kette pruefen, nicht starten")
    args = parser.parse_args(argv)

    settings = load()
    if args.port:
        settings = replace(settings, port=args.port)
    if args.chain:
        settings = replace(settings, chain_dir=args.chain.expanduser())

    if args.check:
        try:
            index = chain.build_index(settings)
        except chain.ChainError as exc:
            print(f"FEHLER: {exc}", file=sys.stderr)
            return 2
        werte = chain.counts(index)
        print(f"Kette: {settings.chain_dir}")
        print(f"  offen={werte['offen']} entschieden_offen={werte['entschieden_offen']} "
              f"done={werte['done']} archiviert={werte['archiviert']} gesamt={werte['gesamt']}")
        print(f"  naechste freie ID: {chain.next_id(index)}")
        print(f"  Ziel fuer neue Eintraege: {chain.target_part(settings).name}")
        return 0

    if args.open:
        webbrowser.open(f"http://{settings.host}:{settings.port}")
    serve(settings)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
