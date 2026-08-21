# SPDX-License-Identifier: MIT
"""Lesesicht, ID-Vergabe und das Einstellen neuer Entscheidungen."""
from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from decision_clicker import chain, writer
from decision_clicker.config import Settings
from decision_clicker.ui import parse_options


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
    writer.append_entry(kette, ziel, writer.render_entry(erste, "Testeintrag eins"))

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
    writer.append_entry(kette, ziel, writer.render_entry(
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


def test_einstellen_bewahrt_bestand_und_nachfolger_pointer(kette: Settings, original_bytes):
    """Der Bestand bleibt unverändert; ein Nachfolger-Pointer bleibt am Ende."""
    ziel = chain.target_part(kette)
    alt = original_bytes[ziel.name]
    pointer = b"Pointer /"
    pointer_start = alt.index(pointer)
    bestand = alt[:pointer_start]
    nachfolger = alt[pointer_start:]
    writer.append_entry(kette, ziel, writer.render_entry(
        chain.next_id(chain.build_index(kette)), "Angehaengt"))
    neu = ziel.read_bytes()
    assert neu.startswith(bestand), "Bestehender Text wurde verändert"
    assert neu.endswith(nachfolger), "Nachfolger-Pointer wurde verschoben oder verändert"
    assert "Angehaengt" in neu[len(bestand):-len(nachfolger)].decode("utf-8")


def test_neuer_eintrag_steht_hinter_dem_letzten_bestand(kette: Settings):
    """Regressionsschutz: der Kopf-Pointer darf nicht als Ende gelesen werden."""
    ziel = chain.target_part(kette)
    vorher = chain.build_index(kette)
    letzte_zeile = max(
        e["source_line"] for e in vorher["entries"]
        if Path(e["source_path"]) == ziel
    )
    neu_id = chain.next_id(vorher)
    writer.append_entry(kette, ziel, writer.render_entry(neu_id, "Ganz hinten"))
    eintrag = chain.find(chain.build_index(kette), neu_id)
    assert eintrag["source_line"] > letzte_zeile


def test_neuer_eintrag_ist_sofort_klickbar(kette: Settings):
    neu_id = chain.next_id(chain.build_index(kette))
    ziel = chain.target_part(kette)
    writer.append_entry(kette, ziel, writer.render_entry(
        neu_id, "Direkt entscheidbar", optionen=["A — so", "B — anders"]))
    eintrag = chain.find(chain.build_index(kette), neu_id)
    writer.fill_decision(kette, Path(eintrag["source_path"]), eintrag["source_line"],
                         "A", on="2026-08-07")
    danach = chain.find(chain.build_index(kette), neu_id)
    assert danach["status_class"] == chain.STATUS_PENDING


def test_done_register_bekommt_einen_beleg(kette: Settings):
    index = chain.build_index(kette)
    eintrag = chain.open_entries(index)[0]
    writer.fill_decision(kette, Path(eintrag["source_path"]), eintrag["source_line"],
                         "B", "Notiz", on="2026-08-07")
    writer.append_done(kette, eintrag, "B", "Notiz", on="2026-08-07")
    text = kette.done_file.read_text(encoding="utf-8-sig")
    assert eintrag["id"] in text
    assert "[B — Notiz]" in text
    assert "ENTSCHIEDEN AM: 2026-08-07" in text


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
