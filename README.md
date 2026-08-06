# Decision-Clicker

Lokales Klick-Werkzeug für die zentrale Entscheidungskette
`~/OneDrive/.TOPICS/_control-center/_DECISIONS`.

Agenten und Sessions **stellen Entscheidungen ein**, Lukas **klickt sich durch**,
jede Entscheidung wird **dokumentiert** und bleibt **langfristig auffindbar**.

---

## Starten

Doppelklick auf **`START.bat`** — der Browser öffnet sich von selbst auf
<http://127.0.0.1:8096>. Beenden mit `Strg+C` im schwarzen Fenster.

Der Server bindet ausschließlich an `127.0.0.1`; von außen ist nichts erreichbar.
Läuft schon eine Instanz, öffnet `START.bat` nur den Browser und startet keine zweite.

Ohne Batch-Datei:

```
set PYTHONIOENCODING=utf-8
set PYTHONPATH=src
python -m decision_clicker            # Server auf 8096
python -m decision_clicker --check    # nur nachsehen, nichts starten
```

## Die vier Ansichten

| Seite | Was sie tut |
|---|---|
| **Übersicht** (`/`) | Zähler je Statusklasse, Liste aller offenen Entscheidungen |
| **Durchklicken** (`/klick`) | Eine Entscheidung pro Ansicht: Titel, Kontext, Optionen als Knöpfe, Empfehlung hervorgehoben, Freitext-Anmerkung, „Später entscheiden" |
| **Einstellen** (`/neu`) | Formular für eine neue Entscheidung; die ID wird kollisionssicher vergeben |
| **Register** (`/register`) | Durchsuchbare Liste aller getroffenen Entscheidungen aus Kette, DECIDED-AND-DONE und Archiv |

Dazu `/api/health` (Kurzstatus als JSON) und `/api/index` (vollständiger Index).

---

## Was beim Klick genau passiert

1. **Sperrprüfung.** Liegt eine fremde `LOCK*.txt` im Entscheidungsordner, wird
   nicht geschrieben — der Klick wird mit Begründung abgewiesen.
2. **Sicherung.** Die Zieldatei wird vorher nach `_decision-archive/_bak/` kopiert.
3. **Ein Feld, eine Datumszeile.** In der TO-DECIDE-Datei wird ausschließlich die
   Zeile `ENTSCHEIDUNG DES USERS:` gefüllt und dahinter eine Leerzeile plus
   `ENTSCHIEDEN AM: …` ergänzt. Sonst ändert sich **nichts** — keine Formatierung,
   keine Zeilenenden, kein Encoding, keine fremden Zeilen.
4. **Beleg.** Ein Eintrag wird an `DECIDED-AND-DONE.md` angehängt.
5. **Index.** `decisions.index.json` und `INDEX-REPORT.md` werden neu erzeugt.

Ein bereits entschiedener Eintrag wird **nie** überschrieben (HTTP 409).

**Warum die Leerzeile vor dem Datum:** Der Kettenparser sammelt Feldwerte
mehrzeilig bis zur nächsten Leerzeile. Ohne sie würde das Datum in den
Entscheidungswert gezogen und im Index-Report als Teil der Entscheidung
erscheinen. Mit ihr bleibt beides sauber getrennt.

**Der Eintrag bleibt in der aktiven Kette stehen.** Nach der Kettenregel wandert
er erst nach *verifizierter Umsetzung* nach `DECIDED-AND-DONE.md` — und das
verifiziert kein Klick. Der Clicker erzeugt nur den Beleg, dass die Entscheidung
gefallen ist.

---

## Warum eigenständig und nicht im `ellmos-unified-gui`

Dort existiert seit dem 01.08. ein P10-Decisions-Panel. Es bleibt, wie es ist:

- Sein `DecisionsAdapter` sagt im eigenen Docstring zu, **nie zu schreiben** und
  keine zweite Quelle der Wahrheit zu halten. Ein Schreibpfad hätte genau diese
  Zusage gebrochen.
- Die Unified GUI ist FastAPI + Jinja2 und trägt Adapter für BACH, das bis
  ~12.08. judging-gesperrt ist. Der Clicker soll davon unabhängig laufen.
- Sie liegt in OneDrive mit eigenem `.git` — neue Arbeit gehört nach Plan D in
  einen lokalen Klon.

Der Clicker folgt stattdessen dem Muster des **lock-watchers**: stdlib
`http.server`, keine Abhängigkeit, `START.bat`, eigener Port. Arbeitsteilung:
**P10 zeigt, der Clicker schreibt.**

Den Kettenparser baut er ausdrücklich **nicht** nach — er lädt
`_DECISIONS/_tools/decisions_index.py` als Modul. Ein zweiter, leicht
abweichender Parser wäre der schlimmere Fehler.

---

## ID-Vergabe

`D-JJJJMMTT-NNN`, fortlaufend je Tag. Vor jeder Vergabe werden **alle** bekannten
IDs geprüft — aktive Kette, `DECIDED-AND-DONE.md` **und** Archiv. Eine archivierte
ID gilt als vergeben; genau daraus sind die fünf bekannten Kollisionen
`D-20260731-009` bis `-013` entstanden. Bestehende Kollisionen werden **gemeldet,
nicht umnummeriert** — IDs können in Tickets und Commits referenziert sein.

Neue Einträge gehen ans Ende des letzten Kettenteils. Ist der zu lang geworden,
weist der Clicker auf die Cut-and-Clue-Regel hin, **teilt aber nicht selbst** —
ein struktureller Eingriff in die Kette gehört zu einem Menschen.

---

## Tests

```
python -m pytest -q
```

40 Tests, davon der Kern in `tests/test_writer_roundtrip.py`: Er füllt
Entscheidungsfelder in **Kopien echter TO-DECIDE-Dateien** und weist per Diff
nach, dass genau eine Zeile ersetzt und genau zwei ergänzt wurden — alles andere
bleibt Byte für Byte gleich, inklusive CRLF in Teil 4 und LF in den Teilen 1–3.

`tests/test_server.py` fährt einen echten Server auf einem freien Port hoch (nie
8096) und geht den vollständigen Weg über HTTP.

**Kein Test fasst die echte Kette an.** Für den Beleg am Echtsystem gibt es
`tools/selftest_http.py`: legt eine Dummy-Entscheidung an, klickt sie durch,
prüft Datei, Sicherung und Beleg — und baut den Dummy anschließend Byte-genau
zurück; das Protokoll landet in `_decision-archive/`.

---

## Werkzeuge

| Datei | Zweck |
|---|---|
| `tools/seed_alltagsorganisation.py` | Stellt die Alltagsorganisations-Entscheidungen (E01–E07 plus Briefing vom 07.08.) ein. Idempotent, `--dry-run` zeigt nur. Beantwortet nichts. |
| `tools/selftest_http.py` | Selbsttest am Echtsystem, siehe oben. |

---

## OneDrive-Anbindung (Plan D)

Entwickelt, getestet und committet wird **hier** in `C:\_Local_DEV\repos\decision-clicker`.
In OneDrive liegt **kein `.git`** und keine zweite Arbeitskopie.

Damit Lukas das Werkzeug findet, gehört unter
`~/OneDrive/.TOPICS/_control-center/_decision-clicker/` ein reiner Zeiger
(`MANIFEST.md` mit Pfad und Startanleitung) — kein Spiegel des Codes. Der
Clicker liest die Kette ohnehin direkt aus OneDrive; eine gespiegelte Kopie
brächte nur einen zweiten, veraltenden Stand.

Nach Plan-D-Modulklassen ist das **Klasse B** (Agentenwerkzeug): Manifest und
Zeiger in OneDrive, Code lokal.

---

## Phase 2: Aufgaben-Manager (Konzept, noch nicht gebaut)

Die gleiche Oberfläche bekommt Reiter neben „Entscheidungen". Grundsatz für
alle: **schreibend nur dort, wo der Clicker Kanon ist — überall sonst lesend.**

### Reiter „Aufgaben"
Lukas' eigene Aufgaben. Kanonquelle ist noch zu klären: Rinnsal
(`~/.rinnsal/scanner_tasks.db`, außerhalb OneDrive) führt heute die
Hintergrund-Scanner-Aufgaben, TASKPLAN die Vorhaben mit Aufwand. Beides ist
Agenten-Werkzeug, nicht Lukas' persönliche Liste — die Wahl gehört als eigene
Entscheidung in die Kette, bevor gebaut wird.

### Reiter „Routinen" (read-only)
Sicht auf die Routinika-Datenbank, `.../SOFTWARE/CASH/RDY_Routinika_SOCIAL/`
(`database.py` als Einstieg; der konkrete DB-Pfad ist vor dem Bau zu ermitteln,
nicht zu raten). **Nur lesen:** Routinika ist laut E03-Empfehlung Kanon für
Routinen; ein zweiter Schreibweg wäre exakt die Doppelpflege, die abgeschafft
werden soll. Zweck hier: Fälligkeiten neben den Entscheidungen sichtbar machen.

### Reiter „BACH" (read-only, **frühestens ab 13.08.**)
BACH ist bis ~12.08. judging-gesperrt. Bis dahin enthält dieses Projekt
**keinerlei BACH-Zugriff** — kein Import, kein Pfad, keine Konfiguration.
Danach, und nur lesend: Termine (`calendar`), Kontakte (`contact`), Abos
(`abo`), Versicherungsfristen (`versicherung fristen`). Zugriff über die
BACH-Library `bach_api`, nie direkt auf `bach.db`.

### Was Phase 2 ausdrücklich nicht wird
Kein weiteres Dashboard. UpToday ist das Cockpit, BACH der Erinnerungskanal —
beide Rollen sind besetzt (siehe E05: FullAssistantHub einfrieren, weil seine
Rolle doppelt besetzt war). Der Clicker bleibt das Werkzeug für **Entscheidungen
und deren Nachbarschaft**.

---

## Grenzen

- Kein GitHub-Remote. Repo-Anlage und Push entscheidet der Nutzer.
- Fasst BACH nicht an (Judging-Hold).
- Beantwortet keine Entscheidung selbst — er stellt ein, zeigt und schreibt auf.
- Formatiert TO-DECIDE-Dateien nie um und löscht nichts.
