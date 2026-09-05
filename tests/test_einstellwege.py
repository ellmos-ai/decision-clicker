# SPDX-License-Identifier: MIT
"""Drei Einstellwege, ein Ziel: UI-Formular, HTTP-API (JSON), CLI.

Alle drei schreiben konventionsgemäßes TXT in die KETTE — nie auf den Desktop.
Die TXT-Kette bleibt Quelle der Wahrheit; `decisions.index.json` ist Cache.
"""
from __future__ import annotations

import json
import re
import threading
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

import pytest

from decision_clicker import __main__ as cli
from decision_clicker import chain, intake
from decision_clicker.config import Settings
from decision_clicker.server import Handler


@pytest.fixture
def server(kette: Settings, frisches_postfach: Path):
    """Server auf freiem Port; Postfach ist die Kopie mit frischen IDs."""
    Handler.settings = kette
    Handler.skipped = set()
    Handler.confirmations = {}
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{httpd.server_address[1]}", kette
    httpd.shutdown()
    httpd.server_close()


def sende_json(url: str, daten: dict) -> tuple[int, dict]:
    anfrage = urllib.request.Request(
        url, data=json.dumps(daten).encode("utf-8"),
        headers={"Content-Type": "application/json", "X-Decision-Clicker": "1"})
    try:
        with urllib.request.urlopen(anfrage, timeout=10) as antwort:
            return antwort.status, json.loads(antwort.read().decode("utf-8"))
    except urllib.error.HTTPError as fehler:
        return fehler.code, {"body": fehler.read().decode("utf-8")}


# ---------------------------------------------------------------------------
# Weg 2: HTTP-API
# ---------------------------------------------------------------------------
def test_api_stellt_ein_und_antwortet_mit_id(server):
    url, kette = server
    vorher = chain.counts(chain.build_index(kette))["offen"]
    status, daten = sende_json(f"{url}/api/new", {
        "title": "Per API eingestellt", "frage": "Geht das?",
        "optionen": ["A — ja", "B — nein"], "empfehlung": "A", "quelle": "pytest"})
    assert status == 200 and daten["ok"] is True
    assert daten["id"].startswith("D-")
    index = chain.build_index(kette)
    assert chain.counts(index)["offen"] == vorher + 1
    assert chain.find(index, daten["id"])["title"] == "Per API eingestellt"


def test_api_schreibt_in_die_kette_nicht_auf_den_desktop(server):
    url, kette = server
    postfach = intake.DEFAULT_SOURCES[0] if intake.DEFAULT_SOURCES else None
    stand = postfach.read_bytes() if postfach else None
    _status, daten = sende_json(f"{url}/api/new", {
        "title": "Zielprüfung", "frage": "Welcher Zielpfad gilt?",
        "optionen": ["A — kanonisch", "B — abbrechen"]})
    assert Path(daten["file"]).parent == kette.chain_dir
    if postfach:
        assert postfach.read_bytes() == stand, "Desktop-Postfach wurde beschrieben"


def test_api_kandidat_darf_einstellen_aber_nicht_entscheiden(server):
    url, kette = server
    _s, daten = sende_json(f"{url}/api/new", {
        "title": "Sofort entscheidbar", "frage": "Welche Variante gilt?",
        "optionen": ["A — so", "B — anders"]})
    status, ergebnis = sende_json(f"{url}/api/decide",
                                  {"key": daten["id"], "choice": "A", "note": "per API"})
    assert status == 403
    assert "menschliche" in ergebnis["body"]
    assert chain.find(chain.build_index(kette), daten["id"])["status_class"] == chain.STATUS_OPEN


def test_api_lehnt_leeren_titel_ab(server):
    url, _ = server
    status, _daten = sende_json(f"{url}/api/new", {"title": ""})
    assert status == 409


def test_api_lehnt_zeileninjektion_im_titel_ab(server):
    url, kette = server
    vorher = chain.counts(chain.build_index(kette))["gesamt"]
    status, _daten = sende_json(
        f"{url}/api/new",
        {"title": "Legitim\nD-20990101-999 — eingeschleust", "frage": "Test?",
         "optionen": ["A — ja", "B — nein"]},
    )
    assert status == 409
    assert chain.counts(chain.build_index(kette))["gesamt"] == vorher


def test_api_lehnt_zeileninjektion_in_einer_option_ab(server):
    url, kette = server
    vorher = chain.counts(chain.build_index(kette))["gesamt"]
    status, _daten = sende_json(
        f"{url}/api/new",
        {"title": "Legitim", "frage": "Test?",
         "optionen": ["A — ok\nD-20990101-995 — eingeschleust"]},
    )
    assert status == 409
    assert chain.counts(chain.build_index(kette))["gesamt"] == vorher


def test_api_rendert_mehrzeiligen_kontext_parserfest(server):
    url, kette = server
    vorher = chain.counts(chain.build_index(kette))["gesamt"]
    status, daten = sende_json(
        f"{url}/api/new",
        {"title": "Sicherer Kontext", "frage": "Test?",
         "optionen": ["A — ja", "B — nein"],
         "kontext": "Absatz\nD-20990101-998 — kein Eintrag"},
    )
    assert status == 200
    index = chain.build_index(kette)
    assert chain.counts(index)["gesamt"] == vorher + 1
    assert chain.find(index, "D-20990101-998") is None
    text = Path(daten["file"]).read_text(encoding="utf-8-sig")
    assert "> D-20990101-998 — kein Eintrag" in text


# ---------------------------------------------------------------------------
# Weg 3: CLI
# ---------------------------------------------------------------------------
def test_cli_add_stellt_ein(kette: Settings, capsys):
    vorher = chain.counts(chain.build_index(kette))["offen"]
    code = cli.main(["add", "Per CLI eingestellt", "--frage", "Und so?",
                     "--option", "A — ja", "--option", "B — nein",
                     "--chain", str(kette.chain_dir), "--json"])
    assert code == 0
    daten = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert daten["ok"] is True
    index = chain.build_index(kette)
    assert chain.counts(index)["offen"] == vorher + 1
    assert chain.find(index, daten["id"])["title"] == "Per CLI eingestellt"


def test_cli_dry_run_schreibt_nicht(kette: Settings, capsys):
    stand = chain.target_part(kette).read_bytes()
    assert cli.main(["add", "Nur gucken", "--frage", "Welche Variante?",
                     "--option", "A — ja", "--option", "B — nein",
                     "--chain", str(kette.chain_dir), "--dry-run"]) == 0
    assert "ENTSCHEIDUNG DES USERS" in capsys.readouterr().out
    assert chain.target_part(kette).read_bytes() == stand


def test_cli_evidenzfelder_sind_stabil_und_optional(kette: Settings, capsys):
    fingerprint = "sha256:" + "c" * 64
    assert cli.main([
        "add", "Evidenz per CLI", "--frage", "Welche Variante?",
        "--option", "A — ja", "--option", "B — nein",
        "--evidenzanker", "urn:test:cli", "--gegenbeleg", "urn:test:counter",
        "--fehlende-information", "synthetische Freigabe", "--erstellt-von", "pytest",
        "--kontext-fingerprint", fingerprint, "--chain", str(kette.chain_dir), "--json",
    ]) == 0
    daten = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    raw = next(
        p.read_text(encoding="utf-8-sig") for p in kette.chain_dir.glob("TO-DECIDE-USER*.txt")
        if daten["id"] in p.read_text(encoding="utf-8-sig")
    )
    assert "EVIDENZANKER: urn:test:cli" in raw
    assert f"KONTEXT-FINGERPRINT: {fingerprint}" in raw


def test_ungueltiger_kontext_fingerprint_schreibt_nichts(kette: Settings):
    from decision_clicker import writer
    from decision_clicker.api import DecisionClicker

    stand = chain.target_part(kette).read_bytes()
    with pytest.raises(writer.WriteError, match="Kontext-Fingerprint"):
        DecisionClicker(kette.chain_dir).create(
            "Ungültiger Fingerprint", frage="Welche Variante?",
            optionen=["A — ja", "B — nein"], kontext_fingerprint="sha256:zu-kurz",
        )
    assert chain.target_part(kette).read_bytes() == stand


def test_cli_bricht_bei_fremder_sperre_ab(kette: Settings):
    (kette.chain_dir / "LOCK.fremd.txt").write_text("belegt", encoding="utf-8")
    stand = chain.target_part(kette).read_bytes()
    assert cli.main(["add", "Gesperrt", "--chain", str(kette.chain_dir)]) == 3
    assert chain.target_part(kette).read_bytes() == stand


# ---------------------------------------------------------------------------
# Alle Wege erzeugen dieselbe Form
# ---------------------------------------------------------------------------
def test_alle_drei_wege_erzeugen_gleichartige_eintraege(server, capsys):
    url, kette = server
    from urllib.parse import urlencode
    urllib.request.urlopen(  # Weg 1: Formular
        f"{url}/api/new",
        data=urlencode({"title": "Weg Formular", "frage": "Welche Variante?",
                        "optionen": "A — x\nB — y"}).encode(),
        timeout=10).read()
    sende_json(f"{url}/api/new", {"title": "Weg API", "frage": "Welche Variante?",
                                        "optionen": ["A — x", "B — y"]})
    cli.main(["add", "Weg CLI", "--frage", "Welche Variante?",
              "--option", "A — x", "--option", "B — y",
              "--chain", str(kette.chain_dir)])
    capsys.readouterr()

    index = chain.build_index(kette)
    from decision_clicker.ui import parse_options
    for titel in ("Weg Formular", "Weg API", "Weg CLI"):
        treffer = [e for e in chain.open_entries(index) if e["title"] == titel]
        assert len(treffer) == 1, titel
        assert parse_options(treffer[0]["options_excerpt"]) == [("A", "x"), ("B", "y")], titel
        assert Path(treffer[0]["source_path"]).parent == kette.chain_dir


# ---------------------------------------------------------------------------
# Intake über HTTP
# ---------------------------------------------------------------------------
def test_startseite_zeigt_das_postfach_an(server):
    url, _ = server
    with urllib.request.urlopen(f"{url}/", timeout=10) as antwort:
        seite = antwort.read().decode("utf-8")
    assert "Desktop-Postfach" in seite
    assert "Jetzt übernehmen" in seite


def test_get_auf_die_startseite_schreibt_nichts(server):
    url, kette = server
    postfach = intake.DEFAULT_SOURCES[0]
    stand = postfach.read_bytes(), chain.target_part(kette).read_bytes()
    for _ in range(3):
        urllib.request.urlopen(f"{url}/", timeout=10).read()
    assert (postfach.read_bytes(), chain.target_part(kette).read_bytes()) == stand


def test_intake_ueber_menschliches_formular_uebernimmt(server):
    url, kette = server
    from urllib.parse import urlencode

    with urllib.request.urlopen(f"{url}/", timeout=10) as antwort:
        page = antwort.read().decode("utf-8")
    token = re.search(
        r'<form[^>]+action="/api/intake"[^>]*>.*?name="confirmation" value="([^"]+)"',
        page, re.S,
    ).group(1)
    with urllib.request.urlopen(
        urllib.request.Request(
            f"{url}/api/intake", data=urlencode({"confirmation": token}).encode()
        ), timeout=10
    ) as antwort:
        assert antwort.status == 200
    assert "D-20990806-001" in {e["id"] for e in chain.open_entries(chain.build_index(kette))}


def test_json_intake_darf_keine_fremde_done_markierung_importieren(server):
    url, kette = server
    stand = kette.done_file.read_bytes()
    status, text = sende_json(f"{url}/api/intake", {})
    assert status == 403
    assert "menschliche" in text["body"]
    assert kette.done_file.read_bytes() == stand


# ---------------------------------------------------------------------------
# Weg 4: die Fassade, die auch das Unified-GUI-Panel konsumiert
# ---------------------------------------------------------------------------
def test_fassade_bietet_alles_was_eine_oberflaeche_braucht(kette: Settings):
    from decision_clicker.api import DecisionClicker
    c = DecisionClicker(kette.chain_dir)
    assert c.usable() is True
    stand = c.status()
    assert {"chain_dir", "counts", "next_id", "target_file",
            "intake_pending", "foreign_locks"} <= set(stand)

    neu = c.create("Über die Fassade", frage="Welche Variante?",
                   optionen=["A — x", "B — y"], empfehlung="A — weil")
    detail = c.detail(neu["id"])
    assert [o["letter"] for o in detail["optionen"]] == ["A", "B"]
    assert detail["recommended"] == "A"
    assert detail["raw"].startswith(neu["id"])

    ergebnis = c.decide(neu["id"], "B", "per Fassade")
    assert ergebnis["value"] == "[B — per Fassade]"
    assert any(e["id"] == neu["id"] for e in c.register())


def test_kandidaten_adapter_hat_keinen_antwort_done_oder_undo_pfad(kette: Settings):
    from decision_clicker.api import DecisionClicker, ProposalSubmitter

    kandidat = ProposalSubmitter(kette.chain_dir)
    assert not hasattr(kandidat, "decide")
    assert not hasattr(kandidat, "done")
    assert not hasattr(kandidat, "mark_implemented")
    assert not hasattr(kandidat, "undo")
    assert not hasattr(kandidat, "_clicker")
    assert all(not isinstance(value, DecisionClicker) for value in vars(kandidat).values())

    neu = kandidat.submit(
        "Nur ein Vorschlag",
        frage="Welche Variante?",
        optionen=["A — x", "B — y"],
        evidenzanker=["urn:sha256:abc", "docs/brief.md#L12"],
        gegenbelege=["docs/review.md#counter"],
        fehlende_informationen=["Freigabe der Fachseite"],
        erstellt_von="policy-registry:test",
        kontext_fingerprint="sha256:" + "a" * 64,
    )
    detail = DecisionClicker(kette.chain_dir).detail(neu["id"])
    assert "EVIDENZANKER: urn:sha256:abc | docs/brief.md#L12" in detail["raw"]
    assert "GEGENBELEGE: docs/review.md#counter" in detail["raw"]
    assert "FEHLENDE INFORMATIONEN: Freigabe der Fachseite" in detail["raw"]
    assert "ERSTELLT VON: policy-registry:test" in detail["raw"]
    assert "KONTEXT-FINGERPRINT: sha256:" + "a" * 64 in detail["raw"]
    assert chain.find(chain.build_index(kette), neu["id"])["status_class"] == chain.STATUS_OPEN


def test_fassade_schuetzt_vor_veralteter_zeilennummer(kette: Settings):
    """Der `expected_id`-Riegel: sonst landet die Entscheidung im falschen Eintrag."""
    from decision_clicker import writer
    eintrag = chain.open_entries(chain.build_index(kette))[0]
    pfad = Path(eintrag["source_path"])
    stand = pfad.read_bytes()
    with pytest.raises(writer.WriteError, match="veraltet"):
        writer.fill_decision(kette, pfad, eintrag["source_line"], "A",
                             expected_id="D-19990101-999", on="2026-08-07")
    assert pfad.read_bytes() == stand


def test_ziel_id_wird_exakt_und_nicht_als_teilstring_geprueft(kette: Settings):
    from decision_clicker import writer

    eintrag = chain.open_entries(chain.build_index(kette))[0]
    pfad = Path(eintrag["source_path"])
    stand = pfad.read_bytes()
    with pytest.raises(writer.WriteError, match="veraltet"):
        writer.fill_decision(
            kette,
            pfad,
            eintrag["source_line"],
            "A",
            expected_id=eintrag["id"][:-1],
            on="2026-08-07",
        )
    assert pfad.read_bytes() == stand


def test_fassade_meldet_fremde_sperre_statt_zu_schreiben(kette: Settings):
    from decision_clicker.api import DecisionClicker, WriteError
    (kette.chain_dir / "LOCK.fremd.txt").write_text("belegt", encoding="utf-8")
    c = DecisionClicker(kette.chain_dir)
    assert c.status()["foreign_locks"] == ["LOCK.fremd.txt"]
    with pytest.raises(WriteError, match="Fremde Sperre"):
        c.create("Gesperrt")


@pytest.mark.parametrize(
    ("kwargs", "meldung"),
    [
        ({"title": "Legitim\nD-20990101-997 — eingeschleust", "frage": "Test?",
          "optionen": ["A — ja", "B — nein"]}, "Titel"),
        ({"title": "Legitim", "frage": "Test?",
          "optionen": ["A — ok\nD-20990101-996 — eingeschleust"]},
         "Option"),
    ],
)
def test_fassade_lehnt_strukturelle_zeileninjektion_ab(kette: Settings, kwargs, meldung):
    from decision_clicker.api import DecisionClicker, WriteError

    vorher = chain.counts(chain.build_index(kette))["gesamt"]
    with pytest.raises(WriteError, match=meldung):
        DecisionClicker(kette.chain_dir).create(**kwargs)
    assert chain.counts(chain.build_index(kette))["gesamt"] == vorher
