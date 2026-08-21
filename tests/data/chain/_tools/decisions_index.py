#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""decisions_index.py — Index ueber die zentrale Entscheidungskette (_DECISIONS).

Liest die gesamte TO-DECIDE-Kette read-only und erzeugt zwei abgeleitete Artefakte:

  decisions.index.json   maschinenlesbar (Schema "decisions.index/1")
  INDEX-REPORT.md        kompakter Lesebericht, echt offene Eintraege zuerst

Verbindliche Eigenschaften:

* **Read-only gegenueber den Quellen.** Das Werkzeug schreibt ausschliesslich in
  sein Ausgabeverzeichnis (Default: dieser Ordner). Keine Quelldatei wird
  veraendert, keine ID umnummeriert.
* **Idempotent.** Gleicher Input => gleicher Output (bis auf `generated_at`).
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
import re
import sys
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

VERSION = "1.0.0"
SCHEMA = "decisions.index/1"
GENERATOR = f"decisions_index.py {VERSION}"

DEFAULT_ROOT = Path.cwd()

# Reihenfolge ist bedeutsam: die aktive Kette wird ZUERST gescannt, damit bei
# ID-Kollisionen die aktiven Eintraege die vorderen Suffixe (#a, #b) erhalten.
ACTIVE_GLOBS = ("TO-DECIDE-USER.txt", "TO-DECIDE-USER_*.txt", "TO-DECIDE-USER-*.txt")
DONE_NAME = "DECIDED-AND-DONE.md"
ARCHIVE_DIR = "_decision-archive"

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
ENTRY_RE = re.compile(
    rf"^(?:(?P<hashes>#{{1,4}})\s+)?(?P<id>{_ID})\s*"
    rf"(?:[\u2014\u2013]|--|-)?\s*(?P<title>.*?)\s*$"
)
ID_ONLY_RE = re.compile(rf"^{_ID}$")

# Feldzeilen. Gross-/Kleinschreibung variiert zwischen den Kettenteilen.
FIELD_PATTERNS: dict[str, re.Pattern[str]] = {
    "status": re.compile(r"^STATUS\s*:\s*(.*)$", re.I),
    "quelle": re.compile(r"^QUELLE\s*:\s*(.*)$", re.I),
    "frage": re.compile(r"^FRAGE\s*:\s*(.*)$", re.I),
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
    """`SCOPE: host: NODE-1` => `host:NODE-1`; unbekanntes bleibt unveraendert."""
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
    match = ENTRY_RE.match(line.rstrip())
    if not match:
        return None
    if not match.group("hashes") and not line.startswith("D-"):
        return None
    return match.group("id"), (match.group("title") or "").strip()


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
        hit = next(
            ((name, pat.match(stripped)) for name, pat in FIELD_PATTERNS.items()
             if pat.match(stripped)),
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
    """Quelldateien in fester Reihenfolge: aktive Kette, DONE, Archiv."""
    sources: list[tuple[Path, str]] = []
    seen: set[Path] = set()

    def add(path: Path, domain: str) -> None:
        if path.is_file() and path not in seen:
            seen.add(path)
            sources.append((path, domain))

    for pattern in ACTIVE_GLOBS:
        for path in sorted(root.glob(pattern)):
            add(path, "active")
    add(root / DONE_NAME, "done")
    archive = root / ARCHIVE_DIR
    if archive.is_dir():
        for path in sorted(archive.iterdir()):
            if path.suffix.lower() in (".txt", ".md"):
                add(path, "archive")
    return sources


def assign_keys(entries: list[Entry]) -> list[dict]:
    """Eindeutige `key`s vergeben und ID-Kollisionen der AKTIVEN Kette melden.

    Kollision = dieselbe ID mehrfach INNERHALB der aktiven Kette. Nur dort ist
    eine Referenz mehrdeutig; dieselbe ID zusaetzlich in Archiv/DONE zu finden
    ist der Normalfall (Snapshot derselben Entscheidung) und keine Kollision.

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
    payload = [entry.as_dict(root) for entry in entries]

    by_status: dict[str, int] = {name: 0 for name in STATUS_CLASSES}
    by_scope: dict[str, int] = {}
    for item in payload:
        by_status[item["status_class"]] = by_status.get(item["status_class"], 0) + 1
        by_scope[item["scope"]] = by_scope.get(item["scope"], 0) + 1

    active_ids = {e.entry_id for e in entries if e.domain == "active"}
    archived_ids = {e.entry_id for e in entries if e.domain != "active"}

    return {
        "schema": SCHEMA,
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "generator": GENERATOR,
        "root": str(root),
        "files": files,
        "counts": {
            "total": len(payload),
            "active_chain": sum(1 for e in entries if e.domain == "active"),
            "by_status_class": by_status,
            "by_scope": dict(sorted(by_scope.items())),
            "id_collisions": len(collisions),
            "ids_in_active_and_history": len(active_ids & archived_ids),
        },
        "collisions": collisions,
        "entries": payload,
    }


def render_report(index: dict) -> str:
    counts = index["counts"]
    entries = index["entries"]
    open_entries = [e for e in entries if e["status_class"] == STATUS_OPEN]
    pending = [e for e in entries if e["status_class"] == STATUS_DECIDED_PENDING]

    lines = [
        "# INDEX-REPORT — Entscheidungskette",
        "",
        "> Auto-generiert von `decisions_index.py` — **nicht von Hand pflegen**.",
        "> Kanonisch bleiben die `TO-DECIDE-USER*.txt` und `DECIDED-AND-DONE.md`.",
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
        f"Aktive Kette: {counts['active_chain']} Eintraege · "
        f"ID-Kollisionen (aktive Kette): {counts['id_collisions']}",
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

    lines += ["## Entschieden, Umsetzung offen", ""]
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
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--root", type=Path, default=DEFAULT_ROOT,
                        help="Ordner der Entscheidungskette (_DECISIONS)")
    parser.add_argument("--out-dir", type=Path, default=None,
                        help="Ausgabeordner (Default: _tools neben der Kette)")
    parser.add_argument("--json-only", action="store_true", help="kein INDEX-REPORT.md")
    parser.add_argument("--print", dest="do_print", action="store_true",
                        help="Report zusaetzlich auf stdout")
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
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
