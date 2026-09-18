# SPDX-License-Identifier: MIT
"""Regressionstests für UI-Overflow und Granularität (T-20260913-362478843).

Prüft:
1. CSS-Überlaufschutz: `.card`, `button.wahl`, `.kontext`, `.subcard`, `.table-wrap`.
2. Saubere Darstellung und Zeilenumbruch auch bei extrem langen deutschen Wörtern/URLs.
3. Echte deutsche Umlaute in der Benutzeroberfläche.
4. Granularität: 'eine Kachel = genau eine entscheidbare Frage'.
5. Zerlegung gebündelter Entscheidungen beim Intake in Sub-Einträge (-1, -2).
6. Passung und Auswahl der Items zur Entscheidung (Optionen gehören exakt zu ihrer Frage).
7. Fragen ohne Optionen verbleiben als reiner Kontext statt unentscheidbarer Kacheln.
"""
from __future__ import annotations

from pathlib import Path

from decision_clicker import intake, ui


def test_css_overflow_guardrails_enthalten():
    """Wachhund: CSS muss Überlaufschutz für Kacheln, Optionen und Tabellen besitzen."""
    css = ui.CSS
    # Box-Sizing & Viewport
    assert "box-sizing:border-box" in css
    assert "min-width:320px" in css
    assert "overflow-x:hidden" in css

    # .card & .subcard
    assert "max-width:100%" in css
    assert "overflow-wrap:anywhere" in css
    assert "word-break:break-word" in css
    assert "hyphens:auto" in css

    # button.wahl: darf nicht umbrechen verweigern oder aus der Kachel laufen
    assert "white-space:normal" in css
    assert "button.wahl{display:block;width:100%;max-width:100%" in css

    # Tabellen-Wrapper
    assert ".table-wrap{width:100%;overflow-x:auto" in css


def test_echte_deutsche_umlaute_in_ui_texten():
    """Die Oberfläche muss echte UTF-8-Umlaute (ä, ö, ü, ß) ausliefern."""
    leer_klick = ui.klick(None, 0).decode("utf-8")
    assert "Übersicht" in leer_klick
    assert "Durchklicken" in leer_klick

    dummy_entry = {
        "key": "D-20260913-999",
        "title": "Prüfung der Rücklagen",
        "date": "2026-09-13",
        "source_file": "TO-DECIDE-USER.txt",
        "source_line": 1,
        "question": "Soll die Übergangsregelung für Vermieter gewählt werden?",
        "_optionen": [("A", "Vollständig übernehmen"), ("B", "Zurückstellen")],
        "recommendation_excerpt": "A — vollständig",
    }
    klick_html = ui.klick(dummy_entry, 1).decode("utf-8")
    assert "Übergangsregelung" in klick_html
    assert "Zurückstellen" in klick_html
    assert "Später entscheiden" in klick_html
    assert "Begründung, Einschränkung, Auflage …" in klick_html


def test_lange_deutsche_zusammensetzungen_bleiben_gekapselt():
    """Extrem lange Wörter und URLs werden in der Kachel gerendert ohne Layoutbruch."""
    monster_wort = "Rindfleischetikettierungsüberwachungsaufgabenübertragungsgesetz"
    monster_url = "https://subdomain.example.org/very/deeply/nested/path/to/resource?with=lots&of=parameters&including=hash#anchor"
    entry = {
        "key": "D-20260913-998",
        "title": f"Titel mit {monster_wort}",
        "date": "2026-09-13",
        "source_file": "TO-DECIDE-USER.txt",
        "source_line": 10,
        "question": f"Frage mit {monster_url} und {monster_wort}?",
        "_optionen": [("A", f"Weg A mit {monster_wort}"), ("B", f"Weg B mit {monster_url}")],
        "recommendation_excerpt": "A",
    }
    rendered = ui.klick(entry, 1).decode("utf-8")
    assert monster_wort in rendered
    assert "https://subdomain.example.org/very/deeply/nested/path/to/resource" in rendered
    # Kacheln und Buttons verwenden overflow-wrap:anywhere
    assert 'class="card"' in rendered
    assert 'button class="wahl"' in rendered


def test_collect_question_blocks_einfache_entscheidung():
    """Einzeilige / normale Entscheidung liefert genau einen Frageblock."""
    raw = """
FRAGE: Soll der bestehende Rollout fortgeführt werden?
OPTIONEN:
- A — Fortführen
- B — Pausieren
EMPFEHLUNG: A — weil stabil.
"""
    blocks = intake.collect_question_blocks(raw.splitlines())
    assert len(blocks) == 1
    assert blocks[0].num == 1
    assert "Soll der bestehende Rollout" in blocks[0].question
    assert len(blocks[0].options) == 2
    assert blocks[0].options[0] == "A — Fortführen"
    assert blocks[0].options[1] == "B — Pausieren"
    assert "A" in blocks[0].empfehlung


def test_collect_question_blocks_gebuendelte_entscheidung():
    """Gebündelte Vorlage (wie D-20260913-003) wird in isolierte Fragen mit Passung zerlegt."""
    raw = """
FRAGE 1 (`OC-2026-09-13-B`): Wie werden scheduler und agent-launcher zerlegt?

OPTIONEN:
  [A] Nach dem Muster von doc-services: den Engpass bestimmen
  [B] Ganze Datei in einem Zug

FRAGE 2 (`OC-2026-09-13-C`): Was geschieht mit swarm-ai?

OPTIONEN:
  [A] Modul erst bauen
  [B] Paar streichen

EMPFEHLUNG: Frage 1 **A** — weil prüfbar. Frage 2 **B**, solange kein Konsument da ist.
"""
    blocks = intake.collect_question_blocks(raw.splitlines())
    assert len(blocks) == 2

    # Frage 1
    assert blocks[0].num == 1
    assert "scheduler und agent-launcher" in blocks[0].question
    assert len(blocks[0].options) == 2
    assert blocks[0].options[0].startswith("A — Nach dem Muster")
    assert blocks[0].options[1].startswith("B — Ganze Datei")
    assert "A" in blocks[0].empfehlung

    # Frage 2
    assert blocks[1].num == 2
    assert "Was geschieht mit swarm-ai?" in blocks[1].question
    assert len(blocks[1].options) == 2
    assert blocks[1].options[0].startswith("A — Modul erst bauen")
    assert blocks[1].options[1].startswith("B — Paar streichen")
    assert "B" in blocks[1].empfehlung


def test_frage_ohne_optionen_bleibt_kontext():
    """Frage ohne eigene Optionen wird nicht als unentscheidbare Kachel gewertet."""
    raw = """
FRAGE: Warum ist dieser Schritt notwendig? (Hintergrundinformation)

FRAGE 2: Welcher Weg soll für die Umsetzung gewählt werden?
OPTIONEN:
- A — Direkter Pfad
- B — Indirekter Pfad
EMPFEHLUNG: A
"""
    blocks = intake.collect_question_blocks(raw.splitlines())
    actionable = [b for b in blocks if b.options]
    assert len(actionable) == 1
    assert actionable[0].num == 2
    assert "Welcher Weg soll" in actionable[0].question


def test_intake_zerlegt_gebuendelten_eintrag():
    """Intake zerlegt gebündelte Vorlagen in Sub-Einträge (-1, -2) mit Passung der Items."""
    raw = """
ID: D-20260913-003
TITEL: Rücktransport-Programm
FRAGE 1: Erste Frage?
OPTIONEN:
[A] Option 1A
[B] Option 1B

FRAGE 2: Zweite Frage?
OPTIONEN:
[A] Option 2A
[B] Option 2B
EMPFEHLUNG: Frage 1 A. Frage 2 B.
"""
    basis = intake.IntakeEntry(
        entry_id="D-20260913-003",
        title="Rücktransport-Programm",
        path=Path("TO-DECIDE-USER.txt"),
        start=0,
        end=len(raw.splitlines()),
        raw=raw,
        fields={"PROJEKT": "Ecosystem"},
        optionen=[],
    )
    zerlegt = intake.decompose_compound_entry(basis)
    assert len(zerlegt) == 2

    # Teil 1
    assert zerlegt[0].entry_id == "D-20260913-003-1"
    assert "Frage 1" in zerlegt[0].title
    assert zerlegt[0].frage == "Erste Frage?"
    assert len(zerlegt[0].optionen) == 2
    assert zerlegt[0].optionen[0] == "A — Option 1A"
    assert zerlegt[0].optionen[1] == "B — Option 1B"
    assert "A" in zerlegt[0].empfehlung

    # Teil 2
    assert zerlegt[1].entry_id == "D-20260913-003-2"
    assert "Frage 2" in zerlegt[1].title
    assert zerlegt[1].frage == "Zweite Frage?"
    assert len(zerlegt[1].optionen) == 2
    assert zerlegt[1].optionen[0] == "A — Option 2A"
    assert zerlegt[1].optionen[1] == "B — Option 2B"
    assert "B" in zerlegt[1].empfehlung


def test_ui_klick_rendert_subcards_fuer_gebuendelte_fragen():
    """UI rendert für gebündelte Einträge getrennte Sub-Kacheln mit zugeordneten Optionen."""
    raw = """
FRAGE 1: Soll Feature X aktiviert werden?
OPTIONEN:
- A — Feature X aktivieren
- B — Feature X deaktivieren

FRAGE 2: Welcher Modus für Feature Y?
OPTIONEN:
- A — Modus Schnell
- B — Modus Sicher

EMPFEHLUNG: Frage 1 **A**, Frage 2 **B**.
"""
    entry = {
        "key": "D-20260913-003",
        "title": "Doppelentscheidung",
        "date": "2026-09-13",
        "source_file": "TO-DECIDE-USER.txt",
        "source_line": 1,
        "_raw": raw,
        "question": raw,
    }
    html = ui.klick(entry, 1, confirmation="test-token").decode("utf-8")

    # Beide Sub-Kacheln vorhanden
    assert '<div class="subcard"><h3>Frage 1: Soll Feature X aktiviert werden?</h3>' in html
    assert '<div class="subcard"><h3>Frage 2: Welcher Modus für Feature Y?</h3>' in html

    # Passung der Optionen zur jeweiligen Kachel
    assert "Passung zu dieser Einzelfrage" in html
    assert "Feature X aktivieren" in html
    assert "Modus Schnell" in html

    # Kombinationsauswahl im Formular
    assert "(1) [A] + (2) [B]" in html
    assert 'value="(1) A / (2) B"' in html
    assert '<span class="tag">empfohlen</span>' in html
