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


def test_lock_uebernimmt_keinen_bereits_belegten_gleichnamigen_claim(kette: Settings):
    fremd = b"LOCK -- foreign fixture\nAGENT: other-process\n"
    kette.lock_file.write_bytes(fremd)

    with pytest.raises(writer.WriteError, match="bereits vorhanden"):
        writer.write_lock(kette, "Test")

    assert kette.lock_file.read_bytes() == fremd
    assert writer.foreign_locks(kette) == [kette.lock_file]


def test_release_verweigert_fremden_gleichnamigen_claim(kette: Settings):
    fremd = b"LOCK -- foreign fixture\nAGENT: other-process\n"
    kette.lock_file.write_bytes(fremd)

    with pytest.raises(writer.WriteError, match="nicht diesem Prozess"):
        writer.release_lock(kette)

    assert kette.lock_file.read_bytes() == fremd


def test_release_bewahrt_zwischenzeitlich_ersetzten_claim(kette: Settings):
    writer.write_lock(kette, "Test")
    eigener_claim = kette.lock_file.read_bytes()
    assert b"CLAIM-ID:" in eigener_claim
    fremder_ersatz = b"LOCK -- replacement fixture\nAGENT: other-process\n"
    kette.lock_file.write_bytes(fremder_ersatz)

    with pytest.raises(writer.WriteError, match="ersetzt oder verändert"):
        writer.release_lock(kette)

    assert kette.lock_file.read_bytes() == fremder_ersatz
    assert writer.foreign_locks(kette) == [kette.lock_file]


def test_release_ohne_vorhandenen_claim_bleibt_false(kette: Settings):
    assert writer.release_lock(kette) is False


def _fsync_scheitert_fuer_unregistrierten_claim(kette: Settings, monkeypatch, fehler: BaseException) -> None:
    """Nur das fsync des noch nicht registrierten Lock-Handles scheitern lassen."""
    import os

    echtes_fsync = os.fsync

    def fsync(fd):
        if kette.lock_file.exists() and writer._OWNED_LOCKS.get(kette.lock_file.resolve(strict=False)) is None:
            raise fehler
        return echtes_fsync(fd)

    monkeypatch.setattr(os, "fsync", fsync)


def test_schreibfehler_hinterlaesst_keinen_verwaisten_eigenen_claim(kette: Settings, monkeypatch):
    _fsync_scheitert_fuer_unregistrierten_claim(kette, monkeypatch, OSError(28, "No space left on device"))

    with pytest.raises(writer.WriteError, match="Teil-Claim entfernt"):
        writer.write_lock(kette, "Test")

    assert not kette.lock_file.exists()
    assert writer.foreign_locks(kette) == []
    monkeypatch.undo()
    writer.write_lock(kette, "Test")  # kein Selbstblock nach dem Fehler
    assert writer.release_lock(kette) is True


def test_abbruch_beim_schreiben_raeumt_eigenen_claim_auf(kette: Settings, monkeypatch):
    _fsync_scheitert_fuer_unregistrierten_claim(kette, monkeypatch, KeyboardInterrupt())

    with pytest.raises(KeyboardInterrupt):
        writer.write_lock(kette, "Test")

    assert not kette.lock_file.exists()
    assert writer.foreign_locks(kette) == []


def test_teil_claim_mit_fremdem_inhalt_bleibt_stehen(kette: Settings):
    fremd = b"LOCK -- replacement fixture\nAGENT: other-process\n"
    kette.lock_file.write_bytes(fremd)

    assert writer._discard_partial_claim(kette.lock_file, b"LOCK \xe2\x80\x94 decision-clicker\n") is False
    assert kette.lock_file.read_bytes() == fremd


def _fsync_hinterlaesst(kette: Settings, monkeypatch, zustand) -> None:
    """Vor dem fsync-Fehler den Dateizustand herstellen, den der Aufraeumer vorfinden soll."""
    import os

    def fsync(fd):
        zustand(fd)
        raise OSError(28, "No space left on device")

    monkeypatch.setattr(os, "fsync", fsync)
    monkeypatch.setattr(writer.time, "sleep", lambda _pause: None)


@pytest.mark.parametrize("laenge", [0, 10])
def test_echter_praefix_teil_claim_wird_entfernt(kette: Settings, monkeypatch, laenge: int):
    import os

    gesehen = []

    def kuerzen(fd):
        os.ftruncate(fd, laenge)
        gesehen.append(kette.lock_file.stat().st_size)

    _fsync_hinterlaesst(kette, monkeypatch, kuerzen)

    with pytest.raises(writer.WriteError, match="Teil-Claim entfernt"):
        writer.write_lock(kette, "Test")

    assert gesehen == [laenge]  # der Aufraeumer fand wirklich nur 0 Bytes bzw. ein Praefix vor
    assert not kette.lock_file.exists()
    assert writer.foreign_locks(kette) == []


def test_nicht_entfernbarer_teil_claim_wird_als_solcher_gemeldet(kette: Settings, monkeypatch):
    fremd = b"LOCK -- replacement fixture\nAGENT: other-process\n"
    _fsync_hinterlaesst(kette, monkeypatch, lambda _fd: kette.lock_file.write_bytes(fremd))

    with pytest.raises(writer.WriteError, match="Teil-Claim NICHT entfernt, bitte prüfen"):
        writer.write_lock(kette, "Test")

    assert kette.lock_file.read_bytes() == fremd
    assert writer.foreign_locks(kette) == [kette.lock_file]


def _voruebergehend_gesperrt(kette: Settings, monkeypatch, methode: str, fehlversuche: int, danach=None) -> list:
    """``Path.<methode>`` fuer die Sperrdatei zunaechst mit einer Sharing-Verletzung scheitern lassen."""
    echt = getattr(Path, methode)
    versuche = []

    def gesperrt(self, *args, **kwargs):
        if self == kette.lock_file and len(versuche) < fehlversuche:
            versuche.append(methode)
            if danach is not None and len(versuche) == fehlversuche:
                danach()
            raise PermissionError(13, "sharing violation")
        return echt(self, *args, **kwargs)

    monkeypatch.setattr(Path, methode, gesperrt)
    monkeypatch.setattr(writer.time, "sleep", lambda _pause: None)
    return versuche


@pytest.mark.parametrize("methode", ["read_bytes", "unlink"])
def test_teil_claim_wird_trotz_voruebergehender_sperre_entfernt(kette: Settings, monkeypatch, methode: str):
    eigener = b"LOCK \xe2\x80\x94 decision-clicker\nCLAIM-ID: abc\n"
    kette.lock_file.write_bytes(eigener[:10])
    versuche = _voruebergehend_gesperrt(kette, monkeypatch, methode, 2)

    assert writer._discard_partial_claim(kette.lock_file, eigener) is True

    assert len(versuche) == 2
    assert not kette.lock_file.exists()


def test_dauerhaft_gesperrter_teil_claim_bleibt_gemeldet_stehen(kette: Settings, monkeypatch):
    eigener = b"LOCK \xe2\x80\x94 decision-clicker\nCLAIM-ID: abc\n"
    kette.lock_file.write_bytes(eigener[:10])
    versuche = _voruebergehend_gesperrt(kette, monkeypatch, "unlink", 10**6)

    assert writer._discard_partial_claim(kette.lock_file, eigener) is False

    assert len(versuche) == len(writer._RETRY_PAUSES) + 1
    assert kette.lock_file.read_bytes() == eigener[:10]


def test_wiederholung_loescht_keinen_zwischenzeitlich_fremden_claim(kette: Settings, monkeypatch):
    eigener = b"LOCK \xe2\x80\x94 decision-clicker\nCLAIM-ID: abc\n"
    fremd = b"LOCK -- replacement fixture\nAGENT: other-process\n"
    kette.lock_file.write_bytes(eigener[:10])
    _voruebergehend_gesperrt(kette, monkeypatch, "unlink", 1,
                             danach=lambda: kette.lock_file.write_bytes(fremd))

    assert writer._discard_partial_claim(kette.lock_file, eigener) is False

    assert kette.lock_file.read_bytes() == fremd
