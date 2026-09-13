# SPDX-License-Identifier: MIT
"""Synthetische Tests für den Ein-Dokument-Aktivvertrag."""
from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from decision_clicker.chain_tools import decisions_index as di

FIXTURES = Path(__file__).resolve().parent / "data" / "chain_tools" / "fixtures"
FIXTURES_COLLISION = Path(__file__).resolve().parent / "data" / "chain_tools" / "fixtures_collision"


@pytest.fixture()
def index() -> dict:
    return di.build_index(FIXTURES)


@pytest.fixture()
def by_key(index: dict) -> dict[str, dict]:
    return {entry["key"]: entry for entry in index["entries"]}


def test_erfasst_ein_aktivdokument_done_und_archiv(index: dict) -> None:
    assert {item["domain"] for item in index["files"]} == {"active", "done", "archive"}
    assert index["counts"]["total"] == 7
    assert index["counts"]["active_chain"] == 3
    assert index["counts"]["active_decision_ready"] == 3


def test_synthetische_fixture_erfuellt_aktivvertrag(index: dict) -> None:
    assert index["active_contract"] == {
        "canonical_file": "TO-DECIDE-USER.txt", "valid": True, "errors": []}
    assert index["counts"]["active_contract_errors"] == 0


def test_nichtkanonischer_kettenteil_wird_nicht_aktiv_und_verletzt_vertrag(tmp_path: Path) -> None:
    source = tmp_path / "kette"
    shutil.copytree(FIXTURES, source)
    konflikt = source / "TO-DECIDE-USER_2-WORKSTATION-LG.txt"
    konflikt.write_text(
        "D-20990101-001 — Konfliktkopie\n\nSTATUS: OFFEN\n"
        "FRAGE: Ignorieren?\nOPTIONEN:\n- A — Ja.\n- B — Nein.\n"
        "ENTSCHEIDUNG DES USERS: [HIER EINTRAGEN]\n",
        encoding="utf-8",
    )

    result = di.build_index(source)

    assert result["counts"]["active_chain"] == 3
    assert result["ignored_active_candidates"] == [konflikt.name]
    assert result["active_contract"]["valid"] is False
    assert "D-20990101-001" not in {entry["id"] for entry in result["entries"]}


def test_banner_block_ohne_d_id_wird_gemeldet_statt_verschluckt(tmp_path: Path) -> None:
    """Regression T-20260902-666804408: ein `====`-Banner ohne D-ID landete
    bisher stillschweigend im Body des vorherigen Eintrags -- weder gezaehlt
    noch als uebersprungener Kandidat gemeldet."""
    source = tmp_path / "kette"
    shutil.copytree(FIXTURES, source)
    path = source / di.ACTIVE_NAME
    banner = (
        "\n"
        "================================================================================\n"
        "ENTSCHEIDUNG: Banner-Block ohne D-ID\n"
        "================================================================================\n"
        "\n"
        "ENTSCHEIDUNG DES USERS: [HIER EINTRAGEN]\n"
        "\n"
        "---\n"
    )
    path.write_text(path.read_text(encoding="utf-8") + banner, encoding="utf-8")

    result = di.build_index(source)

    # Nicht als eigener aktiver Eintrag gezaehlt -- nur gemeldet.
    assert result["counts"]["active_chain"] == 3
    assert any("Banner-Block ohne D-ID" in item for item in result["ignored_active_candidates"])
    assert result["active_contract"]["valid"] is False
    assert any(
        "Banner-Block ohne D-ID" in error for error in result["active_contract"]["errors"])


def test_beantworteter_eintrag_im_aktivdokument_ist_vertragsfehler(tmp_path: Path) -> None:
    source = tmp_path / "kette"
    shutil.copytree(FIXTURES, source)
    path = source / di.ACTIVE_NAME
    path.write_text(
        path.read_text(encoding="utf-8").replace(
            "ENTSCHEIDUNG DES USERS: [HIER EINTRAGEN]",
            "ENTSCHEIDUNG DES USERS: [A]",
            1,
        ),
        encoding="utf-8",
    )

    result = di.build_index(source)

    assert result["active_contract"]["valid"] is False
    assert result["counts"]["active_decision_ready"] == 2
    assert any("D-20260101-002" in error for error in result["active_contract"]["errors"])


def test_unvollstaendige_frage_im_aktivdokument_ist_vertragsfehler(tmp_path: Path) -> None:
    source = tmp_path / "kette"
    shutil.copytree(FIXTURES, source)
    path = source / di.ACTIVE_NAME
    path.write_text(
        path.read_text(encoding="utf-8").replace(
            "OPTIONEN:\n- A — Erste Variante.\n- B — Zweite Variante.\n", "", 1),
        encoding="utf-8",
    )
    result = di.build_index(source)
    assert result["active_contract"]["valid"] is False
    assert result["counts"]["active_decision_ready"] == 2


def test_umrahmte_pipe_ueberschrift_wird_erkannt(by_key: dict) -> None:
    assert by_key["D-20260102-010"]["title"] == "Umrahmte Legacy-Überschrift"


def test_eintrag_ohne_markdown_ueberschrift_wird_erkannt(by_key: dict) -> None:
    assert by_key["D-20260102-009"]["title"] == "Eintrag ohne Markdown-Überschrift"


@pytest.mark.parametrize(("key", "expected"), [
    ("D-20260101-002", di.STATUS_OPEN),
    ("D-20260102-009", di.STATUS_OPEN),
    ("D-20260101-003@DECIDED-AND-DONE", di.STATUS_DONE),
    ("D-20260101-005@TO-DECIDE-USER_ARCHIV_2026-01-01", di.STATUS_ARCHIVED),
])
def test_statusklassen(by_key: dict, key: str, expected: str) -> None:
    assert by_key[key]["status_class"] == expected


@pytest.mark.parametrize("value", [
    "", "[HIER EINTRAGEN]", "[OFFEN]", "[A/B]", "[A/B/C]",
    "[HIER A ODER B EINTRAGEN]", "  [ hier eintragen ] ",
])
def test_platzhalter_gelten_als_unentschieden(value: str) -> None:
    assert di.is_placeholder(value)


@pytest.mark.parametrize("value", ["[B]", "[A — mit Begründung]", "C mit Prüferregel"])
def test_echte_entscheidungen_sind_keine_platzhalter(value: str) -> None:
    assert not di.is_placeholder(value)


def test_aktive_id_kollision_wird_gemeldet_und_macht_vertrag_ungueltig(tmp_path: Path) -> None:
    source = tmp_path / "kette"
    shutil.copytree(FIXTURES, source)
    path = source / di.ACTIVE_NAME
    text = path.read_text(encoding="utf-8")
    block = text[text.index("## D-20260101-002"):text.index("D-20260102-009")]
    path.write_text(text + "\n" + block, encoding="utf-8")

    result = di.build_index(source)

    assert result["counts"]["id_collisions"] == 1
    assert result["collisions"][0]["id"] == "D-20260101-002"
    assert result["active_contract"]["valid"] is False


def test_historischer_snapshot_ist_keine_aktive_kollision(index: dict, by_key: dict) -> None:
    assert index["counts"]["id_collisions"] == 0
    assert index["counts"]["ids_in_active_and_history"] == 1
    assert "D-20260101-002@TO-DECIDE-USER_ARCHIV_2026-01-01" in by_key


def test_id_aus_verschachteltem_manifest_bleibt_reserviert(tmp_path: Path) -> None:
    source = tmp_path / "kette"
    shutil.copytree(FIXTURES, source)
    nested = source / "_decision-archive" / "historischer-lauf"
    nested.mkdir()
    (nested / "MANIFEST.md").write_text(
        "Historische Provenienz: D-20991231-777\n", encoding="utf-8")

    result = di.build_index(source)

    assert "D-20991231-777" in result["reserved_ids"]
    assert result["counts"]["reserved_archive_ids"] >= 1


def test_alle_keys_eindeutig(index: dict) -> None:
    keys = [entry["key"] for entry in index["entries"]]
    assert len(keys) == len(set(keys))


def test_scope_default_ist_global_und_implizit(by_key: dict) -> None:
    entry = by_key["D-20260102-009"]
    assert entry["scope"] == "global"
    assert entry["scope_explicit"] is False


def test_explizites_scope_feld_wird_normalisiert(by_key: dict) -> None:
    entry = by_key["D-20260101-002"]
    assert entry["scope"] == "host:ASUS-GEI"
    assert entry["scope_explicit"] is True


@pytest.mark.parametrize(("raw", "expected"), [
    ("global", "global"),
    ("host: ASUS-GEI", "host:ASUS-GEI"),
    (r"projekt: .TOPICS\.AI", r"projekt:.TOPICS\.AI"),
])
def test_scope_normalisierung(raw: str, expected: str) -> None:
    assert di.normalise_scope(raw) == expected


def test_option_zeilen_ohne_listenkopf_werden_erkannt(by_key: dict) -> None:
    entry = by_key["D-20260102-009"]
    assert "Option A" in entry["options_excerpt"]
    assert entry["decision_ready"] is True


def test_zeilennummern_zeigen_auf_die_ueberschrift() -> None:
    path = FIXTURES / di.ACTIVE_NAME
    entries = di.parse_file(path, "active")
    lines = path.read_text(encoding="utf-8").splitlines()
    for entry in entries:
        assert entry.entry_id in lines[entry.source_line - 1]


def test_report_nennt_offene_vor_historisch_entschiedenen(index: dict) -> None:
    report = di.render_report(index)
    assert report.index("## Echt offen") < report.index("## Historisch entschieden")
    assert "**GÜLTIG**" in report


def test_lauf_ist_idempotent_und_schreibt_nur_ins_ausgabeverzeichnis(tmp_path: Path) -> None:
    source = tmp_path / "kette"
    shutil.copytree(FIXTURES, source)
    before = {p: p.read_bytes() for p in source.rglob("*") if p.is_file()}
    out = tmp_path / "out"

    assert di.main(["--root", str(source), "--out-dir", str(out)]) == 0
    first = (out / "decisions.index.json").read_text(encoding="utf-8")
    assert di.main(["--root", str(source), "--out-dir", str(out)]) == 0
    second = (out / "decisions.index.json").read_text(encoding="utf-8")

    assert {p: p.read_bytes() for p in source.rglob("*") if p.is_file()} == before
    assert (out / "INDEX-REPORT.md").is_file()
    strip = lambda text: [  # noqa: E731
        line for line in text.splitlines() if '"generated_at"' not in line]
    assert strip(first) == strip(second)


def test_ungueltiger_vertrag_liefert_exit_1(tmp_path: Path) -> None:
    source = tmp_path / "kette"
    shutil.copytree(FIXTURES, source)
    (source / "TO-DECIDE-USER_2.txt").write_text("Konflikt", encoding="utf-8")
    assert di.main(["--root", str(source), "--out-dir", str(tmp_path / "out")]) == 1


def test_json_ist_schema_konform(tmp_path: Path) -> None:
    out = tmp_path / "out"
    assert di.main(["--root", str(FIXTURES), "--out-dir", str(out)]) == 0
    data = json.loads((out / "decisions.index.json").read_text(encoding="utf-8"))
    assert data["schema"] == "decisions.index/1"
    required = {
        "key", "id", "date", "title", "question", "status_class",
        "decision_field_raw", "decision_ready", "source_file", "source_line",
    }
    assert data["active_contract"]["valid"] is True
    for entry in data["entries"]:
        assert required <= set(entry)
        assert entry["status_class"] in di.STATUS_CLASSES


def test_fehlender_wurzelordner_meldet_fehler(tmp_path: Path, capsys) -> None:
    assert di.main(["--root", str(tmp_path / "gibtsnicht")]) == 2
    assert "nicht gefunden" in capsys.readouterr().err


# --------------------------------------------------------------------------
# history_collisions — T-20260913-772954756
# --------------------------------------------------------------------------
def test_saubere_fixture_meldet_keine_historienkollision(index: dict) -> None:
    """Der Regelfall darf nicht anschlagen.

    Die Fixture enthält bewusst denselben Eintrag D-20260101-002 einmal aktiv
    und einmal als Archivschnitt MIT umformuliertem Titel — genau der legitime
    Umzug, den die Prüfung ausnehmen muss.
    """
    assert index["counts"]["history_id_collisions"] == 0
    assert index["history_collisions"] == []


def test_reale_doppelvergabe_wird_vollstaendig_gemeldet() -> None:
    """15 IDs, 16 Blöcke: D-20260906-002 trägt zusätzlich einen zurückgesetzten Klick."""
    index = di.build_index(FIXTURES_COLLISION)
    treffer = index["history_collisions"]
    assert index["counts"]["history_id_collisions"] == 15
    assert [item["id"] for item in treffer] == [
        f"D-20260906-{n:03d}" for n in range(1, 16)]
    # Der Dreifachfall erscheint als drei Fundorte unter zwei Inhalten.
    zwei = next(item for item in treffer if item["id"] == "D-20260906-002")
    assert len(zwei["occurrences"]) == 3
    assert zwei["variants"] == 2
    assert sum(len(item["occurrences"]) for item in treffer) == 31


def test_meldung_nennt_id_und_beide_fundorte() -> None:
    index = di.build_index(FIXTURES_COLLISION)
    eins = next(i for i in index["history_collisions"] if i["id"] == "D-20260906-001")
    titel = {occ["title"] for occ in eins["occurrences"]}
    assert len(eins["occurrences"]) == 2
    assert any("PR #8" in t for t in titel)
    assert any("Routinika" in t for t in titel)
    for occ in eins["occurrences"]:
        assert occ["source_file"] == "DECIDED-AND-DONE.md"
        assert occ["domain"] == "done"
        assert occ["line"] > 0


def test_gleicher_block_zweimal_ist_keine_kollision(tmp_path: Path) -> None:
    """Derselbe Titel in aktiver Kette und DONE bleibt der erlaubte Umzug."""
    root = tmp_path / "kette"
    shutil.copytree(FIXTURES, root)
    (root / "DECIDED-AND-DONE.md").write_text(
        "# DECIDED-AND-DONE\n\n"
        "## D-20260101-002 — Offenes Beispiel\n\n"
        "STATUS: ERLEDIGT\nQUELLE: Fixture.\n"
        "ENTSCHEIDUNG DES USERS: [A]\n\n---\n",
        encoding="utf-8")
    assert di.build_index(root)["history_collisions"] == []


def test_archivtreffer_allein_loest_nicht_aus(tmp_path: Path) -> None:
    """Ein Archivschnitt ist eine Kopie — er darf nie allein eine Kollision bilden."""
    root = tmp_path / "kette"
    shutil.copytree(FIXTURES, root)
    (root / "_decision-archive" / "ZWEITER-SCHNITT.md").write_text(
        "# Archivschnitt\n\n"
        "## D-20260101-003 — Voellig anderer Titel als im DONE-Register\n\n"
        "STATUS: ARCHIV\nQUELLE: Fixture.\n"
        "ENTSCHEIDUNG DES USERS: [A]\n\n---\n",
        encoding="utf-8")
    index = di.build_index(root)
    assert index["history_collisions"] == []


def test_historienkollision_aendert_exitcode_nicht(tmp_path: Path) -> None:
    """Nur melden, nicht reparieren: der Aktivvertrag bleibt gültig, Exit 0.

    Wichtig, weil der decision-clicker seinen Buchungsweg auf
    `active_contract.valid` gated — ein historischer Befund darf ihn nicht
    fail-closed sperren.
    """
    out = tmp_path / "out"
    assert di.main(["--root", str(FIXTURES_COLLISION), "--out-dir", str(out)]) == 0
    data = json.loads((out / "decisions.index.json").read_text(encoding="utf-8"))
    assert data["active_contract"]["valid"] is True
    assert data["counts"]["history_id_collisions"] == 15
    assert data["counts"]["id_collisions"] == 0
    report = (out / "INDEX-REPORT.md").read_text(encoding="utf-8")
    assert "D-20260906-014" in report


# --------------------------------------------------------------------------
# Parser-Artefakt: Fliesstext mit fuehrender D-ID — T-20260913-445082817
# --------------------------------------------------------------------------
@pytest.mark.parametrize("zeile", [
    # Reale Fundstellen aus TO-DECIDE-USER.txt (Stand 2026-09-13): das Ende
    # einer Klammer `(... D-...)`, das beim Zeilenumbruch in Spalte 0 landete.
    "D-20260913-001) bleiben drei Paare. Alle drei sind **nicht** durch Bauarbeit",
    "D-20260912-001) — und die gehört nicht nebenbei in einen Aufräumlauf.",
    # Weitere Satzzeichen, die keinen Trenner bilden.
    "D-20260101-002, und danach folgt normaler Fließtext.",
    "D-20260101-002. Ein Satz, der mit der ID beginnt.",
    "D-20260101-002; Aufzählung im Fließtext.",
])
def test_fliesstext_mit_fuehrender_id_ist_keine_ueberschrift(zeile: str) -> None:
    assert di.match_heading(zeile) is None


@pytest.mark.parametrize("zeile,erwartet_id,erwartet_titel", [
    ("## D-20260101-002 — Offenes Beispiel", "D-20260101-002", "Offenes Beispiel"),
    ("D-20260102-009 — Eintrag ohne Markdown-Überschrift", "D-20260102-009",
     "Eintrag ohne Markdown-Überschrift"),
    ("=== D-20260102-010 | Umrahmte Legacy-Überschrift ===", "D-20260102-010",
     "Umrahmte Legacy-Überschrift"),
    ("## D-20260101-004-ASUS-GEI — Host-Alias-ID", "D-20260101-004-ASUS-GEI",
     "Host-Alias-ID"),
    ("## D-20260101-002", "D-20260101-002", ""),
    ("D-20260101-002 -- Doppelter Bindestrich", "D-20260101-002",
     "Doppelter Bindestrich"),
])
def test_echte_ueberschriften_bleiben_erkannt(
        zeile: str, erwartet_id: str, erwartet_titel: str) -> None:
    assert di.match_heading(zeile) == (erwartet_id, erwartet_titel)


def test_geisterueberschrift_erzeugt_keine_id_kollision(tmp_path: Path) -> None:
    """Der eigentliche Schaden: eine bereits vergebene ID taucht doppelt auf.

    Ohne den Trenner-Lookahead entstand aus dem Fließtext ein zweiter Eintrag
    mit derselben ID — und damit eine gemeldete Kollision ohne echten Anlass.
    """
    root = tmp_path / "kette"
    shutil.copytree(FIXTURES, root)
    aktiv = root / "TO-DECIDE-USER.txt"
    aktiv.write_text(
        aktiv.read_text(encoding="utf-8")
        + "\n## D-20260101-007 — Eintrag mit Klammerverweis\n\n"
          "STATUS: OFFEN\nQUELLE: Fixture.\n"
          "FRAGE: Was passiert bei einem Zeilenumbruch in der Klammer (siehe\n"
          "D-20260101-007) mitten im Satz?\n"
          "OPTIONEN:\n- A — Nichts.\n- B — Ein Geistereintrag.\n"
          "EMPFEHLUNG: A.\nENTSCHEIDUNG DES USERS: [HIER EINTRAGEN]\n\n---\n",
        encoding="utf-8")
    index = di.build_index(root)
    assert index["counts"]["id_collisions"] == 0
    assert index["history_collisions"] == []
    treffer = [e for e in index["entries"] if e["id"] == "D-20260101-007"]
    assert len(treffer) == 1
    assert treffer[0]["title"] == "Eintrag mit Klammerverweis"


# --------------------------------------------------------------------------
# FRAGE mit Qualifier — T-20260913-686066300
# --------------------------------------------------------------------------
@pytest.mark.parametrize("kopf,erwartet", [
    ("FRAGE: Schlichte Form?", "Schlichte Form?"),
    ("FRAGE 1 (`OC-2026-09-13-B`): Wie wird zerlegt?", "Wie wird zerlegt?"),
    ("FRAGE (`A7-2026-09-13-A`): Wie weit darf Plan D?", "Wie weit darf Plan D?"),
    ("FRAGE M2: Repo-Rollen?", "Repo-Rollen?"),
])
def test_frage_erlaubt_qualifier_vor_dem_doppelpunkt(kopf: str, erwartet: str) -> None:
    """Dieselbe Toleranz, die `ENTSCHEIDUNG DES USERS ...:` seit jeher hat.

    Ohne sie galten zwei reale Vorlagen als unvollständig, obwohl ihre Frage
    dastand — sie trugen nur eine Kennung vor dem Doppelpunkt.
    """
    assert di.parse_fields([kopf])["frage"] == erwartet


def test_fragen_im_fliesstext_bleiben_kein_feld() -> None:
    """`\\b` hinter FRAGE: ein längeres Wort darf das Feld nicht auslösen."""
    assert "frage" not in di.parse_fields(["FRAGEN AUS DEM TICKET: drei Stück"])
    assert "frage" not in di.parse_fields(["FRAGESTELLUNG: nur Prosa"])


def test_vorlage_mit_qualifier_ist_entscheidungsreif(tmp_path: Path) -> None:
    """Form komplett + Frage mit Kennung => decision_ready, Aktivvertrag gültig."""
    root = tmp_path / "kette"
    shutil.copytree(FIXTURES, root)
    aktiv = root / "TO-DECIDE-USER.txt"
    aktiv.write_text(
        aktiv.read_text(encoding="utf-8")
        + "\n## D-20260101-008 — Eintrag mit Kennung in der Frage\n\n"
          "STATUS: OFFEN\nQUELLE: Fixture.\n"
          "FRAGE 1 (`KN-2026-01-01-A`): Wird die Kennung akzeptiert?\n"
          "OPTIONEN:\n  [A] Ja.\n  [B] Nein.\n"
          "EMPFEHLUNG: A.\nENTSCHEIDUNG DES USERS: [HIER EINTRAGEN]\n\n---\n",
        encoding="utf-8")
    index = di.build_index(root)
    treffer = next(e for e in index["entries"] if e["id"] == "D-20260101-008")
    assert treffer["decision_ready"] is True
    assert treffer["question"] == "Wird die Kennung akzeptiert?"
    assert index["active_contract"]["valid"] is True
