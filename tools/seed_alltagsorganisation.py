# SPDX-License-Identifier: MIT
"""Seed: offene Alltagsorganisations-Entscheidungen in die Kette einstellen.

Quellen (beide read-only gelesen, nichts daran geaendert):
  * `~/OneDrive/.USR/ALLTAGSORGANISATION-BESTANDSAUFNAHME_2026-07-24.md`, Abschnitt 7 (E01-E07)
  * `~/OneDrive/.USR/BACH-VS-FULLSTACK_ENTSCHEIDUNGSBRIEFING_2026-08-07.md`, Abschnitt 6

Punkt 1 aus Abschnitt 6 des Briefings ("E01-E07 sind unbeantwortet") bekommt
bewusst KEINEN eigenen Eintrag: er ist der Zeiger auf genau die sieben
Entscheidungen, die hier einzeln eingestellt werden.

Der Lauf ist idempotent: bereits eingestellte Titel werden uebersprungen.
Er beantwortet nichts — jeder Eintrag geht als OFFEN in die Kette.

Aufruf:  PYTHONIOENCODING=utf-8 python tools/seed_alltagsorganisation.py [--dry-run]
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from decision_clicker import chain, writer  # noqa: E402
from decision_clicker.config import load  # noqa: E402

BESTAND = "`%OneDrive%\\.USR\\ALLTAGSORGANISATION-BESTANDSAUFNAHME_2026-07-24.md`, Abschnitt 7"
BRIEFING = "`%OneDrive%\\.USR\\BACH-VS-FULLSTACK_ENTSCHEIDUNGSBRIEFING_2026-08-07.md`, Abschnitt 6"

# (Titel, Frage, Kontext, Optionen, Empfehlung, Quelle)
SEEDS: list[dict] = [
    # ---------------------------------------------------------------- E01-E07
    dict(
        title="E01 — Workflow-Kombination für die Alltagsorganisation",
        frage="Welche Workflow-Kombination wird für Abos, Termine, Routinen, Kontakte, "
              "Versicherungen, Konten und Hobbys gesetzt?",
        kontext=(
            "Offen seit der Bestandsaufnahme vom 2026-07-24; im Entscheidungsregister stand "
            "dazu bisher kein Eintrag. Das Briefing vom 2026-08-07 hat die Lage neu vermessen "
            "und die Empfehlung bestätigt.\n"
            "Neu belegt am 2026-08-07: Ein BACH-Ersatz-Full-Stack existiert weder gebaut noch "
            "geplant; BACH synchronisiert als einziges System zwischen Laptop und Workstation; "
            "der proaktive Kanal (Mac Studio) liefert seit 2026-05-16 keinen Dump mehr."
        ),
        optionen=[
            "A — Spezialisten-Suite: die Apps führen, BACH bleibt außen vor.",
            "B — BACH-Zentrale: alles nach BACH umziehen.",
            "C — Cockpit und Agent (Hybrid): Apps behalten ihre Domänen, BACH erinnert und eskaliert.",
            "D — Claude-zentriert: Sessions und Artefakte als Organisationssystem.",
        ],
        empfehlung="C — nutzt jede vorhandene Investition in ihrer stärksten Rolle und gibt "
                   "Kontrolle genau dort ab, wo LLMs heute verlässlich sind.",
        quelle=BESTAND + f"; bestätigt in {BRIEFING}, Punkt 1.",
    ),
    dict(
        title="E02 — Medikamenten-Kanon",
        frage="Welches Werkzeug ist der Datenhalter für Medikamente?",
        kontext="Drei Kandidaten halten heute überlappend Medikamentendaten. Ohne Festlegung "
                "bleibt Doppelpflege bestehen.",
        optionen=[
            "A — MediPlaner V5.0 (Vollversion).",
            "B — MediPlan Family.",
            "C — UpToday-Kachel als Datenhalter.",
        ],
        empfehlung="A — Family bleibt reine Produktlinie, UpToday zeigt nur an.",
        quelle=BESTAND,
    ),
    dict(
        title="E03 — Routinen-Kanon",
        frage="Wo werden Routinen geführt — in Routinika, in BACH oder in beidem?",
        kontext="Parallelpflege in zwei Systemen ist laut Bestandsaufnahme die Hauptquelle des "
                "heutigen Wildwuchses. Das Briefing vom 2026-08-07 hält fest, dass Routinika "
                "zusätzlich einen festgelegten Haupthost braucht (siehe Entscheidung zum Haupthost), "
                "sonst driften zwei Bestände auseinander.",
        optionen=[
            "A — Routinika ist Kanon; BACH spiegelt nur Fälligkeiten ins Briefing.",
            "B — BACH-Routinen sind Kanon.",
            "C — Beides parallel führen.",
        ],
        empfehlung="A — C führt die Doppelpflege wieder ein, die abgeschafft werden soll.",
        quelle=BESTAND,
    ),
    dict(
        title="E04 — Abo- und Versicherungsdaten regelmäßig nach BACH exportieren",
        frage="Sollen AboTracker-JSON und `fin_insurances` als Scheduler-Job nach BACH laufen, "
              "damit BACH Fristen-Wecker spielen kann?",
        kontext="Ohne diese Brücke bleibt der Fristenschutz Handarbeit. Der App-Export "
                "`bach.fin_insurances.v1` existiert bereits; auf BACH-Seite fehlt der Importer "
                "(Briefing 2026-08-07, Einrichtungsschritt 9).",
        optionen=[
            "A — Ja, als geplanter Job (Scheduler bzw. BACH-Chain).",
            "B — Nein, manuell bei Bedarf.",
        ],
        empfehlung="A — ohne die Brücke bleibt genau der Teil Handarbeit, der automatisiert "
                   "werden sollte.",
        quelle=BESTAND,
    ),
    dict(
        title="E05 — FullAssistantHub: einfrieren oder weiterbauen",
        frage="Wie geht es mit dem FullAssistantHub weiter?",
        kontext="Seine Rolle (Bündeln und Briefing) ist durch UpToday und BACH bereits doppelt "
                "besetzt. Weiterbau eröffnete eine dritte Dashboard-Linie.",
        optionen=[
            "A — Einfrieren: Registry-Status behalten, kein Weiterbau.",
            "B — Als reinen Tray-Launcher fertigstellen.",
            "C — Voll weiterentwickeln.",
        ],
        empfehlung="A — keine dritte Linie für eine bereits doppelt besetzte Rolle.",
        quelle=BESTAND,
    ),
    dict(
        title="E06 — Cloud- und Desktop-App-Artefakte mit Organisationsfunktion",
        frage="Sollen die Organisations-Artefakte stillgelegt und ihre Inhalte einmalig in die "
              "Kanon-Apps übertragen werden?",
        kontext="Artefakte ohne Datenhaltung und ohne Erinnerungsfunktion erzeugen "
                "Scheinsicherheit. Offener Punkt aus der Bestandsaufnahme: Die Cloud-Artefakte "
                "der Desktop-App konnten von außen nicht inventarisiert werden — vor dem "
                "Stilllegen einmal in der App durchsehen. Reihenfolge laut Umsetzungsplan: "
                "erst nach funktionierendem Briefing, damit nichts ersatzlos wegfällt.",
        optionen=[
            "A — Stilllegen, Inhalte einmalig in die Kanon-Apps übertragen.",
            "B — Weiterlaufen lassen.",
        ],
        empfehlung="A — nach Durchsicht in der Desktop-App und erst nach funktionierendem Briefing.",
        quelle=BESTAND,
    ),
    dict(
        title="E07 — Haushaltsfinanzen: BACHs Struktur befüllen statt Neues bauen",
        frage="Wird die vorhandene BACH-Struktur befüllt, oder entsteht ein neues Mini-Tool?",
        kontext="Korrektur nach Live-Erkundung: Die im Erstbefund vermutete Budget-Lücke ist "
                "überwiegend keine. BACH rechnet Fixkosten bereits live aus echten Verträgen "
                "(493,44 € pro Monat); `haushalt costs`, `fin_contracts` und `steuer` sind "
                "produktiv. Leer sind nur `bank_accounts` und `financial_summary`.",
        optionen=[
            "A — Ja: nur die Konten- und Summary-Ebene befüllen, sonst nichts bauen.",
            "B — Ein neues Mini-Tool bauen.",
            "C — Vorerst offen lassen.",
        ],
        empfehlung="A — die Struktur steht bereits und ist produktiv im Einsatz.",
        quelle=BESTAND,
    ),
    # -------------------------------------------------- Briefing 2026-08-07
    dict(
        title="Alltagsorganisation: Option C in der neuen Aufteilung bestätigen",
        frage="Wird Option C in der neuen Aufteilung bestätigt — Kanon folgt dem Sync, und BACH "
              "führt Termine, Kontakte, Versicherungen, Abos und Konten?",
        kontext="Das Briefing vom 2026-08-07 weicht an sechs Stellen von der Bestandsaufnahme ab. "
                "Die wichtigste: Der Sync wird zum Auswahlkriterium. Gemessen synchronisieren die "
                "Apps nicht, BACH schon — wer den Kanon nach Funktionstiefe verteilt, verteilt ihn "
                "in Wahrheit auf Rechner. Diese Entscheidung schreibt E01 fort und ist deren "
                "konkrete Ausgestaltung, nicht ihre Wiederholung.",
        optionen=[
            "A — Ja: Kanon folgt dem Sync; BACH führt Termine, Kontakte, Versicherungen, Abos und Konten.",
            "B — Nein: Kanon weiter nach Funktionstiefe verteilen, wie in der Bestandsaufnahme.",
        ],
        empfehlung="A — nur BACH synchronisiert nachweislich zwischen den Hosts.",
        quelle=BRIEFING + ", Punkt 2.",
    ),
    dict(
        title="Versicherungen: BACH als Kanon statt VersicherungsManager",
        frage="Wird BACH `versicherung` der Datenhalter für Versicherungen, mit dem "
              "VersicherungsManager als Oberfläche?",
        kontext="Abweichung 2 des Briefings. Neu belegt: BACH hat Fristenwarnung, Schadenfälle "
                "und Fixkosten-Einrechnung; die App ist im Status DEV, und die Brücke ist "
                "einseitig (App-Export vorhanden, BACH-Import fehlt). Der VersicherungsManager "
                "bliebe Produkt und Komfort-Oberfläche.",
        optionen=[
            "A — BACH `versicherung` ist Kanon; die App bleibt Oberfläche und Produkt.",
            "B — VersicherungsManager bleibt Kanon für die eigenen Daten.",
        ],
        empfehlung="A — bis ein Importer existiert, führt BACH die eigenen Daten.",
        quelle=BRIEFING + ", Punkt 3.",
    ),
    dict(
        title="Haupthost für die Alltags-Apps: Laptop oder Workstation",
        frage="Welcher Rechner ist Haupthost für Routinika, MediPlaner, HausLagerist, AboTracker "
              "und VersicherungsManager?",
        kontext="Ohne Festlegung driften die Bestände auseinander — namentlich Routinika und "
                "AboTracker. Die Apps synchronisieren nicht; gepflegt werden darf ab der "
                "Festlegung nur noch auf dem Haupthost. Das Briefing schlägt den Laptop vor, "
                "kennzeichnet das aber ausdrücklich als Vorschlag, nicht als Befund. Der Schritt "
                "ist sofort möglich und vom BACH-Judging-Hold nicht betroffen.",
        optionen=[
            "A — Laptop (ASUS-GEI).",
            "B — Workstation (WORKSTATION-LG).",
        ],
        empfehlung="A — Vorschlag des Briefings; die Wahl hängt daran, wo Lukas die Apps "
                   "tatsächlich täglich benutzt, und ist deshalb bewusst offen.",
        quelle=BRIEFING + ", Punkt 4; Einrichtungsschritt 2.",
    ),
    dict(
        title="Proaktiver Kanal: auf dem Mac Studio belassen oder auf Windows umziehen",
        frage="Soll der proaktive Kanal (Briefing-Scheduler) auf dem Mac Studio bleiben oder auf "
              "einen der beiden Windows-Hosts wandern?",
        kontext="Der Mac-Studio-Zweig liefert seit 2026-05-16 keinen Dump mehr in "
                "`.SYNC\\bach_db_transit\\`; damit fehlt genau die Proaktivität, die das "
                "eigentliche Problem lösen soll. Die beiden Windows-Hosts synchronisieren "
                "ohnehin täglich. Der Mac läuft dafür 24/7, die Windows-Hosts nicht. "
                "Umsetzung frühestens ab 13.08. (BACH-Judging-Hold); die Diagnose ist vorher möglich.",
        optionen=[
            "A — Auf dem Mac Studio belassen und den Sync reparieren (Einrichtungsschritt 5).",
            "B — Auf Laptop oder Workstation umziehen.",
        ],
        empfehlung="A — der Mac ist der einzige Host mit 24/7-Verfügbarkeit; zuerst gilt "
                   "ohnehin die reine Diagnose (Schritt 1).",
        quelle=BRIEFING + ", Punkt 5; Einrichtungsschritte 1 und 5.",
    ),
    dict(
        title="Zustellkanal für das tägliche Briefing",
        frage="Über welchen Kanal wird das tägliche Briefing zugestellt?",
        kontext="Im gelesenen Briefing-Code ist kein Telegram-Versand enthalten — die bisher "
                "angenommene Zustellung ist damit nicht belegt. In der BACH-MessageBox liegen "
                "108 ungelesene Nachrichten; sie abzutragen wäre die erste Amtshandlung des "
                "scharf geschalteten Briefings. Umsetzung frühestens ab 13.08.",
        optionen=[
            "A — Telegram (`@bach_assistant_bot`), Versandweg nachrüsten.",
            "B — Desktop-Benachrichtigung auf dem Haupthost.",
            "C — Mail an hallo@um-bruch.org.",
        ],
        empfehlung="A — ein Kanal, den Lukas ohnehin mobil liest; setzt voraus, dass der "
                   "Versandweg tatsächlich ergänzt wird.",
        quelle=BRIEFING + ", Punkt 6; Einrichtungsschritt 7.",
    ),
    dict(
        title="Bankkonten: manuelle Saldo-Pflege oder CAMT-Import reparieren",
        frage="Reicht die manuelle Saldo-Pflege, oder soll der CAMT-Import repariert werden?",
        kontext="`bank_accounts` und `financial_summary` sind leer. Der Schreibweg über "
                "`/api/financial/bank-accounts` existiert bereits (Teilschritt 10a). Der "
                "CAMT-Import ist defekt: falscher Importpfad und fehlende Persistenz, er zeigt "
                "heute nur fünf Buchungen an (10b). Für `financial_summary` fehlt jeder "
                "Schreibpfad. Ausdrücklich kein neues Finanztool bauen.",
        optionen=[
            "A — Nur 10a: Konten anlegen und den Saldo monatlich manuell pflegen.",
            "B — 10a und danach 10b: zusätzlich den CAMT-Import reparieren.",
        ],
        empfehlung="A als Sofortmaßnahme; B nur, wenn der monatliche Handgriff tatsächlich stört.",
        quelle=BRIEFING + ", Punkt 7; Einrichtungsschritt 10.",
    ),
    dict(
        title="Hobbys: Interessenliste oder eigenes Hobby-Modul",
        frage="Reicht eine Interessenliste plus Assistent, oder soll ein echtes Hobby-Modul mit "
              "Auswahllogik entstehen?",
        kontext="Heute gibt es für Hobbys keinen Datenanker; der persönliche Assistent führt "
                "reine Konversation. Eine schlichte Interessen- und Aktivitätenliste (eine Datei "
                "genügt) würde das lösen; Durchführung liefe über Routinika, Planung über "
                "`bach calendar` und `location_search.py`. Ein echtes Modul mit Vorschlagslogik "
                "wäre ein Neubau und müsste in die Prioritätenfolge einsortiert werden.",
        optionen=[
            "A — Interessenliste plus Assistent, kein Neubau.",
            "B — Echtes Hobby-Modul mit Auswahllogik bauen.",
        ],
        empfehlung="A — bewusst kein Neubau, solange der Datenanker den Zweck erfüllt.",
        quelle=BRIEFING + ", Punkt 8; Einrichtungsschritt 11.",
    ),
    dict(
        title="`bach task`: Fälligkeitsfeld nachrüsten oder Termine bei Routinika belassen",
        frage="Soll `bach task` ein Fälligkeitsfeld bekommen, oder bleiben terminierte Aufgaben "
              "ausschließlich in Routinika?",
        kontext="BACHs Aufgabenverwaltung kennt heute kein Fälligkeitsdatum — einer der Gründe, "
                "warum ein Vollumzug nach BACH verworfen wurde. Bleibt es dabei, führt BACH nur "
                "Delegations-Tasks, und alles Terminierte liegt in Routinika. Umsetzung "
                "frühestens ab 13.08.",
        optionen=[
            "A — `bach task` um ein Fälligkeitsfeld erweitern.",
            "B — Terminiertes bleibt in Routinika; BACH führt nur Delegations-Tasks.",
        ],
        empfehlung="B — hält die Domänengrenze sauber und vermeidet eine zweite Fälligkeitsquelle.",
        quelle=BRIEFING + ", Punkt 9.",
    ),
    dict(
        title="Kalender-Handler: `reminder_minutes` und `recurrence_rule` nachrüsten",
        frage="Sollen `reminder_minutes` und `recurrence_rule` im Kalender-Handler nachgerüstet "
              "werden, oder reicht die reine Terminliste?",
        kontext="Die Spalten existieren im Schema bereits; nur der Schreibpfad im Handler fehlt. "
                "Ohne sie bleibt der Kalender eine reine Liste ohne Erinnerung und ohne "
                "Wiederholung. Umsetzung frühestens ab 13.08. (Einrichtungsschritt 6).",
        optionen=[
            "A — Beide Felder im Handler nachrüsten.",
            "B — Reine Terminliste genügt.",
        ],
        empfehlung="A — die Spalten sind da; ohne Erinnerung fehlt dem Kalender der eigentliche Nutzen.",
        quelle=BRIEFING + ", Punkt 10; Einrichtungsschritt 6.",
    ),
]

SCOPE = "global"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--dry-run", action="store_true", help="nur zeigen, nichts schreiben")
    args = parser.parse_args(argv)

    settings = load()
    fremde = writer.foreign_locks(settings)
    if fremde and not args.dry_run:
        print(f"ABBRUCH: fremde Sperre aktiv: {[p.name for p in fremde]}", file=sys.stderr)
        return 3

    index = chain.build_index(settings)
    vorhanden = {e["title"].strip().lower() for e in index["entries"]}
    ziel = chain.target_part(settings)
    print(f"Ziel: {ziel}")
    print(f"Offen vor dem Lauf: {chain.counts(index)['offen']}")

    geschrieben, uebersprungen = [], []
    for seed in SEEDS:
        if seed["title"].strip().lower() in vorhanden:
            uebersprungen.append(seed["title"])
            continue
        entry_id = chain.next_id(index)
        rendered = writer.render_entry(
            entry_id, seed["title"], quelle=seed["quelle"], frage=seed["frage"],
            optionen=seed["optionen"], empfehlung=seed["empfehlung"],
            kontext=seed["kontext"], scope=SCOPE,
        )
        if args.dry_run:
            print(f"\n--- WUERDE SCHREIBEN: {entry_id} ---\n{rendered}")
            geschrieben.append(entry_id)
            # Fuer die Trockenprobe die ID belegen, damit sie nicht doppelt faellt.
            index["entries"].append({**index["entries"][0], "id": entry_id, "key": entry_id})
            continue
        writer.append_entry(settings, ziel, rendered)
        index = chain.build_index(settings)
        vorhanden.add(seed["title"].strip().lower())
        geschrieben.append(entry_id)
        print(f"  eingestellt: {entry_id} — {seed['title']}")

    if not args.dry_run:
        chain.refresh_artifacts(settings)
        index = chain.build_index(settings)
        print(f"Offen nach dem Lauf: {chain.counts(index)['offen']}")
        print(f"ID-Kollisionen in der aktiven Kette: {chain.counts(index)['kollisionen']}")
    print(f"\nEingestellt: {len(geschrieben)} · Uebersprungen (schon vorhanden): {len(uebersprungen)}")
    for titel in uebersprungen:
        print(f"  schon da: {titel}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
