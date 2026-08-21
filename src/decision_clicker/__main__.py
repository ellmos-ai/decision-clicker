# SPDX-License-Identifier: MIT
"""Einstieg des Decision-Clickers.

    python -m decision_clicker                 Server auf 127.0.0.1:8096
    python -m decision_clicker --check         Kette prüfen, nichts starten
    python -m decision_clicker add …           Entscheidung einstellen (CLI-Weg)
    python -m decision_clicker intake          Desktop-Postfach übernehmen
"""
from __future__ import annotations

import argparse
import json
import sys
import webbrowser
from dataclasses import replace
from pathlib import Path

from . import chain, intake, writer
from .config import Settings, load
from .server import serve


def _configure_utf8_output() -> None:
    """CLI-Umlaute auch in umgeleiteten Windows-Ausgaben stabil halten."""
    for stream in (sys.stdout, sys.stderr):
        if reconfigure := getattr(stream, "reconfigure", None):
            reconfigure(encoding="utf-8", errors="replace")


def _gemeinsam(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--chain", type=Path, help="Ordner der Entscheidungskette")


def _einstellungen(args: argparse.Namespace) -> Settings:
    settings = load()
    if getattr(args, "port", None):
        settings = replace(settings, port=args.port)
    if getattr(args, "chain", None):
        settings = replace(settings, chain_dir=args.chain.expanduser())
    return settings


# ---------------------------------------------------------------------------
def cmd_check(args: argparse.Namespace) -> int:
    settings = _einstellungen(args)
    index = chain.build_index(settings)
    werte = chain.counts(index)
    offen_postfach = intake.takeover(settings, dry_run=True)
    print(f"Kette: {settings.chain_dir}")
    print(f"  offen={werte['offen']} entschieden_offen={werte['entschieden_offen']} "
          f"done={werte['done']} archiviert={werte['archiviert']} gesamt={werte['gesamt']}")
    print(f"  nächste freie ID: {chain.next_id(index)}")
    print(f"  Ziel für neue Einträge: {chain.target_part(settings).name}")
    print(f"  Desktop-Postfach: {len(offen_postfach)} noch nicht übernommen"
          + (f" ({', '.join(e['id'] for e in offen_postfach)})" if offen_postfach else ""))
    return 0


def cmd_add(args: argparse.Namespace) -> int:
    """Dritter Einstellweg neben UI-Formular und HTTP-API — dasselbe Ziel."""
    settings = _einstellungen(args)
    with writer.MUTATION_LOCK:
        if fremde := writer.foreign_locks(settings):
            print(f"ABBRUCH: fremde Sperre {[p.name for p in fremde]}", file=sys.stderr)
            return 3
        index = chain.build_index(settings)
        entry_id = chain.next_id(index)
        ziel = chain.target_part(settings)
        rendered = writer.render_entry(
            entry_id, args.title, quelle=args.quelle or "", frage=args.frage or "",
            optionen=args.option or [], empfehlung=args.empfehlung or "",
            kontext=args.kontext or "", scope=args.scope or "",
        )
        if args.dry_run:
            print(rendered)
            return 0
        ergebnis = writer.append_entry(settings, ziel, rendered)
        chain.refresh_artifacts(settings)
    if args.json:
        print(json.dumps({"ok": True, "id": entry_id, **ergebnis}, ensure_ascii=False))
    else:
        print(f"{entry_id} eingestellt in {ziel.name} (Zeile {ergebnis['line']})")
        print(f"Sicherung: {ergebnis['backup']}")
    return 0


def cmd_intake(args: argparse.Namespace) -> int:
    settings = _einstellungen(args)
    with writer.MUTATION_LOCK:
        ergebnis = intake.takeover(settings, dry_run=args.dry_run)
    if not ergebnis:
        print("Desktop-Postfach: nichts zu übernehmen.")
        return 0
    kopf = "WÜRDE ÜBERNEHMEN" if args.dry_run else "ÜBERNOMMEN"
    for eintrag in ergebnis:
        print(f"{kopf}: {eintrag['id']} -> {eintrag['ziel']} "
              f"({'entschieden' if eintrag['entschieden'] else 'offen'}) — {eintrag['titel'][:60]}")
    print(f"{len(ergebnis)} Einträge.")
    return 0


def cmd_serve(args: argparse.Namespace) -> int:
    settings = _einstellungen(args)
    if args.open:
        webbrowser.open(f"http://{settings.host}:{settings.port}")
    serve(settings)
    return 0


# ---------------------------------------------------------------------------
def main(argv: list[str] | None = None) -> int:
    _configure_utf8_output()
    parser = argparse.ArgumentParser(prog="decision-clicker", description=__doc__)
    parser.add_argument("--port", type=int, help="Port (Default 8096)")
    parser.add_argument("--open", action="store_true", help="Browser mit öffnen")
    parser.add_argument("--check", action="store_true", help="nur Kette prüfen")
    _gemeinsam(parser)
    unter = parser.add_subparsers(dest="befehl")

    p_add = unter.add_parser("add", help="Entscheidung in die Kette einstellen")
    p_add.add_argument("title", help="Titel der Entscheidung")
    p_add.add_argument("--frage", help="Was genau ist zu entscheiden?")
    p_add.add_argument("--option", action="append", metavar="'A — Text'",
                       help="Option; mehrfach angebbar")
    p_add.add_argument("--empfehlung")
    p_add.add_argument("--kontext")
    p_add.add_argument("--quelle")
    p_add.add_argument("--scope", help="global | host:<name> | projekt:<pfad>")
    p_add.add_argument("--json", action="store_true", help="Ergebnis als JSON")
    p_add.add_argument("--dry-run", action="store_true", help="nur zeigen")
    _gemeinsam(p_add)
    p_add.set_defaults(func=cmd_add)

    p_in = unter.add_parser("intake", help="Desktop-Postfach in die Kette übernehmen")
    p_in.add_argument("--dry-run", action="store_true", help="nur zeigen")
    _gemeinsam(p_in)
    p_in.set_defaults(func=cmd_intake)

    args = parser.parse_args(argv)
    if args.check:
        args.func = cmd_check
    elif not hasattr(args, "func"):
        args.func = cmd_serve

    try:
        return args.func(args)
    except (chain.ChainError, writer.WriteError) as fehler:
        print(f"FEHLER: {fehler}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
