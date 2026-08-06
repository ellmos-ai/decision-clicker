# SPDX-License-Identifier: MIT
"""HTTP-Selbsttest gegen die ECHTE Kette — mit einer eigens angelegten Dummy-Entscheidung.

Belegt den vollstaendigen Weg: Server startet, Startseite zaehlt, Dummy wird
eingestellt, durchgeklickt, in die Kette geschrieben, Sicherung liegt vor.
Danach wird der Dummy restlos zurueckgebaut und ins Archiv protokolliert —
die Kette steht am Ende Byte fuer Byte wie vorher.

Es wird NIE eine echte offene Entscheidung beantwortet.

Aufruf: PYTHONIOENCODING=utf-8 python tools/selftest_http.py
"""
from __future__ import annotations

import sys
import threading
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime
from http.server import ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from decision_clicker import chain, writer  # noqa: E402
from decision_clicker.config import load  # noqa: E402
from decision_clicker.server import Handler  # noqa: E402

DUMMY_TITEL = "SELBSTTEST decision-clicker — bitte ignorieren, wird zurückgebaut"


def hole(url: str) -> tuple[int, str]:
    try:
        with urllib.request.urlopen(url, timeout=15) as antwort:
            return antwort.status, antwort.read().decode("utf-8")
    except urllib.error.HTTPError as fehler:
        return fehler.code, fehler.read().decode("utf-8")


def sende(url: str, daten: dict[str, str]) -> tuple[int, str]:
    roh = urllib.parse.urlencode(daten).encode("utf-8")
    try:
        with urllib.request.urlopen(url, data=roh, timeout=15) as antwort:
            return antwort.status, antwort.read().decode("utf-8")
    except urllib.error.HTTPError as fehler:
        return fehler.code, fehler.read().decode("utf-8")


def schritt(nummer: int, text: str) -> None:
    print(f"\n[{nummer}] {text}")


def main() -> int:
    settings = load()
    ziel = chain.target_part(settings)
    done = settings.done_file
    stand_ziel, stand_done = ziel.read_bytes(), done.read_bytes()
    url = f"http://{settings.host}:{settings.port}"

    Handler.settings = settings
    Handler.skipped = set()
    httpd = ThreadingHTTPServer((settings.host, settings.port), Handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    print(f"Server laeuft auf {url} · Kette: {settings.chain_dir}")

    fehler: list[str] = []

    def pruefe(bedingung: bool, text: str) -> None:
        print(f"    {'OK  ' if bedingung else 'FEHL'} {text}")
        if not bedingung:
            fehler.append(text)

    try:
        schritt(1, "GET / — Startseite")
        status, seite = hole(f"{url}/")
        offen_vorher = chain.counts(chain.build_index(settings))["offen"]
        pruefe(status == 200, f"HTTP {status}")
        pruefe(f'<span class="n">{offen_vorher}</span>' in seite,
               f"Zaehler zeigt {offen_vorher} offene Entscheidungen")
        pruefe("Durchklicken" in seite, "Navigation vorhanden")

        schritt(2, "GET /klick, /neu, /register, /api/health")
        for pfad in ("/klick", "/neu", "/register", "/api/health"):
            code, _ = hole(f"{url}{pfad}")
            pruefe(code == 200, f"{pfad} -> HTTP {code}")

        schritt(3, "POST /api/new — Dummy-Entscheidung einstellen")
        status, _ = sende(f"{url}/api/new", {
            "title": DUMMY_TITEL,
            "frage": "Schreibt der Clicker korrekt in die Kette?",
            "optionen": "A — ja, Weg belegt\nB — nein",
            "empfehlung": "A — dieser Lauf beantwortet es",
            "kontext": "Technischer Selbsttest vom "
                       f"{datetime.now():%Y-%m-%d %H:%M}. Wird nach dem Lauf zurückgebaut.",
            "quelle": "tools/selftest_http.py", "scope": "global"})
        pruefe(status == 200, f"HTTP {status}")
        index = chain.build_index(settings)
        treffer = [e for e in chain.open_entries(index) if e["title"] == DUMMY_TITEL]
        pruefe(len(treffer) == 1, f"genau ein Dummy in der Kette (gefunden: {len(treffer)})")
        if not treffer:
            return 1
        dummy = treffer[0]
        print(f"    Dummy: {dummy['key']} in {dummy['source_file']}, Zeile {dummy['source_line']}")
        pruefe(chain.counts(index)["offen"] == offen_vorher + 1, "Zaehler um 1 gestiegen")

        schritt(4, f"GET /klick?key={dummy['key']} — Durchklick-Ansicht")
        status, seite = hole(f"{url}/klick?key={dummy['key']}")
        pruefe(status == 200, f"HTTP {status}")
        pruefe('value="A"' in seite and 'value="B"' in seite, "beide Optionen als Knopf")
        pruefe("empfohlen" in seite, "Empfehlung markiert")
        pruefe("Schreibt der Clicker korrekt" in seite, "Kontext sichtbar")

        schritt(5, "POST /api/decide — Entscheidung eintragen")
        status, _ = sende(f"{url}/api/decide",
                          {"key": dummy["key"], "choice": "A", "note": "Selbsttest bestätigt"})
        pruefe(status == 200, f"HTTP {status} (303 auf /klick, urllib folgt)")

        schritt(6, "Kette pruefen")
        text = ziel.read_text(encoding="utf-8-sig")
        pruefe("ENTSCHEIDUNG DES USERS: [A — Selbsttest bestätigt]" in text,
               "Entscheidungsfeld gefuellt")
        pruefe("ENTSCHIEDEN AM:" in text.split(dummy["id"])[-1], "Datumszeile ergaenzt")
        sicherungen = sorted(settings.backup_dir.glob(f"{ziel.stem}_decide_*{ziel.suffix}"))
        pruefe(bool(sicherungen), f"Sicherung angelegt ({len(sicherungen)} Stueck)")
        if sicherungen:
            print(f"    juengste Sicherung: {sicherungen[-1]}")
        pruefe(dummy["id"] in done.read_text(encoding="utf-8-sig"), "Beleg in DECIDED-AND-DONE.md")
        neu = chain.find(chain.build_index(settings), dummy["key"])
        pruefe(neu["status_class"] == chain.STATUS_PENDING, "gilt jetzt als entschieden")

        schritt(7, "Zweiter Klick auf dieselbe ID prallt ab")
        status, seite = sende(f"{url}/api/decide", {"key": dummy["key"], "choice": "B", "note": ""})
        pruefe(status == 409 and "bereits entschieden" in seite,
               f"HTTP {status} — kein Ueberschreiben")

        schritt(8, "Rueckbau des Dummys")
        protokoll = settings.archive_dir / f"SELFTEST_decision-clicker_{datetime.now():%Y-%m-%d}.txt"
        # Auf BYTE-Ebene abschneiden: `read_text` uebersetzt CRLF zu LF, damit
        # waere der Versatz falsch und der Block leer (Fehler vom 2026-08-07).
        block = ziel.read_bytes()[len(stand_ziel):].decode("utf-8")
        protokoll.write_text(
            "Protokoll des decision-clicker-Selbsttests — KEINE echte Entscheidung.\n"
            f"Angelegt und zurueckgebaut am {datetime.now():%Y-%m-%d %H:%M}.\n"
            f"Dummy-ID: {dummy['id']}\n\n" + block, encoding="utf-8")
        writer.backup(ziel, settings, tag="selftest-rueckbau")
        ziel.write_bytes(stand_ziel)
        done.write_bytes(stand_done)
        chain.refresh_artifacts(settings)
        pruefe(ziel.read_bytes() == stand_ziel, "Kettenteil Byte-identisch wiederhergestellt")
        pruefe(done.read_bytes() == stand_done, "DECIDED-AND-DONE.md Byte-identisch")
        pruefe(chain.counts(chain.build_index(settings))["offen"] == offen_vorher,
               f"wieder {offen_vorher} offene Entscheidungen")
        print(f"    Protokoll: {protokoll}")
    finally:
        httpd.shutdown()
        httpd.server_close()

    print("\n" + "=" * 60)
    if fehler:
        print(f"SELBSTTEST FEHLGESCHLAGEN — {len(fehler)} Punkt(e):")
        for text in fehler:
            print(f"  - {text}")
        return 1
    print("SELBSTTEST VOLLSTAENDIG BESTANDEN")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
