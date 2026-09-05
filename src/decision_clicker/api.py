# SPDX-License-Identifier: MIT
"""Konsumenten-Fassade der Kernlogik — GUI-unabhaengig.

Alles, was eine Oberflaeche vom Decision-Clicker braucht, in einer Klasse mit
einfachen Typen (dict/list/str). Wer diese Fassade benutzt, muss weder die
Kettendateien noch `chain`/`writer`/`intake` kennen.

Konsumenten:
  * die mitgelieferte Mini-Oberflaeche (`decision_clicker.server`),
  * das Panel P10 der ellmos Unified GUI (ueber deren `DecisionsAdapter`),
  * CLI und HTTP-API dieses Pakets.

Die TXT-Kette bleibt in allen Faellen die Quelle der Wahrheit; diese Fassade
haelt keinen eigenen Zustand und liest bei jedem Aufruf frisch.
"""
from __future__ import annotations

from pathlib import Path

from . import chain, intake, ui, writer
from .config import Settings, load

__all__ = ["DecisionClicker", "ProposalSubmitter", "ChainError", "WriteError"]

ChainError = chain.ChainError
WriteError = writer.WriteError


def _settings_for(chain_dir: str | Path | None) -> Settings:
    settings = load()
    if chain_dir:
        from dataclasses import replace
        settings = replace(settings, chain_dir=Path(chain_dir).expanduser())
    return settings


def _submit_proposal(
    settings: Settings, title: str, *, frage: str = "", optionen: list[str] | None = None,
    empfehlung: str = "", kontext: str = "", quelle: str = "", scope: str = "",
    evidenzanker: list[str] | None = None, gegenbelege: list[str] | None = None,
    fehlende_informationen: list[str] | None = None, erstellt_von: str = "",
    kontext_fingerprint: str = "",
) -> dict:
    """Nur einen offenen Vorschlag schreiben; keine Antwort-/Done-Fähigkeit."""
    with writer.MUTATION_LOCK:
        fremde = writer.foreign_locks(settings)
        if fremde:
            raise WriteError(
                f"Fremde Sperre im Entscheidungsordner ({', '.join(p.name for p in fremde)}) "
                "— es wird nicht geschrieben."
            )
        if not (title or "").strip():
            raise WriteError("Ohne Titel wird nichts eingestellt.")
        index = chain.build_index(settings)
        chain.require_valid_contract(index)
        entry_id = chain.next_id(index)
        ziel = chain.target_part(settings)
        rendered = writer.render_entry(
            entry_id, title.strip(), quelle=quelle.strip(), frage=frage.strip(),
            optionen=[o for o in (optionen or []) if o.strip()],
            empfehlung=empfehlung.strip(), kontext=kontext, scope=scope.strip(),
            evidenzanker=evidenzanker, gegenbelege=gegenbelege,
            fehlende_informationen=fehlende_informationen,
            erstellt_von=erstellt_von, kontext_fingerprint=kontext_fingerprint,
        )
        ergebnis = writer.append_entry(settings, ziel, rendered)
        try:
            chain.refresh_artifacts(settings)
        except Exception:  # noqa: BLE001 -- Kette ist kanonisch, Index abgeleitet
            pass
        return {"ok": True, "id": entry_id, "title": title.strip(), **ergebnis}


def options_of(entry: dict, raw: str) -> list[tuple[str, str]]:
    """Optionen aus dem VOLLTEXT lesen, nicht aus dem Index-Auszug.

    Der Index kuerzt `options_excerpt` auf 400 Zeichen; bei ausfuehrlichen
    Eintraegen fiel dadurch die letzte Option unter den Tisch und war nicht
    waehlbar (belegt an D-20260806-001). Genommen wird die laengere Lesart.
    """
    aus_volltext: list[tuple[str, str]] = []
    for option in intake.collect_options(raw.splitlines()):
        buchstabe, _, text = option.partition(" — ")
        if text:
            aus_volltext.append((buchstabe.strip().upper(), text.strip()))
    aus_auszug = ui.parse_options(entry.get("options_excerpt", ""))
    return aus_volltext if len(aus_volltext) >= len(aus_auszug) else aus_auszug


class DecisionClicker:
    """Fassade auf eine Entscheidungskette."""

    def __init__(self, chain_dir: str | Path | None = None) -> None:
        self.settings = _settings_for(chain_dir)

    # ------------------------------------------------------------------
    # Lesen
    # ------------------------------------------------------------------
    def usable(self) -> bool:
        """Ist die Kette JETZT bedienbar? Wirft nie — fuer probe()-Aufrufer."""
        try:
            index = chain.build_index(self.settings)
            chain.require_valid_contract(index)
            return True
        except Exception:  # noqa: BLE001
            return False

    def status(self) -> dict:
        index = chain.build_index(self.settings)
        return {
            "chain_dir": str(self.settings.chain_dir),
            "counts": chain.counts(index),
            "active_contract": index.get("active_contract", {}),
            "next_id": chain.next_id(index),
            "target_file": chain.target_part(self.settings).name,
            "intake_pending": len(self.intake_pending()),
            "foreign_locks": [p.name for p in writer.foreign_locks(self.settings)],
        }

    def open_entries(self) -> list[dict]:
        return chain.open_entries(chain.build_index(self.settings))

    def detail(self, key: str) -> dict:
        """Ein Eintrag mit Volltext und aufgeloesten Optionen."""
        entry = chain.find(chain.build_index(self.settings), key)
        if entry is None:
            raise WriteError(f"{key} steht nicht in der Kette.")
        roh = self.raw_text(entry)
        return dict(entry, raw=roh,
                    optionen=[{"letter": b, "text": t} for b, t in options_of(entry, roh)],
                    recommended=self.recommended_letter(entry))

    def raw_text(self, entry: dict) -> str:
        path = Path(entry["source_path"])
        if not path.is_file():
            return entry.get("question", "")
        lines = path.read_text(encoding="utf-8-sig").splitlines(keepends=True)
        try:
            start, end = writer.entry_bounds(self.settings, lines, entry["source_line"])
        except WriteError:
            return entry.get("question", "")
        return "".join(lines[start:end]).strip()

    @staticmethod
    def recommended_letter(entry: dict) -> str:
        treffer = ui.RECOMMENDED_RE.match((entry.get("recommendation_excerpt") or "").strip())
        return treffer.group(1).upper() if treffer else ""

    def register(self, query: str = "") -> list[dict]:
        index = chain.build_index(self.settings)
        eintraege = chain.register_entries(self.settings, index)
        needle = query.strip().lower()
        if not needle:
            return eintraege
        return [
            e for e in eintraege
            if needle in (f"{e['key']} {e['title']} {e['decision_field_raw']} "
                          f"{e.get('question', '')}").lower()
        ]

    # ------------------------------------------------------------------
    # Schreiben — jeder Weg sichert vorher und respektiert fremde Sperren
    # ------------------------------------------------------------------
    def _guard(self) -> None:
        fremde = writer.foreign_locks(self.settings)
        if fremde:
            raise WriteError(
                f"Fremde Sperre im Entscheidungsordner ({', '.join(p.name for p in fremde)}) "
                "— es wird nicht geschrieben.")

    def decide(self, key: str, choice: str, note: str = "") -> dict:
        """Entscheidung belegen und sofort aus der Aktivvorlage entfernen."""
        with writer.MUTATION_LOCK:
            self._guard()
            if not (choice or "").strip():
                raise WriteError("Ohne Auswahl wird nichts eingetragen.")
            index = chain.build_index(self.settings)
            chain.require_valid_contract(index)
            entry = chain.find(index, key)
            if entry is None:
                if any(item["id"] == key and item["status"] == "aktiv"
                       for item in chain.clicker_history(self.settings)):
                    raise WriteError(f"{key} ist bereits entschieden und nicht mehr aktiv.")
                raise WriteError(f"{key} steht nicht in der Kette.")
            if entry.get("decision_ready") is not True:
                raise WriteError(f"{key} ist nicht entscheidungsreif aktiv.")
            ergebnis = writer.decide_entry(self.settings, entry, choice, note)
            self._refresh()
            return {"ok": True, "id": entry["id"], "key": key, **ergebnis}

    # ------------------------------------------------------------------
    # Verlauf & Rueckgaengig
    # ------------------------------------------------------------------
    def history(self) -> list[dict]:
        """Vom Clicker getroffene Entscheidungen, juengste zuerst."""
        return chain.clicker_history(self.settings)

    def undo(self, key: str, reason: str = "Klicker-Oberfläche, rückgängig gemacht") -> dict:
        """Einen Klick rueckgaengig machen — nur fuer clicker-eigene Entscheidungen.

        Die Entscheidung erscheint danach wieder als offen (`open_entries()`);
        der urspruengliche Beleg bleibt stehen und bekommt zusaetzlich einen
        ZURUECKGESETZT-Vermerk.
        """
        with writer.MUTATION_LOCK:
            self._guard()
            entry = next(
                (item for item in chain.clicker_history(self.settings)
                 if item["id"] == key and item["status"] == "aktiv"),
                None,
            )
            if entry is None:
                raise WriteError(
                    f"{key} hat keinen offenen Clicker-Beleg — extern entschieden "
                    "oder bereits zurückgesetzt, nicht rückgängig machbar.")
            ergebnis = writer.undo_decision(self.settings, entry, reason)
            self._refresh()
            return ergebnis

    def create(self, title: str, *, frage: str = "", optionen: list[str] | None = None,
               empfehlung: str = "", kontext: str = "", quelle: str = "",
               scope: str = "", evidenzanker: list[str] | None = None,
               gegenbelege: list[str] | None = None,
               fehlende_informationen: list[str] | None = None,
               erstellt_von: str = "", kontext_fingerprint: str = "") -> dict:
        """Neue Entscheidung konventionsgemaess in die KETTE einstellen."""
        return _submit_proposal(
            self.settings, title, frage=frage, optionen=optionen, empfehlung=empfehlung,
            kontext=kontext, quelle=quelle, scope=scope, evidenzanker=evidenzanker,
            gegenbelege=gegenbelege, fehlende_informationen=fehlende_informationen,
            erstellt_von=erstellt_von, kontext_fingerprint=kontext_fingerprint,
        )

    # ------------------------------------------------------------------
    # Desktop-Postfach
    # ------------------------------------------------------------------
    def intake_pending(self) -> list[dict]:
        try:
            return intake.takeover(self.settings, dry_run=True)
        except (OSError, ChainError, WriteError):
            return []

    def intake_apply(self) -> list[dict]:
        with writer.MUTATION_LOCK:
            self._guard()
            return intake.takeover(self.settings)

    def intake_sources(self) -> list[str]:
        return [str(p) for p in intake.sources(self.settings)]

    # ------------------------------------------------------------------
    def _refresh(self) -> None:
        """Abgeleitete Artefakte nachziehen — Fehler kippen keine Entscheidung."""
        try:
            chain.refresh_artifacts(self.settings)
        except Exception:  # noqa: BLE001
            pass


class ProposalSubmitter:
    """Schmale Grenze für KI-, Memory- und Policy-Kandidaten.

    Dieser Adapter kann ausschließlich offene Vorschläge einstellen. Er bietet
    absichtlich weder ``decide``/``done`` noch ``undo``. Menschliche UI-Adapter
    verwenden für einen sichtbaren Klick weiterhin :class:`DecisionClicker`.
    """

    def __init__(self, chain_dir: str | Path | None = None) -> None:
        self._settings = _settings_for(chain_dir)

    def submit(self, title: str, *, frage: str = "", optionen: list[str] | None = None,
               empfehlung: str = "", kontext: str = "", quelle: str = "",
               scope: str = "", evidenzanker: list[str] | None = None,
               gegenbelege: list[str] | None = None,
               fehlende_informationen: list[str] | None = None,
               erstellt_von: str = "", kontext_fingerprint: str = "") -> dict:
        return _submit_proposal(
            self._settings, title, frage=frage, optionen=optionen, empfehlung=empfehlung,
            kontext=kontext, quelle=quelle, scope=scope,
            evidenzanker=evidenzanker, gegenbelege=gegenbelege,
            fehlende_informationen=fehlende_informationen,
            erstellt_von=erstellt_von, kontext_fingerprint=kontext_fingerprint,
        )
