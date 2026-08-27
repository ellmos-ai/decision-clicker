# SPDX-License-Identifier: MIT
"""Lesesicht, ID-Vergabe und das Einstellen neuer Entscheidungen."""
from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from decision_clicker import chain, writer
from decision_clicker.config import Settings
from decision_clicker.ui import parse_options


def _render(entry_id: str, title: str, **kwargs) -> str:
    """Kleinste entscheidungsreife synthetische Vorlage."""
    kwargs.setdefault("frage", "Welche Testvariante gilt?")
    kwargs.setdefault("optionen", ["A — erste", "B — zweite"])
    return writer.render_entry(entry_id, title, **kwargs)


# ---------------------------------------------------------------------------
# Lesen
# ---------------------------------------------------------------------------
def test_kette_wird_gelesen(kette: Settings):
    index = chain.build_index(kette)
    assert index["schema"] == "decisions.index/1"
    assert index["counts"]["total"] >= 6


def test_offene_haben_leeres_entscheidungsfeld(kette: Settings):
    for eintrag in chain.open_entries(chain.build_index(kette)):
        assert eintrag["status_class"] == chain.STATUS_OPEN
        assert not eintrag["is_alias"]


def test_register_zeigt_nur_getroffene_entscheidungen(kette: Settings):
    for eintrag in chain.decided_entries(chain.build_index(kette)):
        assert eintrag["status_class"] != chain.STATUS_OPEN


def test_fehlende_kette_meldet_sich_deutlich(tmp_path: Path):
    leer = Settings(chain_dir=tmp_path / "gibt-es-nicht")
    with pytest.raises(chain.ChainError):
        chain.build_index(leer)


# ---------------------------------------------------------------------------
# ID-Vergabe — Lehre aus den bekannten Kollisionen
# ---------------------------------------------------------------------------
def test_neue_id_kollidiert_mit_keinem_bestand(kette: Settings):
    index = chain.build_index(kette)
    neu = chain.next_id(index)
    assert neu not in chain.known_ids(index)


def test_id_vergabe_beachtet_auch_archiv_und_done(kette: Settings):
    """Eine im Archiv liegende ID ist vergeben — sonst entstehen Kollisionen."""
    index = chain.build_index(kette)
    archiviert = {e["id"] for e in index["entries"] if e["domain"] != "active"}
    assert archiviert, "Testkette hat kein Archiv — Aussage waere leer"
    assert chain.next_id(index) not in archiviert


def test_id_vergabe_beachtet_auch_nur_im_manifest_belegte_ids(kette: Settings):
    nested = kette.archive_dir / "historischer-lauf"
    nested.mkdir()
    (nested / "MANIFEST.md").write_text(
        "Früher belegt: D-20991231-001\n", encoding="utf-8")
    index = chain.build_index(kette)
    assert "D-20991231-001" in chain.known_ids(index)
    assert chain.next_id(index, date(2099, 12, 31)) == "D-20991231-002"


def test_zweite_id_am_selben_tag_zaehlt_hoch(kette: Settings):
    """Aufsteigend und frei — aber NICHT zwingend +1.

    Bereits verbrauchte Nummern (etwa aus einem Selbsttest, dessen Eintrag nur
    noch im Archiv steht) werden übersprungen. Genau das ist erwünscht: eine
    einmal vergebene ID wird nie ein zweites Mal ausgegeben.
    """
    index = chain.build_index(kette)
    tag = date(2026, 8, 7)
    erste = chain.next_id(index, tag)
    ziel = chain.target_part(kette)
    writer.append_entry(kette, ziel, _render(erste, "Testeintrag eins"))

    nachher = chain.build_index(kette)
    zweite = chain.next_id(nachher, tag)
    assert zweite != erste
    assert zweite not in chain.known_ids(nachher)
    assert int(zweite.split("-")[-1]) > int(erste.split("-")[-1])


# ---------------------------------------------------------------------------
# Einstellen
# ---------------------------------------------------------------------------
def test_neuer_eintrag_erscheint_als_offen(kette: Settings):
    index = chain.build_index(kette)
    vorher = chain.counts(index)["offen"]
    neu_id = chain.next_id(index)
    ziel = chain.target_part(kette)
    writer.append_entry(kette, ziel, _render(
        neu_id, "Soll der Clicker getestet werden?",
        frage="Test?", optionen=["A — ja", "B — nein"], empfehlung="A — weil Test",
        quelle="tests/test_chain.py"))

    nachher = chain.build_index(kette)
    assert chain.counts(nachher)["offen"] == vorher + 1
    eintrag = chain.find(nachher, neu_id)
    assert eintrag is not None
    assert eintrag["title"] == "Soll der Clicker getestet werden?"
    assert eintrag["status_class"] == chain.STATUS_OPEN
    assert parse_options(eintrag["options_excerpt"]) == [("A", "ja"), ("B", "nein")]


def test_einstellen_bewahrt_den_vollstaendigen_bestand(kette: Settings, original_bytes):
    """Anhängen verändert kein Byte des bestehenden Aktivdokuments."""
    ziel = chain.target_part(kette)
    alt = original_bytes[ziel.name]
    writer.append_entry(kette, ziel, _render(
        chain.next_id(chain.build_index(kette)), "Angehaengt"))
    neu = ziel.read_bytes()
    assert neu.startswith(alt), "Bestehender Text wurde verändert"
    assert "Angehaengt" in neu[len(alt):].decode("utf-8")


def test_neuer_eintrag_steht_hinter_dem_letzten_bestand(kette: Settings):
    """Regressionsschutz: der Kopf-Pointer darf nicht als Ende gelesen werden."""
    ziel = chain.target_part(kette)
    vorher = chain.build_index(kette)
    letzte_zeile = max(
        e["source_line"] for e in vorher["entries"]
        if Path(e["source_path"]) == ziel
    )
    neu_id = chain.next_id(vorher)
    writer.append_entry(kette, ziel, _render(neu_id, "Ganz hinten"))
    eintrag = chain.find(chain.build_index(kette), neu_id)
    assert eintrag["source_line"] > letzte_zeile


def test_zielwahl_bleibt_beim_einen_kanonischen_dokument(kette: Settings):
    """Auch eine Konfliktkopie darf nie zum neuen Aktivziel werden."""
    konflikt = kette.chain_dir / "TO-DECIDE-USER_9.txt"
    konflikt.write_text("historischer Konfliktstand", encoding="utf-8")
    assert chain.target_part(kette).name == "TO-DECIDE-USER.txt"
    index = chain.build_index(kette)
    assert index["active_contract"]["valid"] is False


def test_ungueltiger_aktivvertrag_blockiert_schreibwege(kette: Settings):
    from decision_clicker.api import DecisionClicker

    konflikt = kette.chain_dir / "TO-DECIDE-USER_2.txt"
    konflikt.write_text("Konfliktstand", encoding="utf-8")
    stand = chain.target_part(kette).read_bytes()
    clicker = DecisionClicker(kette.chain_dir)
    assert clicker.usable() is False
    with pytest.raises(chain.ChainError, match="Ungültiger Aktivvertrag"):
        clicker.create(
            "Blockierter Test", frage="Welche Variante?",
            optionen=["A — eins", "B — zwei"])
    assert chain.target_part(kette).read_bytes() == stand


def test_neuer_eintrag_ist_sofort_klickbar_und_verlaesst_dann_aktiv(kette: Settings):
    neu_id = chain.next_id(chain.build_index(kette))
    ziel = chain.target_part(kette)
    writer.append_entry(kette, ziel, _render(
        neu_id, "Direkt entscheidbar", optionen=["A — so", "B — anders"]))
    eintrag = chain.find(chain.build_index(kette), neu_id)
    writer.decide_entry(kette, eintrag, "A", on="2026-08-07")
    danach = chain.find(chain.build_index(kette), neu_id)
    assert danach is None


def test_done_register_bekommt_einen_beleg(kette: Settings):
    index = chain.build_index(kette)
    eintrag = chain.open_entries(index)[0]
    writer.decide_entry(kette, eintrag, "B", "Notiz", on="2026-08-07")
    text = kette.done_file.read_text(encoding="utf-8-sig")
    assert eintrag["id"] in text
    assert "[B — Notiz]" in text
    assert "ENTSCHIEDEN AM: 2026-08-07" in text


def test_unvollstaendige_neue_vorlage_wird_abgelehnt():
    with pytest.raises(writer.WriteError, match="Frage"):
        writer.render_entry("D-20990101-001", "Ohne Frage", optionen=["A — ja"])
    with pytest.raises(writer.WriteError, match="Optionen"):
        writer.render_entry("D-20990101-001", "Ohne Optionen", frage="Test?")


# ---------------------------------------------------------------------------
# Optionen-Erkennung
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("roh,erwartet", [
    ("A — jetzt | B — spaeter", [("A", "jetzt"), ("B", "spaeter")]),
    ("- A — jetzt\n- B — spaeter", [("A", "jetzt"), ("B", "spaeter")]),
    ("Option A: jetzt | Option B: spaeter", [("A", "jetzt"), ("B", "spaeter")]),
    ("", []),
])
def test_optionen_werden_tolerant_erkannt(roh, erwartet):
    assert parse_options(roh) == erwartet


# ---------------------------------------------------------------------------
# Sperren
# ---------------------------------------------------------------------------
def test_fremde_sperre_wird_gesehen(kette: Settings):
    assert writer.foreign_locks(kette) == []
    (kette.chain_dir / "LOCK.fremd.txt").write_text("fremd", encoding="utf-8")
    assert [p.name for p in writer.foreign_locks(kette)] == ["LOCK.fremd.txt"]


def test_eigene_sperre_blockiert_sich_nicht_selbst(kette: Settings):
    writer.write_lock(kette, "Test")
    assert writer.foreign_locks(kette) == []
    assert writer.release_lock(kette) is True
    assert not kette.lock_file.exists()
