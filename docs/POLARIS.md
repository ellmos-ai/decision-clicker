# Polaris (Polarstern): ein Schreiber für die Kette

Nur wer den Polaris star hält, schreibt in die Kettendateien (`TO-DECIDE-USER.txt`,
`DECIDED-AND-DONE.md`, `_decision-archive/`, `_archive/`, `_polaris-journal/`) und legt
LOCK-Dateien an oder entfernt sie. Lesen bleibt immer möglich.

**Ehrliche Garantie:** Polaris schließt aus, dass zwei Writer *gleichzeitig gültig* schreiben
dürfen. Ein angehaltener Alt-Halter (VM-Suspend, blockierte Platte), der nach einer Übernahme noch
schreibt, lässt sich ohne Compare-and-Set im Dateisystem nicht verhindern. Er wird erkannt
(Fence-Stempel, Journal, Nachprüfung beim Commit-Marker) und der Schaden begrenzt.

## Auswahl

| Kette | Stern |
|---|---|
| im Ökosystem registriert (BACH-Lead konfiguriert oder Pfad `.../_CONTROL/_DECISIONS`) | **ServerStar** (HTTP, Geräte-Token). Ohne erreichbaren Lead: nur lesbar, HTTP 409 |
| nicht geteilt, Einzelbetrieb | **LocalStar** (SQLite im Nutzerordner) |

Konfiguration: `DECISION_CLICKER_STAR` = `auto` (Standard) | `server` | `local`. Einen `off`-Schalter
gibt es nicht. ServerStar: `DECISION_CLICKER_LEAD_URL` (oder `BACH_LEAD_URL`),
`DECISION_CLICKER_DEVICE_TOKEN` (oder `BACH_DEVICE_TOKEN`), optional `DECISION_CLICKER_WORKER`
(`agent@host`), `DECISION_CLICKER_STAR_RESOURCE` (Standard `decisions-chain`).
`DECISION_CLICKER_STATE_DIR` setzt den Nutzerordner (Backups, `star.db`); **Backups liegen nie im
Kettenordner.**

## Ablauf einer Transaktion

1. Erwerb mit dem Manifest-Hash des lokalen Standes (Sync-Schranke). Passt er nicht zum zuletzt
   gemeldeten Stand: `stale_resource_version`, nur lesbar.
2. Offenes Journal des Vorgängers abschließen (idempotent) oder verwerfen, wenn nichts geschrieben wurde.
3. Vor **jeder** Kettenschreibung prüft der Choke-Point (`writer._guard`) den Stern: lokale Frist ab
   Sendezeit und Monoton-Uhr, bei Zeitlücke online.
4. Mehrdatei-Transaktionen (`decide_entry`, `restore_decision`/`undo_decision`) schreiben vorher ein
   Journal `_polaris-journal/<tx>.json` (Plan) und danach den Fortschritt je Schritt. Bei Sternverlust:
   stoppen, **kein Auto-Revert**, Journal bleibt liegen.
5. Letzter Schritt: Manifest-Hash als Commit-Marker per renew melden, dann zurückgeben.

## Manifest

SHA-256 über sortierte relative Pfade (`/`), Größe und SHA-256 jeder Datei; fehlende Dateien und leere
Ordner gehen als `MISSING` ein. Pfade: siehe `star.CHAIN_PATHS`. Identisch zu BACH `lease_core.manifest_version`
für Dateien und fehlende Pfade.

## Fence-Stempel (kein Formatbruch)

```
POLARIS-STAR: decisions-chain#<fence> <host> tx=<8 hex>
```

Eine eigene Zeile, nie in einer Feldzeile: unter der Überschrift neuer Einträge, als eigener Absatz im
Registerblock (`DECIDED-AND-DONE.md`), am Ende des `ZURÜCKGESETZT AM:`-Vermerks (`— POLARIS-STAR: ...`).
Ein wiederhergestellter Originalblock (Undo) bleibt Byte für Byte unverändert. Beleg: der Stempel beginnt
weder mit einer ID noch mit einem Feldnamen, steht nie unmittelbar an einem Mehrzeilenfeld und ändert die
Parser-Ergebnisse nicht (`decisions_index.py`, `decisions_db.py` und die Clicker-Parser liefern identische
Einträge mit und ohne Stempelzeilen, Aktivvertrag gültig).

## Dienstbetrieb und CLI

* **Dienst** (`decision-clicker serve`, Writer-Kern als laufender Dienst): der star wird beim Start erworben,
  alle 40 s (`DECISION_CLICKER_STAR_RENEW`) erneuert und beim Beenden zurückgegeben. Der Server-Schreiber
  bleibt so auch ohne Klick „aktiv“, ein Standby wird abgelehnt (`held`). Verliert der Dienst den star,
  stoppen Schreibaktionen (HTTP 409), `status()["star"]` zeigt `held: false`, `lost_count` und den Fehler,
  und der Heartbeat erwirbt neu (inklusive Journal-Wiederaufnahme).
* **Einmalige CLI-Aufrufe und LocalStar** erwerben den star pro Transaktion.

## Rollen und `rebaseline`

`DECISION_CLICKER_STAR_ROLE` = `standby` (Standard) | `server`. Nur die Server-Rolle (die der Lead aus
Registrierung und Gerät kennt) darf bei abweichendem Manifest ohne offenen In-flight-Marker per `rebaseline`
erwerben: externe Änderungen (z. B. direkt angehängte Agenteneinträge) setzen den Stand neu, der Lead
protokolliert `rebaseline_external_change`. Ein offener In-flight-Marker blockiert auch den Server
(`inflight_open`, erst Recovery). Der Standby braucht immer den exakten Abgleich. LocalStar (nur ein Host)
rebaselinet automatisch.

## Nicht geschützt (außerhalb des Ressourcenumfangs)

`_tools/decisions.index.json` und `INDEX-REPORT.md` sind abgeleitete Artefakte; sie werden bei Bedarf
regeneriert. Konfliktkopien davon (OneDrive) sind harmlos. Ebenso `chain_tools.materialize` (Werkzeugkopien
in `_tools/`) und die Übernahme-Markierung im Desktop-Postfach (Datei außerhalb der Kette).

## Bekanntes Restfenster

Bricht der star genau zwischen dem Schreiben des Journals und der Meldung des In-flight-Markers ab, kann die
Server-Rolle per `rebaseline` weiterarbeiten (das Journal wird verworfen, weil nichts geschrieben war); ein
Standby bleibt bis dahin nur lesbar (`stale_resource_version`).
