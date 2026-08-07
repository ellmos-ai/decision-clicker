# SPDX-License-Identifier: MIT
"""Lesezugriff auf die Entscheidungskette.

Der Parser wird NICHT nachgebaut: `decisions_index.py` aus `_DECISIONS/_tools/`
ist die eine Quelle der Wahrheit fuer das Lesen der Kette und wird hier als
Modul geladen. Faellt es aus, faellt der Clicker aus — das ist gewollt, denn
ein zweiter, leicht abweichender Parser waere die schlimmere Variante.
"""
from __future__ import annotations

import importlib.util
import re
import sys
from datetime import date
from functools import lru_cache
from pathlib import Path
from types import ModuleType

from .config import CUT_AND_CLUE_LINES, Settings

STATUS_OPEN = "OFFEN"
STATUS_PENDING = "ENTSCHIEDEN_UMSETZUNG_OFFEN"
STATUS_DONE = "DONE"
STATUS_ARCHIVED = "ARCHIVIERT"

ID_RE = re.compile(r"D-(\d{8})-(\d{2,4})")
PART_RE = re.compile(r"^TO-DECIDE-USER(?:_(\d+))?\.txt$", re.I)


class ChainError(RuntimeError):
    """Die Kette ist nicht lesbar — nie stillschweigend uebergehen."""


# ---------------------------------------------------------------------------
# Indexwerkzeug laden
# ---------------------------------------------------------------------------
@lru_cache(maxsize=4)
def _load_index_tool(script: Path) -> ModuleType:
    if not script.is_file():
        raise ChainError(f"Indexwerkzeug nicht gefunden: {script}")
    spec = importlib.util.spec_from_file_location("decisions_index_tool", script)
    if spec is None or spec.loader is None:
        raise ChainError(f"Indexwerkzeug nicht ladbar: {script}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def build_index(settings: Settings) -> dict:
    """Frischer Index direkt aus den Kettendateien (kein Cache, read-only)."""
    tool = _load_index_tool(settings.index_script)
    if not settings.chain_dir.is_dir():
        raise ChainError(f"Kettenordner nicht gefunden: {settings.chain_dir}")
    return tool.build_index(settings.chain_dir)


def refresh_artifacts(settings: Settings) -> None:
    """`decisions.index.json` + `INDEX-REPORT.md` neu erzeugen.

    Schreibt ausschliesslich in das Ausgabeverzeichnis des Indexwerkzeugs.
    Fehler hier duerfen eine bereits geschriebene Entscheidung nicht kippen.
    """
    tool = _load_index_tool(settings.index_script)
    index = tool.build_index(settings.chain_dir)
    out = settings.tools_dir
    out.mkdir(parents=True, exist_ok=True)
    import json

    (out / "decisions.index.json").write_text(
        json.dumps(index, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    (out / "INDEX-REPORT.md").write_text(tool.render_report(index), encoding="utf-8")


# ---------------------------------------------------------------------------
# Sichten
# ---------------------------------------------------------------------------
def open_entries(index: dict) -> list[dict]:
    """Echt offene Eintraege, aelteste zuerst — Aliase bleiben aussen vor."""
    items = [
        e for e in index["entries"]
        if e["status_class"] == STATUS_OPEN and not e["is_alias"]
    ]
    return sorted(items, key=lambda e: (e["date"], e["id"]))


def decided_entries(index: dict) -> list[dict]:
    """Alles mit getroffener Entscheidung — fuer das Register."""
    wanted = (STATUS_PENDING, STATUS_DONE, STATUS_ARCHIVED)
    items = [e for e in index["entries"] if e["status_class"] in wanted]
    return sorted(items, key=lambda e: (e["date"], e["id"]), reverse=True)


def register_entries(settings: Settings, index: dict) -> list[dict]:
    """Langzeit-Register: alle getroffenen Entscheidungen, über Quellen dedupliziert.

    Dieselbe D-ID kann in der Kette UND im Desktop-Postfach stehen — dann ist
    das EIN Eintrag mit zwei Fundstellen, nicht zwei Einträge. Die Kette
    gewinnt als kanonische Fassung; das Postfach erscheint als Zusatz-Fundstelle.
    """
    from . import intake  # spät, damit chain ohne Postfach nutzbar bleibt

    zusammen: dict[str, dict] = {}
    for eintrag in decided_entries(index):
        vorhanden = zusammen.get(eintrag["id"])
        if vorhanden is None:
            zusammen[eintrag["id"]] = dict(eintrag, fundstellen=[eintrag["source_file"]])
        elif eintrag["source_file"] not in vorhanden["fundstellen"]:
            vorhanden["fundstellen"].append(eintrag["source_file"])

    try:
        postfach = intake.scan(settings)
    except OSError:
        postfach = []
    for eintrag in postfach:
        if not eintrag.decided:
            continue
        fundstelle = f"Desktop/{eintrag.path.name}"
        vorhanden = zusammen.get(eintrag.entry_id)
        if vorhanden is not None:
            if fundstelle not in vorhanden["fundstellen"]:
                vorhanden["fundstellen"].append(fundstelle)
            continue
        zusammen[eintrag.entry_id] = {
            "key": eintrag.entry_id, "id": eintrag.entry_id,
            "date": f"{eintrag.entry_id[2:6]}-{eintrag.entry_id[6:8]}-{eintrag.entry_id[8:10]}",
            "title": eintrag.title, "question": eintrag.frage,
            "status_class": "DESKTOP-POSTFACH", "decision_field_raw": eintrag.decision,
            "source_file": fundstelle, "source_line": eintrag.start + 1,
            "fundstellen": [fundstelle],
        }
    return sorted(zusammen.values(), key=lambda e: (e["date"], e["id"]), reverse=True)


def find(index: dict, key: str) -> dict | None:
    for entry in index["entries"]:
        if entry["key"] == key:
            return entry
    return None


def counts(index: dict) -> dict[str, int]:
    by_status = index["counts"]["by_status_class"]
    return {
        "offen": len(open_entries(index)),
        "offen_roh": by_status.get(STATUS_OPEN, 0),
        "entschieden_offen": by_status.get(STATUS_PENDING, 0),
        "done": by_status.get(STATUS_DONE, 0),
        "archiviert": by_status.get(STATUS_ARCHIVED, 0),
        "gesamt": index["counts"]["total"],
        "kollisionen": index["counts"]["id_collisions"],
    }


# ---------------------------------------------------------------------------
# ID-Vergabe
# ---------------------------------------------------------------------------
def known_ids(index: dict) -> set[str]:
    """Alle je vergebenen IDs — aktive Kette, DONE und Archiv zusammen.

    Bewusst ueber ALLE Bereiche: eine im Archiv liegende ID ist vergeben und
    darf nicht neu vergeben werden. Genau daraus sind die bekannten
    Kollisionen entstanden.
    """
    return {e["id"] for e in index["entries"]}


def next_id(index: dict, on: date | None = None) -> str:
    """Naechste freie ID des Tages, kollisionssicher gegen den ganzen Bestand."""
    day = (on or date.today()).strftime("%Y%m%d")
    taken = {
        int(m.group(2))
        for m in (ID_RE.fullmatch(i) for i in known_ids(index))
        if m and m.group(1) == day
    }
    number = 1
    while number in taken:
        number += 1
    return f"D-{day}-{number:03d}"


# ---------------------------------------------------------------------------
# Zieldatei fuer neue Eintraege
# ---------------------------------------------------------------------------
def target_part(settings: Settings) -> Path:
    """Letzter Kettenteil; laeuft er ueber, wird das gemeldet statt geteilt.

    Ein automatischer Cut-and-Clue-Split waere ein struktureller Eingriff in
    die Kette — den trifft ein Mensch, nicht dieses Werkzeug.
    """
    parts: list[tuple[int, Path]] = []
    for path in settings.chain_dir.glob("TO-DECIDE-USER*.txt"):
        match = PART_RE.match(path.name)
        if match:
            parts.append((int(match.group(1) or 1), path))
    if not parts:
        raise ChainError(f"Kein Kettenteil in {settings.chain_dir} gefunden")
    _, path = max(parts, key=lambda item: item[0])
    return path


def part_is_full(path: Path) -> bool:
    return len(path.read_text(encoding="utf-8-sig").splitlines()) > CUT_AND_CLUE_LINES
