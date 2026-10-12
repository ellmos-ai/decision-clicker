# SPDX-License-Identifier: MIT
"""Transaktionsjournal fuer Mehrdatei-Transaktionen (Polaris, Festlegung 5).

``decide_entry``, ``undo_decision`` und ``restore_decision`` schreiben VOR dem
ersten Schreiben ein Journal (Transaktions-ID, Fence, Ausgangs-Hashes,
Schrittplan) und danach den Fortschritt je Schritt. Geht der Stern mitten
drin verloren, wird gestoppt: kein Auto-Revert, das Journal bleibt liegen.
Der naechste Halter findet es beim Erwerb und schliesst die Transaktion
idempotent ab (Roll-forward) oder verwirft es, wenn nichts geschrieben wurde,
bevor er Neues schreibt. Der Journal-Ort (``_polaris-journal/``) liegt im
Ressourcenumfang und damit im Manifest der Sync-Schranke.
"""
from __future__ import annotations

import base64
import hashlib
import json
from datetime import datetime
from pathlib import Path

from .config import Settings
from .errors import StarUnavailable
from .star import JOURNAL_DIR, Transaction, inflight_version

SCHEMA = "decision-clicker.journal.v1"
ACTIVE_NAME = "TO-DECIDE-USER.txt"


def journal_dir(settings: Settings) -> Path:
    return Path(settings.chain_dir) / JOURNAL_DIR


def sha256_of(path: Path) -> str | None:
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None


class Journal:
    def __init__(self, settings: Settings, data: dict) -> None:
        self.settings, self.data = settings, data
        self.path = journal_dir(settings) / f"{data['txid']}.json"

    @classmethod
    def begin(cls, settings: Settings, tx: Transaction, op: str, entry_id: str,
              steps: list[str], params: dict) -> Journal:
        data = {
            "schema": SCHEMA, "txid": tx.txid, "op": op, "resource": tx.cfg.resource, "fence": tx.fence,
            "host": tx.cfg.host, "entry_id": entry_id, "started": datetime.now().isoformat(timespec="seconds"),
            "hashes_before": {
                ACTIVE_NAME: sha256_of(Path(settings.chain_dir) / ACTIVE_NAME),
                "DECIDED-AND-DONE.md": sha256_of(settings.done_file),
            },
            "steps": steps, "done": [], "params": params,
        }
        journal = cls(settings, data)
        journal._store()
        tx.report(inflight_version(tx.txid), inflight=True)  # ab hier erwirbt der Nachfolger ueber das Journal
        return journal

    def _store(self) -> None:
        from . import writer  # spaet: writer importiert dieses Modul
        writer._write(self.settings, self.path, json.dumps(self.data, ensure_ascii=False, indent=1) + "\n", False)

    def advance(self, step: str) -> None:
        self.data["done"].append(step)
        self._store()

    def close(self) -> None:
        from . import writer
        writer._unlink(self.settings, self.path)


def open_journals(settings: Settings) -> list[dict]:
    folder = journal_dir(settings)
    if not folder.is_dir():
        return []
    found = []
    for path in sorted(folder.glob("*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise StarUnavailable(f"Offenes Journal {path.name} ist unlesbar ({exc}) — nicht abschliessbar, "
                                  "Kette bleibt nur lesbar.") from exc
        data["_path"] = path
        found.append(data)
    return found


def encode_block(block: str) -> str:
    return base64.b64encode(block.encode("utf-8")).decode("ascii")


def decode_block(encoded: str) -> str:
    return base64.b64decode(encoded, validate=True).decode("utf-8")


# ---------------------------------------------------------------------------
# Wiederaufnahme beim Erwerb
# ---------------------------------------------------------------------------
def _find_line(settings: Settings, path: Path, entry_id: str) -> int | None:
    from .chain import _load_index_tool
    match_heading = _load_index_tool(settings.index_script).match_heading
    if not path.is_file():
        return None
    for number, line in enumerate(path.read_text(encoding="utf-8-sig").splitlines(), start=1):
        hit = match_heading(line.rstrip("\r\n"))
        if hit and hit[0] == entry_id:
            return number
    return None


def _done_block(settings: Settings, entry_id: str, txid: str, needle: str) -> bool:
    """Gibt es im Register einen Block dieser ID, dessen Zeilen ``needle`` (mit ``tx``) tragen?"""
    from .chain import DONE_HEADING_RE
    if not settings.done_file.is_file():
        return False
    lines = settings.done_file.read_text(encoding="utf-8-sig").splitlines()
    heads = [(i, m.group(1)) for i, line in enumerate(lines) if (m := DONE_HEADING_RE.match(line))]
    for pos, (start, found) in enumerate(heads):
        if found != entry_id:
            continue
        end = heads[pos + 1][0] if pos + 1 < len(heads) else len(lines)
        body = "\n".join(lines[start:end])
        if f"tx={txid}" in body or f"recovers={txid}" in body:
            if needle == "" or needle in body:
                return True
    return False


def recover(settings: Settings, tx: Transaction) -> None:
    """Offene Journale abschliessen oder verwerfen, bevor etwas Neues geschrieben wird."""
    from . import writer
    for data in open_journals(settings):
        name = data["_path"].name
        try:
            if data.get("op") == "decide":
                _recover_decide(settings, tx, data)
            elif data.get("op") == "restore":
                _recover_restore(settings, tx, data)
            else:
                raise StarUnavailable(f"Offenes Journal {name} hat eine unbekannte Operation.")
        except StarUnavailable:
            raise
        except Exception as exc:  # noqa: BLE001
            raise StarUnavailable(f"Offenes Journal {name} ist nicht abschliessbar ({exc}) — Kette bleibt "
                                  "nur lesbar.") from exc
        writer._unlink(settings, data["_path"])


def _recover_decide(settings: Settings, tx: Transaction, data: dict) -> None:
    from . import writer
    from .chain import _load_index_tool
    p, eid, orig = data["params"], data["entry_id"], data["txid"]
    path = Path(settings.chain_dir) / ACTIVE_NAME
    tool = _load_index_tool(settings.index_script)
    done_present = _done_block(settings, eid, orig, "")
    line = _find_line(settings, path, eid)
    filled = False
    if line is not None:
        lines = path.read_text(encoding="utf-8-sig").splitlines(keepends=True)
        start, end = writer.entry_bounds(settings, lines, line)
        for row in lines[start:end]:
            match = writer.DECISION_FIELD_RE.match(row.rstrip("\r\n"))
            if match:
                filled = not tool.is_placeholder(match.group(2))
                break
        if not filled and ("fill" in data["done"] or "done" in data["done"]):
            raise StarUnavailable(f"{eid}: Journal meldet Fortschritt, den diese Kopie der Kette nicht zeigt — "
                                  "vermutlich noch nicht synchron; Kette bleibt nur lesbar.")
        if not filled and not done_present:
            return  # nichts geschrieben: Journal verwerfen (Zuruecksetzen = nichts zu tun)
        if not filled:
            raise StarUnavailable(f"{eid}: Beleg ohne ausgefuellte Entscheidung — manuelle Pruefung noetig.")
    if "done" in data["done"] and not done_present:
        raise StarUnavailable(f"{eid}: Journal meldet den Registerbeleg, diese Kopie zeigt ihn nicht — "
                              "vermutlich noch nicht synchron; Kette bleibt nur lesbar.")
    original = decode_block(p["original_block_b64"])
    if not done_present:
        entry = {"id": eid, "title": p["title"], "source_file": p["source_file"], "source_line": p["source_line"]}
        writer.append_done(settings, entry, p["choice"], p["note"], on=p["on"], original_block=original,
                           stamp=f"{tx.stamp()} recovers={orig}")
    line = _find_line(settings, path, eid)
    if line is not None:
        writer.remove_entry(settings, path, line, expected_id=eid)


def _recover_restore(settings: Settings, tx: Transaction, data: dict) -> None:
    from . import writer
    p, eid, orig = data["params"], data["entry_id"], data["txid"]
    path = Path(settings.chain_dir) / ACTIVE_NAME
    in_active = _find_line(settings, path, eid) is not None
    marked = _done_block(settings, eid, orig, "ZUR")
    if "restore" in data["done"] and not in_active:
        raise StarUnavailable(f"{eid}: Journal meldet den Restore, diese Kopie zeigt ihn nicht — vermutlich "
                              "noch nicht synchron; Kette bleibt nur lesbar.")
    if not in_active and not marked:
        return  # nichts geschrieben
    if not in_active:
        raise StarUnavailable(f"{eid}: Rueckgaengig-Vermerk ohne Aktiveintrag — manuelle Pruefung noetig.")
    if not marked:
        writer.mark_decision_undone(settings, eid, p["reason"], on=p["on"],
                                    stamp=f"{tx.stamp()} recovers={orig}")
