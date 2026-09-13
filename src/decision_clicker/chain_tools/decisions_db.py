#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""decisions_db.py -- lokaler SQLite-Index ueber die Entscheidungskette.

[C 2026-09-06 D-20260906-003] Umsetzung des Nutzerentscheids 3A zu Ticket
T-20260902-654459638: KEIN Cutover auf sqlite-transit-sync. Die Quelle bleibt
die OneDrive-synchrone Textkette (``TO-DECIDE-USER.txt`` +
``DECIDED-AND-DONE.md`` + ``_decision-archive/``); jeder Host baut sich daraus
lokal einen wegwerfbaren SQLite-Index. Es gibt keinen Schreibpfad zurueck in
die Quelle und keine Verteilung der DB zwischen Hosts.

Der Parser wird NICHT dupliziert: dieses Skript laedt ``decisions_index`` als
Modul (derselbe Weg, den auch der decision-clicker nimmt) und legt dessen
Eintraege in SQLite ab. Die DB liegt bewusst ausserhalb von OneDrive und
ausserhalb jedes Repos.

Aufruf:
    PYTHONIOENCODING=utf-8 python decisions_db.py             # baut, wenn veraltet
    PYTHONIOENCODING=utf-8 python decisions_db.py --check     # Exit 1 = veraltet
    PYTHONIOENCODING=utf-8 python decisions_db.py --rebuild   # baut immer neu

Pfade sind hostagnostisch und brauchen kein Argument: die Wurzel wird aus dem
Skriptstandort abgeleitet (Override ``--root``/``DECISIONS_ROOT``), der DB-Pfad
ueber ``--db``/``DECISIONS_DB``.
"""
from __future__ import annotations

import argparse
import hashlib
import os
import sqlite3
import sys
from contextlib import closing
from datetime import datetime
from pathlib import Path

# Eine Datei, zwei Rollen: als Paketmodul (decision_clicker.chain_tools) und als
# materialisiertes Einzelskript in <kette>/_tools/. Der relative Import greift nur im
# ersten Fall; im zweiten liegt decisions_index.py als Geschwisterdatei daneben.
try:  # pragma: no cover - abhaengig von der Aufrufform
    from . import decisions_index as di
except ImportError:  # pragma: no cover - materialisierte Einzelskript-Form
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import decisions_index as di  # noqa: E402

VERSION = "1.0.0"
SCHEMA_NAME = "decisions.db/1"
GENERATOR = f"decisions_db.py {VERSION}"

# Kein Benutzername im Pfad -> gilt unveraendert auf ASUS-GEI und WORKSTATION-LG.
DEFAULT_DB = Path(
    os.environ.get("DECISIONS_DB") or Path("C:/_Local_DEV/DATA_STORE/decisions.db")
)

# Wurzel aus dem Skriptstandort ableiten (dieses Skript liegt in <wurzel>/_tools/),
# NICHT `di.DEFAULT_ROOT` erben: der zeigt seit dem Ordnerumzug vom 2026-09-06
# (_control-center/_DECISIONS -> _control-center/_CONTROL/_DECISIONS) auf den
# alten Pfad. Dort steht nur noch ein MOVED-Stub. `DECISIONS_ROOT` bleibt der
# gemeinsame Override beider Werkzeuge.
DEFAULT_ROOT = Path(
    os.environ.get("DECISIONS_ROOT") or Path(__file__).resolve().parent.parent
)

DDL = """
CREATE TABLE decisions (
    key          TEXT PRIMARY KEY,
    id           TEXT NOT NULL,
    datum        TEXT,
    status       TEXT,
    titel        TEXT,
    quelle_datei TEXT,
    zeile        INTEGER,
    volltext     TEXT
);
CREATE INDEX decisions_id_idx ON decisions(id);
CREATE INDEX decisions_status_idx ON decisions(status);
CREATE TABLE sources (quelle_datei TEXT PRIMARY KEY, sha256 TEXT NOT NULL);
CREATE TABLE meta (schluessel TEXT PRIMARY KEY, wert TEXT);
"""


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def source_hashes(root: Path) -> dict[str, str]:
    """Alle Quelldateien der Kette mit Inhaltshash -- Grundlage fuer --check."""
    return {di.relname(p, root): sha256(p) for p, _ in di.collect_sources(root)}


def stale_reason(db_path: Path, root: Path) -> str | None:
    """None = DB ist aktuell. Sonst ein Satz, warum nicht."""
    if not db_path.is_file():
        return f"DB fehlt: {db_path}"
    try:
        with closing(sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)) as conn:
            stored = dict(conn.execute("SELECT quelle_datei, sha256 FROM sources"))
            stored_root = dict(
                conn.execute("SELECT schluessel, wert FROM meta")
            ).get("root")
    except sqlite3.DatabaseError as exc:
        return f"DB unlesbar ({exc}) -- --rebuild noetig"
    if stored_root != str(root):
        return f"DB wurde ueber anderer Wurzel gebaut: {stored_root}"
    current = source_hashes(root)
    if missing := sorted(set(stored) - set(current)):
        return f"Quelldatei(en) verschwunden: {', '.join(missing)}"
    if added := sorted(set(current) - set(stored)):
        return f"Neue Quelldatei(en): {', '.join(added)}"
    if changed := sorted(k for k, v in current.items() if stored[k] != v):
        return f"Geaenderte Quelldatei(en): {', '.join(changed)}"
    return None


def _fts5_available(conn: sqlite3.Connection) -> bool:
    try:
        conn.execute("CREATE VIRTUAL TABLE temp.fts_probe USING fts5(x)")
        conn.execute("DROP TABLE temp.fts_probe")
        return True
    except sqlite3.OperationalError:
        return False


def build(db_path: Path, root: Path) -> dict:
    """DB atomar neu erzeugen. Die alte bleibt bis zum Schluss unangetastet."""
    entries: list[di.Entry] = []
    for path, domain in di.collect_sources(root):
        entries.extend(di.parse_file(path, domain))
    di.assign_keys(entries)  # fuellt entry.key, meldet Kollisionen (hier egal)

    tmp = db_path.with_name(db_path.name + ".tmp")
    db_path.parent.mkdir(parents=True, exist_ok=True)
    tmp.unlink(missing_ok=True)

    with closing(sqlite3.connect(tmp)) as conn, conn:
        conn.executescript(DDL)
        conn.executemany(
            "INSERT INTO decisions VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            [(e.key, e.entry_id, e.date, e.status_class(), e.title,
              di.relname(e.source_path, root), e.source_line, e.raw_text)
             for e in entries],
        )
        fts = _fts5_available(conn)
        if fts:
            conn.execute(
                "CREATE VIRTUAL TABLE decisions_fts USING fts5(key UNINDEXED, titel, volltext)"
            )
            conn.execute(
                "INSERT INTO decisions_fts SELECT key, titel, volltext FROM decisions"
            )
        conn.executemany(
            "INSERT INTO sources VALUES (?, ?)", sorted(source_hashes(root).items())
        )
        conn.executemany("INSERT INTO meta VALUES (?, ?)", [
            ("schema", SCHEMA_NAME),
            ("generator", GENERATOR),
            ("root", str(root)),
            ("generated_at", datetime.now().isoformat(timespec="seconds")),
            ("fts5", "1" if fts else "0"),
        ])
    os.replace(tmp, db_path)
    return {"entries": len(entries), "fts5": fts, "db": str(db_path)}


def main(argv: list[str] | None = None) -> int:
    # `__doc__` ist unter `python -OO` None -- dann waere der Argparse-Aufbau
    # ein AttributeError, bevor irgendetwas geprueft wird.
    parser = argparse.ArgumentParser(
        description=(__doc__ or "decisions db").splitlines()[0])
    parser.add_argument("--root", type=Path, default=DEFAULT_ROOT,
                        help="Wurzel der Entscheidungskette")
    parser.add_argument("--db", type=Path, default=DEFAULT_DB, help="Ziel-DB")
    parser.add_argument("--check", action="store_true",
                        help="nur pruefen; Exit 1, wenn die DB veraltet ist")
    parser.add_argument("--rebuild", action="store_true", help="immer neu bauen")
    args = parser.parse_args(argv)

    root = args.root.resolve()
    if not root.is_dir():
        print(f"FEHLER: Wurzel nicht gefunden: {root}")
        return 2

    reason = stale_reason(args.db, root)
    if args.check:
        print(f"veraltet: {reason}" if reason else f"aktuell: {args.db}")
        return 1 if reason else 0
    if not reason and not args.rebuild:
        print(f"aktuell, kein Neubau noetig: {args.db}")
        return 0

    result = build(args.db, root)
    print(f"gebaut: {result['entries']} Eintraege -> {result['db']}"
          f" (FTS5: {'ja' if result['fts5'] else 'nein'}; Anlass: {reason or 'rebuild'})")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
