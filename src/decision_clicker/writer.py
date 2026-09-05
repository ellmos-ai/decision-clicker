# SPDX-License-Identifier: MIT
"""Konservatives Schreiben im Ein-Dokument-Aktivvertrag.

Ein Klick sichert den offenen Originalblock, schreibt einen append-only Beleg
und entfernt den beantworteten Block aus der Aktivvorlage. Undo stellt nur
einen nachweislich vom Clicker gesicherten Originalblock wieder her. Die
kleinen Low-Level-Helfer für Feldänderungen bleiben für Regressionstests und
kontrollierte Migrationen verfügbar.
"""
from __future__ import annotations

import base64
import re
import shutil
import threading
from datetime import datetime
from pathlib import Path

from .chain import DONE_HEADING_RE, ChainError, _load_index_tool
from .config import Settings

DECISION_FIELD_RE = re.compile(r"^(\s*ENTSCHEIDUNG\s+DES\s+USERS\b[^:]*:)(.*)$", re.I)
DECIDED_AT_RE = re.compile(r"^\s*ENTSCHIEDEN\s+AM\s*:", re.I)
CLICKER_DECIDED_AT_RE = re.compile(r"^\s*ENTSCHIEDEN\s+AM\s*:.*\(decision-clicker\)\s*$", re.I)
POINTER_RE = re.compile(r"^\s*Pointer\s*/", re.I)
SEPARATOR_RE = re.compile(r"^\s*-{3,}\s*$")
ORIGINAL_BLOCK_RE = re.compile(r"^ORIGINALBLOCK-BASE64\s*:\s*([A-Za-z0-9+/=]+)\s*$", re.I)

TOOL_TAG = "decision-clicker"
PLACEHOLDER = "[HIER EINTRAGEN]"
MUTATION_LOCK = threading.RLock()

ENTRY_ID_RE = re.compile(r"^D-\d{8}-\d{2,4}(?:-[A-Za-z0-9]+)*$")
LINE_BREAK_RE = re.compile(r"[\r\n\v\f\x1c-\x1e\x85\u2028\u2029]")
CONTEXT_FINGERPRINT_RE = re.compile(r"^sha256:[0-9a-f]{64}$")


class WriteError(RuntimeError):
    """Der Schreibvorgang wurde abgebrochen — die Datei ist unveraendert."""


def single_line(value: str, field: str) -> str:
    """Ein skalares Kettenfeld validieren, bevor es Struktur werden kann."""
    if LINE_BREAK_RE.search(value):
        raise WriteError(f"{field} darf keinen Zeilenumbruch enthalten.")
    return value.strip()


def metadata_values(values: list[str] | None, field: str) -> str:
    """Optionale Metadatenliste als stabiles, rücklesbares Skalarfeld rendern."""
    return " | ".join(
        value for item in (values or []) if (value := single_line(item, field))
    )


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
        raise WriteError(f"Zeile {start_line} liegt außerhalb der Datei")
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
        heading = _load_index_tool(settings.index_script).match_heading(kopf)
        actual_id = heading[0] if heading else None
        if actual_id != expected_id:
            raise WriteError(
                f"{path.name}:{start_line} trägt nicht mehr {expected_id} "
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
# Rueckgaengig — die genaue Umkehrung von `fill_decision` + `append_done`
# ---------------------------------------------------------------------------
def revert_decision(
    settings: Settings,
    path: Path,
    start_line: int,
    *,
    expected_id: str | None = None,
    make_backup: bool = True,
) -> dict:
    """Entscheidungsfeld zurueck auf den Platzhalter — die Umkehrung von `fill_decision`.

    Entfernt genau die zwei Zeilen (Leerzeile + `ENTSCHIEDEN AM: ... (decision-clicker)`),
    die `fill_decision` eingefuegt hat, und setzt den Feldwert zurueck auf
    `[HIER EINTRAGEN]`. Alles andere im Eintrag bleibt Byte fuer Byte stehen —
    derselbe Leitsatz wie beim Schreiben.

    Lehnt ab, wenn der Eintrag nicht (mehr) entschieden ist, oder wenn die
    ENTSCHIEDEN-AM-Zeile nicht erkennbar von diesem Werkzeug stammt: eine
    von Hand oder einer Automation getroffene Entscheidung wird NIE
    zurueckgenommen, nur weil jemand die ID kennt.
    """
    text, has_bom = _read(path)
    lines = text.splitlines(keepends=True)
    start, end = entry_bounds(settings, lines, start_line)

    if expected_id:
        kopf = lines[start].rstrip("\r\n")
        heading = _load_index_tool(settings.index_script).match_heading(kopf)
        actual_id = heading[0] if heading else None
        if actual_id != expected_id:
            raise WriteError(
                f"{path.name}:{start_line} trägt nicht mehr {expected_id} "
                f"(dort steht jetzt: {kopf[:70]!r}) — Ansicht ist veraltet, "
                "bitte neu laden."
            )

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
    ending = lines[field_index][len(body):] or _newline_of(lines[start:end]) or _newline_of(lines)
    match = DECISION_FIELD_RE.match(body)
    assert match is not None  # oben bereits geprueft
    label, current = match.group(1), match.group(2)

    tool = _load_index_tool(settings.index_script)
    if tool.is_placeholder(current):
        raise WriteError(
            f"Eintrag ab Zeile {start_line} in {path.name} ist nicht entschieden "
            "— nichts zum Zurücknehmen."
        )

    zeile_1 = lines[field_index + 1].strip("\r\n") if field_index + 1 < end else "x"
    zeile_2 = lines[field_index + 2].rstrip("\r\n") if field_index + 2 < end else ""
    if zeile_1 != "" or not CLICKER_DECIDED_AT_RE.match(zeile_2):
        raise WriteError(
            f"{path.name}:{start_line} wurde nicht erkennbar von {TOOL_TAG} entschieden "
            "(keine passende ENTSCHIEDEN-AM-Zeile) — extern entschieden, nicht rückgängig machbar."
        )

    backup_path = backup(path, settings, tag="undo") if make_backup else None

    lines[field_index] = f"{label} {PLACEHOLDER}{ending}"
    del lines[field_index + 1:field_index + 3]

    _write(path, "".join(lines), has_bom)
    return {
        "file": str(path),
        "line": field_index + 1,
        "backup": str(backup_path) if backup_path else None,
    }


def remove_entry(
    settings: Settings,
    path: Path,
    start_line: int,
    *,
    expected_id: str,
    make_backup: bool = True,
) -> dict:
    """Einen exakt adressierten Eintragsblock aus dem Aktivdokument entfernen."""
    text, has_bom = _read(path)
    lines = text.splitlines(keepends=True)
    start, end = entry_bounds(settings, lines, start_line)
    heading = _load_index_tool(settings.index_script).match_heading(
        lines[start].rstrip("\r\n"))
    actual_id = heading[0] if heading else None
    if actual_id != expected_id:
        raise WriteError(
            f"{path.name}:{start_line} trägt nicht mehr {expected_id} "
            f"(gefunden: {actual_id or 'keine ID'}) — nichts entfernt."
        )
    backup_path = backup(path, settings, tag="remove") if make_backup else None
    del lines[start:end]
    _write(path, "".join(lines), has_bom)
    return {
        "file": str(path), "line": start_line,
        "backup": str(backup_path) if backup_path else None,
    }


def mark_decision_undone(
    settings: Settings,
    entry_id: str,
    reason: str,
    *,
    on: str | None = None,
    make_backup: bool = True,
) -> dict:
    """Append-only-Vermerk in `DECIDED-AND-DONE.md`: Entscheidung zurückgesetzt.

    Der urspruengliche Beleg bleibt vollstaendig stehen — es wird NICHTS
    geloescht, nur eine Zeile ergaenzt. Zielblock ist der zuletzt
    geschriebene, noch nicht als zurückgesetzt markierte Clicker-Beleg
    dieser ID; gibt es keinen, wird abgelehnt statt geraten.
    """
    path = settings.done_file
    if not path.is_file():
        raise WriteError(f"{path} nicht gefunden")
    text, has_bom = _read(path)
    lines = text.splitlines(keepends=True)
    newline = _newline_of(lines)

    heads: list[tuple[int, str]] = []
    for index, line in enumerate(lines):
        if match := DONE_HEADING_RE.match(line.rstrip("\r\n")):
            heads.append((index, match.group(1)))

    target: tuple[int, int] | None = None
    for pos, (index, hid) in enumerate(heads):
        if hid != entry_id:
            continue
        end = heads[pos + 1][0] if pos + 1 < len(heads) else len(lines)
        block = "".join(lines[index:end])
        if f"({TOOL_TAG})" not in block:
            continue
        if re.search(r"^ZUR[UÜ]CKGESETZT\s+AM\s*:", block, re.I | re.M):
            continue  # dieser Beleg ist bereits zurueckgesetzt — naechsten pruefen
        target = (index, end)
    if target is None:
        raise WriteError(
            f"{entry_id} hat keinen offenen {TOOL_TAG}-Beleg in {path.name} "
            "— extern entschieden oder bereits zurückgesetzt."
        )
    start, end = target

    einfuegen = end
    while einfuegen > start + 1 and lines[einfuegen - 1].strip() == "":
        einfuegen -= 1

    stamp = on or datetime.now().strftime("%Y-%m-%d")
    marker = f"ZURÜCKGESETZT AM: {stamp} ({reason}) — Entscheidung wieder offen"
    backup_path = backup(path, settings, tag="undo") if make_backup else None
    lines[einfuegen:einfuegen] = [f"{marker}{newline}"]
    _write(path, "".join(lines), has_bom)
    return {"file": str(path), "backup": str(backup_path) if backup_path else None}


def undo_decision(
    settings: Settings,
    entry: dict,
    reason: str,
    *,
    on: str | None = None,
    make_backup: bool = True,
) -> dict:
    """Einen Clicker-Klick aus dem Vollblock-Beleg wieder aktiv machen."""
    return restore_decision(
        settings, entry["id"], reason, on=on, make_backup=make_backup)


# ---------------------------------------------------------------------------
# Neue Eintraege
# ---------------------------------------------------------------------------
OPTION_LINE_RE = re.compile(r"^\s*(?:[-•*]\s*)?(?i:Option\s+)?([A-Z])\s*[:—–-]\s*(.*)$")


def normalise_option(line: str) -> str:
    """Optionszeile in die Listenform der Kette bringen: `- A — Text`."""
    line = single_line(line, "Eine Option")
    if not line:
        raise WriteError("Eine Option darf nicht leer sein.")
    match = OPTION_LINE_RE.match(line)
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
    evidenzanker: list[str] | None = None,
    gegenbelege: list[str] | None = None,
    fehlende_informationen: list[str] | None = None,
    erstellt_von: str = "",
    kontext_fingerprint: str = "",
    newline: str = "\r\n",
) -> str:
    """Eintrag nach der Konvention des Kettenkopfes parserfest rendern.

    Skalare Felder sind zwingend einzeilig. Freier Kontext bleibt mehrzeilig,
    wird aber als Markdown-Zitat eingerueckt, damit eine Zeile wie
    ``D-20990101-999 — ...`` niemals als zweiter Eintrag geparst wird.
    """
    entry_id = single_line(entry_id, "ID")
    if not ENTRY_ID_RE.fullmatch(entry_id):
        raise WriteError(f"Ungültige Entscheidungs-ID: {entry_id!r}")
    title = single_line(title, "Titel")
    status = single_line(status, "Status")
    quelle = single_line(quelle, "Quelle")
    frage = single_line(frage, "Frage")
    empfehlung = single_line(empfehlung, "Empfehlung")
    scope = single_line(scope, "Scope")
    evidenzanker_text = metadata_values(evidenzanker, "Evidenzanker")
    gegenbelege_text = metadata_values(gegenbelege, "Gegenbeleg")
    fehlende_text = metadata_values(fehlende_informationen, "Fehlende Information")
    erstellt_von = single_line(erstellt_von, "Erstellt von")
    kontext_fingerprint = single_line(kontext_fingerprint, "Kontext-Fingerprint").lower()
    if kontext_fingerprint and not CONTEXT_FINGERPRINT_RE.fullmatch(kontext_fingerprint):
        raise WriteError("Kontext-Fingerprint muss sha256: gefolgt von 64 Hex-Zeichen sein.")
    if status.strip().upper() == "OFFEN":
        if not frage:
            raise WriteError("Eine aktive Entscheidung benötigt eine Frage.")
        if not optionen or not any(option.strip() for option in optionen):
            raise WriteError("Eine aktive Entscheidung benötigt Optionen.")
    rows: list[str] = [f"{entry_id} — {title}", "", f"STATUS: {status}"]
    if scope:
        rows.append(f"SCOPE: {scope}")
    if quelle:
        rows.append(f"QUELLE: {quelle}")
    for name, value in (
        ("EVIDENZANKER", evidenzanker_text),
        ("GEGENBELEGE", gegenbelege_text),
        ("FEHLENDE INFORMATIONEN", fehlende_text),
        ("ERSTELLT VON", erstellt_von),
        ("KONTEXT-FINGERPRINT", kontext_fingerprint),
    ):
        if value:
            rows += ["", f"{name}: {value}"]
    if kontext:
        context_lines = kontext.strip().splitlines() or [""]
        rows += ["", "KONTEXT:", *[f"> {line}" if line else ">" for line in context_lines]]
    if frage:
        rows += ["", f"FRAGE: {frage}"]
    if optionen:
        rows += ["", "OPTIONEN:"]
        rows += [normalise_option(option) for option in optionen]
    if empfehlung:
        rows += ["", f"EMPFEHLUNG: {empfehlung}"]
    rows += ["", f"ENTSCHEIDUNG DES USERS: {PLACEHOLDER}", "", "---", ""]
    return newline.join(rows) + newline


def append_entry(
    settings: Settings,
    path: Path,
    rendered: str,
    *,
    make_backup: bool = True,
    preserve_rendered_newlines: bool = False,
) -> dict:
    """Eintrag am Ende des Aktivdokuments anhängen — vor einem Legacy-Pointer."""
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
    if letzte_ueberschrift >= 0:
        for index in range(letzte_ueberschrift + 1, len(lines)):
            if POINTER_RE.match(lines[index]):
                insert_at = index
                while insert_at > 0 and SEPARATOR_RE.match(
                    lines[insert_at - 1].rstrip("\r\n")
                ):
                    insert_at -= 1
                break

    backup_path = backup(path, settings, tag="new") if make_backup else None
    block = (
        rendered
        if preserve_rendered_newlines
        else rendered.replace("\r\n", "\n").replace("\n", newline)
    )
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
    original_block: str = "",
) -> dict:
    """Getroffene Entscheidung in `DECIDED-AND-DONE.md` protokollieren.

    Bei der normalen Clicker-Transaktion wird zusaetzlich der unveraenderte
    offene Originalblock eingebettet. So kann Undo ihn spaeter verlustfrei in
    das eine Aktivdokument zurueckstellen.
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
        "AKTIVVORLAGE: entfernt — beantwortete Punkte sind nicht mehr aktiv.",
        "UMSETZUNG: separat zu verfolgen; ein offener Umsetzungsstand reaktiviert die Frage nicht.",
        "",
    ]
    if original_block:
        encoded = base64.b64encode(original_block.encode("utf-8")).decode("ascii")
        rows += [f"ORIGINALBLOCK-BASE64: {encoded}", ""]
    backup_path = backup(path, settings, tag="done") if make_backup else None
    tail = "" if text.endswith(("\n", "\r")) else newline
    _write(path, text + tail + newline.join(rows) + newline, has_bom)
    return {"file": str(path), "backup": str(backup_path) if backup_path else None}


def decide_entry(
    settings: Settings,
    entry: dict,
    choice: str,
    note: str = "",
    *,
    on: str | None = None,
) -> dict:
    """Antwort protokollieren und den Vollblock sofort aus Aktiv entfernen."""
    if entry.get("decision_ready") is not True:
        raise WriteError(f"{entry.get('key', entry.get('id', '?'))} ist nicht entscheidungsreif aktiv.")
    path = Path(entry["source_path"])
    text, _has_bom = _read(path)
    lines = text.splitlines(keepends=True)
    start, end = entry_bounds(settings, lines, entry["source_line"])
    original_block = "".join(lines[start:end])

    filled = fill_decision(
        settings, path, entry["source_line"], choice, note,
        expected_id=entry["id"], on=on)
    try:
        record = append_done(
            settings, entry, choice, note, on=on, original_block=original_block)
    except Exception:
        revert_decision(
            settings, path, entry["source_line"], expected_id=entry["id"],
            make_backup=False)
        raise
    try:
        removed = remove_entry(
            settings, path, entry["source_line"], expected_id=entry["id"],
            make_backup=False)
    except Exception:
        revert_decision(
            settings, path, entry["source_line"], expected_id=entry["id"],
            make_backup=False)
        mark_decision_undone(
            settings, entry["id"], "Transaktion abgebrochen", on=on,
            make_backup=False)
        raise
    return {
        "ok": True, "id": entry["id"], "value": filled["value"],
        "date": filled["date"], "file": filled["file"], "line": filled["line"],
        "backup": filled["backup"], "record": record, "removed": removed,
    }


def _restorable_original_block(settings: Settings, entry_id: str) -> str:
    """Originalblock des neuesten offenen Clicker-Belegs dieser ID."""
    text, _has_bom = _read(settings.done_file)
    lines = text.splitlines()
    heads: list[tuple[int, str]] = []
    for index, line in enumerate(lines):
        if match := DONE_HEADING_RE.match(line):
            heads.append((index, match.group(1)))
    candidate = ""
    for pos, (start, found_id) in enumerate(heads):
        if found_id != entry_id:
            continue
        end = heads[pos + 1][0] if pos + 1 < len(heads) else len(lines)
        block = lines[start:end]
        if not any(CLICKER_DECIDED_AT_RE.match(line) for line in block):
            continue
        if any(re.match(r"^ZUR[UÜ]CKGESETZT\s+AM\s*:", line, re.I) for line in block):
            continue
        encoded = next(
            (match.group(1) for line in block if (match := ORIGINAL_BLOCK_RE.match(line))),
            "",
        )
        if encoded:
            try:
                candidate = base64.b64decode(encoded, validate=True).decode("utf-8")
            except (ValueError, UnicodeDecodeError) as exc:
                raise WriteError(f"Beschädigter Originalblock-Beleg für {entry_id}.") from exc
    if not candidate:
        raise WriteError(
            f"{entry_id} hat keinen offenen Clicker-Vollblock-Beleg — "
            "extern entschieden, Legacy-Beleg oder bereits zurückgesetzt."
        )
    return candidate


def restore_decision(
    settings: Settings,
    entry_id: str,
    reason: str,
    *,
    on: str | None = None,
    make_backup: bool = True,
) -> dict:
    """Einen archivierten Clicker-Vollblock wieder als offen aktivieren."""
    entry_id = single_line(entry_id, "ID")
    if not ENTRY_ID_RE.fullmatch(entry_id):
        raise WriteError(f"Ungültige Entscheidungs-ID: {entry_id!r}")
    tool = _load_index_tool(settings.index_script)
    index = tool.build_index(settings.chain_dir)
    if any(item["domain"] == "active" and item["id"] == entry_id for item in index["entries"]):
        raise WriteError(f"{entry_id} steht bereits im Aktivdokument.")
    original_block = _restorable_original_block(settings, entry_id)
    first = next((line for line in original_block.splitlines() if line.strip()), "")
    heading = tool.match_heading(first)
    if not heading or heading[0] != entry_id:
        raise WriteError(f"Originalblock-Beleg passt nicht zu {entry_id}.")

    target = settings.chain_dir / "TO-DECIDE-USER.txt"
    if not target.is_file():
        raise WriteError(f"Kanonisches Aktivdokument fehlt: {target}")
    active_backup = backup(target, settings, tag="undo") if make_backup else None
    done_backup = backup(settings.done_file, settings, tag="undo") if make_backup else None
    restored = append_entry(
        settings, target, original_block, make_backup=False,
        preserve_rendered_newlines=True)
    try:
        marker = mark_decision_undone(
            settings, entry_id, reason, on=on, make_backup=False)
    except Exception:
        fresh = tool.build_index(settings.chain_dir)
        active = next(
            item for item in fresh["entries"]
            if item["domain"] == "active" and item["id"] == entry_id)
        remove_entry(
            settings, target, active["source_line"], expected_id=entry_id,
            make_backup=False)
        raise
    restored["backup"] = str(active_backup) if active_backup else None
    marker["backup"] = str(done_backup) if done_backup else None
    return {"ok": True, "id": entry_id, "kette": restored, "beleg": marker}


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
            "AGENT: decision-clicker",
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
    "ChainError", "MUTATION_LOCK", "WriteError", "append_done", "append_entry", "backup",
    "decide_entry",
    "entry_bounds", "fill_decision", "foreign_locks", "mark_decision_undone",
    "release_lock", "render_decision", "render_entry", "revert_decision",
    "remove_entry", "restore_decision", "single_line", "undo_decision", "write_lock",
]
