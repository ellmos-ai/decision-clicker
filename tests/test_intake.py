# SPDX-License-Identifier: MIT
"""Desktop-Intake: erkennen, übernehmen, markieren, deduplizieren.

Gearbeitet wird ausschließlich auf `tests/data/postfach_sample.txt`. Die
synthetische Datei enthält beide Formate nebeneinander —
Kettenkonvention und die Fremdform `ID: D-…` — und genau daran muss der Scanner
sich bewähren.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from decision_clicker import chain, intake, writer
from decision_clicker.config import Settings

OFFEN_ID = "D-20990806-001"       # im frischen Postfach: der offene Eintrag
ERLEDIGT_IDS = ("D-20990805-001", "D-20990805-002")


def test_synthetisches_postfach_bleibt_lesbar(postfach: Path):
    """Wachhund: Änderungen an der veröffentlichten Fixture fallen auf."""
    eintraege = intake.parse(postfach)
    assert eintraege, "Fixture vorhanden, aber kein Eintrag erkannt"
    assert all(e.entry_id.startswith("D-") for e in eintraege)


# ---------------------------------------------------------------------------
# Erkennen
# ---------------------------------------------------------------------------
def test_beide_formate_werden_erkannt(postfach: Path):
    eintraege = intake.parse(postfach)
    ids = [e.entry_id for e in eintraege]
    assert "D-20260805-001" in ids, "Kettenkonvention (ID in Spalte 0) nicht erkannt"
    assert "D-20260806-001" in ids, "Fremdform 'ID: D-…' nicht erkannt"


def test_fremdform_ist_auch_fuer_den_kanonischen_parser_sichtbar(postfach: Path, kette: Settings):
    """Der konsolidierte Parser erkennt die Legacy-ID ohne zweiten Aktivpfad."""
    tool = chain._load_index_tool(kette.index_script)
    sichtbar = {e.entry_id for e in tool.parse_file(postfach, "intake")}
    assert "D-20260806-001" in sichtbar
    assert "D-20260806-001" in {e.entry_id for e in intake.parse(postfach)}


def test_entschieden_und_offen_werden_unterschieden(postfach: Path):
    nach_id = {e.entry_id: e for e in intake.parse(postfach)}
    assert nach_id["D-20260805-001"].decided is True
    assert nach_id["D-20260806-001"].decided is False


def test_mehrzeilige_frage_wird_vollstaendig_gelesen(postfach: Path):
    eintrag = {e.entry_id: e for e in intake.parse(postfach)}["D-20260806-001"]
    assert eintrag.frage.startswith("Braucht irgendein Schritt")
    assert eintrag.frage.rstrip().endswith("?"), "Frage wurde am Zeilenumbruch abgeschnitten"


def test_optionen_der_fremdform_werden_gesammelt(postfach: Path):
    eintrag = {e.entry_id: e for e in intake.parse(postfach)}["D-20260806-001"]
    buchstaben = [o.split(" — ")[0] for o in eintrag.optionen]
    assert buchstaben == ["A", "B", "C"]
    assert "Tiebreaker" in eintrag.optionen[2]


# ---------------------------------------------------------------------------
# Übernehmen
# ---------------------------------------------------------------------------
def test_uebernahme_verteilt_auf_kette_und_register(frisches_postfach: Path, kette: Settings):
    vorher_offen = chain.counts(chain.build_index(kette))["offen"]
    ergebnis = intake.takeover(kette, on="2026-08-07")
    assert len(ergebnis) == 3

    index = chain.build_index(kette)
    offen = {e["id"] for e in chain.open_entries(index)}
    assert OFFEN_ID in offen, "offener Postfach-Eintrag fehlt in der Klick-Queue"
    assert chain.counts(index)["offen"] == vorher_offen + 1

    done = kette.done_file.read_text(encoding="utf-8-sig")
    assert all(eid in done for eid in ERLEDIGT_IDS)
    assert not set(ERLEDIGT_IDS) & offen, "erledigter Eintrag darf nicht zum Klicken erscheinen"


def test_uebernommener_eintrag_behaelt_seine_id(frisches_postfach: Path, kette: Settings):
    """IDs werden nie neu vergeben — sie können extern referenziert sein."""
    intake.takeover(kette, on="2026-08-07")
    eintrag = chain.find(chain.build_index(kette), OFFEN_ID)
    assert eintrag is not None
    assert eintrag["date"] == "2099-08-06", "Datum der ID darf sich nicht verschieben"


def test_originalwortlaut_bleibt_erhalten(frisches_postfach: Path, kette: Settings):
    quelle = {e.entry_id: e for e in intake.parse(frisches_postfach)}[OFFEN_ID].raw
    intake.takeover(kette, on="2026-08-07")
    ziel = chain.target_part(kette).read_text(encoding="utf-8-sig")
    for zeile in quelle.splitlines():
        if zeile.strip():
            assert f"| {zeile}".rstrip() in ziel, f"Zeile verloren: {zeile[:50]}"


def test_zitat_schuetzt_das_echte_entscheidungsfeld(frisches_postfach: Path, kette: Settings):
    """Ohne den Zitat-Präfix würde der Writer das Feld IM ZITAT füllen."""
    intake.takeover(kette, on="2026-08-07")
    eintrag = chain.find(chain.build_index(kette), OFFEN_ID)
    writer.fill_decision(kette, Path(eintrag["source_path"]), eintrag["source_line"],
                         "B", on="2026-08-07")
    text = chain.target_part(kette).read_text(encoding="utf-8-sig")
    assert "ENTSCHEIDUNG DES USERS: [B]" in text
    assert "| ENTSCHEIDUNG DES USERS:" in text, "Zitatzeile wurde angetastet"


def test_postfach_wird_markiert_statt_geleert(frisches_postfach: Path, kette: Settings):
    vorher = frisches_postfach.read_bytes()
    intake.takeover(kette, on="2026-08-07")
    nachher = frisches_postfach.read_text(encoding="utf-8-sig")
    assert nachher.count(intake.TAKEN_MARK) == 3
    # nichts geloescht: jede nicht-leere Originalzeile steht noch da
    for zeile in vorher.decode("utf-8-sig").splitlines():
        if zeile.strip():
            assert zeile in nachher, f"Zeile verschwunden: {zeile[:50]}"


def test_zweiter_lauf_uebernimmt_nichts_doppelt(frisches_postfach: Path, kette: Settings):
    intake.takeover(kette, on="2026-08-07")
    stand_postfach = frisches_postfach.read_bytes()
    stand_kette = chain.target_part(kette).read_bytes()
    stand_done = kette.done_file.read_bytes()

    assert intake.takeover(kette, on="2026-08-07") == []
    assert frisches_postfach.read_bytes() == stand_postfach
    assert chain.target_part(kette).read_bytes() == stand_kette
    assert kette.done_file.read_bytes() == stand_done


def test_bereits_uebernommenes_wird_nicht_erneut_geholt(postfach: Path, kette: Settings):
    """Der eingefrorene Stand trägt die IDs, die real längst in der Kette stehen."""
    assert intake.takeover(kette, dry_run=True, on="2026-08-07") == []


def test_trockenlauf_schreibt_nichts(frisches_postfach: Path, kette: Settings):
    stand = frisches_postfach.read_bytes(), chain.target_part(kette).read_bytes()
    ergebnis = intake.takeover(kette, dry_run=True, on="2026-08-07")
    assert len(ergebnis) == 3
    assert (frisches_postfach.read_bytes(), chain.target_part(kette).read_bytes()) == stand


def test_fremde_sperre_verhindert_die_uebernahme(frisches_postfach: Path, kette: Settings):
    (kette.chain_dir / "LOCK.fremd.txt").write_text("belegt", encoding="utf-8")
    stand = frisches_postfach.read_bytes()
    with pytest.raises(writer.WriteError, match="Fremde Sperre"):
        intake.takeover(kette, on="2026-08-07")
    assert frisches_postfach.read_bytes() == stand


# ---------------------------------------------------------------------------
# Register
# ---------------------------------------------------------------------------
def test_register_fuehrt_postfach_eintraege(postfach: Path, kette: Settings):
    register = chain.register_entries(kette, chain.build_index(kette))
    ids = {e["id"] for e in register}
    assert {"D-20260805-001", "D-20260805-002"} <= ids


def test_register_dedupliziert_ueber_beide_fundstellen(postfach: Path, kette: Settings):
    """Dieselbe ID steht in der Kette UND im Postfach — im Register einmal."""
    register = chain.register_entries(kette, chain.build_index(kette))
    treffer = [e for e in register if e["id"] == "D-20260805-001"]
    assert len(treffer) == 1, "ID doppelt im Register"
    assert len(treffer[0]["fundstellen"]) >= 2, treffer[0]["fundstellen"]
    assert any("Desktop" in f for f in treffer[0]["fundstellen"])
