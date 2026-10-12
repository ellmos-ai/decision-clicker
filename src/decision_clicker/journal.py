# SPDX-License-Identifier: MIT
"""Transaktionsjournal fuer Mehrdatei-Transaktionen (Polaris, Festlegung 5).

``decide_entry``, ``undo_decision`` und ``restore_decision`` schreiben VOR dem
ersten Schreiben ein Journal (Transaktions-ID, Fence, Ausgangs-Hashes,
Schrittplan) und danach den Fortschritt je Schritt. Geht der Stern mitten
drin verloren, wird gestoppt: kein Auto-Revert, das Journal bleibt liegen.
Der naechste Halter findet es beim Erwerb und schliesst die Transaktion
idempotent ab (Roll-forward) oder verwirft es, wenn nichts geschrieben wurde,
bevor er Neues schreibt. Der Journal-Ort (``_polaris-journal/``) liegt AUSSERHALB des
Manifests der Sync-Schranke: das Loeschen des Journals aendert den gemeldeten Stand nicht,
deshalb kommt der Commit-Marker vor dem Loeschen (R29-1).

Recovery nur mit Beweis (R29-2): Das Journal haelt die Datei-Hashes vor der Transaktion und nach
jedem Schritt. Roll-forward nur, wenn die lokale Kette genau dem Zustand nach dem letzten
vermerkten Schritt entspricht; jede andere Kette ist noch nicht synchron oder fremd: warten,
nie verwerfen. Verworfen wird nur, wenn nachweislich nichts geschrieben wurde. Das Journal wird
atomar geschrieben und traegt eine Pruefsumme (``journal_corrupt`` -> nur lesbar).
"""
from __future__ import annotations

import base64
import hashlib
import json
from datetime import datetime
from pathlib import Path

from .config import Settings
from .errors import StarUnavailable
from .star import JOURNAL_DIR, TMP_SUFFIX, Transaction, _denied, inflight_version

SCHEMA = "decision-clicker.journal.v1"
ACTIVE_NAME = "TO-DECIDE-USER.txt"
DONE_NAME = "DECIDED-AND-DONE.md"
#: Welche Kettendatei ein Schritt schreibt: so laesst sich der Hash VOR dem Schreiben vermerken
#: (``pending``) und ein Abbruch zwischen Schreiben und Fortschrittsvermerk beweisen.
STEP_FILE = {"decide": {"fill": ACTIVE_NAME, "done": DONE_NAME, "remove": ACTIVE_NAME},
             "restore": {"restore": ACTIVE_NAME, "mark": DONE_NAME}}


def journal_dir(settings: Settings) -> Path:
    return Path(settings.chain_dir) / JOURNAL_DIR


def sha256_of(path: Path) -> str | None:
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None


def chain_hashes(settings: Settings) -> dict[str, str | None]:
    """Hashes der beiden von Mehrdatei-Transaktionen geschriebenen Kettendateien."""
    return {ACTIVE_NAME: sha256_of(Path(settings.chain_dir) / ACTIVE_NAME),
            DONE_NAME: sha256_of(settings.done_file)}


def _checksum(data: dict) -> str:
    body = {k: v for k, v in data.items() if k != "checksum" and not k.startswith("_")}
    return hashlib.sha256(json.dumps(body, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()


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
            "hashes_before": chain_hashes(settings), "hashes_after": {},
            "steps": steps, "done": [], "params": params,
        }
        journal = cls(settings, data)
        journal.tx = tx
        journal._store()
        tx.journal = journal
        tx.report(inflight_version(tx.txid), inflight=True)  # ab hier erwirbt der Nachfolger ueber das Journal
        return journal

    def _store(self) -> None:
        from . import writer  # spaet: writer importiert dieses Modul
        self.data["checksum"] = _checksum(self.data)
        body = {k: v for k, v in self.data.items() if not k.startswith("_")}
        writer._write(self.settings, self.path, json.dumps(body, ensure_ascii=False, indent=1) + "\n", False)

    def intend(self, name: str, digest: str) -> None:
        """Vor dem Schreiben einer Kettendatei: ihren kuenftigen Hash vermerken (nur fuer den naechsten Schritt)."""
        done, steps = len(self.data["done"]), self.data["steps"]
        if done < len(steps) and STEP_FILE.get(self.data["op"], {}).get(steps[done]) == name:
            self.data["pending"] = {"step": steps[done], "file": name, "hash": digest}
            self._store()

    def advance(self, step: str) -> None:
        """Schritt ist geschrieben: Fortschritt samt Ist-Hashes (Beweis fuer die Recovery) vermerken."""
        self.data.pop("pending", None)
        self.data["done"].append(step)
        self.data["hashes_after"][step] = chain_hashes(self.settings)
        self._store()

    def mark_aborted(self) -> None:
        """Rollback ist durch: die Kette gilt jetzt (und nur jetzt) als sauber zurueckgerollt."""
        self.data["aborted"] = chain_hashes(self.settings)
        self._store()

    def close_if_proven(self) -> None:
        """Fehlerpfad: das Journal nur loeschen, wenn die Kette nachweislich dem Vorher-Zustand oder dem
        vermerkten Rollback-Zustand entspricht; sonst bleibt es fuer die Recovery liegen."""
        local = chain_hashes(self.settings)
        if local == self.data["hashes_before"] or local == self.data.get("aborted"):
            self.close()

    def close(self) -> None:
        from . import writer
        self.tx.journal = None
        writer._unlink(self.settings, self.path)


def _hash_map(value) -> bool:
    return (isinstance(value, dict) and set(value) == {ACTIVE_NAME, DONE_NAME}
            and all(v is None or (isinstance(v, str) and len(v) == 64) for v in value.values()))


def _validate(data: dict, path: Path) -> None:
    """Typen und Schrittfolge; jede Abweichung ist ``journal_corrupt`` (ValueError)."""
    if (not isinstance(data, dict) or data.get("schema") != SCHEMA or data.get("txid") != path.stem
            or data.get("checksum") != _checksum(data)):
        raise ValueError("Pruefsumme oder Schema stimmt nicht")
    op, steps, done = data.get("op"), data.get("steps"), data.get("done")
    if op not in STEP_FILE or steps != list(STEP_FILE[op]):
        raise ValueError("Operation oder Schrittfolge unbekannt")
    if not isinstance(done, list) or done != steps[:len(done)]:
        raise ValueError("done ist kein Praefix der Schrittfolge")
    after = data.get("hashes_after")
    if not isinstance(after, dict) or set(after) != set(done) or not all(_hash_map(v) for v in after.values()):
        raise ValueError("hashes_after passt nicht zu done")
    if not _hash_map(data.get("hashes_before")):
        raise ValueError("hashes_before ist ungueltig")
    if "aborted" in data and not _hash_map(data["aborted"]):
        raise ValueError("aborted ist ungueltig")
    pending = data.get("pending")
    if pending is not None and not (
            isinstance(pending, dict) and set(pending) == {"step", "file", "hash"}
            and pending["step"] in steps and pending["file"] in (ACTIVE_NAME, DONE_NAME)
            and isinstance(pending["hash"], str) and len(pending["hash"]) == 64):
        raise ValueError("pending ist ungueltig")
    if not isinstance(data.get("params"), dict) or not isinstance(data.get("entry_id"), str):
        raise ValueError("params oder entry_id ungueltig")


def open_journals(settings: Settings) -> list[dict]:
    folder = journal_dir(settings)
    if not folder.is_dir():
        return []
    found = []
    for path in sorted(folder.glob("*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            _validate(data, path)
        except (OSError, ValueError, KeyError, TypeError) as exc:
            raise _denied("journal_corrupt", f"{path.name}: {exc}") from exc
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


def _classify(settings: Settings, tx: Transaction, data: dict) -> str:
    """``discard`` (nichts geschrieben), ``forward`` (Roll-forward) oder ``delete`` (nur noch loeschen);
    sonst ``StarUnavailable`` (warten)."""
    states = [data["hashes_before"]] + [data["hashes_after"].get(step) for step in data["done"]]
    done = len(data["done"])
    local = chain_hashes(settings)
    if data.get("aborted") == local:
        return "abort"  # Rollback war durch, nur das Loeschen fehlte
    pending = data.get("pending")
    if pending and done < len(data["steps"]) and pending.get("step") == data["steps"][done] \
            and states[done] != local:
        applied = dict(states[done], **{pending["file"]: pending["hash"]})
        if applied == local:  # geschrieben, aber der Fortschrittsvermerk fehlt: der Hash war vorab vermerkt
            data["done"].append(pending["step"])
            data["hashes_after"][pending["step"]] = local
            states.append(local)
            done += 1
    if states[done] != local:
        raise _denied("journal_unmatched", f"{data['_path'].name}: Kette passt nicht zum Stand nach "
                                           f"{done} von {len(data['steps'])} Schritten")
    if done == 0:
        return "discard"  # alle Hashes == vorher: nachweislich nichts geschrieben
    if tx.via == f"inflight:{data['txid']}":
        return "forward"
    if done == len(data["steps"]):
        return "delete"  # Commit war erfolgreich, nur das Loeschen fehlte; Kette == Ziel
    raise _denied("journal_unmatched", f"{data['_path'].name}: Journal ohne In-flight-Marker ist unvollstaendig")


def recover(settings: Settings, tx: Transaction) -> None:
    """Offene Journale abschliessen oder verwerfen, bevor etwas Neues geschrieben wird.

    Die Recovery journalisiert selbst: waehrend des Roll-forward ist ``tx.journal`` das offene Journal,
    jeder Schritt vermerkt vorab ``pending`` und danach den Fortschritt (ein Abbruch mittendrin bleibt beweisbar)."""
    from . import writer
    for data in open_journals(settings):
        name = data["_path"].name
        verdict = _classify(settings, tx, data)
        if verdict == "delete":
            writer._unlink(settings, data["_path"])
            continue
        if verdict in ("discard", "abort"):
            tx.commit_marker(ignore=data["txid"], required=True)
            writer._unlink(settings, data["_path"])
            continue
        step = {"decide": _recover_decide, "restore": _recover_restore}.get(data.get("op"))
        if step is None:
            raise StarUnavailable(f"Offenes Journal {name} hat eine unbekannte Operation.")
        log = Journal(settings, data)
        log.tx = tx
        tx.journal = log
        try:
            step(settings, tx, log)
        except StarUnavailable:
            raise
        except Exception as exc:  # noqa: BLE001
            raise StarUnavailable(f"Offenes Journal {name} ist nicht abschliessbar ({exc}) — Kette bleibt "
                                  "nur lesbar.") from exc
        tx.commit_marker(ignore=data["txid"], required=True)  # erst den Stand melden, dann das Journal loeschen
        log.close()
    _sweep_tmp(settings, tx)


def _sweep_tmp(settings: Settings, tx: Transaction) -> None:
    """Eigene ``*.polaris-tmp`` abgeschlossener oder verworfener Transaktionen entfernen (best effort)."""
    mine = f"@{tx.cfg.host}{TMP_SUFFIX}"
    live = {tx.txid} | {p.stem for p in (journal_dir(settings).glob("*.json") if journal_dir(settings).is_dir()
                                         else [])}
    for path in Path(settings.chain_dir).rglob("*" + TMP_SUFFIX):
        if not path.name.endswith(mine):
            continue
        txid = path.name[:-len(mine)].rsplit(".", 1)[-1].split("-", 1)[0]
        if txid in live:
            continue
        try:
            path.unlink()
        except OSError:
            pass


def _recover_decide(settings: Settings, tx: Transaction, log: Journal) -> None:
    from . import writer
    data = log.data
    p, eid, orig = data["params"], data["entry_id"], data["txid"]
    path = Path(settings.chain_dir) / ACTIVE_NAME
    if "done" not in data["done"]:
        if not _done_block(settings, eid, orig, ""):
            original = decode_block(p["original_block_b64"])
            entry = {"id": eid, "title": p["title"], "source_file": p["source_file"],
                     "source_line": p["source_line"]}
            writer.append_done(settings, entry, p["choice"], p["note"], on=p["on"], original_block=original,
                               stamp=f"{tx.stamp()} recovers={orig}")
        log.advance("done")
    if "remove" not in data["done"]:
        line = _find_line(settings, path, eid)
        if line is not None:
            writer.remove_entry(settings, path, line, expected_id=eid)
        log.advance("remove")


def _recover_restore(settings: Settings, tx: Transaction, log: Journal) -> None:
    from . import writer
    data = log.data
    p, eid, orig = data["params"], data["entry_id"], data["txid"]
    if "mark" not in data["done"]:
        if not _done_block(settings, eid, orig, "ZUR"):
            writer.mark_decision_undone(settings, eid, p["reason"], on=p["on"],
                                        stamp=f"{tx.stamp()} recovers={orig}")
        log.advance("mark")
