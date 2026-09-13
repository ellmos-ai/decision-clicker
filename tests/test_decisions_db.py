# SPDX-License-Identifier: MIT
"""Selbsttest fuer den lokalen SQLite-Index (decisions_db.py).

Baut ein Mini-Register mit drei Eintraegen -- zwei offene plus der
Status-quo-Entscheid D-20260906-003 selbst -- und prueft Bau, Staleness und
Idempotenz. [C 2026-09-06 D-20260906-003]
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from decision_clicker.chain_tools import decisions_db as db

AKTIV = """D-20990101-001 — Erste offene Frage

STATUS: OFFEN
FRAGE: Soll A geschehen?
OPTIONEN:
- A — Ja.
- B — Nein.
ENTSCHEIDUNG DES USERS: [HIER EINTRAGEN]

D-20990101-002 — Zweite offene Frage

STATUS: OFFEN
FRAGE: Soll B geschehen?
OPTIONEN:
- A — Ja.
- B — Nein.
ENTSCHEIDUNG DES USERS: [HIER EINTRAGEN]
"""

DONE = """# Register

## D-20260906-003 — Decisions-DB: lokaler Index statt Cutover

STATUS: ENTSCHIEDEN
FRAGE: Cutover auf sqlite-transit-sync?
OPTIONEN:
- A — lokal reproduzierbarer SQLite-Index ueber die Textquelle.
- B — zentraler Bau plus Transit-Sync.
ENTSCHEIDUNG DES USERS: 3A — alle A, kein Cutover.
"""


@pytest.fixture()
def register(tmp_path: Path) -> Path:
    root = tmp_path / "kette"
    root.mkdir()
    (root / "TO-DECIDE-USER.txt").write_text(AKTIV, encoding="utf-8")
    (root / "DECIDED-AND-DONE.md").write_text(DONE, encoding="utf-8")
    return root


def rows(db_path: Path) -> dict[str, sqlite3.Row]:
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        return {r["key"]: r for r in conn.execute("SELECT * FROM decisions")}


def test_baut_alle_eintraege_mit_status_und_volltext(register: Path, tmp_path: Path) -> None:
    target = tmp_path / "out" / "decisions.db"

    result = db.build(target, register)

    assert result["entries"] == 3
    by_key = rows(target)
    assert set(by_key) == {"D-20990101-001", "D-20990101-002",
                           "D-20260906-003@DECIDED-AND-DONE"}
    offen = by_key["D-20990101-001"]
    assert (offen["status"], offen["datum"]) == (db.di.STATUS_OPEN, "2099-01-01")
    assert offen["quelle_datei"] == "TO-DECIDE-USER.txt" and offen["zeile"] == 1
    entschieden = by_key["D-20260906-003@DECIDED-AND-DONE"]
    assert entschieden["status"] == db.di.STATUS_DONE
    assert "kein Cutover" in entschieden["volltext"]


def test_check_meldet_frisch_dann_veraltet_und_rebuild_heilt(register: Path, tmp_path: Path) -> None:
    target = tmp_path / "decisions.db"
    assert db.stale_reason(target, register)  # DB fehlt noch

    db.build(target, register)
    assert db.stale_reason(target, register) is None

    (register / "TO-DECIDE-USER.txt").write_text(
        AKTIV + "\nD-20990101-003 — Dritte Frage\n\nSTATUS: OFFEN\n"
        "FRAGE: Und C?\nOPTIONEN:\n- A — Ja.\nENTSCHEIDUNG DES USERS: [HIER EINTRAGEN]\n",
        encoding="utf-8",
    )
    assert "Geaenderte Quelldatei" in (db.stale_reason(target, register) or "")

    assert db.build(target, register)["entries"] == 4
    assert db.stale_reason(target, register) is None


def test_main_ist_idempotent_und_baut_nur_bei_bedarf(register: Path, tmp_path: Path, capsys) -> None:
    target = tmp_path / "decisions.db"
    argv = ["--root", str(register), "--db", str(target)]

    assert db.main(argv) == 0
    assert "gebaut" in capsys.readouterr().out
    assert db.main(argv) == 0
    assert "kein Neubau noetig" in capsys.readouterr().out
    assert db.main(argv + ["--check"]) == 0
    assert db.main(argv + ["--rebuild"]) == 0
    assert "gebaut" in capsys.readouterr().out
