# SPDX-License-Identifier: MIT
"""Tests für die Materialisierung der Ketten-Werkzeuge.

Der Zweck des Moduls ist Drift-Vermeidung. Diese Tests prüfen genau die drei
Zusagen, auf denen das beruht: eine einzige Quelle, ein erkennbarer Kopf auf der
Kopie, und kein stilles Überschreiben einer Handänderung.
"""
from __future__ import annotations

import pathlib
from pathlib import Path

import pytest

from decision_clicker import chain_tools


def test_leere_kette_meldet_fehlend(tmp_path: Path) -> None:
    befunde = chain_tools.check(tmp_path)
    assert {b.name for b in befunde} == set(chain_tools.WERKZEUGE)
    assert all(b.zustand == "fehlt" for b in befunde)
    assert not any(b.ok for b in befunde)


def test_materialisieren_erzeugt_beide_werkzeuge(tmp_path: Path) -> None:
    geschrieben = chain_tools.materialize(tmp_path)
    assert {p.name for p in geschrieben} == set(chain_tools.WERKZEUGE)
    for name in chain_tools.WERKZEUGE:
        assert (tmp_path / "_tools" / name).is_file()
    assert all(b.ok for b in chain_tools.check(tmp_path))


def test_kopie_traegt_den_warnkopf_und_bleibt_ausfuehrbar(tmp_path: Path) -> None:
    chain_tools.materialize(tmp_path)
    text = (tmp_path / "_tools" / "decisions_index.py").read_text(encoding="utf-8")
    # Shebang muss die erste Zeile bleiben, sonst ist die Datei nicht mehr startbar.
    assert text.startswith("#!"), "Banner darf die Shebang-Zeile nicht verdraengen"
    assert "MATERIALISIERTE KOPIE" in text
    assert "decision_clicker.chain_tools" in text


def test_materialisierte_datei_ist_gueltiges_python(tmp_path: Path) -> None:
    import ast

    chain_tools.materialize(tmp_path)
    for name in chain_tools.WERKZEUGE:
        quelle = (tmp_path / "_tools" / name).read_text(encoding="utf-8")
        ast.parse(quelle)  # wirft bei kaputtem Banner-Einbau


def test_zweiter_lauf_ist_idempotent(tmp_path: Path) -> None:
    chain_tools.materialize(tmp_path)
    assert chain_tools.materialize(tmp_path) == [], "unveraenderte Kette darf nicht neu geschrieben werden"


def test_handaenderung_wird_nicht_still_ueberschrieben(tmp_path: Path) -> None:
    chain_tools.materialize(tmp_path)
    ziel = tmp_path / "_tools" / "decisions_index.py"
    ziel.write_text(ziel.read_text(encoding="utf-8") + "\n# jemand hat hier gearbeitet\n",
                    encoding="utf-8")
    assert [b.zustand for b in chain_tools.check(tmp_path) if b.name == ziel.name] == ["veraltet"]
    with pytest.raises(chain_tools.MaterializeError):
        chain_tools.materialize(tmp_path)
    # Der Inhalt muss den gescheiterten Lauf unveraendert ueberstehen.
    assert "jemand hat hier gearbeitet" in ziel.read_text(encoding="utf-8")


def test_force_zieht_nach(tmp_path: Path) -> None:
    chain_tools.materialize(tmp_path)
    ziel = tmp_path / "_tools" / "decisions_db.py"
    ziel.write_text("# ueberschrieben\n", encoding="utf-8")
    assert chain_tools.materialize(tmp_path, force=True) == [ziel]
    assert all(b.ok for b in chain_tools.check(tmp_path))


def test_materialisiertes_decisions_db_findet_seinen_parser(tmp_path: Path) -> None:
    """Die Doppelrolle ist der Kern: dieselbe Datei muss auch OHNE Paket laufen.

    Als Paketmodul greift `from . import decisions_index`; als Einzelskript in
    `_tools/` muss der Fallback die Geschwisterdatei finden. Waeren es zwei
    Varianten, waere die Drift wieder da.
    """
    import subprocess
    import sys

    chain_tools.materialize(tmp_path)
    ergebnis = subprocess.run(
        [sys.executable, str(tmp_path / "_tools" / "decisions_db.py"), "--help"],
        capture_output=True, text=True,
    )
    assert ergebnis.returncode == 0, ergebnis.stderr


def test_globales_check_verschluckt_das_subkommando_nicht(tmp_path: Path) -> None:
    """Regression: `chain-tools --check` landete im globalen Ketten-Check.

    Der Parser hat ein globales `--check` ("nur Kette pruefen"). Solange main()
    dieses Flag unbesehen auswertete, uebernahm es jedes gleichnamige Flag eines
    Subparsers -- `chain-tools --check` pruefte die Kette statt die Werkzeuge und
    scheiterte an einem fehlenden Aktivdokument. Das trifft jedes kuenftige
    Subkommando mit `--check`, nicht nur dieses.
    """
    from decision_clicker import __main__ as cli

    chain_tools.materialize(tmp_path)
    assert cli.main(["chain-tools", "--chain", str(tmp_path), "--check"]) == 0

    (tmp_path / "_tools" / "decisions_db.py").write_text("# fremd\n", encoding="utf-8")
    assert cli.main(["chain-tools", "--chain", str(tmp_path), "--check"]) == 1


def test_eingefrorene_fixture_nennt_das_paket_als_quelle() -> None:
    """Der Kopf der eingefrorenen Kopie muss auf den JETZIGEN Quellort zeigen.

    Bis 2026-09-13 nannte er die Entscheidungskette. Seit die Werkzeuge im Paket
    liegen und die Kette daraus materialisiert wird, ist das falsch: Wer dem Kopf
    folgt, landete am Projektionsort statt an der Quelle. Ein Hinweis, den
    niemand prueft, verrottet genauso still wie die Kopie, vor der er warnt.
    """
    kopf = (pathlib.Path(__file__).parent / "data" / "chain" / "_tools"
            / "decisions_index.py").read_text(encoding="utf-8")[:3000]
    assert "EINGEFRORENE TESTKOPIE" in kopf
    assert "src/decision_clicker/chain_tools/decisions_index.py" in kopf, (
        "Der Kopf muss den Paketpfad als kanonische Quelle nennen")
    assert "PROJEKTION" in kopf, (
        "Der Kopf muss sagen, dass <_DECISIONS>/_tools/ kein Quellort mehr ist")
