# SPDX-License-Identifier: MIT
"""Rückgängig-Machen im Ein-Dokument-Aktivvertrag.

Der Clicker entfernt beantwortete Vollblöcke sofort aus Aktiv. Undo stellt den
gesicherten Originalblock bytegetreu wieder ein und ergänzt den historischen
Beleg append-only; die frühere Position im Gesamtdokument ist nicht Teil des
Vertrags.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from decision_clicker import chain, writer
from decision_clicker.api import DecisionClicker
from decision_clicker.config import Settings


def _offene(kette: Settings) -> list[dict]:
    return chain.open_entries(chain.build_index(kette))


# ---------------------------------------------------------------------------
# Byte-genauer Roundtrip
# ---------------------------------------------------------------------------
def test_undo_stellt_die_kette_byte_identisch_wieder_her(kette: Settings, original_bytes):
    eintrag = _offene(kette)[0]
    pfad = Path(eintrag["source_path"])
    vorher = original_bytes[pfad.name]

    writer.fill_decision(kette, pfad, eintrag["source_line"], "B", "Testnotiz", on="2026-08-07")
    assert pfad.read_bytes() != vorher, "Vorbedingung: die Entscheidung muss etwas geändert haben"

    neu = chain.find(chain.build_index(kette), eintrag["key"])
    writer.revert_decision(kette, pfad, neu["source_line"], expected_id=neu["id"])

    assert pfad.read_bytes() == vorher, "Undo muss die Kettendatei byte-identisch zurücklassen"


def test_undo_ueber_die_fassade_ist_wieder_offen(kette: Settings):
    """`decide()` -> `undo()`: die ID gilt danach wieder als offen, nicht als entschieden."""
    clicker = DecisionClicker(kette.chain_dir)
    eintrag = _offene(kette)[0]
    original_block = clicker.raw_text(eintrag)
    pfad = Path(eintrag["source_path"])
    original_text, _ = writer._read(pfad)
    lines = original_text.splitlines(keepends=True)
    start, end = writer.entry_bounds(kette, lines, eintrag["source_line"])
    original_block_bytes = "".join(lines[start:end]).encode("utf-8")

    clicker.decide(eintrag["key"], "A", "Notiz")
    zwischenstand = chain.find(chain.build_index(kette), eintrag["key"])
    assert zwischenstand is None

    clicker.undo(eintrag["key"])

    danach = chain.find(chain.build_index(kette), eintrag["key"])
    assert danach["status_class"] == chain.STATUS_OPEN
    assert danach["key"] in [e["key"] for e in _offene(kette)]
    assert clicker.raw_text(danach) == original_block
    assert original_block_bytes in pfad.read_bytes()
    assert chain.build_index(kette)["active_contract"]["valid"] is True


def test_undo_loescht_den_beleg_nicht_sondern_vermerkt_ihn(kette: Settings):
    clicker = DecisionClicker(kette.chain_dir)
    eintrag = _offene(kette)[0]

    clicker.decide(eintrag["key"], "A", "Notiz")
    beleg_vorher = kette.done_file.read_text(encoding="utf-8-sig")
    assert eintrag["id"] in beleg_vorher

    clicker.undo(eintrag["key"], reason="Fehlklick, Test")

    beleg_nachher = kette.done_file.read_text(encoding="utf-8-sig")
    # Append-only heisst: jede Zeile von vorher steht noch drin (nichts geloescht) —
    # NICHT, dass der alte Block als zusammenhaengender String erhalten bleibt,
    # denn die neue Zeile wird MITTEN im Block eingefuegt (vor den Trennzeilen).
    for zeile in beleg_vorher.splitlines():
        assert zeile in beleg_nachher, f"Zeile aus dem Beleg verschwunden: {zeile!r}"
    assert "ZURÜCKGESETZT AM:" in beleg_nachher
    assert "Fehlklick, Test" in beleg_nachher
    assert "Entscheidung wieder offen" in beleg_nachher

    # Der Vermerk steht IM Block dieser ID, nicht irgendwo sonst im Dokument.
    block_start = beleg_nachher.index(f"## {eintrag['id']}")
    naechste = beleg_nachher.find("\n## ", block_start + 1)
    block = beleg_nachher[block_start:naechste if naechste != -1 else len(beleg_nachher)]
    assert "ZURÜCKGESETZT AM:" in block, "Vermerk landete nicht im richtigen Block"


def test_verlauf_zeigt_zurueckgesetzt_nach_undo(kette: Settings):
    """`history()` ist juengste-zuerst — bei einer ID mit Vorgeschichte (in der
    echten Kette schon vorgekommen, siehe D-20260729-00[1-3]) ist NICHT
    garantiert, dass sie nur einmal auftaucht. Massgeblich ist immer der
    NEUESTE Eintrag, also `history()[0]`, nicht ein per-ID-Dict."""
    clicker = DecisionClicker(kette.chain_dir)
    eintrag = _offene(kette)[0]

    clicker.decide(eintrag["key"], "A")
    vor_undo = clicker.history()[0]
    assert vor_undo["id"] == eintrag["id"]
    assert vor_undo["status"] == "aktiv"

    clicker.undo(eintrag["key"])
    nach_undo = clicker.history()[0]
    assert nach_undo["id"] == eintrag["id"]
    assert nach_undo["status"] == "zurueckgesetzt"


# ---------------------------------------------------------------------------
# Schutzverhalten
# ---------------------------------------------------------------------------
def test_undo_ohne_vorherige_entscheidung_wird_abgelehnt(kette: Settings):
    eintrag = _offene(kette)[0]
    pfad = Path(eintrag["source_path"])
    vorher = pfad.read_bytes()
    with pytest.raises(writer.WriteError, match="nicht entschieden"):
        writer.revert_decision(kette, pfad, eintrag["source_line"])
    assert pfad.read_bytes() == vorher


def test_zweiter_undo_auf_dieselbe_id_schlaegt_fehl(kette: Settings):
    clicker = DecisionClicker(kette.chain_dir)
    eintrag = _offene(kette)[0]
    clicker.decide(eintrag["key"], "A")
    clicker.undo(eintrag["key"])
    with pytest.raises(writer.WriteError):
        clicker.undo(eintrag["key"])


def test_undo_lehnt_extern_entschiedenes_ab(kette: Settings):
    """Ohne die 'decision-clicker'-Markierung wird nichts zurückgenommen."""
    eintrag = _offene(kette)[0]
    pfad = Path(eintrag["source_path"])
    text = pfad.read_text(encoding="utf-8-sig")
    text = text.replace("ENTSCHEIDUNG DES USERS: [HIER EINTRAGEN]",
                         "ENTSCHEIDUNG DES USERS: [A]\n\nENTSCHIEDEN AM: 2026-08-07 (von Hand)",
                         1)
    pfad.write_text(text, encoding="utf-8-sig")
    neu = chain.find(chain.build_index(kette), eintrag["key"])
    assert neu["status_class"] == chain.STATUS_PENDING

    with pytest.raises(writer.WriteError, match="extern entschieden"):
        writer.revert_decision(kette, pfad, neu["source_line"], expected_id=neu["id"])


def test_undo_ohne_offenen_clicker_beleg_wird_abgelehnt(kette: Settings):
    """`mark_decision_undone` fuer eine ID ohne Clicker-Beleg lehnt ab."""
    with pytest.raises(writer.WriteError, match="keinen offenen"):
        writer.mark_decision_undone(kette, "D-20990101-999", "Test")


def test_jede_undo_aenderung_legt_eine_sicherung_an(kette: Settings):
    clicker = DecisionClicker(kette.chain_dir)
    eintrag = _offene(kette)[0]
    clicker.decide(eintrag["key"], "A")

    vor_undo_kette = Path(eintrag["source_path"]).read_bytes()
    vor_undo_done = kette.done_file.read_bytes()

    ergebnis = clicker.undo(eintrag["key"])

    kette_sicherung = Path(ergebnis["kette"]["backup"])
    beleg_sicherung = Path(ergebnis["beleg"]["backup"])
    assert kette_sicherung.is_file() and kette_sicherung.read_bytes() == vor_undo_kette
    assert beleg_sicherung.is_file() and beleg_sicherung.read_bytes() == vor_undo_done


def test_fremde_sperre_verhindert_das_zuruecknehmen(kette: Settings):
    clicker = DecisionClicker(kette.chain_dir)
    eintrag = _offene(kette)[0]
    clicker.decide(eintrag["key"], "A")
    (kette.chain_dir / "LOCK.anderer-agent.txt").write_text("belegt", encoding="utf-8")
    with pytest.raises(writer.WriteError, match="Fremde Sperre"):
        clicker.undo(eintrag["key"])
