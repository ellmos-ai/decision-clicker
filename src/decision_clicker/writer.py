# SPDX-License-Identifier: MIT
"""Konservatives Schreiben in die Entscheidungskette.

Leitsatz: Es wird genau das Entscheidungsfeld gefuellt und genau eine
Datumszeile ergaenzt. Kein Umformatieren, kein Neuschreiben, keine
Zeilenenden-Normalisierung, keine Encoding-Umstellung. Alles andere in der
Datei bleibt Byte fuer Byte, wie es war — die Testsuite belegt das.

Warum die Datumszeile hinter einer Leerzeile steht: Der Kettenparser sammelt
Feldwerte mehrzeilig bis zur naechsten Leerzeile. Ohne die Leerzeile wuerde
das Datum in den Entscheidungswert gezogen und im Index-Report als Teil der
Entscheidung erscheinen. Mit ihr bleibt der Index sauber.
"""
from __future__ import annotations

import re
import shutil
from datetime import datetime
from pathlib import Path

from .chain import ChainError, _load_index_tool
from .config import Settings

DECISION_FIELD_RE = re.compile(r"^(\s*ENTSCHEIDUNG\s+DES\s+USERS\b[^:]*:)(.*)$", re.I)
DECIDED_AT_RE = re.compile(r"^\s*ENTSCHIEDEN\s+AM\s*:", re.I)
POINTER_RE = re.compile(r"^\s*Pointer\s*/", re.I)
SEPARATOR_RE = re.compile(r"^\s*-{3,}\s*$")

TOOL_TAG = "decision-clicker"


class WriteError(RuntimeError):
    """Der Schreibvorgang wurde abgebrochen — die Datei ist unveraendert."""


# ---------------------------------------------------------------------------
# Datei-Grundlagen
# ---------------------------------------------------------------------------
def _read(path: Path) -> tuple[str, bool]:
    raw = path.read_bytes()
    has_bom = raw.startswith(b"\xef\xbb\xbf")
    return raw.decode("utf-8-sig"), has_bom


def _write(path: Path, text: str, has_bom: bool) -> None:
    data = text.encode("utf-8")
    if has_bom:
        data = b"\xef\xbb\xbf" + data
    path.write_bytes(data)


def _newline_of(lines: list[str], fallback: str = "\r\n") -> str:
    """Zeilenende aus dem Bestand uebernehmen statt eines zu erfinden."""
    for line in lines:
        if line.endswith("\r\n"):
            return "\r\n"
        if line.endswith("\n"):
            return "\n"
    return fallback


def backup(path: Path, settings: Settings, tag: str = "") -> Path:
    """Sicherung der Zieldatei VOR jeder Aenderung."""
    settings.backup_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    suffix = f"_{tag}" if tag else ""
    target = settings.backup_dir / f"{path.stem}{suffix}_{stamp}{path.suffix}"
    counter = 1
    while target.exists():
        counter += 1
        target = settings.backup_dir / f"{path.stem}{suffix}_{stamp}~{counter}{path.suffix}"
    shutil.copy2(path, target)
    return target


# ---------------------------------------------------------------------------
# Eintragsgrenzen
# ---------------------------------------------------------------------------
def entry_bounds(settings: Settings, lines: list[str], start_line: int) -> tuple[int, int]:
    """[start, end) des Eintragsblocks; `start_line` ist 1-basiert."""
    match_heading = _load_index_tool(settings.index_script).match_heading
    start = start_line - 1
    if start < 0 or start >= len(lines):
        raise WriteError(f"Zeile {start_line} liegt ausserhalb der Datei")
    for index in range(start + 1, len(lines)):
        if match_heading(lines[index].rstrip("\r\n")):
            return start, index
    return start, len(lines)


def render_decision(choice: str, note: str = "") -> str:
    """Wert des Entscheidungsfeldes in der Schreibweise der Kette."""
    choice = " ".join(choice.split())
    note = " ".join(note.split())
    if not choice:
        raise WriteError("Leere Entscheidung wird nicht geschrieben")
    inner = f"{choice} — {note}" if note else choice
    return f"[{inner}]"


# ---------------------------------------------------------------------------
# Kernoperation
# ---------------------------------------------------------------------------
def fill_decision(
    settings: Settings,
    path: Path,
    start_line: int,
    choice: str,
    note: str = "",
    *,
    expected_id: str | None = None,
    on: str | None = None,
    make_backup: bool = True,
) -> dict:
    """Entscheidungsfeld eines Eintrags fuellen.

    Genau eine Zeile wird ersetzt; genau zwei Zeilen (leer + Datum) kommen
    dahinter. Ein bereits gefuelltes Feld wird nicht ueberschrieben.

    `expected_id` ist der Schutz gegen veraltete Zeilennummern: Ein Aufrufer,
    der aus einem zwischengespeicherten Index kommt, kann auf eine Zeile
    zeigen, an der inzwischen ein ANDERER Eintrag steht. Ohne diese Pruefung
    wuerde die Entscheidung dann in den falschen Eintrag geschrieben.
    """
    text, has_bom = _read(path)
    lines = text.splitlines(keepends=True)
    start, end = entry_bounds(settings, lines, start_line)

    if expected_id:
        kopf = lines[start].rstrip("\r\n")
        if expected_id not in kopf:
            raise WriteError(
                f"{path.name}:{start_line} traegt nicht mehr {expected_id} "
                f"(dort steht jetzt: {kopf[:70]!r}) — Ansicht ist veraltet, "
                "bitte neu laden."
            )
    newline = _newline_of(lines[start:end]) or _newline_of(lines)

    field_index = None
    for index in range(start, end):
        if DECISION_FIELD_RE.match(lines[index].rstrip("\r\n")):
            field_index = index
            break
    if field_index is None:
        raise WriteError(
            f"Kein Feld 'ENTSCHEIDUNG DES USERS' im Eintrag ab Zeile {start_line} in {path.name}"
        )

    body = lines[field_index].rstrip("\r\n")
    ending = lines[field_index][len(body):] or newline
    match = DECISION_FIELD_RE.match(body)
    assert match is not None  # oben bereits geprueft
    label, current = match.group(1), match.group(2)

    tool = _load_index_tool(settings.index_script)
    if not tool.is_placeholder(current):
        raise WriteError(
            f"Eintrag ab Zeile {start_line} ist bereits entschieden: {current.strip()}"
        )

    stamp = on or datetime.now().strftime("%Y-%m-%d")
    backup_path = backup(path, settings, tag="decide") if make_backup else None

    lines[field_index] = f"{label} {render_decision(choice, note)}{ending}"
    insert_at = field_index + 1
    if not any(DECIDED_AT_RE.match(line) for line in lines[start:end]):
        lines[insert_at:insert_at] = [newline, f"ENTSCHIEDEN AM: {stamp} ({TOOL_TAG}){newline}"]

    _write(path, "".join(lines), has_bom)
    return {
        "file": str(path),
        "line": field_index + 1,
        "value": render_decision(choice, note),
        "date": stamp,
        "backup": str(backup_path) if backup_path else None,
    }


# ---------------------------------------------------------------------------
# Neue Eintraege
# ---------------------------------------------------------------------------
OPTION_LINE_RE = re.compile(r"^\s*(?:[-•*]\s*)?(?i:Option\s+)?([A-Z])\s*[:—–-]\s*(.*)$")


def normalise_option(line: str) -> str:
    """Optionszeile in die Listenform der Kette bringen: `- A — Text`."""
    match = OPTION_LINE_RE.match(line.strip())
    if not match:
        return f"- {line.strip()}"
    return f"- {match.group(1).upper()} — {match.group(2).strip()}"


def render_entry(
    entry_id: str,
    title: str,
    *,
    status: str = "OFFEN",
    quelle: str = "",
    frage: str = "",
    optionen: list[str] | None = None,
    empfehlung: str = "",
    kontext: str = "",
    scope: str = "",
    newline: str = "\r\n",
) -> str:
    """Eintrag nach der Konvention des Kettenkopfes rendern."""
    rows: list[str] = [f"{entry_id} — {title}", "", f"STATUS: {status}"]
    if scope:
        rows.append(f"SCOPE: {scope}")
    if quelle:
        rows.append(f"QUELLE: {quelle}")
    if kontext:
        rows += ["", "KONTEXT:", *kontext.strip().splitlines()]
    if frage:
        rows += ["", f"FRAGE: {frage}"]
    if optionen:
        rows += ["", "OPTIONEN:"]
        rows += [normalise_option(option) for option in optionen]
    if empfehlung:
        rows += ["", f"EMPFEHLUNG: {empfehlung}"]
    rows += ["", "ENTSCHEIDUNG DES USERS: [HIER EINTRAGEN]", "", "---", ""]
    return newline.join(rows) + newline


def append_entry(
    settings: Settings,
    path: Path,
    rendered: str,
    *,
    make_backup: bool = True,
) -> dict:
    """Eintrag am Ende des Kettenteils anhaengen — vor einem Pointer-Block."""
    text, has_bom = _read(path)
    lines = text.splitlines(keepends=True)
    newline = _newline_of(lines)

    # Der Pointer-Block steht in manchen Teilen am Ende, in allen aber auch im
    # Kopf. Gesucht ist nur ein NACHFOLGER-Pointer, also einer hinter dem
    # letzten Eintrag — sonst landet der neue Eintrag vor der ganzen Kette.
    match_heading = _load_index_tool(settings.index_script).match_heading
    letzte_ueberschrift = -1
    for index, line in enumerate(lines):
        if match_heading(line.rstrip("\r\n")):
            letzte_ueberschrift = index

    insert_at = len(lines)
    for index in range(letzte_ueberschrift + 1, len(lines)):
        if POINTER_RE.match(lines[index]):
            insert_at = index
            while insert_at > 0 and SEPARATOR_RE.match(lines[insert_at - 1].rstrip("\r\n")):
                insert_at -= 1
            break

    backup_path = backup(path, settings, tag="new") if make_backup else None
    block = rendered.replace("\r\n", "\n").replace("\n", newline)
    prefix = "" if insert_at == 0 or lines[insert_at - 1].strip() == "" else newline
    lines.insert(insert_at, prefix + block)
    _write(path, "".join(lines), has_bom)
    return {
        "file": str(path),
        "line": insert_at + 1,
        "backup": str(backup_path) if backup_path else None,
    }


# ---------------------------------------------------------------------------
# Register
# ---------------------------------------------------------------------------
def append_done(
    settings: Settings,
    entry: dict,
    choice: str,
    note: str = "",
    *,
    on: str | None = None,
    make_backup: bool = True,
) -> dict:
    """Getroffene Entscheidung in `DECIDED-AND-DONE.md` protokollieren.

    Der Eintrag bleibt in der aktiven Kette stehen: Nach der Kettenregel wird
    er erst nach VERIFIZIERTER Umsetzung verschoben, und das verifiziert kein
    Klick. Hier entsteht nur der Beleg, dass die Entscheidung gefallen ist.
    """
    path = settings.done_file
    if not path.is_file():
        raise WriteError(f"{path} nicht gefunden")
    text, has_bom = _read(path)
    lines = text.splitlines(keepends=True)
    newline = _newline_of(lines)
    stamp = on or datetime.now().strftime("%Y-%m-%d")

    rows = [
        "",
        f"## {entry['id']} — {entry['title']}",
        "",
        f"ENTSCHIEDEN AM: {stamp} ({TOOL_TAG})",
        f"ENTSCHEIDUNG: {render_decision(choice, note)}",
        f"QUELLE IN DER KETTE: `{entry['source_file']}`, Zeile {entry['source_line']}",
        "UMSETZUNG: offen — der Eintrag bleibt bis zur verifizierten Umsetzung in der aktiven Kette.",
        "",
    ]
    backup_path = backup(path, settings, tag="done") if make_backup else None
    tail = "" if text.endswith(("\n", "\r")) else newline
    _write(path, text + tail + newline.join(rows) + newline, has_bom)
    return {"file": str(path), "backup": str(backup_path) if backup_path else None}


def append_done_block(settings: Settings, rows: list[str], *, make_backup: bool = True) -> dict:
    """Fertigen Textblock an `DECIDED-AND-DONE.md` anhängen."""
    path = settings.done_file
    if not path.is_file():
        raise WriteError(f"{path} nicht gefunden")
    text, has_bom = _read(path)
    newline = _newline_of(text.splitlines(keepends=True))
    backup_path = backup(path, settings, tag="intake") if make_backup else None
    tail = "" if text.endswith(("\n", "\r")) else newline
    _write(path, text + tail + newline.join(rows) + newline, has_bom)
    return {"file": str(path), "backup": str(backup_path) if backup_path else None}


def mark_taken_over(
    settings: Settings,
    path: Path,
    start: int,
    end: int,
    marker: str,
    *,
    make_backup: bool = True,
) -> dict:
    """Postfach-Eintrag als übernommen markieren — rein additiv.

    Der Vermerk wird ans Ende des Eintragsblocks gesetzt, vor abschliessenden
    Trennlinien und Leerzeilen. Es wird nichts geloescht und nichts
    umformatiert; Nachzuegler-Automationen duerfen weiter ans Dateiende
    schreiben.
    """
    text, has_bom = _read(path)
    lines = text.splitlines(keepends=True)
    if not 0 <= start < end <= len(lines):
        raise WriteError(f"Blockgrenzen {start}:{end} passen nicht zu {path.name}")
    newline = _newline_of(lines[start:end]) or _newline_of(lines)

    einfuegen = end
    while einfuegen > start + 1:
        vorher = lines[einfuegen - 1].rstrip("\r\n")
        if vorher.strip() == "" or SEPARATOR_RE.match(vorher) or re.fullmatch(r"={3,}", vorher.strip()):
            einfuegen -= 1
            continue
        break

    backup_path = backup(path, settings, tag="intake-mark") if make_backup else None
    lines[einfuegen:einfuegen] = [newline, f"{marker}{newline}"]
    _write(path, "".join(lines), has_bom)
    return {
        "file": str(path),
        "line": einfuegen + 2,
        "backup": str(backup_path) if backup_path else None,
    }


# ---------------------------------------------------------------------------
# Sperre
# ---------------------------------------------------------------------------
def write_lock(settings: Settings, purpose: str, hours: int = 24) -> Path:
    path = settings.lock_file
    now = datetime.now()
    path.write_text(
        "\n".join([
            "LOCK — decision-clicker",
            f"AGENT: OP-DECIDER (Claude Code, Opus 5)",
            f"ZWECK: {purpose}",
            f"ANGELEGT: {now.strftime('%Y-%m-%d %H:%M')}",
            f"VERFALL: {hours} h",
            "SCOPE: _DECISIONS (Kettendateien + DECIDED-AND-DONE.md)",
            "",
        ]),
        encoding="utf-8",
    )
    return path


def release_lock(settings: Settings) -> bool:
    if settings.lock_file.is_file():
        settings.lock_file.unlink()
        return True
    return False


def foreign_locks(settings: Settings) -> list[Path]:
    """Fremde Sperren im Kettenordner — Klicks werden dann verweigert."""
    return [
        path for path in settings.chain_dir.glob("LOCK*.txt")
        if path.name != settings.lock_file.name
    ]


__all__ = [
    "ChainError", "WriteError", "append_done", "append_entry", "backup",
    "entry_bounds", "fill_decision", "foreign_locks", "release_lock",
    "render_decision", "render_entry", "write_lock",
]
