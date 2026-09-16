#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""decisions_index.py — Index ueber die zentrale Entscheidungskette (_DECISIONS).

Liest das eine kanonische aktive Entscheidungsdokument read-only und erzeugt
zwei abgeleitete Artefakte:

  decisions.index.json   maschinenlesbar (Schema "decisions.index/1")
  INDEX-REPORT.md        kompakter Lesebericht, echt offene Eintraege zuerst

Verbindliche Eigenschaften:

* **Read-only gegenueber den Quellen.** Das Werkzeug schreibt ausschliesslich in
  sein Ausgabeverzeichnis (Default: dieser Ordner). Keine Quelldatei wird
  veraendert, keine ID umnummeriert.
* **Idempotent.** Gleicher Input => gleicher Output (bis auf `generated_at`).
* **Aktivvertrag.** Ausschliesslich ``TO-DECIDE-USER.txt`` ist aktiv. Dort
  duerfen nur unbeantwortete, entscheidungsreife Eintraege stehen.
* **ID-Kollisionen werden gemeldet, nicht repariert.** IDs koennen anderswo
  referenziert sein; eine Umnummerierung durch ein Werkzeug waere ein
  stiller Bruch. Kollidierende Eintraege bleiben ueber `key` (`<ID>#a`, `#b`, …)
  eindeutig adressierbar.

Aufruf:
    PYTHONIOENCODING=utf-8 python decisions_index.py [--root DIR] [--out-dir DIR]
                                                     [--print] [--json-only]
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

VERSION = "1.4.0"
SCHEMA = "decisions.index/1"
GENERATOR = f"decisions_index.py {VERSION}"

# Hostneutral (T-20260906-186783185, GATE-4-Korrektur): vorher hart auf den
# Laptop-Pfad C:\Users\User\... codiert. `DECISIONS_ROOT` erlaubt einen
# expliziten Override (z. B. fuer Tests oder abweichende Layouts); ohne ihn
# wird der Pfad relativ zum Home-Verzeichnis des jeweiligen Hosts aufgeloest --
# funktioniert unveraendert auf `C:\Users\<user>\...` (Workstation / Laptop),
# ohne dass `--root` zwingend uebergeben werden muss. Siehe .TOPICS/CLAUDE.md:
# derselbe Fix bereits fuer `.ELLMOS.MIGRATED.md` angewandt (T-20260815-37).
DEFAULT_ROOT = Path(
    os.environ.get("DECISIONS_ROOT")
    # [C 2026-09-06 USER-MIND-Umzug] Standort-Ableitung statt altem
    # _control-center/_DECISIONS-Pfad, vgl. decisions_db.py
    or Path(__file__).resolve().parent.parent
)

# Reihenfolge ist bedeutsam: die aktive Kette wird ZUERST gescannt, damit bei
# ID-Kollisionen die aktiven Eintraege die vorderen Suffixe (#a, #b) erhalten.
#
# Die Dateinamen werden weiter unten bewusst mit exakten Mustern erkannt. Ein
# weiter Glob wie ``TO-DECIDE-USER_*.txt`` nimmt sonst OneDrive-Konfliktkopien
# wie ``TO-DECIDE-USER_4-WORKSTATION-LG.txt`` als aktive Kettenteile auf.
DONE_NAME = "DECIDED-AND-DONE.md"
ARCHIVE_DIR = "_decision-archive"
ACTIVE_NAME = "TO-DECIDE-USER.txt"

STATUS_OPEN = "OFFEN"
STATUS_DECIDED_PENDING = "ENTSCHIEDEN_UMSETZUNG_OFFEN"
STATUS_DONE = "DONE"
STATUS_ARCHIVED = "ARCHIVIERT"
STATUS_CLASSES = (STATUS_OPEN, STATUS_DECIDED_PENDING, STATUS_DONE, STATUS_ARCHIVED)

# --------------------------------------------------------------------------
# Muster
# --------------------------------------------------------------------------
# Eintrags-Ueberschrift: entweder "## D-...", oder die ID direkt am Zeilenanfang.
# Bewusst NICHT erfasst: Schnellindex-Zeilen ("- D-... — …") und Fliesstext-
# Referenzen — die beginnen nie in Spalte 0 mit der reinen ID.
_ID = r"D-\d{8}-\d{2,4}(?:-[A-Za-z0-9]+)*"
# Hinter der ID MUSS ein echter Trenner stehen: Zeilenende, Whitespace, Gedanken-
# strich, Bindestrich oder Pipe. Ohne diesen Lookahead las der Parser jede
# umgebrochene Fliesstextzeile, die zufaellig mit einer D-ID beginnt, als
# Ueberschrift -- belegt an TO-DECIDE-USER.txt mit `D-20260913-001) bleiben drei
# Paare ...` und `D-20260912-001) \u2014 und die gehoert nicht ...`, beides das Ende
# einer Klammer `(... D-...)` am Zeilenumbruch. Folge waren zwei Geistereintraege
# mit bereits vergebener ID, also gemeldete ID-Kollisionen ohne echten Anlass
# (T-20260913-445082817).
ENTRY_RE = re.compile(
    rf"^(?:(?P<hashes>#{{1,4}})\s+)?(?P<id>{_ID})(?=$|[\s\u2014\u2013|-])\s*"
    rf"(?:[\u2014\u2013]|--|-)?\s*(?P<title>.*?)\s*$"
)
LEGACY_ID_RE = re.compile(rf"^ID\s*:\s*(?P<id>{_ID})\s*$", re.I)
LEGACY_TITLE_RE = re.compile(r"^TITEL\s*:\s*(?P<title>.*?)\s*$", re.I)
ID_ONLY_RE = re.compile(rf"^{_ID}$")
ID_TOKEN_RE = re.compile(rf"\b({_ID})\b")

# Feldzeilen. Gross-/Kleinschreibung variiert zwischen den Kettenteilen.
FIELD_PATTERNS: dict[str, re.Pattern[str]] = {
    "status": re.compile(r"^STATUS\s*:\s*(.*)$", re.I),
    "quelle": re.compile(r"^QUELLE\s*:\s*(.*)$", re.I),
    # Qualifier vor dem Doppelpunkt sind erlaubt -- "FRAGE 1 (`OC-2026-09-13-B`):"
    # oder "FRAGE (`A7-2026-09-13-A`):". Dieselbe Toleranz hat "ENTSCHEIDUNG DES
    # USERS" (Varianten wie "... E02:") seit jeher; beim FRAGE-Feld fehlte sie, und
    # zwei reale Vorlagen galten deshalb als unvollstaendig, obwohl ihre Frage
    # dastand (T-20260913-686066300). `\b` schuetzt vor "FRAGEN AUS ...:".
    "frage": re.compile(r"^FRAGE\b[^:]*:\s*(.*)$", re.I),
    "optionen": re.compile(r"^OPTIONEN\s*:\s*(.*)$", re.I),
    "empfehlung": re.compile(r"^EMPFEHLUNG\s*:\s*(.*)$", re.I),
    "scope": re.compile(r"^SCOPE\s*:\s*(.*)$", re.I),
    # "ENTSCHEIDUNG DES USERS:" und Varianten wie "ENTSCHEIDUNG DES USERS E02:"
    "entscheidung": re.compile(r"^ENTSCHEIDUNG\s+DES\s+USERS\b[^:]*:\s*(.*)$", re.I),
}
# Weitere Zeilenkoepfe, die einen Mehrzeilen-Wert beenden, ohne selbst
# ausgewertet zu werden (sonst schluckt ein Feld den halben Eintrag).
TERMINATOR_RE = re.compile(
    r"^(FAKTEN|KONTEXT|KONFLIKT|NACHZUG|MIGRATION|MIGRATIONSBELEG|UMSETZUNG"
    r"|UMSETZUNGSSTATUS|UMSETZUNGSHINWEIS|UMSETZUNGSGATE|VERBINDLICHE[^:]*"
    r"|HINWEIS|KORREKTUR|BETROFFEN|VORFALL|ALS ENTSCHIEDEN BELEGT|OFFEN"
    r"|OPTION\s+[A-Z]|KANONISCHE ID|ZUSATZABGRENZUNG|VERIFIZIERTER STAND"
    r"|EMPFEHLUNG|QUELLE|STATUS|FRAGE|OPTIONEN|SCOPE)\s*[:\u2014-]",
    re.I,
)
SEPARATOR_RE = re.compile(r"^\s*(-{3,}|={3,}|_{3,})\s*$")
POINTER_RE = re.compile(r"^Pointer\s*/", re.I)

# Banner-Ueberschrift eines Blocks, der ein Entscheidungsmerkmal traegt, aber
# keine D-ID hat ("ENTSCHEIDUNG: <Titel>" statt "## D-... — <Titel>"). Bewusst
# ausgenommen: die Feldzeile "ENTSCHEIDUNG DES USERS: ...".
BANNER_TITLE_RE = re.compile(r"^ENTSCHEIDUNG\s*:\s*(?!DES\s+USERS\b)(?P<title>.+)$", re.I)

# Platzhalter im Entscheidungsfeld = noch keine Entscheidung.
_PLACEHOLDER_EXACT = {"", "OFFEN", "N/A", "-", "TBD", "HIER EINTRAGEN"}
_PLACEHOLDER_HIER_RE = re.compile(r"^HIER\b.*EINTRAGEN$", re.I)
_PLACEHOLDER_CHOICE_RE = re.compile(r"^[A-D](?:\s*[/|]\s*[A-D])+$", re.I)

HOST_FILE_RE = re.compile(r"^TO-DECIDE-USER-(?P<host>[A-Za-z0-9_-]+)\.txt$", re.I)
PART_FILE_RE = re.compile(r"^TO-DECIDE-USER(?:_(?P<part>\d+))?\.txt$", re.I)

MAX_EXCERPT = 400


# --------------------------------------------------------------------------
# Datenmodell
# --------------------------------------------------------------------------
@dataclass
class Entry:
    entry_id: str
    title: str
    source_path: Path
    source_line: int
    domain: str  # active | done | archive
    fields: dict[str, str] = field(default_factory=dict)
    key: str = ""
    collision_suffix: str | None = None

    # ------------------------------------------------------------------
    @property
    def date(self) -> str:
        digits = self.entry_id.split("-")[1]
        return f"{digits[0:4]}-{digits[4:6]}-{digits[6:8]}"

    @property
    def decision_raw(self) -> str:
        return self.fields.get("entscheidung", "")

    @property
    def has_decision(self) -> bool:
        return not is_placeholder(self.decision_raw)

    @property
    def is_alias(self) -> bool:
        blob = f"{self.fields.get('status', '')} {self.title}".upper()
        return "MIGRATIONSALIAS" in blob

    @property
    def alias_of(self) -> str | None:
        if not self.is_alias:
            return None
        match = re.search(rf"KANONISCH\w*\s+(?:ID\s*:?\s*)?in\s+({_ID})", self.raw_text, re.I)
        if match:
            return match.group(1)
        match = re.search(rf"KANONISCHE\s+ID\s*:\s*({_ID})", self.raw_text, re.I)
        return match.group(1) if match else None

    raw_text: str = ""

    # ------------------------------------------------------------------
    def status_class(self) -> str:
        if self.domain == "archive":
            return STATUS_ARCHIVED
        if self.domain == "done":
            return STATUS_DONE
        return STATUS_DECIDED_PENDING if self.has_decision else STATUS_OPEN

    @property
    def decision_ready(self) -> bool:
        """Nur vollstaendige, unbeantwortete Eintraege im Aktivdokument."""
        return (
            self.domain == "active"
            and not self.has_decision
            and not self.is_alias
            and bool(self.fields.get("frage", "").strip())
            and bool(self.fields.get("optionen", "").strip())
            and "entscheidung" in self.fields
        )

    def scope(self) -> tuple[str, bool]:
        explicit = self.fields.get("scope", "").strip()
        if explicit:
            return normalise_scope(explicit), True
        host = HOST_FILE_RE.match(self.source_path.name)
        if host:
            return f"host:{host.group('host').upper()}", False
        return "global", False

    def chain_part(self) -> int | None:
        match = PART_FILE_RE.match(self.source_path.name)
        if not match:
            return None
        return int(match.group("part")) if match.group("part") else 1

    def as_dict(self, root: Path) -> dict:
        scope, scope_explicit = self.scope()
        return {
            "key": self.key,
            "id": self.entry_id,
            "collision_suffix": self.collision_suffix,
            "date": self.date,
            "title": self.title,
            "question": excerpt(self.fields.get("frage", "")),
            "status_class": self.status_class(),
            "status_raw": excerpt(self.fields.get("status", "")),
            "scope": scope,
            "scope_explicit": scope_explicit,
            "decision_field_raw": excerpt(self.decision_raw),
            "decision_ready": self.decision_ready,
            "options_excerpt": excerpt(self.fields.get("optionen", "")),
            "recommendation_excerpt": excerpt(self.fields.get("empfehlung", "")),
            "source_excerpt": excerpt(self.fields.get("quelle", ""), 200),
            "is_alias": self.is_alias,
            "alias_of": self.alias_of,
            "domain": self.domain,
            "source_file": relname(self.source_path, root),
            "source_path": str(self.source_path),
            "source_line": self.source_line,
            "chain_part": self.chain_part(),
        }


# --------------------------------------------------------------------------
# Hilfen
# --------------------------------------------------------------------------
def normalise_scope(value: str) -> str:
    """`SCOPE: host: ASUS-GEI` => `host:ASUS-GEI`; unbekanntes bleibt unveraendert."""
    text = " ".join(value.split()).rstrip(".")
    match = re.match(r"^(global|host|projekt|akteur)\s*:?\s*(.*)$", text, re.I)
    if not match:
        return text
    kind = match.group(1).lower()
    rest = match.group(2).strip()
    if kind == "global" or not rest:
        return kind
    return f"{kind}:{rest.upper() if kind == 'host' else rest}"


def is_placeholder(value: str) -> bool:
    text = " ".join(value.split()).strip()
    text = text.strip("[]").strip().rstrip(".")
    if text.upper() in _PLACEHOLDER_EXACT:
        return True
    if _PLACEHOLDER_HIER_RE.match(text):
        return True
    return bool(_PLACEHOLDER_CHOICE_RE.match(text))


def excerpt(value: str, limit: int = MAX_EXCERPT) -> str:
    text = " ".join(value.split())
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "\u2026"


def relname(path: Path, root: Path) -> str:
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return path.name


def read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8-sig")
    except UnicodeDecodeError:
        return path.read_text(encoding="utf-8", errors="replace")


# --------------------------------------------------------------------------
# Parser
# --------------------------------------------------------------------------
def match_heading(line: str) -> tuple[str, str] | None:
    """(id, titel) fuer eine Eintrags-Ueberschrift, sonst None."""
    if line[:1].isspace() or line.startswith("-") or line.startswith("*"):
        return None
    candidate = line.rstrip()
    if candidate.startswith("="):
        candidate = re.sub(r"^=+\s*|\s*=+$", "", candidate)
    match = ENTRY_RE.match(candidate)
    if not match:
        legacy = LEGACY_ID_RE.fullmatch(candidate)
        return (legacy.group("id"), "") if legacy else None
    if not match.group("hashes") and not candidate.startswith("D-"):
        return None
    title = (match.group("title") or "").strip()
    title = re.sub(r"^\|\s*", "", title)
    return match.group("id"), title


def parse_fields(body: list[str]) -> dict[str, str]:
    """Feldwerte eines Eintragsblocks; Mehrzeiler bis Leerzeile/naechster Kopf."""
    fields: dict[str, str] = {}
    current: str | None = None
    buffer: list[str] = []

    def flush() -> None:
        nonlocal current, buffer
        if current and current not in fields:
            fields[current] = "\n".join(buffer).strip()
        current, buffer = None, []

    for line in body:
        stripped = line.strip()
        if not stripped or SEPARATOR_RE.match(stripped) or POINTER_RE.match(stripped):
            flush()
            continue
        # Walrus statt zweimal matchen: der `if`-Zweig und der gelieferte Wert
        # sind jetzt derselbe Treffer. Vorher lief dieselbe Regex pro Kandidat
        # zweimal, und fuer einen Typpruefer war nicht sichtbar, dass der zweite
        # Aufruf nie None liefern kann (Pyright: reportOptionalMemberAccess).
        hit = next(
            ((name, found) for name, pat in FIELD_PATTERNS.items()
             if (found := pat.match(stripped)) is not None),
            None,
        )
        if hit:
            name, match = hit
            flush()
            current, buffer = name, [match.group(1).strip()]
            continue
        if current and TERMINATOR_RE.match(stripped):
            flush()
            continue
        if current:
            buffer.append(stripped)
    flush()

    # "OPTIONEN:" fehlt in Teil 3/4 — dort stehen "Option A: …"-Zeilen einzeln.
    if not fields.get("optionen"):
        options = [ln.strip() for ln in body
                   if re.match(r"^Option\s+[A-Z]\s*[:\u2014-]", ln.strip(), re.I)]
        if options:
            fields["optionen"] = " | ".join(options)
    return fields


def parse_file(path: Path, domain: str) -> list[Entry]:
    lines = read_text(path).splitlines()
    heads: list[tuple[int, str, str]] = []
    for number, line in enumerate(lines, start=1):
        hit = match_heading(line)
        if hit:
            heads.append((number, hit[0], hit[1]))

    entries: list[Entry] = []
    for index, (number, entry_id, title) in enumerate(heads):
        end = heads[index + 1][0] - 1 if index + 1 < len(heads) else len(lines)
        body = lines[number:end]
        raw = "\n".join(lines[number - 1:end])
        if not title:
            title = next(
                (hit.group("title").strip() for line in body
                 if (hit := LEGACY_TITLE_RE.match(line))),
                "",
            )
        entries.append(Entry(
            entry_id=entry_id,
            title=title or "(ohne Titel)",
            source_path=path,
            source_line=number,
            domain=domain,
            fields=parse_fields(body),
            raw_text=raw,
        ))
    return entries


def collect_sources(root: Path) -> list[tuple[Path, str]]:
    """Quellen in fester Reihenfolge: EIN Aktivdokument, DONE, Archiv."""
    sources: list[tuple[Path, str]] = []
    seen: set[Path] = set()

    def add(path: Path, domain: str) -> None:
        if path.is_file() and path not in seen:
            seen.add(path)
            sources.append((path, domain))

    add(root / ACTIVE_NAME, "active")
    add(root / DONE_NAME, "done")
    archive = root / ARCHIVE_DIR
    if archive.is_dir():
        for path in sorted(archive.iterdir()):
            if path.suffix.lower() in (".txt", ".md"):
                add(path, "archive")
    return sources


def ignored_active_candidates(root: Path) -> list[Path]:
    """Nichtkanonische TO-DECIDE-Dateien melden, aber nie aktiv einlesen.

    Die Dateien bleiben sichtbar, damit eine notwendige verlustfreie
    Reconciliation nicht durch stilles Ignorieren ersetzt wird.
    """
    return [
        path
        for path in sorted(root.iterdir())
        if path.is_file()
        and path.suffix.lower() == ".txt"
        and path.name.upper().startswith("TO-DECIDE-USER")
        and path.name != ACTIVE_NAME
    ]


def swallowed_decision_markers(entries: list[Entry], root: Path) -> list[str]:
    """Entscheidungs-Marker, die im Body eines aktiven Eintrags verschwunden sind.

    `parse_fields()` haelt pro Feld nur den ERSTEN Treffer (flush() ueberschreibt
    ein bereits gesetztes Feld nie). Eine ZWEITE "ENTSCHEIDUNG DES USERS:"-Zeile
    im selben Eintragskoerper bedeutet: ein eigener Block wurde nicht als eigene
    `## D-...`-Ueberschrift erkannt (z. B. ein `====`-Banner ohne D-ID) und ist
    dadurch stillschweigend im Vorgaenger-Eintrag verschwunden. Fail-loud statt
    stiller Vollstaendigkeitsbehauptung -- siehe `ignored_active_candidates`.
    """
    pattern = FIELD_PATTERNS["entscheidung"]
    findings: list[str] = []
    for entry in entries:
        if entry.domain != "active":
            continue
        body_lines = entry.raw_text.splitlines()[1:]  # Zeile 0 = Ueberschrift
        hits = [i for i, line in enumerate(body_lines) if pattern.match(line.strip())]
        for extra in hits[1:]:  # der erste Treffer gehoert dem Eintrag selbst
            line_no = entry.source_line + 1 + extra
            title = next(
                (m.group("title").strip() for back in range(extra - 1, -1, -1)
                 if (m := BANNER_TITLE_RE.match(body_lines[back].strip()))),
                None,
            )
            label = title or f"weiterer Entscheidungs-Marker im Block {entry.key or entry.entry_id}"
            findings.append(
                f"{relname(entry.source_path, root)}:{line_no} — {label} "
                "(kein D-ID, nicht als eigener Eintrag geparst)"
            )
    return findings


def reserved_archive_ids(root: Path) -> list[str]:
    """Alle im Archiv vorkommenden D-IDs konservativ reservieren.

    Das eigentliche Index-Payload bleibt kompakt und liest nur die bisherigen
    direkten Archivquellen. Fuer die globale ID-Vergabe werden aber auch
    verschachtelte Vollstaende, Hashmanifeste und Backups beruecksichtigt.
    Eine blosse Referenz reserviert eine ID lieber zu viel als zu wenig.
    """
    archive = root / ARCHIVE_DIR
    if not archive.is_dir():
        return []
    found: set[str] = set()
    for path in archive.rglob("*"):
        if path.is_file() and path.suffix.lower() in (".txt", ".md", ".json"):
            found.update(ID_TOKEN_RE.findall(read_text(path)))
    return sorted(found)


DECISION_MARKER_RE = re.compile(
    r"USER-ENTSCHEID(?:UNG)?\b|NUTZERENTSCHEID(?:UNG)?\b|\[U\s+\d{4}-\d{2}-\d{2}[,\]]"
)
CC_STATUS_LINE_RE = re.compile(r"^STATUS\s*:\s*(.*)$", re.I | re.M)


def cross_check_tickets(tickets_dir: Path) -> dict:
    """Kreuzprueft Tickets gegen die Entscheidungskette -- read-only.

    Ursache fuer T-20260906-186783185 (Sweep 2026-09-06): ~30 USER-Tickets
    ohne Registervorlage, 15 im Ticket getroffene Entscheidungen ungebucht.
    Meldet zwei Befundklassen:

      decision_marker_without_id: Ticket traegt einen woertlichen
        Entscheidungsmarker (USER-ENTSCHEIDUNG/NUTZERENTSCHEIDUNG/[U DATUM])
        im Text, zitiert aber keine D-ID -- die Entscheidung wurde
        vermutlich nie zentral gebucht.
      user_decision_without_id: Ticket-STATUS-Zeile nennt eine
        ".../decision"-Kategorie (wartet ausdruecklich auf eine
        Nutzerentscheidung), zitiert aber keine D-ID -- kein Hinweis, ob
        dafuer schon eine Vorlage in TO-DECIDE-USER.txt existiert.

    Liefert KEINE Bewertung, ob eine Zuordnung fachlich zutrifft -- das
    verlangt die Themen-Gegenprobe aus T-20260906-186783185 Aufgabe 1
    (Datum/Titelstichworte/Briefing-Runden-IDs pruefen); dieses Werkzeug
    ersetzt sie nicht, es macht nur sichtbar, wo ueberhaupt geprueft werden
    muss. Schreibt nichts in den Ticketbestand.
    """
    findings: dict[str, list[str]] = {
        "decision_marker_without_id": [],
        "user_decision_without_id": [],
    }
    if not tickets_dir.is_dir():
        return findings
    skip_dirs = {"_logs", "_templates", "__pycache__"}
    for path in sorted(tickets_dir.rglob("*.txt")):
        if skip_dirs & set(path.relative_to(tickets_dir).parts[:-1]):
            continue
        text = read_text(path)
        if not text:
            continue
        if ID_TOKEN_RE.search(text):
            continue  # zitiert bereits mindestens eine D-ID
        rel = str(path.relative_to(tickets_dir)).replace("\\", "/")
        if DECISION_MARKER_RE.search(text):
            findings["decision_marker_without_id"].append(rel)
        status_match = CC_STATUS_LINE_RE.search(text)
        if status_match and "/decision" in status_match.group(1).lower():
            findings["user_decision_without_id"].append(rel)
    return findings


def _content_fingerprint(entry: Entry) -> str:
    """Normalisierter Titel eines Eintrags -- Inhaltsmerkmal fuer `history_collisions`.

    Bewusst NUR der Titel: Er ist das einzige Feld, das ein Block auf seinem
    ganzen Weg behaelt (Vorlage -> DONE -> Archivschnitt). `FRAGE` faellt beim
    Buchen durch den decision-clicker weg (der DONE-Block traegt stattdessen
    ENTSCHEIDUNG/ORIGINALBLOCK-BASE64), ein Titel+Frage-Hash wuerde deshalb
    genau den legitimen Umzug als Kollision melden, den er ausnehmen soll.
    `FRAGE` wird nur noch als Feinunterscheidung benutzt, wenn BEIDE Eintraege
    eine haben (siehe `history_collisions`).
    """
    text = re.sub(r"[`\"'*_]", "", entry.title).casefold()
    return re.sub(r"\s+", " ", text).strip()


def history_collisions(entries: list[Entry]) -> list[dict]:
    """Dieselbe ID mit VERSCHIEDENEM Inhalt -- ueber alle Quellen hinweg.

    Die Luecke, die das schliesst (T-20260913-772954756): `assign_keys()` prueft
    Kollisionen nur innerhalb der aktiven Kette, weil dieselbe ID in DONE/Archiv
    normalerweise derselbe Block in einem spaeteren Zustand ist. Tragen aber ZWEI
    VERSCHIEDENE Entscheidungen dieselbe ID, faellt das nirgends auf -- genau so
    entstanden am 2026-09-06 die 15 Doppel D-20260906-001..015 (zwei Hosts
    schrieben unabhaengig in dieselbe Nummernreihe, der Vertragscheck meldete
    "0 Kollisionen").

    Geprueft wird ueber denselben Bestand, den `decision_clicker.chain.known_ids()`
    fuer die ID-Vergabe kennt: aktive Kette + DECIDED-AND-DONE + Archiv. Die
    zusaetzlich dort beruecksichtigten `reserved_ids` sind blosse ID-Tokens aus
    Archivdateien ohne geparsten Inhalt -- sie koennen an einem Inhaltsvergleich
    nicht teilnehmen und bleiben aussen vor.

    Kollision = gleiche ID, mindestens zwei verschiedene Titel-Fingerprints
    UNTER DEN LEBENDEN QUELLEN (`active` + `done`). Haben zwei Eintraege denselben
    Titel, aber BEIDE ein `FRAGE`-Feld mit unterschiedlichem Text, zaehlt das
    ebenfalls; ein fehlendes `FRAGE` loest nie aus (siehe `_content_fingerprint`).

    Warum `archive` mitgelesen, aber nicht ausloesend ist: Ein Archivschnitt ist
    per Konstruktion eine KOPIE eines Kettenzustands, und die Archivare
    formulieren Titel dabei um -- die projekteigene saubere Testfixture enthaelt
    genau so einen Fall ("Offenes Beispiel" -> "Historischer Snapshot des
    aktiven Beispiels", dieselbe Entscheidung D-20260101-002). Ein Archivtreffer
    allein waere deshalb Rauschen. Archiv-Fundstellen erscheinen weiterhin in
    `occurrences`, damit die Meldung den vollstaendigen Fundort-Satz zeigt.

    Meldet nur, repariert nichts: Das Ergebnis geht bewusst NICHT in
    `active_contract.errors` und laesst den Exitcode unveraendert. Sonst wuerde
    ein historischer Befund den Aktivvertrag auf UNGUELTIG kippen und damit den
    Buchungsweg des decision-clicker fail-closed sperren, der genau darauf gated.
    """
    buckets: dict[str, list[Entry]] = {}
    for entry in entries:
        buckets.setdefault(entry.entry_id, []).append(entry)

    findings: list[dict] = []
    for entry_id, group in sorted(buckets.items()):
        lebend = [e for e in group if e.domain in ("active", "done")]
        if len(lebend) < 2:
            continue
        variants: dict[tuple[str, str], list[Entry]] = {}
        for entry in lebend:
            variants.setdefault((_content_fingerprint(entry), ""), []).append(entry)
        if len(variants) == 1:
            # Gleicher Titel -- nur dann weiter aufteilen, wenn BEIDE Seiten
            # eine FRAGE haben und die sich unterscheidet.
            fragen = {e.fields.get("frage", "").strip() for e in lebend}
            fragen.discard("")
            if len(fragen) < 2 or any(not e.fields.get("frage", "").strip() for e in lebend):
                continue
            variants = {}
            for entry in lebend:
                variants.setdefault(
                    (_content_fingerprint(entry), entry.fields["frage"].strip()), []
                ).append(entry)
            if len(variants) < 2:
                continue
        findings.append({
            "id": entry_id,
            "variants": len(variants),
            "occurrences": [{
                "title": e.title,
                "domain": e.domain,
                "source_file": e.source_path.name,
                "line": e.source_line,
            } for e in sorted(group, key=lambda e: (e.source_path.name, e.source_line))],
        })
    return findings


def assign_keys(entries: list[Entry]) -> list[dict]:
    """Eindeutige `key`s vergeben und ID-Kollisionen der AKTIVEN Kette melden.

    Kollision = dieselbe ID mehrfach INNERHALB der aktiven Kette. Nur dort ist
    eine Referenz SOFORT mehrdeutig. Der breitere Fall -- dieselbe ID mit
    verschiedenem Inhalt in DONE/Archiv -- wird getrennt von
    `history_collisions()` gemeldet.

    Schluesselvergabe:
    * aktiv, eindeutig   -> `D-...`
    * aktiv, kollidiert  -> `D-...#a`, `#b`, …
    * Archiv/DONE        -> `D-...@<datei>` (nimmt der aktiven Kette nie ein
      Suffix weg und bleibt trotzdem global eindeutig)
    """
    active_buckets: dict[str, list[Entry]] = {}
    for entry in entries:
        if entry.domain == "active":
            active_buckets.setdefault(entry.entry_id, []).append(entry)

    collisions: list[dict] = []
    for entry_id, group in sorted(active_buckets.items()):
        if len(group) == 1:
            group[0].key = entry_id
            continue
        for offset, entry in enumerate(group):
            entry.collision_suffix = f"#{chr(ord('a') + offset)}"
            entry.key = f"{entry_id}{entry.collision_suffix}"
        collisions.append({
            "id": entry_id,
            "count": len(group),
            "occurrences": [{
                "key": e.key,
                "title": e.title,
                "source_file": e.source_path.name,
                "line": e.source_line,
            } for e in group],
        })

    used = {e.key for e in entries if e.key}
    for entry in entries:
        if entry.key:
            continue
        base = f"{entry.entry_id}@{entry.source_path.stem}"
        key, offset = base, 1
        while key in used:
            offset += 1
            key = f"{base}~{offset}"
        entry.key, used = key, used | {key}
    return collisions


# --------------------------------------------------------------------------
# Ausgabe
# --------------------------------------------------------------------------
def build_index(root: Path) -> dict:
    entries: list[Entry] = []
    files: list[dict] = []
    for path, domain in collect_sources(root):
        parsed = parse_file(path, domain)
        entries.extend(parsed)
        files.append({"file": relname(path, root), "domain": domain, "entries": len(parsed)})

    collisions = assign_keys(entries)
    history = history_collisions(entries)
    payload = [entry.as_dict(root) for entry in entries]

    by_status: dict[str, int] = {name: 0 for name in STATUS_CLASSES}
    by_scope: dict[str, int] = {}
    for item in payload:
        by_status[item["status_class"]] = by_status.get(item["status_class"], 0) + 1
        by_scope[item["scope"]] = by_scope.get(item["scope"], 0) + 1

    active_ids = {e.entry_id for e in entries if e.domain == "active"}
    archived_ids = {e.entry_id for e in entries if e.domain != "active"}
    reserved_ids = reserved_archive_ids(root)

    ignored = ignored_active_candidates(root)
    swallowed = swallowed_decision_markers(entries, root)
    active_entries = [item for item in payload if item["domain"] == "active"]
    contract_errors: list[str] = []
    if not (root / ACTIVE_NAME).is_file():
        contract_errors.append(f"Kanonisches Aktivdokument fehlt: {ACTIVE_NAME}")
    if ignored:
        contract_errors.append(
            "Nichtkanonische TO-DECIDE-Dateien im Wurzelordner: "
            + ", ".join(path.name for path in ignored)
        )
    if swallowed:
        contract_errors.append(
            "Nicht geparste Entscheidungs-Marker im Aktivdokument: " + "; ".join(swallowed)
        )
    if collisions:
        contract_errors.append(
            "ID-Kollisionen im Aktivdokument: "
            + ", ".join(item["id"] for item in collisions)
        )
    for item in active_entries:
        if not item["decision_ready"]:
            contract_errors.append(
                f"Nicht entscheidungsreifer Aktiveintrag: {item['id']} "
                f"({item['source_file']}:{item['source_line']})"
            )
    return {
        "schema": SCHEMA,
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "generator": GENERATOR,
        "root": str(root),
        "files": files,
        "ignored_active_candidates": [relname(path, root) for path in ignored] + swallowed,
        "active_contract": {
            "canonical_file": ACTIVE_NAME,
            "valid": not contract_errors,
            "errors": contract_errors,
        },
        "reserved_ids": reserved_ids,
        "counts": {
            "total": len(payload),
            "active_chain": sum(1 for e in entries if e.domain == "active"),
            "by_status_class": by_status,
            "by_scope": dict(sorted(by_scope.items())),
            "id_collisions": len(collisions),
            "history_id_collisions": len(history),
            "ids_in_active_and_history": len(active_ids & (archived_ids | set(reserved_ids))),
            "reserved_archive_ids": len(reserved_ids),
            "ignored_active_candidates": len(ignored) + len(swallowed),
            "active_decision_ready": sum(1 for item in active_entries if item["decision_ready"]),
            "active_contract_errors": len(contract_errors),
        },
        "collisions": collisions,
        "history_collisions": history,
        "entries": payload,
    }


def render_report(index: dict) -> str:
    counts = index["counts"]
    entries = index["entries"]
    open_entries = [e for e in entries if e.get("decision_ready")]
    pending = [e for e in entries if e["status_class"] == STATUS_DECIDED_PENDING]

    lines = [
        "# INDEX-REPORT — Entscheidungskette",
        "",
        "> Auto-generiert von `decisions_index.py` — **nicht von Hand pflegen**.",
        "> Aktiv ist ausschliesslich `TO-DECIDE-USER.txt`; beantwortete Punkte",
        "> stehen nur noch in `DECIDED-AND-DONE.md` oder im reversiblen Archiv.",
        "",
        f"Stand: {index['generated_at']} · Generator: {index['generator']}",
        "",
        "## Zaehlung",
        "",
        "| Klasse | Anzahl |",
        "|---|---|",
        f"| {STATUS_OPEN} (echt offen) | {counts['by_status_class'][STATUS_OPEN]} |",
        f"| {STATUS_DECIDED_PENDING} | {counts['by_status_class'][STATUS_DECIDED_PENDING]} |",
        f"| {STATUS_DONE} | {counts['by_status_class'][STATUS_DONE]} |",
        f"| {STATUS_ARCHIVED} | {counts['by_status_class'][STATUS_ARCHIVED]} |",
        f"| **gesamt** | **{counts['total']}** |",
        "",
        f"Aktives Dokument: {counts['active_chain']} entscheidungsreife Eintraege · "
        f"ID-Kollisionen (aktive Kette): {counts['id_collisions']}",
        "",
        "## Aktivvertrag",
        "",
        ("**GÜLTIG** — genau ein aktives Dokument, nur unbeantwortete und "
         "entscheidungsreife Einträge."
         if index["active_contract"]["valid"] else "**UNGÜLTIG**"),
        "",
    ]
    if not index["active_contract"]["valid"]:
        lines.extend(f"- {error}" for error in index["active_contract"]["errors"])
        lines.append("")
    lines += [
        "## ID-Kollisionen über alle Quellen (Historie)",
        "",
        "> Dieselbe D-ID trägt verschiedene Entscheidungen. Meldung ohne Reparatur —",
        "> IDs werden nach Aktivvertrag Punkt 5 nie umnummeriert; die Auflösung ist",
        "> ein Nutzerentscheid.",
        "",
    ]
    history = index.get("history_collisions", [])
    if history:
        for item in history:
            lines.append(f"- **`{item['id']}`** — {item['variants']} verschiedene Inhalte:")
            lines.extend(
                f"  - {occ['domain']} · `{occ['source_file']}`:{occ['line']} — {occ['title']}"
                for occ in item["occurrences"]
            )
    else:
        lines.append("_Keine._")
    lines += [
        "",
        "## Nichtkanonische Aktivkandidaten",
        "",
    ]
    ignored = index.get("ignored_active_candidates", [])
    if ignored:
        lines.append(
            "Diese Dateien verletzen den Ein-Dokument-Vertrag und wurden deshalb "
            "**nicht** als aktiv eingelesen:"
        )
        lines.append("")
        lines.extend(f"- `{name}`" for name in ignored)
    else:
        lines.append("_Keine._")
    lines += [
        "",
        "## Echt offen — hier fehlt eine Nutzerentscheidung",
        "",
    ]
    if not open_entries:
        lines.append("_Keine._")
    for item in open_entries:
        lines += [
            f"### {item['key']} — {item['title']}",
            "",
            f"- Quelle: `{item['source_file']}`, Zeile {item['source_line']} · "
            f"Scope: `{item['scope']}`"
            f"{'' if item['scope_explicit'] else ' (implizit)'}",
            f"- Entscheidungsfeld: `{item['decision_field_raw'] or '(kein Feld im Eintrag)'}`",
        ]
        if item["status_raw"]:
            lines.append(f"- STATUS laut Eintrag: {item['status_raw']}")
        if item["question"]:
            lines.append(f"- Frage: {item['question']}")
        if item["options_excerpt"]:
            lines.append(f"- Optionen: {item['options_excerpt']}")
        if item["recommendation_excerpt"]:
            lines.append(f"- Empfehlung: {item['recommendation_excerpt']}")
        lines.append("")

    lines += ["## Historisch entschieden, Umsetzung offen", ""]
    if not pending:
        lines.append("_Keine._")
    for item in pending:
        lines.append(
            f"- **{item['key']}** — {item['title']} "
            f"(`{item['source_file']}`:{item['source_line']}"
            f"{', ALIAS -> ' + item['alias_of'] if item['alias_of'] else ''})"
        )
    lines.append("")

    lines += [
        "## ID-Kollisionen (gemeldet, NICHT umnummeriert)",
        "",
        "IDs koennen extern referenziert sein — eine Umnummerierung durch ein",
        "Werkzeug waere ein stiller Bruch. Die Eintraege bleiben ueber den",
        "`key` (`<ID>#a`, `#b`) eindeutig adressierbar.",
        "",
    ]
    if not index["collisions"]:
        lines.append("_Keine._")
    for item in index["collisions"]:
        lines.append(f"- **{item['id']}** ({item['count']}x):")
        for occurrence in item["occurrences"]:
            lines.append(
                f"  - `{occurrence['key']}` — {occurrence['title']} "
                f"(`{occurrence['source_file']}`:{occurrence['line']})"
            )
    lines += ["", "## Quelldateien", "", "| Datei | Bereich | Eintraege |", "|---|---|---|"]
    for item in index["files"]:
        lines.append(f"| `{item['file']}` | {item['domain']} | {item['entries']} |")
    lines.append("")
    return "\n".join(lines)


# --------------------------------------------------------------------------
def main(argv: list[str] | None = None) -> int:
    # `__doc__` ist unter `python -OO` None -- dann waere der Argparse-Aufbau
    # ein AttributeError, bevor irgendetwas geprueft wird.
    parser = argparse.ArgumentParser(
        description=(__doc__ or "decisions index").splitlines()[0])
    parser.add_argument("--root", type=Path, default=DEFAULT_ROOT,
                        help="Ordner der Entscheidungskette (_DECISIONS)")
    parser.add_argument("--out-dir", type=Path, default=None,
                        help="Ausgabeordner (Default: _tools neben der Kette)")
    parser.add_argument("--json-only", action="store_true", help="kein INDEX-REPORT.md")
    parser.add_argument("--print", dest="do_print", action="store_true",
                        help="Report zusaetzlich auf stdout")
    parser.add_argument("--cross-check", type=Path, default=None,
                        help="Read-only: Tickets in diesem Ordner gegen D-ID-"
                             "Zitate pruefen (siehe T-20260906-186783185)")
    args = parser.parse_args(argv)

    root: Path = args.root.expanduser()
    if not root.is_dir():
        print(f"FEHLER: Kettenordner nicht gefunden: {root}", file=sys.stderr)
        return 2

    out_dir: Path = (args.out_dir or Path(__file__).resolve().parent).expanduser()
    out_dir.mkdir(parents=True, exist_ok=True)

    index = build_index(root)
    (out_dir / "decisions.index.json").write_text(
        json.dumps(index, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    report = render_report(index)
    if not args.json_only:
        (out_dir / "INDEX-REPORT.md").write_text(report, encoding="utf-8")
    if args.do_print:
        print(report)

    counts = index["counts"]
    print(f"{counts['total']} Eintraege ({counts['active_chain']} aktiv) -> {out_dir}")
    print(f"  offen: {counts['by_status_class'][STATUS_OPEN]} · "
          f"entschieden/Umsetzung offen: {counts['by_status_class'][STATUS_DECIDED_PENDING]} · "
          f"done: {counts['by_status_class'][STATUS_DONE]} · "
          f"archiviert: {counts['by_status_class'][STATUS_ARCHIVED]}")
    print(f"  ID-Kollisionen in der aktiven Kette: {counts['id_collisions']}")
    print(f"  ID-Kollisionen ueber alle Quellen (Historie): "
          f"{counts['history_id_collisions']}")
    for item in index["history_collisions"]:
        orte = " | ".join(
            f"{occ['source_file']}:{occ['line']} ({occ['domain']}) {occ['title'][:46]}"
            for occ in item["occurrences"]
        )
        print(f"    - {item['id']}: {orte}")
    print(f"  Aktivvertrag: {'gueltig' if index['active_contract']['valid'] else 'UNGUELTIG'}")

    if args.cross_check:
        cc_dir = args.cross_check.expanduser()
        cc = cross_check_tickets(cc_dir)
        n_a = len(cc["decision_marker_without_id"])
        n_b = len(cc["user_decision_without_id"])
        print(f"\nKreuzpruefung Tickets <-> D-IDs ({cc_dir}):")
        print(f"  Entscheidungsmarker im Ticket ohne D-ID-Zitat: {n_a}")
        for rel in cc["decision_marker_without_id"]:
            print(f"    - {rel}")
        print(f"  STATUS .../decision ohne D-ID-Zitat: {n_b}")
        for rel in cc["user_decision_without_id"]:
            print(f"    - {rel}")
        (out_dir / "CROSS-CHECK-REPORT.json").write_text(
            json.dumps(cc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    return 0 if index["active_contract"]["valid"] else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
