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
from decision_clicker.server import Handler, serve


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


def sende(url: str, daten: dict[str, str], headers: dict[str, str] | None = None) -> tuple[int, str]:
    roh = urllib.parse.urlencode(daten).encode("utf-8")
    request = urllib.request.Request(url, data=roh, headers=headers or {})
    try:
        with urllib.request.urlopen(request, timeout=10) as antwort:
            return antwort.status, antwort.read().decode("utf-8")
    except urllib.error.HTTPError as fehler:
        return fehler.code, fehler.read().decode("utf-8")


def sende_json(url: str, daten: dict, *, include_guard: bool = True,
               headers: dict[str, str] | None = None) -> tuple[int, dict | str]:
    import json

    request_headers = {"Content-Type": "application/json"}
    if include_guard:
        request_headers["X-Decision-Clicker"] = "1"
    request_headers.update(headers or {})
    request = urllib.request.Request(
        url, data=json.dumps(daten).encode("utf-8"), headers=request_headers)
    try:
        with urllib.request.urlopen(request, timeout=10) as antwort:
            return antwort.status, json.loads(antwort.read().decode("utf-8"))
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


def test_antworten_setzen_browser_sicherheitsheader(server):
    url, _ = server
    with urllib.request.urlopen(f"{url}/", timeout=10) as antwort:
        assert antwort.headers["X-Content-Type-Options"] == "nosniff"
        assert antwort.headers["X-Frame-Options"] == "DENY"
        assert "frame-ancestors 'none'" in antwort.headers["Content-Security-Policy"]


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

    status, seite = sende(f"{url}/api/decide",
                          {"key": ziel["key"], "choice": "B", "note": "über HTTP geprüft"})
    assert status == 200  # direkte Bestaetigungsseite, keine Weiterleitung mehr
    assert "Entschieden" in seite
    assert ziel["id"] in seite

    text = pfad.read_text(encoding="utf-8-sig")
    assert "[B — über HTTP geprüft]" in text
    assert "ENTSCHIEDEN AM:" in text

    sicherungen = list(kette.backup_dir.glob(f"{pfad.stem}_decide_*{pfad.suffix}"))
    assert sicherungen, "Keine Sicherung angelegt"
    assert any(s.read_bytes() == vorher for s in sicherungen)

    assert ziel["id"] in kette.done_file.read_text(encoding="utf-8-sig")
    danach = chain.find(chain.build_index(kette), ziel["key"])
    assert danach["status_class"] == chain.STATUS_PENDING


def test_klick_zeigt_deutliche_bestaetigung_statt_stiller_weiterleitung(server):
    """Regression zum Fehlklick-Anlass vom 2026-08-07: der Nutzer muss SEHEN,
    was gerade entschieden wurde, statt kommentarlos zur naechsten Entscheidung
    weitergereicht zu werden."""
    url, kette = server
    ziel = chain.open_entries(chain.build_index(kette))[0]
    _status, seite = sende(f"{url}/api/decide", {"key": ziel["key"], "choice": "A", "note": ""})
    assert "✅" in seite
    assert f'Entschieden: {ziel["id"]}' in seite
    assert "Option A" in seite
    assert 'action="/api/undo/' in seite, "Rueckgaengig-Knopf muss sofort sichtbar sein"
    assert "Weiter zur nächsten Entscheidung" in seite


def test_decide_ueber_json_bekommt_weiter_json_ohne_bestaetigungsseite(server):
    """Automationen (JSON-Aufrufer) bekommen weiterhin nur die Rohdaten."""
    import json
    url, kette = server
    ziel = chain.open_entries(chain.build_index(kette))[0]
    payload = json.dumps({"key": ziel["key"], "choice": "A", "note": ""}).encode("utf-8")
    request = urllib.request.Request(
        f"{url}/api/decide", data=payload,
        headers={"Content-Type": "application/json", "X-Decision-Clicker": "1"})
    with urllib.request.urlopen(request, timeout=10) as antwort:
        daten = json.loads(antwort.read().decode("utf-8"))
    assert daten["ok"] is True
    assert daten["id"] == ziel["id"]


def test_http_decide_verifiziert_die_indexierte_id(server, monkeypatch):
    url, kette = server
    ziel = chain.open_entries(chain.build_index(kette))[0]
    original = writer.fill_decision
    gesehen: dict[str, str] = {}

    def pruefend(*args, **kwargs):
        gesehen["expected_id"] = kwargs.get("expected_id")
        return original(*args, **kwargs)

    monkeypatch.setattr(writer, "fill_decision", pruefend)
    status, _ = sende(f"{url}/api/decide", {"key": ziel["key"], "choice": "A"})
    assert status == 200
    assert gesehen["expected_id"] == ziel["id"]


def test_json_schreiben_ohne_api_guard_wird_abgewiesen(server):
    url, kette = server
    vorher = chain.counts(chain.build_index(kette))["gesamt"]
    status, text = sende_json(
        f"{url}/api/new", {"title": "Ohne Guard"}, include_guard=False)
    assert status == 403
    assert "X-Decision-Clicker" in text
    assert chain.counts(chain.build_index(kette))["gesamt"] == vorher


def test_cross_origin_post_wird_ohne_schreiben_abgewiesen(server):
    url, kette = server
    vorher = chain.counts(chain.build_index(kette))["gesamt"]
    status, _ = sende(
        f"{url}/api/new", {"title": "Fremde Website"},
        {"Origin": "https://evil.example", "Sec-Fetch-Site": "cross-site"},
    )
    assert status == 403
    assert chain.counts(chain.build_index(kette))["gesamt"] == vorher


def test_same_origin_formular_darf_schreiben(server):
    url, kette = server
    vorher = chain.counts(chain.build_index(kette))["gesamt"]
    status, _ = sende(
        f"{url}/api/new", {"title": "Gleicher Ursprung"},
        {"Origin": url, "Sec-Fetch-Site": "same-origin"},
    )
    assert status == 200
    assert chain.counts(chain.build_index(kette))["gesamt"] == vorher + 1


def test_falscher_host_wird_als_dns_rebinding_abgewiesen(server):
    url, kette = server
    vorher = chain.counts(chain.build_index(kette))["gesamt"]
    status, _ = sende(
        f"{url}/api/new", {"title": "Falscher Host"}, {"Host": "evil.example"})
    assert status == 403
    assert chain.counts(chain.build_index(kette))["gesamt"] == vorher


def test_server_verweigert_eine_nicht_lokale_bind_adresse(kette):
    from dataclasses import replace

    with pytest.raises(writer.WriteError, match="Loopback"):
        serve(replace(kette, host="0.0.0.0", port=0))


def test_parallele_http_anlage_vergibt_eindeutige_ids(server, monkeypatch):
    import time
    from concurrent.futures import ThreadPoolExecutor

    url, kette = server
    original = chain.next_id

    def verlangsamt(index):
        result = original(index)
        time.sleep(0.08)
        return result

    monkeypatch.setattr(chain, "next_id", verlangsamt)
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(
            lambda title: sende_json(f"{url}/api/new", {"title": title}),
            ("Parallel eins", "Parallel zwei"),
        ))
    assert [status for status, _ in results] == [200, 200]
    ids = [payload["id"] for _status, payload in results]
    assert len(set(ids)) == 2
    index = chain.build_index(kette)
    assert all(chain.find(index, entry_id) is not None for entry_id in ids)


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


def test_register_zeigt_fundstellen(server, postfach):
    url, kette = server
    from decision_clicker import intake
    intake.takeover(kette, on="2026-08-07")
    _status, seite = hole(f"{url}/register")
    assert "Fundstelle(n)" in seite
    assert "Desktop/TO-DECIDE-USER.txt" in seite, "Postfach-Fundstelle fehlt im Register"


def test_register_fuehrt_jede_id_nur_einmal(server, frisches_postfach):
    import re
    url, kette = server
    from decision_clicker import intake
    intake.takeover(kette, on="2026-08-07")
    _status, seite = hole(f"{url}/register?q=D-20990805")
    ids = re.findall(r"<tr><td><code>(D-\S+?)</code>", seite)
    assert len(ids) == len(set(ids)), f"ID doppelt im Register: {ids}"


# ---------------------------------------------------------------------------
# Verlauf & Rueckgaengig (OP-CLICKER-UNDO, 2026-08-07)
# ---------------------------------------------------------------------------
def test_verlauf_zeigt_die_bekannte_anzahl(server):
    """Die Testkette ist eine VOLLE Kopie der echten Kette — Verlauf ist also
    nicht zwingend leer. Verglichen wird gegen `chain.clicker_history()`."""
    url, kette = server
    status, seite = hole(f"{url}/verlauf")
    assert status == 200
    assert "Verlauf" in seite
    erwartet = chain.clicker_history(kette)
    assert f"{len(erwartet)} Einträge" in seite
    for eintrag in erwartet[:3]:
        assert eintrag["id"] in seite


def test_verlauf_zeigt_getroffene_entscheidung(server):
    url, kette = server
    ziel = chain.open_entries(chain.build_index(kette))[0]
    sende(f"{url}/api/decide", {"key": ziel["key"], "choice": "A", "note": "Verlaufstest"})
    status, seite = hole(f"{url}/verlauf")
    assert status == 200
    assert ziel["id"] in seite
    assert "aktiv" in seite
    assert f'action="/api/undo/{ziel["id"]}"' in seite


def test_api_history_ist_maschinenlesbar(server):
    """Juengste-zuerst: `treffer[0]` ist der gerade getroffene Eintrag — auch
    wenn dieselbe ID in der echten Kette schon einmal (mit anderem Ausgang)
    im Verlauf stand, siehe D-20260729-00[1-3] nach dem Sofort-Rollback."""
    import json
    url, kette = server
    ziel = chain.open_entries(chain.build_index(kette))[0]
    sende(f"{url}/api/decide", {"key": ziel["key"], "choice": "A", "note": ""})
    _status, roh = hole(f"{url}/api/history")
    daten = json.loads(roh)
    treffer = [e for e in daten["eintraege"] if e["id"] == ziel["id"]]
    assert treffer, "kein Verlaufseintrag fuer die frisch entschiedene ID"
    assert treffer[0]["status"] == "aktiv"
    assert treffer[0]["choice"] == "[A]"


def test_undo_setzt_die_entscheidung_ueber_http_zurueck(server):
    url, kette = server
    ziel = chain.open_entries(chain.build_index(kette))[0]
    pfad = Path(ziel["source_path"])
    vorher = pfad.read_bytes()

    sende(f"{url}/api/decide", {"key": ziel["key"], "choice": "B", "note": "wird rueckgaengig"})
    zwischenstand = chain.find(chain.build_index(kette), ziel["key"])
    assert zwischenstand["status_class"] == chain.STATUS_PENDING

    status, seite = sende(f"{url}/api/undo/{ziel['key']}", {})
    assert status == 200
    assert ziel["id"] in seite  # landet auf /klick?key=... mit derselben ID

    assert pfad.read_bytes() == vorher, "Kette muss byte-identisch zum Vorzustand sein"
    danach = chain.find(chain.build_index(kette), ziel["key"])
    assert danach["status_class"] == chain.STATUS_OPEN

    _status, verlauf_seite = hole(f"{url}/verlauf")
    assert "zurückgesetzt" in verlauf_seite


def test_zweiter_undo_ueber_http_prallt_ab(server):
    url, kette = server
    ziel = chain.open_entries(chain.build_index(kette))[0]
    sende(f"{url}/api/decide", {"key": ziel["key"], "choice": "A", "note": ""})
    sende(f"{url}/api/undo/{ziel['key']}", {})
    status, seite = sende(f"{url}/api/undo/{ziel['key']}", {})
    assert status == 409
    assert "nicht rückgängig machbar" in seite or "extern entschieden" in seite


def test_undo_auf_nie_entschiedene_id_prallt_ab(server):
    url, kette = server
    ziel = chain.open_entries(chain.build_index(kette))[0]
    status, _seite = sende(f"{url}/api/undo/{ziel['key']}", {})
    assert status == 409


def test_fremde_sperre_verhindert_auch_das_undo(server):
    url, kette = server
    ziel = chain.open_entries(chain.build_index(kette))[0]
    sende(f"{url}/api/decide", {"key": ziel["key"], "choice": "A", "note": ""})
    (kette.chain_dir / "LOCK.anderer-agent.txt").write_text("belegt", encoding="utf-8")
    status, seite = sende(f"{url}/api/undo/{ziel['key']}", {})
    assert status == 409
    assert "Fremde Sperre" in seite
