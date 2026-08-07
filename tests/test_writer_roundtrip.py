# SPDX-License-Identifier: MIT
"""Der zentrale Beweis: ausser dem gefuellten Feld aendert sich nichts.

Diese Datei ist der Grund, warum das Werkzeug ueberhaupt in die Kette
schreiben darf. Sie laeuft gegen KOPIEN echter TO-DECIDE-Dateien.
"""
from __future__ import annotations

import difflib
from pathlib import Path

import pytest

from decision_clicker import chain, writer
from decision_clicker.config import Settings


def _offene(kette: Settings) -> list[dict]:
    return chain.open_entries(chain.build_index(kette))


# ---------------------------------------------------------------------------
# Byte-Identitaet
# ---------------------------------------------------------------------------
def test_nur_das_entscheidungsfeld_aendert_sich(kette: Settings, original_bytes):
    """Genau 3 Zeilen unterscheiden sich: Feld + Leerzeile + Datumszeile."""
    offen = _offene(kette)
    assert offen, "Testkette enthaelt keine offene Entscheidung"
    ziel = offen[0]
    pfad = Path(ziel["source_path"])

    writer.fill_decision(kette, pfad, ziel["source_line"], "B", "Testnotiz", on="2026-08-07")

    # read_bytes()+decode() statt read_text(): Letzteres macht Universal-Newline-
    # Uebersetzung (CRLF -> LF), was in CRLF-Teilen der Kette (z. B. Teil 4)
    # JEDE Zeile als "geaendert" zeigen wuerde -- ein Artefakt der Lesart, keine
    # echte Aenderung. `vorher` liest schon bytegenau, `nachher` muss es auch.
    vorher = original_bytes[pfad.name].decode("utf-8-sig").splitlines(keepends=True)
    nachher = pfad.read_bytes().decode("utf-8-sig").splitlines(keepends=True)

    delta = [d for d in difflib.ndiff(vorher, nachher) if d[0] in "+-"]
    entfernt = [d[2:] for d in delta if d.startswith("- ")]
    ergaenzt = [d[2:] for d in delta if d.startswith("+ ")]

    assert len(entfernt) == 1, f"Es darf genau eine Zeile ersetzt werden: {entfernt}"
    assert "ENTSCHEIDUNG DES USERS" in entfernt[0]
    assert len(ergaenzt) == 3, f"Feld + Leerzeile + Datum erwartet: {ergaenzt}"
    assert "[B — Testnotiz]" in ergaenzt[0]
    assert ergaenzt[1].strip() == ""
    assert "ENTSCHIEDEN AM: 2026-08-07" in ergaenzt[2]


def test_alle_anderen_dateien_bleiben_unberuehrt(kette: Settings, original_bytes):
    offen = _offene(kette)
    ziel = offen[0]
    pfad = Path(ziel["source_path"])
    writer.fill_decision(kette, pfad, ziel["source_line"], "A", on="2026-08-07")

    for rel, roh in original_bytes.items():
        if rel in (pfad.name, kette.done_file.name):
            continue
        assert (kette.chain_dir / rel).read_bytes() == roh, f"{rel} wurde veraendert"


def test_zeilenenden_und_bom_bleiben_erhalten(kette: Settings, original_bytes):
    """Neue Zeilen uebernehmen den lokalen Zeilenumbruch-Stil — der Rest der
    Datei bleibt unangetastet, auch wenn sie (wie Teil 4 real) keine reine
    CRLF-Datei mehr ist, sondern ueberwiegend CRLF mit ein paar alten
    Einzel-LF-Zeilen. Die Behauptung ist NICHT "die ganze Datei ist einheitlich",
    sondern "fill_decision aendert an der bestehenden Mischung nichts, ausser
    zwei neuen, einheitlich endenden Zeilen"."""
    for eintrag in _offene(kette)[:6]:
        pfad = Path(eintrag["source_path"])
        vorher = original_bytes[pfad.name]
        crlf_vorher = vorher.count(b"\r\n")
        lf_vorher = vorher.count(b"\n")
        lf_only_vorher = lf_vorher - crlf_vorher
        try:
            writer.fill_decision(kette, pfad, eintrag["source_line"], "A", on="2026-08-07")
        except writer.WriteError:
            continue
        nachher = pfad.read_bytes()
        assert nachher.startswith(b"\xef\xbb\xbf") == vorher.startswith(b"\xef\xbb\xbf")
        crlf_nachher = nachher.count(b"\r\n")
        lf_only_nachher = nachher.count(b"\n") - crlf_nachher
        crlf_delta = crlf_nachher - crlf_vorher
        lf_only_delta = lf_only_nachher - lf_only_vorher
        assert crlf_delta + lf_only_delta == 2, "genau zwei neue Zeilen erwartet"
        assert crlf_delta in (0, 2) and lf_only_delta in (0, 2), (
            "die zwei neuen Zeilen muessen einheitlich enden, nicht gemischt")
        assert nachher.count(b"\n") == lf_vorher + 2


def test_umlaute_ueberleben_den_schreibvorgang(kette: Settings):
    eintrag = _offene(kette)[0]
    pfad = Path(eintrag["source_path"])
    writer.fill_decision(kette, pfad, eintrag["source_line"], "A",
                         "Größe, Prüfung, Änderung — später", on="2026-08-07")
    text = pfad.read_text(encoding="utf-8-sig")
    assert "Größe, Prüfung, Änderung — später" in text


# ---------------------------------------------------------------------------
# Index-Wirkung
# ---------------------------------------------------------------------------
def test_eintrag_gilt_danach_als_entschieden(kette: Settings):
    vorher = chain.build_index(kette)
    eintrag = chain.open_entries(vorher)[0]
    writer.fill_decision(kette, Path(eintrag["source_path"]), eintrag["source_line"],
                         "C", "mit Auflage", on="2026-08-07")
    nachher = chain.build_index(kette)
    neu = chain.find(nachher, eintrag["key"])
    assert neu is not None
    assert neu["status_class"] == chain.STATUS_PENDING
    assert chain.counts(nachher)["offen"] == chain.counts(vorher)["offen"] - 1


def test_datumszeile_verschmutzt_den_index_nicht(kette: Settings):
    """Die Leerzeile vor dem Datum haelt es aus dem Entscheidungswert heraus."""
    eintrag = chain.open_entries(chain.build_index(kette))[0]
    writer.fill_decision(kette, Path(eintrag["source_path"]), eintrag["source_line"],
                         "B", on="2026-08-07")
    neu = chain.find(chain.build_index(kette), eintrag["key"])
    assert "ENTSCHIEDEN AM" not in neu["decision_field_raw"]
    assert neu["decision_field_raw"].strip() == "[B]"


# ---------------------------------------------------------------------------
# Schutzverhalten
# ---------------------------------------------------------------------------
def test_bereits_entschiedenes_wird_nicht_ueberschrieben(kette: Settings):
    eintrag = chain.open_entries(chain.build_index(kette))[0]
    pfad = Path(eintrag["source_path"])
    writer.fill_decision(kette, pfad, eintrag["source_line"], "A", on="2026-08-07")
    vorher = pfad.read_bytes()
    with pytest.raises(writer.WriteError, match="bereits entschieden"):
        writer.fill_decision(kette, pfad, eintrag["source_line"], "B", on="2026-08-07")
    assert pfad.read_bytes() == vorher


def test_leere_entscheidung_wird_abgelehnt(kette: Settings):
    eintrag = chain.open_entries(chain.build_index(kette))[0]
    pfad = Path(eintrag["source_path"])
    vorher = pfad.read_bytes()
    with pytest.raises(writer.WriteError):
        writer.fill_decision(kette, pfad, eintrag["source_line"], "   ", on="2026-08-07")
    assert pfad.read_bytes() == vorher


def test_jede_aenderung_legt_eine_sicherung_an(kette: Settings):
    eintrag = chain.open_entries(chain.build_index(kette))[0]
    pfad = Path(eintrag["source_path"])
    vorher = pfad.read_bytes()
    ergebnis = writer.fill_decision(kette, pfad, eintrag["source_line"], "A", on="2026-08-07")
    sicherung = Path(ergebnis["backup"])
    assert sicherung.is_file()
    assert sicherung.parent == kette.backup_dir
    assert sicherung.read_bytes() == vorher, "Sicherung muss den Stand VOR der Aenderung halten"


def test_fehlendes_feld_bricht_ab_statt_zu_raten(kette: Settings):
    pfad = kette.chain_dir / "TO-DECIDE-USER.txt"
    vorher = pfad.read_bytes()
    with pytest.raises(writer.WriteError, match="Kein Feld"):
        writer.fill_decision(kette, pfad, 1, "A", on="2026-08-07")
    assert pfad.read_bytes() == vorher
