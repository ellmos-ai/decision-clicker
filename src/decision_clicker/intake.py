# SPDX-License-Identifier: MIT
"""Desktop-Intake: Postfach einlesen und in die Kette übernehmen.

Ein optionales Desktop-Postfach ist **keine zweite Kanonik**. Es dient nur als
Kompatibilitätsweg für ältere Automationen, die noch nicht direkt in die
Entscheidungskette schreiben.

Der Clicker behandelt sie deshalb als **Postfach**: einlesen, konventionsgemäß
in die Kette übernehmen, dort als übernommen markieren. Nichts wird gelöscht
und nichts umformatiert — Nachzügler-Automationen dürfen weiter hineinschreiben.

Der eigene Scanner ist nötig, weil dort ein **Fremdformat** auftritt, das der
Kettenparser nicht als Eintrag erkennt: ein Block, der mit `ID: D-…` beginnt
statt mit der ID in Spalte 0.
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from .config import Settings, default_onedrive_root


def _default_sources() -> tuple[Path, ...]:
    """Konfigurierbare, hostsneutrale Postfachpfade."""
    if configured := os.environ.get("DECISION_CLICKER_INBOX"):
        return tuple(Path(value).expanduser() for value in configured.split(os.pathsep) if value)
    return (default_onedrive_root() / "Desktop" / "TO-DECIDE-USER.txt",)


DEFAULT_SOURCES = _default_sources()

_ID = r"D-\d{8}-\d{2,4}(?:-[A-Za-z0-9]+)*"
HEADING_RE = re.compile(rf"^(?:#{{1,4}}\s+)?(?P<id>{_ID})\s*(?:[—–]|--|-)?\s*(?P<title>.*?)\s*$")
ID_FIELD_RE = re.compile(rf"^ID\s*:\s*(?P<id>{_ID})\s*$", re.I)
DECISION_RE = re.compile(r"^\s*(?:[→>*-]\s*)?ENTSCHEIDUNG\s+DES\s+USERS\b[^:]*:\s*(.*)$", re.I)
FIELD_RE = re.compile(r"^\s*(?P<name>[A-ZÄÖÜ][A-ZÄÖÜ .–—/-]{2,30})\s*:\s*(?P<wert>.*)$")
OPTION_START_RE = re.compile(
    r"^\s*(?:\[(?P<klammer>[A-Z])\]|(?:[-•*]\s*)?(?i:Option\s+)?(?P<blank>[A-Z])\s*[:—–-]\s)\s*(?P<text>.*)$"
)
SEPARATOR_RE = re.compile(r"^\s*([-=_]{3,})\s*$")

TAKEN_MARK = "ÜBERNOMMEN nach _control-center/_DECISIONS"
PLACEHOLDERS = {"", "-", "N/A", "OFFEN", "TBD"}


# ---------------------------------------------------------------------------
@dataclass
class IntakeEntry:
    entry_id: str
    title: str
    path: Path
    start: int          # 0-basiert, erste Zeile des Blocks
    end: int            # exklusiv
    raw: str
    fields: dict[str, str] = field(default_factory=dict)
    optionen: list[str] = field(default_factory=list)
    decision: str = ""
    marked: bool = False

    @property
    def decided(self) -> bool:
        wert = " ".join(self.decision.split()).strip("[]").strip().rstrip(".")
        return bool(wert) and wert.upper() not in PLACEHOLDERS

    @property
    def frage(self) -> str:
        for name in ("DIE FRAGE", "FRAGE"):
            if name in self.fields:
                return self.fields[name]
        return ""

    @property
    def empfehlung(self) -> str:
        for name in ("EMPFEHLUNG", "EMPFOHLEN"):
            if name in self.fields:
                return self.fields[name]
        for option in self.optionen:  # "[B] … (EMPFEHLUNG von …)"
            if "EMPFEHLUNG" in option.upper():
                return option.split("—", 1)[0].strip() + " — siehe Optionswortlaut"
        return ""


# ---------------------------------------------------------------------------
def sources(settings: Settings) -> list[Path]:
    return [p for p in DEFAULT_SOURCES if p.is_file()]


def _read(path: Path) -> tuple[list[str], bool]:
    raw = path.read_bytes()
    return raw.decode("utf-8-sig").splitlines(keepends=True), raw.startswith(b"\xef\xbb\xbf")


def _is_heading(line: str) -> str | None:
    """Blockanfang: ID in Spalte 0 ODER die Fremdform `ID: D-…`."""
    body = line.rstrip("\r\n")
    treffer = ID_FIELD_RE.match(body)
    if treffer:
        return treffer.group("id")
    if body[:1].isspace() or body.startswith(("-", "*", "|")):
        return None
    treffer = HEADING_RE.match(body)
    if treffer and (body.startswith("D-") or body.startswith("#")):
        return treffer.group("id")
    return None


def collect_options(block: list[str]) -> list[str]:
    """Optionen sammeln — `[A] …`, `- A — …`, `A: …`, `Option A: …`."""
    optionen: list[str] = []
    laufend: list[str] = []
    in_block = False

    def schliessen() -> None:
        if laufend:
            optionen.append(" ".join(" ".join(laufend).split()))
            laufend.clear()

    for line in block:
        body = line.rstrip("\r\n")
        nackt = body.strip()
        if re.match(r"^OPTIONEN\s*:", nackt, re.I):
            in_block = True
            continue
        if not in_block:
            continue
        if not nackt or SEPARATOR_RE.match(nackt):
            schliessen()
            continue
        if DECISION_RE.match(body) or re.match(r"^(BELEG|QUELLE|EMPFEHLUNG|STATUS)\s*:", nackt, re.I):
            schliessen()
            in_block = False
            continue
        treffer = OPTION_START_RE.match(body)
        if treffer:
            schliessen()
            buchstabe = treffer.group("klammer") or treffer.group("blank")
            laufend.append(f"{buchstabe} — {treffer.group('text').strip()}")
        elif laufend:
            laufend.append(nackt)
    schliessen()
    return optionen


def _flush_field(
    current: str | None,
    buffer: list[str],
    fields: dict[str, str],
) -> tuple[None, list[str]]:
    """Mehrzeiliges Feld abschließen, ohne eine Schleifen-Closure zu halten."""
    if current and current not in fields:
        fields[current] = " ".join(" ".join(buffer).split())
    return None, []


def parse(path: Path) -> list[IntakeEntry]:
    lines, _ = _read(path)
    koepfe = [(i, _is_heading(line)) for i, line in enumerate(lines)]
    koepfe = [(i, eid) for i, eid in koepfe if eid]

    eintraege: list[IntakeEntry] = []
    for nummer, (start, entry_id) in enumerate(koepfe):
        end = koepfe[nummer + 1][0] if nummer + 1 < len(koepfe) else len(lines)
        block = lines[start:end]
        felder: dict[str, str] = {}
        entscheidung = ""
        laufend: str | None = None
        puffer: list[str] = []

        for line in block:
            body = line.rstrip("\r\n")
            nackt = body.strip()
            if not nackt or SEPARATOR_RE.match(nackt):
                laufend, puffer = _flush_field(laufend, puffer, felder)
                continue
            treffer = DECISION_RE.match(body)
            if treffer:
                laufend, puffer = _flush_field(laufend, puffer, felder)
                if not entscheidung:
                    entscheidung = treffer.group(1).strip()
                continue
            treffer = FIELD_RE.match(body)
            if treffer:
                laufend, puffer = _flush_field(laufend, puffer, felder)
                laufend = " ".join(treffer.group("name").split()).upper()
                puffer.append(treffer.group("wert").strip())
                continue
            if laufend and not OPTION_START_RE.match(body):
                puffer.append(nackt)  # Fortsetzungszeile eines mehrzeiligen Feldes
            elif laufend:
                laufend, puffer = _flush_field(laufend, puffer, felder)
        laufend, puffer = _flush_field(laufend, puffer, felder)

        kopf = HEADING_RE.match(block[0].rstrip("\r\n"))
        titel = (kopf.group("title").strip() if kopf and not ID_FIELD_RE.match(block[0].rstrip("\r\n")) else "")
        if not titel:
            titel = felder.get("PROJEKT") or felder.get("ANLASS", "")[:90] or "(ohne Titel)"

        eintraege.append(IntakeEntry(
            entry_id=entry_id, title=" ".join(titel.split()), path=path,
            start=start, end=end, raw="".join(block).rstrip(), fields=felder,
            optionen=collect_options(block), decision=entscheidung,
            marked=TAKEN_MARK in "".join(block),
        ))
    return eintraege


def scan(settings: Settings) -> list[IntakeEntry]:
    eintraege: list[IntakeEntry] = []
    for path in sources(settings):
        eintraege.extend(parse(path))
    return eintraege


def pending(settings: Settings, bekannte_ids: set[str]) -> list[IntakeEntry]:
    """Noch nicht übernommene Postfach-Einträge."""
    return [e for e in scan(settings) if not e.marked and e.entry_id not in bekannte_ids]


# ---------------------------------------------------------------------------
def quote(text: str) -> list[str]:
    """Originalwortlaut zitieren.

    Das `| ` ist nicht Kosmetik: ohne den Präfix träfe der Writer auf die
    ursprüngliche Zeile `ENTSCHEIDUNG DES USERS:` im Zitat und würde diese
    füllen statt der echten am Blockende.
    """
    return [f"| {line}".rstrip() for line in text.splitlines()]


def render_takeover(entry: IntakeEntry, *, on: str | None = None, newline: str = "\r\n") -> str:
    """Postfach-Eintrag in Kettenkonvention gießen — Wortlaut bleibt erhalten."""
    stamp = on or datetime.now().strftime("%Y-%m-%d")
    herkunft = (f"`%OneDrive%\\Desktop\\{entry.path.name}` (Desktop-Intake), "
                f"übernommen am {stamp} durch decision-clicker.")
    rows: list[str] = [
        f"{entry.entry_id} — {entry.title}", "",
        f"STATUS: OFFEN — eingegangen via Desktop-Intake am {stamp}.",
        "SCOPE: global",
        f"QUELLE: {herkunft}",
    ]
    if datum := entry.fields.get("DATUM"):
        rows.append(f"VORGELEGT: {datum}")
    if entry.frage:
        rows += ["", f"FRAGE: {entry.frage}"]
    if entry.optionen:
        rows += ["", "OPTIONEN:"] + [f"- {option}" for option in entry.optionen]
    if entry.empfehlung:
        rows += ["", f"EMPFEHLUNG: {entry.empfehlung}"]
    if beleg := entry.fields.get("BELEG"):
        rows += ["", f"BELEG: {beleg}"]
    rows += ["", "ORIGINALWORTLAUT AUS DEM DESKTOP-POSTFACH (unverändert, nur zitiert):"]
    rows += quote(entry.raw)
    rows += ["", "ENTSCHEIDUNG DES USERS: [HIER EINTRAGEN]", "", "---", ""]
    return newline.join(rows) + newline


def takeover(settings: Settings, *, dry_run: bool = False, on: str | None = None) -> list[dict]:
    """Postfach leeren: jeden neuen Eintrag in die Kette holen und dort vermerken.

    Offene Einträge landen im letzten Kettenteil, bereits entschiedene als
    Beleg in `DECIDED-AND-DONE.md`. Die ursprüngliche D-ID bleibt in beiden
    Fällen erhalten — IDs werden nie neu vergeben, sie können extern
    referenziert sein.
    """
    from . import chain, writer  # spät: intake ist die untere Schicht

    stamp = on or datetime.now().strftime("%Y-%m-%d")
    index = chain.build_index(settings)
    offene = pending(settings, chain.known_ids(index))
    if not offene:
        return []

    fremde = writer.foreign_locks(settings)
    if fremde and not dry_run:
        raise writer.WriteError(
            f"Fremde Sperre im Entscheidungsordner: {[p.name for p in fremde]}")

    ergebnisse: list[dict] = []
    for eintrag in offene:
        ziel = settings.done_file if eintrag.decided else chain.target_part(settings)
        marker = (f"→ {TAKEN_MARK} ({stamp}) — dort als {eintrag.entry_id} in "
                  f"{ziel.name}; dieser Eintrag ist ab hier nur noch Historie.")
        eintrag_info = {
            "id": eintrag.entry_id, "titel": eintrag.title,
            "entschieden": eintrag.decided, "ziel": ziel.name,
            "quelle": str(eintrag.path), "marker": marker,
        }
        if dry_run:
            ergebnisse.append(eintrag_info)
            continue

        if eintrag.decided:
            writer.append_done_block(settings, render_done_takeover(eintrag, on=stamp))
        else:
            writer.append_entry(settings, ziel, render_takeover(eintrag, on=stamp))
        # Erst nach erfolgreicher Übernahme markieren — sonst ginge der
        # Eintrag bei einem Abbruch zwischen beiden Schritten verloren.
        frisch = {e.entry_id: e for e in parse(eintrag.path)}[eintrag.entry_id]
        writer.mark_taken_over(settings, frisch.path, frisch.start, frisch.end, marker)
        ergebnisse.append(eintrag_info)

    if not dry_run:
        chain.refresh_artifacts(settings)
    return ergebnisse


def render_done_takeover(entry: IntakeEntry, *, on: str | None = None) -> list[str]:
    """Bereits entschiedener Postfach-Eintrag als Beleg für DECIDED-AND-DONE."""
    stamp = on or datetime.now().strftime("%Y-%m-%d")
    return [
        "",
        f"## {entry.entry_id} — {entry.title}",
        "",
        f"ÜBERNOMMEN AM: {stamp} aus dem Desktop-Postfach "
        f"(`%OneDrive%\\Desktop\\{entry.path.name}`) durch decision-clicker.",
        "STATUS: entschieden und laut Eintrag umgesetzt.",
        f"ENTSCHEIDUNG: {entry.decision}" if entry.decision else "ENTSCHEIDUNG: siehe Wortlaut.",
        "",
        "Originalwortlaut, unverändert zitiert:",
        "",
        *quote(entry.raw),
        "",
    ]
