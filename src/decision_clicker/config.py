# SPDX-License-Identifier: MIT
"""Pfade und Grundeinstellungen des Decision-Clickers.

Alle Pfade sind über Umgebungsvariablen überschreibbar. Der neutrale
Fallback leitet den OneDrive-Ordner aus der Laufzeitumgebung ab und enthält
keinen Benutzer- oder Hostnamen.
"""
from __future__ import annotations

import ipaddress
import os
from dataclasses import dataclass
from pathlib import Path

DEFAULT_PORT = 8096
DEFAULT_HOST = "127.0.0.1"


def is_loopback_host(host: str) -> bool:
    """Nur explizite Loopback-Adressen sind fuer den Mini-Server zulaessig."""
    candidate = host.strip().lower()
    if candidate == "localhost":
        return True
    try:
        return ipaddress.ip_address(candidate).is_loopback
    except ValueError:
        return False


def default_onedrive_root() -> Path:
    """Best-effort-OneDrive-Wurzel ohne hostspezifischen Pfad.

    Windows setzt üblicherweise eine der OneDrive-Variablen. Für lokale
    Standardinstallationen und macOS existieren neutrale Fallbacks. Bei
    abweichender Ablage bleibt ``DECISION_CLICKER_CHAIN`` der eindeutige Weg.
    """
    candidates: list[Path] = []
    for name in ("OneDrive", "OneDriveCommercial", "OneDriveConsumer"):
        if value := os.environ.get(name):
            candidates.append(Path(value).expanduser())
    home = Path.home()
    candidates.extend([
        home / "OneDrive",
        home / "Library" / "CloudStorage" / "OneDrive-Personal",
    ])
    for candidate in candidates:
        if candidate.is_dir():
            return candidate
    return candidates[0]


DEFAULT_CHAIN = default_onedrive_root() / ".TOPICS" / "_control-center" / "_DECISIONS"

# Neue Entscheidungen wandern immer in den letzten Kettenteil, solange er nicht
# überläuft. Cut-and-Clue greift ab dieser Zeilenzahl (Regel im Kettenkopf).
CUT_AND_CLUE_LINES = 900


@dataclass(frozen=True)
class Settings:
    chain_dir: Path
    host: str = DEFAULT_HOST
    port: int = DEFAULT_PORT

    @property
    def tools_dir(self) -> Path:
        return self.chain_dir / "_tools"

    @property
    def index_script(self) -> Path:
        return self.tools_dir / "decisions_index.py"

    @property
    def done_file(self) -> Path:
        return self.chain_dir / "DECIDED-AND-DONE.md"

    @property
    def archive_dir(self) -> Path:
        return self.chain_dir / "_decision-archive"

    @property
    def backup_dir(self) -> Path:
        return self.archive_dir / "_bak"

    @property
    def lock_file(self) -> Path:
        return self.chain_dir / "LOCK.decision-clicker.txt"


def load() -> Settings:
    return Settings(
        chain_dir=Path(os.environ.get("DECISION_CLICKER_CHAIN", str(DEFAULT_CHAIN))),
        host=os.environ.get("DECISION_CLICKER_HOST", DEFAULT_HOST),
        port=int(os.environ.get("DECISION_CLICKER_PORT", str(DEFAULT_PORT))),
    )
