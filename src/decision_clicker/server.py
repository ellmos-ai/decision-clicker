# SPDX-License-Identifier: MIT
"""Lokaler HTTP-Server des Decision-Clickers (stdlib, kein Framework).

Bindet ausschliesslich an 127.0.0.1. Jeder Schreibvorgang legt vorher eine
Sicherung an und prueft auf fremde Sperren im Kettenordner.
"""
from __future__ import annotations

import json
import traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from . import chain, intake, ui, writer
from .config import Settings, load

MAX_BODY = 256 * 1024


def options_of(entry: dict, raw: str) -> list[tuple[str, str]]:
    """Optionen für die Knöpfe — aus dem VOLLTEXT, nicht aus dem Index-Auszug.

    Der Index kürzt `options_excerpt` auf 400 Zeichen. Bei ausführlichen
    Einträgen fiel dadurch die letzte Option unter den Tisch und war nicht
    anklickbar (belegt an D-20260806-001: Option C fehlte). Genommen wird
    darum die längere der beiden Lesarten.
    """
    aus_volltext: list[tuple[str, str]] = []
    for option in intake.collect_options(raw.splitlines()):
        buchstabe, _, text = option.partition(" — ")
        if text:
            aus_volltext.append((buchstabe.strip().upper(), text.strip()))
    aus_auszug = ui.parse_options(entry.get("options_excerpt", ""))
    return aus_volltext if len(aus_volltext) >= len(aus_auszug) else aus_auszug


def entry_text(settings: Settings, entry: dict) -> str:
    """Rohtext eines Eintrags — der Kontext, den Lukas beim Klicken sieht."""
    path = Path(entry["source_path"])
    if not path.is_file():
        return entry.get("question", "")
    lines = path.read_text(encoding="utf-8-sig").splitlines(keepends=True)
    try:
        start, end = writer.entry_bounds(settings, lines, entry["source_line"])
    except writer.WriteError:
        return entry.get("question", "")
    return "".join(lines[start:end]).strip()


class Handler(BaseHTTPRequestHandler):
    server_version = "DecisionClicker/1.0"
    settings: Settings
    skipped: set[str]

    # -- Infrastruktur ----------------------------------------------------
    def log_message(self, fmt: str, *args) -> None:  # noqa: A002
        print(f"  {self.address_string()} {fmt % args}")

    def _send(self, payload: bytes, status: int = 200, ctype: str = "text/html; charset=utf-8") -> None:
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(payload)

    def _json(self, data: dict, status: int = 200) -> None:
        raw = json.dumps(data, ensure_ascii=False, indent=2).encode("utf-8")
        self._send(raw, status, "application/json; charset=utf-8")

    def _redirect(self, target: str) -> None:
        self.send_response(303)
        self.send_header("Location", target)
        self.send_header("Content-Length", "0")
        self.end_headers()

    def _form(self) -> dict[str, str]:
        """Formular ODER JSON — derselbe Einstellweg für Mensch und Automation."""
        length = int(self.headers.get("Content-Length") or 0)
        if length > MAX_BODY:
            raise writer.WriteError("Anfrage zu gross")
        raw = self.rfile.read(length).decode("utf-8") if length else ""
        if "application/json" in (self.headers.get("Content-Type") or ""):
            self.wants_json = True
            daten = json.loads(raw or "{}")
            if isinstance(daten.get("optionen"), list):
                daten["optionen"] = "\n".join(str(o) for o in daten["optionen"])
            return {k: ("" if v is None else str(v)) for k, v in daten.items()}
        self.wants_json = False
        return {k: v[0] for k, v in parse_qs(raw, keep_blank_values=True).items()}

    def _antwort(self, redirect: str, daten: dict) -> None:
        """JSON-Aufrufer bekommen Daten, Browser eine Weiterleitung."""
        if getattr(self, "wants_json", False):
            self._json(daten)
        else:
            self._redirect(redirect)

    def _postfach(self, index: dict) -> list[dict]:
        """Noch nicht übernommene Postfach-Einträge — rein lesend."""
        try:
            return intake.takeover(self.settings, dry_run=True)
        except (OSError, chain.ChainError, writer.WriteError):
            traceback.print_exc()
            return []

    def _guard(self) -> str:
        """Fremde Sperre = kein Schreibzugriff. Gibt eine Meldung oder ''."""
        fremde = writer.foreign_locks(self.settings)
        if fremde:
            namen = ", ".join(p.name for p in fremde)
            return f"Fremde Sperre im Entscheidungsordner aktiv ({namen}) — es wird nicht geschrieben."
        return ""

    # -- GET ---------------------------------------------------------------
    def do_GET(self) -> None:  # noqa: N802
        url = urlparse(self.path)
        query = {k: v[0] for k, v in parse_qs(url.query).items()}
        try:
            self._route_get(url.path, query)
        except chain.ChainError as exc:
            self._send(ui.meldung("Kette nicht lesbar", str(exc), "/", "Erneut"), 500)
        except Exception:  # noqa: BLE001 -- Server darf nie sterben
            traceback.print_exc()
            self._send(ui.meldung("Fehler", traceback.format_exc(limit=3), "/", "Übersicht"), 500)

    def _route_get(self, path: str, query: dict[str, str]) -> None:
        if path == "/":
            index = chain.build_index(self.settings)
            self._send(ui.home(chain.counts(index), chain.open_entries(index), self._guard(),
                               self._postfach(index)))
        elif path == "/klick":
            self._klick(query)
        elif path == "/neu":
            index = chain.build_index(self.settings)
            ziel = chain.target_part(self.settings)
            hinweis = ""
            if chain.part_is_full(ziel):
                hinweis = (f"{ziel.name} ist lang — nach der Cut-and-Clue-Regel wäre ein "
                           "neuer Kettenteil fällig. Das entscheidet ein Mensch, nicht dieses Werkzeug.")
            self._send(ui.neu(chain.next_id(index), ziel.name, hinweis))
        elif path == "/register":
            self._register(query.get("q", ""))
        elif path == "/api/index":
            self._json(chain.build_index(self.settings))
        elif path == "/api/intake":
            index = chain.build_index(self.settings)
            self._json({"offen": self._postfach(index),
                        "quellen": [str(p) for p in intake.sources(self.settings)]})
        elif path == "/api/health":
            index = chain.build_index(self.settings)
            self._json({"ok": True, "chain": str(self.settings.chain_dir),
                        "counts": chain.counts(index),
                        "postfach_offen": len(self._postfach(index)),
                        "fremde_sperren": [p.name for p in writer.foreign_locks(self.settings)]})
        else:
            self._send(ui.meldung("Nicht gefunden", f"Keine Seite unter {path}.", "/", "Übersicht"), 404)

    def _klick(self, query: dict[str, str]) -> None:
        index = chain.build_index(self.settings)
        if skip := query.get("skip"):
            self.skipped.add(skip)
        offen = chain.open_entries(index)
        wanted = query.get("key")
        if wanted:
            entry = chain.find(index, wanted)
            if entry is None or entry["status_class"] != chain.STATUS_OPEN:
                self._send(ui.meldung("Nicht mehr offen",
                                      f"{wanted} ist keine offene Entscheidung (mehr).",
                                      "/klick", "Nächste"), 404)
                return
        else:
            rest = [e for e in offen if e["key"] not in self.skipped]
            if not rest:  # alles zurueckgestellt -> Runde neu beginnen
                self.skipped.clear()
                rest = offen
            entry = rest[0] if rest else None
        if entry is not None:
            roh = entry_text(self.settings, entry)
            entry = dict(entry, _raw=roh, _optionen=options_of(entry, roh))
        verbleibend = len([e for e in offen if e["key"] not in self.skipped])
        self._send(ui.klick(entry, verbleibend, self._guard()))

    def _register(self, suche: str) -> None:
        index = chain.build_index(self.settings)
        items = chain.register_entries(self.settings, index)
        needle = suche.strip().lower()
        if needle:
            items = [
                e for e in items
                if needle in (f"{e['key']} {e['title']} {e['decision_field_raw']} "
                              f"{e['question']}").lower()
            ]
        self._send(ui.register(items, suche))

    # -- POST --------------------------------------------------------------
    def do_POST(self) -> None:  # noqa: N802
        try:
            form = self._form()
            if self.path == "/api/decide":
                self._decide(form)
            elif self.path == "/api/new":
                self._new(form)
            elif self.path == "/api/intake":
                self._intake()
            else:
                self._send(ui.meldung("Nicht gefunden", self.path, "/", "Übersicht"), 404)
        except (writer.WriteError, chain.ChainError) as exc:
            self._send(ui.meldung("Nicht geschrieben", str(exc), "/klick", "Weiter"), 409)
        except Exception:  # noqa: BLE001
            traceback.print_exc()
            self._send(ui.meldung("Fehler", traceback.format_exc(limit=3), "/", "Übersicht"), 500)

    def _decide(self, form: dict[str, str]) -> None:
        if blocker := self._guard():
            raise writer.WriteError(blocker)
        key, choice = form.get("key", ""), form.get("choice", "").strip()
        if not key or not choice:
            raise writer.WriteError("Ohne ID und Auswahl wird nichts eingetragen.")
        index = chain.build_index(self.settings)
        entry = chain.find(index, key)
        if entry is None:
            raise writer.WriteError(f"{key} steht nicht in der Kette.")
        note = form.get("note", "").strip()
        ergebnis = writer.fill_decision(
            self.settings, Path(entry["source_path"]), entry["source_line"], choice, note)
        writer.append_done(self.settings, entry, choice, note)
        self.skipped.discard(key)
        try:
            chain.refresh_artifacts(self.settings)
        except Exception:  # noqa: BLE001 -- Index ist abgeleitet, die Kette zaehlt
            traceback.print_exc()
        print(f"  ENTSCHIEDEN {key} -> {ergebnis['value']} "
              f"({Path(ergebnis['file']).name}:{ergebnis['line']})")
        self._antwort("/klick", {"ok": True, "id": entry["id"], **ergebnis})

    def _new(self, form: dict[str, str]) -> None:
        if blocker := self._guard():
            raise writer.WriteError(blocker)
        title = form.get("title", "").strip()
        if not title:
            raise writer.WriteError("Ohne Titel wird nichts eingestellt.")
        index = chain.build_index(self.settings)
        entry_id = chain.next_id(index)
        ziel = chain.target_part(self.settings)
        optionen = [ln.strip() for ln in form.get("optionen", "").splitlines() if ln.strip()]
        rendered = writer.render_entry(
            entry_id, title,
            quelle=form.get("quelle", "").strip(),
            frage=form.get("frage", "").strip(),
            optionen=optionen,
            empfehlung=form.get("empfehlung", "").strip(),
            kontext=form.get("kontext", ""),
            scope=form.get("scope", "").strip(),
        )
        ergebnis = writer.append_entry(self.settings, ziel, rendered)
        try:
            chain.refresh_artifacts(self.settings)
        except Exception:  # noqa: BLE001
            traceback.print_exc()
        print(f"  EINGESTELLT {entry_id} -> {ziel.name}")
        self._antwort(f"/klick?key={entry_id}",
                      {"ok": True, "id": entry_id, "titel": title, **ergebnis})

    def _intake(self) -> None:
        """Desktop-Postfach in die Kette übernehmen (ausdrücklich ausgelöst)."""
        if blocker := self._guard():
            raise writer.WriteError(blocker)
        ergebnis = intake.takeover(self.settings)
        for eintrag in ergebnis:
            print(f"  UEBERNOMMEN {eintrag['id']} -> {eintrag['ziel']}")
        self._antwort("/", {"ok": True, "uebernommen": ergebnis})


def serve(settings: Settings | None = None) -> None:
    settings = settings or load()
    Handler.settings = settings
    Handler.skipped = set()
    httpd = ThreadingHTTPServer((settings.host, settings.port), Handler)
    url = f"http://{settings.host}:{settings.port}"
    print("=" * 52)
    print("  Decision-Clicker")
    print("=" * 52)
    print(f"  Kette : {settings.chain_dir}")
    print(f"  URL   : {url}")
    try:
        index = chain.build_index(settings)
        werte = chain.counts(index)
        print(f"  Offen : {werte['offen']} Entscheidungen warten auf dich")
    except chain.ChainError as exc:
        print(f"  WARNUNG: {exc}")
    print("  Strg+C beendet den Server.")
    print("=" * 52)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n  Beendet.")
    finally:
        httpd.server_close()
