# SPDX-License-Identifier: MIT
"""HTTP-Ebene: echte Anfragen gegen einen echten Server auf einer Kopie."""
from __future__ import annotations

import threading
import urllib.error
import urllib.parse
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

import pytest

from decision_clicker import chain, writer
from decision_clicker.config import Settings
from decision_clicker.server import Handler


@pytest.fixture
def server(kette: Settings):
    """Server auf freiem Port — belegt nie 8096, damit Tests nichts stoeren."""
    Handler.settings = kette
    Handler.skipped = set()
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{httpd.server_address[1]}", kette
    httpd.shutdown()
    httpd.server_close()


def hole(url: str) -> tuple[int, str]:
    try:
        with urllib.request.urlopen(url, timeout=10) as antwort:
            return antwort.status, antwort.read().decode("utf-8")
    except urllib.error.HTTPError as fehler:
        return fehler.code, fehler.read().decode("utf-8")


def sende(url: str, daten: dict[str, str]) -> tuple[int, str]:
    roh = urllib.parse.urlencode(daten).encode("utf-8")
    try:
        with urllib.request.urlopen(url, data=roh, timeout=10) as antwort:
            return antwort.status, antwort.read().decode("utf-8")
    except urllib.error.HTTPError as fehler:
        return fehler.code, fehler.read().decode("utf-8")


# ---------------------------------------------------------------------------
def test_startseite_zeigt_offene_entscheidungen(server):
    url, kette = server
    status, seite = hole(f"{url}/")
    assert status == 200
    assert "Übersicht" in seite
    offen = chain.counts(chain.build_index(kette))["offen"]
    assert f'<span class="n">{offen}</span>' in seite


def test_alle_seiten_antworten(server):
    url, _ = server
    for pfad in ("/", "/klick", "/neu", "/register", "/api/health", "/api/index"):
        status, _text = hole(f"{url}{pfad}")
        assert status == 200, f"{pfad} -> {status}"


def test_unbekannte_seite_gibt_404(server):
    url, _ = server
    assert hole(f"{url}/gibtsnicht")[0] == 404


def test_klick_zeigt_genau_eine_entscheidung_mit_kontext(server):
    url, kette = server
    naechste = chain.open_entries(chain.build_index(kette))[0]
    status, seite = hole(f"{url}/klick")
    assert status == 200
    assert naechste["key"] in seite
    assert "Kontext" in seite
    assert 'name="note"' in seite


def test_durchklicken_schreibt_in_die_kette(server):
    """Der vollstaendige Weg: POST -> Feld gefuellt, Sicherung da, Beleg da."""
    url, kette = server
    ziel = chain.open_entries(chain.build_index(kette))[0]
    pfad = Path(ziel["source_path"])
    vorher = pfad.read_bytes()

    status, _ = sende(f"{url}/api/decide",
                      {"key": ziel["key"], "choice": "B", "note": "über HTTP geprüft"})
    assert status == 200  # urllib folgt dem 303 auf /klick

    text = pfad.read_text(encoding="utf-8-sig")
    assert "[B — über HTTP geprüft]" in text
    assert "ENTSCHIEDEN AM:" in text

    sicherungen = list(kette.backup_dir.glob(f"{pfad.stem}_decide_*{pfad.suffix}"))
    assert sicherungen, "Keine Sicherung angelegt"
    assert any(s.read_bytes() == vorher for s in sicherungen)

    assert ziel["id"] in kette.done_file.read_text(encoding="utf-8-sig")
    danach = chain.find(chain.build_index(kette), ziel["key"])
    assert danach["status_class"] == chain.STATUS_PENDING


def test_zweiter_klick_auf_dieselbe_id_prallt_ab(server):
    url, kette = server
    ziel = chain.open_entries(chain.build_index(kette))[0]
    sende(f"{url}/api/decide", {"key": ziel["key"], "choice": "A", "note": ""})
    pfad = Path(ziel["source_path"])
    stand = pfad.read_bytes()
    status, seite = sende(f"{url}/api/decide", {"key": ziel["key"], "choice": "B", "note": ""})
    assert status == 409
    assert "bereits entschieden" in seite
    assert pfad.read_bytes() == stand


def test_spaeter_ueberspringt_und_zeigt_die_naechste(server):
    url, kette = server
    offen = chain.open_entries(chain.build_index(kette))
    if len(offen) < 2:
        pytest.skip("Braucht mindestens zwei offene Entscheidungen")
    _status, seite = hole(f"{url}/klick?skip={offen[0]['key']}")
    assert offen[1]["key"] in seite


def test_fremde_sperre_verhindert_das_schreiben(server):
    url, kette = server
    ziel = chain.open_entries(chain.build_index(kette))[0]
    pfad = Path(ziel["source_path"])
    (kette.chain_dir / "LOCK.anderer-agent.txt").write_text("belegt", encoding="utf-8")
    stand = pfad.read_bytes()
    status, seite = sende(f"{url}/api/decide", {"key": ziel["key"], "choice": "A", "note": ""})
    assert status == 409
    assert "Fremde Sperre" in seite
    assert pfad.read_bytes() == stand


def test_einstellen_ueber_das_formular(server):
    url, kette = server
    vorher = chain.counts(chain.build_index(kette))["offen"]
    status, _ = sende(f"{url}/api/new", {
        "title": "Über HTTP eingestellt", "frage": "Klappt das?",
        "optionen": "A — ja\nB — nein", "empfehlung": "A", "kontext": "Prüftext",
        "quelle": "tests/test_server.py", "scope": ""})
    assert status == 200
    index = chain.build_index(kette)
    assert chain.counts(index)["offen"] == vorher + 1
    treffer = [e for e in chain.open_entries(index) if e["title"] == "Über HTTP eingestellt"]
    assert len(treffer) == 1


def test_einstellen_ohne_titel_wird_abgelehnt(server):
    url, kette = server
    vorher = chain.counts(chain.build_index(kette))["offen"]
    status, _ = sende(f"{url}/api/new", {"title": "   "})
    assert status == 409
    assert chain.counts(chain.build_index(kette))["offen"] == vorher


def test_register_findet_ueber_die_suche(server):
    url, kette = server
    eintrag = chain.decided_entries(chain.build_index(kette))[0]
    _status, seite = hole(f"{url}/register?q={urllib.parse.quote(eintrag['id'])}")
    assert eintrag["id"] in seite


def test_gesundheitsauskunft_ist_maschinenlesbar(server):
    import json
    url, _ = server
    _status, roh = hole(f"{url}/api/health")
    daten = json.loads(roh)
    assert daten["ok"] is True
    assert "offen" in daten["counts"]


# ---------------------------------------------------------------------------
# Regressionen aus dem Livecheck vom 2026-08-07
# ---------------------------------------------------------------------------
def test_lange_optionslisten_werden_vollstaendig_angeboten(server):
    """Der Index kuerzt auf 400 Zeichen — die Knoepfe duerfen das nicht erben."""
    url, kette = server
    lang = "x" * 260
    sende(f"{url}/api/new", {
        "title": "Sehr ausfuehrliche Optionen",
        "optionen": f"A — {lang}\nB — {lang}\nC — kurz und wichtig"})
    index = chain.build_index(kette)
    eintrag = [e for e in chain.open_entries(index)
               if e["title"] == "Sehr ausfuehrliche Optionen"][0]
    assert "…" in eintrag["options_excerpt"], "Auszug muesste gekuerzt sein"

    _status, seite = hole(f"{url}/klick?key={eintrag['key']}")
    for buchstabe in ("A", "B", "C"):
        assert f'name="choice" value="{buchstabe}"' in seite, f"Option {buchstabe} fehlt"
    assert "kurz und wichtig" in seite


def test_register_zeigt_fundstellen(server):
    url, kette = server
    from decision_clicker import intake
    intake.takeover(kette, on="2026-08-07")
    _status, seite = hole(f"{url}/register")
    assert "Fundstelle(n)" in seite
    assert "Desktop/TO-DECIDE-USER.txt" in seite, "Postfach-Fundstelle fehlt im Register"


def test_register_fuehrt_jede_id_nur_einmal(server):
    import re
    url, kette = server
    from decision_clicker import intake
    intake.takeover(kette, on="2026-08-07")
    _status, seite = hole(f"{url}/register?q=D-20990805")
    ids = re.findall(r"<tr><td><code>(D-\S+?)</code>", seite)
    assert len(ids) == len(set(ids)), f"ID doppelt im Register: {ids}"
