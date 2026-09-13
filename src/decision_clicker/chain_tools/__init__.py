# SPDX-License-Identifier: MIT
"""Die Werkzeuge, die eine Entscheidungskette in ihrem ``_tools/`` braucht.

README.md §5 verlangt von jeder Kette ein ``_tools/decisions_index.py``, das dem
``decisions.index/1``-Parservertrag entspricht. Bisher *verlangte* dieses Paket die
Datei nur -- geliefert hat sie niemand. Wer eine Kette aufsetzte, kopierte sie von
Hand aus einer anderen Kette, und genau daraus entstand die Drift, die am
2026-09-13 gefunden wurde: eine 1.3.0-Vollkopie in ``tests/data/chain/_tools/``
neben einem 1.4.0-Original, ohne dass eine der beiden Seiten davon wusste
(T-20260913-152165341).

Deshalb liegen die beiden Werkzeuge jetzt **hier** und nur hier:

``decisions_index.py``
    Parser und Berichtsgenerator. Liest das eine kanonische Aktivdokument
    read-only und erzeugt ``decisions.index.json`` plus ``INDEX-REPORT.md``.
``decisions_db.py``
    Legt dieselben Eintraege zusaetzlich in eine lokale SQLite-Datei ausserhalb
    von OneDrive. Dupliziert den Parser NICHT, sondern laedt ihn.

Beide Dateien sind so geschrieben, dass sie in **zwei Rollen** funktionieren:
als importierbares Paketmodul und als materialisiertes Einzelskript in
``<kette>/_tools/``. Das ist die Bedingung dafuer, dass Quelle und Materialisierung
byteidentisch sein koennen -- waeren es zwei Varianten, waere die Drift wieder da.

``materialize()`` schreibt sie in eine Kette, ``check()`` sagt, ob eine bereits
materialisierte Kette noch dem Paketstand entspricht. Ab dann ist ``_tools/`` eine
**Projektion**, kein Quellort.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path

#: Die Dateien, die eine Kette in ihrem ``_tools/`` braucht.
WERKZEUGE = ("decisions_index.py", "decisions_db.py")

#: Wird beim Materialisieren ueber die Datei gelegt -- unmittelbar nach der
#: Shebang-Zeile, damit sie ausfuehrbar bleibt. Ohne diesen Kopf sieht die Kopie
#: aus wie das Original, und genau daran ist die letzte Drift entstanden.
BANNER = """\
# ============================================================================
# MATERIALISIERTE KOPIE -- NICHT HIER BEARBEITEN
# ============================================================================
# Quelle: decision_clicker.chain_tools (Paket decision-clicker)
# Erzeugt mit: decision-clicker chain-tools
#
# Aenderungen gehoeren ins Paket, nicht in diese Datei. Eine Bearbeitung hier
# wird beim naechsten `chain-tools --force` ueberschrieben und faellt bis dahin
# niemandem auf -- das ist die Drift, die dieses Verfahren beenden soll.
# Pruefen, ob diese Kette noch aktuell ist: `decision-clicker chain-tools --check`
# ============================================================================
"""


class MaterializeError(RuntimeError):
    """Das Ziel laesst sich nicht sicher beschreiben."""


@dataclass(frozen=True)
class Befund:
    """Zustand einer Datei in der Kette gegenueber dem Paketstand."""

    name: str
    zustand: str  # "aktuell" | "veraltet" | "fehlt"

    @property
    def ok(self) -> bool:
        return self.zustand == "aktuell"


def _quelle(name: str) -> str:
    return (Path(__file__).resolve().parent / name).read_text(encoding="utf-8")


def _mit_banner(text: str) -> str:
    """Banner hinter die Shebang-Zeile setzen, sonst an den Anfang."""
    if text.startswith("#!"):
        kopf, _, rest = text.partition("\n")
        return f"{kopf}\n{BANNER}{rest}"
    return BANNER + text


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def check(kette: Path) -> list[Befund]:
    """Vergleicht ``<kette>/_tools/`` mit dem Paketstand. Schreibt nichts."""
    ziel = Path(kette) / "_tools"
    befunde = []
    for name in WERKZEUGE:
        datei = ziel / name
        if not datei.is_file():
            befunde.append(Befund(name, "fehlt"))
            continue
        ist = datei.read_text(encoding="utf-8").replace("\r\n", "\n")
        soll = _mit_banner(_quelle(name)).replace("\r\n", "\n")
        befunde.append(Befund(name, "aktuell" if _sha(ist) == _sha(soll) else "veraltet"))
    return befunde


def materialize(kette: Path, *, force: bool = False) -> list[Path]:
    """Schreibt die Werkzeuge nach ``<kette>/_tools/``.

    Ohne ``force`` wird eine vorhandene, abweichende Datei NICHT ueberschrieben:
    Sie koennte eine Handaenderung tragen, die noch niemand ins Paket geholt hat.
    Lieber ein Fehler als ein stiller Verlust.
    """
    ziel = Path(kette) / "_tools"
    ziel.mkdir(parents=True, exist_ok=True)
    geschrieben = []
    for befund in check(kette):
        if befund.ok:
            continue
        if befund.zustand == "veraltet" and not force:
            raise MaterializeError(
                f"{ziel / befund.name} weicht vom Paketstand ab. Erst pruefen, ob die "
                f"Abweichung ins Paket gehoert; danach mit --force ueberschreiben."
            )
        datei = ziel / befund.name
        datei.write_text(_mit_banner(_quelle(befund.name)), encoding="utf-8", newline="\n")
        geschrieben.append(datei)
    return geschrieben
