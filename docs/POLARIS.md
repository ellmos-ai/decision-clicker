# Polaris (Polarstern): ein Schreiber für die Kette

Nur wer den Polaris star hält, schreibt in die Kettendateien (`TO-DECIDE-USER.txt`,
`DECIDED-AND-DONE.md`, `_decision-archive/`, `_archive/`) und in das Transaktionsjournal
(`_polaris-journal/`, liegt bewusst außerhalb des Manifests, siehe unten). Lesen bleibt immer möglich.

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
Kettenordner:** ein `backup_root` (`DECISION_CLICKER_BACKUP_ROOT`) im Kettenordner wird beim Laden der
Konfiguration abgelehnt.

**Transport:** `https://` ist Pflicht. `http://` gilt nur für **IP-Literale**: Loopback (`127.0.0.0/8`, `::1`) und
Tailscale (`100.64.0.0/10`; WireGuard verschlüsselt den Weg). Hostnamen (auch `localhost`, `*.ts.net`) nur mit
`https://`, weil eine Namensauflösung nicht an die Zieladresse gebunden ist und das Bearer-Token sonst im
Klartext woandershin ginge. Alles andere wird fail-closed abgelehnt (Kette nur lesbar). Das Geräte-Token
erscheint nie in Logs, Fehlertexten oder Reprs.

**Pfadwurzel:** `chain_dir` wird beim Laden der Konfiguration **einmal** aufgelöst (`realpath`) und danach fest
verwendet. Übergeordnete Komponenten dürfen Links sein (auf dem Mac ist `~/OneDrive` ein Link nach
`~/Library/CloudStorage/...`; eine Sperre bräche den Betrieb dort). **Innerhalb** der Kette sind Symlinks und
Junctions verboten: der Choke-Point lehnt jeden Pfad ab, dessen Komponenten unterhalb von `chain_dir` ein Link
sind (`WriteError`, auch mit gültigem Stern).

## Ablauf einer Transaktion

1. Erwerb mit dem Manifest-Hash des lokalen Standes (Sync-Schranke). Passt er nicht zum zuletzt
   gemeldeten Stand: `stale_resource_version`, nur lesbar.
2. Offenes Journal des Vorgängers abschließen oder warten (Abschnitt Recovery).
3. Vor **jeder** Kettenschreibung prüft der Choke-Point (`writer._guard`) den Stern: lokale Frist ab
   Sendezeit und Monoton-Uhr, bei Zeitlücke online. Kettendateien werden atomar geschrieben (tmp im selben
   Ordner, `fsync`, `os.replace`; `*.polaris-tmp` zählt nicht zum Manifest). `os.replace` und das Löschen der
   tmp-Datei werden bei `PermissionError`/`OSError` (OneDrive-Sharing-Verletzung) bis zu 5-mal mit wachsender
   Pause wiederholt (zusammen unter 3 s), danach fail-closed: das Ziel bleibt unverändert, ein Reststück bleibt
   liegen und wird beim nächsten Erwerb entfernt, aber nur eigene tmp-Dateien (Host-Kennung im Namen)
   abgeschlossener oder verworfener Transaktionen.
   Pfade im Kettenumfang mit Symlink oder Junction in irgendeiner Komponente lehnt der Choke-Point ab
   (`WriteError`), auch mit gültigem Stern.
4. Mehrdatei-Transaktionen (`decide_entry`, `restore_decision`/`undo_decision`): **Journal → In-flight-Marker →
   Schritte → Commit-Marker → Journal löschen.** Das Journal (`_polaris-journal/<tx>.json`, atomar, mit
   Prüfsumme) trägt Plan, die Datei-Hashes vor der Transaktion, nach jedem Schritt und vorab den Hash des
   nächsten Schreibens (`pending`). Bei Sternverlust: stoppen, **kein Auto-Revert**, Journal bleibt liegen.
5. Der Commit-Marker (renew mit dem Manifest-Hash, löscht den In-flight-Marker) kommt **vor** dem Löschen des
   Journals und ist Pflicht: scheitert er oder liegt ein fremdes Journal offen (`journal_open`), bleibt das
   eigene Journal liegen und die Transaktion gilt als nicht abgeschlossen (decide, restore, undo, Recovery).
   Beim bloßen Verlassen meldet eine Transaktion bei fremdem Journal keinen Manifest-Hash.
6. Fehlerpfade löschen das Journal nur mit Beweis: die Kette muss dem Zustand „vorher“ oder dem nach dem
   Rollback vermerkten Zustand (`aborted`) entsprechen, sonst bleibt es für die Recovery liegen.

## Recovery: nur mit Beweis, sonst warten

| Lage | Verhalten |
|---|---|
| Lead meldet In-flight, Journal lokal nicht da | `journal_not_synced`, nur lesbar, später erneut |
| Journal korrupt, abgeschnitten, Prüfsumme falsch | `journal_corrupt`, nur lesbar, kein Raten |
| Journal da, Kette passt weder zu „vorher“ noch zum Zwischenstand nach dem letzten Vermerk (verzögerte Kopie, Fremdänderung) | `journal_unmatched`, warten, **nie verwerfen** |
| Kette == Zwischenstand, In-flight über dieses Journal erworben | Roll-forward, dann Commit-Marker, dann Journal löschen |
| Kette == „vorher“ (nichts geschrieben) | Journal verwerfen |
| Journal ohne In-flight-Marker (Commit gelungen, Löschen nicht): Kette == Ziel | Journal löschen |
| Journal ohne In-flight-Marker, unvollständig | `journal_unmatched`, warten |

Die Recovery journalisiert selbst: beim Roll-forward ist das Journal das der Transaktion, jeder Schritt vermerkt
vorab `pending` und danach den Fortschritt; ein Abbruch mitten im Roll-forward bleibt so beweisbar und eine
zweite Recovery schließt ab. Beim Laden werden Typen und Schrittfolge geprüft (`journal_corrupt` bei jeder
Abweichung).

Ein Schreiben, dessen Fortschrittsvermerk fehlt (Abbruch zwischen Schreiben und Vermerk), wird über den
vorab vermerkten Hash (`pending`) bewiesen. Restrisiko: eine zusätzliche, nicht journalisierte Schreibung
(Revert-Pfad nach einem Fehler) lässt die Kette „unmatched“; das braucht dann Handarbeit.

## Manifest

SHA-256 über sortierte relative Pfade (`/`), Größe und SHA-256 jeder Datei; fehlende Dateien und leere
Ordner gehen als `MISSING` ein. Pfade: siehe `star.CHAIN_PATHS` (`TO-DECIDE-USER.txt`,
`DECIDED-AND-DONE.md`, `_decision-archive/`, `_archive/`). Identisch zu BACH `lease_core.manifest_version`
für Dateien und fehlende Pfade; der Client lässt zusätzlich `*.polaris-tmp` aus (BACH berechnet nie ein
Manifest, es speichert nur den gemeldeten Hash). **Nicht im Manifest, bewusst:** das Journal (sein
Löschen darf den gemeldeten Stand nicht ändern) und **LOCK-Dateien** (`LOCK*.txt`): fremde Agenten legen sie
laufend an und löschen sie; sie in das Manifest zu nehmen, risse die Sync-Schranke dauerhaft. Der Writer legt
LOCK-Dateien nur mit dem Stern an oder entfernt sie; ihr Inhalt schützt keinen Kettenstand.

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
Registrierung und Gerät kennt) darf bei abweichendem Manifest per `rebaseline` erwerben (externe Änderungen,
z. B. direkt angehängte Agenteneinträge setzen den Stand neu), und nur wenn

* kein Journal lokal liegt und der Lead keinen In-flight-Marker führt (`journal_open` bzw. `inflight_open`;
  ohne lokales Journal bei offenem Marker: `journal_not_synced`) und
* das lokale Manifest über ein **Stabilitätsfenster** gleich bleibt: zwei Messungen im Abstand von 60 s
  (`DECISION_CLICKER_REBASELINE_WINDOW`, Sekunden, `0` schaltet ab), dazu unveränderte Datei-mtimes im
  Kettenumfang. Sonst `rebaseline_unstable`, später erneut versuchen.

Der Lead protokolliert `rebaseline_external_change` mit `previous_version` und `new_version` (altem und
neuem Hash). **Restrisiko:** dauert ein OneDrive-Sync länger als das Fenster und ruht dabei, kann eine
Teilkopie als neuer Stand gelten. Der Standby braucht immer den exakten Abgleich. LocalStar (nur ein Host)
rebaselinet ohne Fenster.

## Nicht geschützt (außerhalb des Ressourcenumfangs)

`_tools/decisions.index.json` und `INDEX-REPORT.md` sind abgeleitete Artefakte; sie werden bei Bedarf
regeneriert. Konfliktkopien davon (OneDrive) sind harmlos. Ebenso `chain_tools.materialize` (Werkzeugkopien
in `_tools/`) und die Übernahme-Markierung im Desktop-Postfach (Datei außerhalb der Kette).

## Bekanntes Restfenster

Bricht der star genau zwischen dem Schreiben des Journals und der Meldung des In-flight-Markers ab, steht
das Journal mit allen Hashes „vorher“: der Nachfolger verwirft es (nachweislich nichts geschrieben). Die
Server-Rolle rebaselinet danach nur nach dem Stabilitätsfenster und ohne Journal; ein Standby bleibt bis
dahin nur lesbar (`stale_resource_version`).
