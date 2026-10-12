# SPDX-License-Identifier: MIT
"""Pfade und Grundeinstellungen des Decision-Clickers.

Alle Pfade sind über Umgebungsvariablen überschreibbar. Der neutrale
Fallback leitet den OneDrive-Ordner aus der Laufzeitumgebung ab und enthält
keinen Benutzer- oder Hostnamen.
"""
from __future__ import annotations

import hashlib
import ipaddress
import os
from dataclasses import dataclass
from pathlib import Path

from .errors import WriteError

DEFAULT_PORT = 8096
DEFAULT_HOST = "127.0.0.1"


def is_loopback_host(host: str) -> bool:
    """Nur explizite Loopback-Adressen sind fuer den Mini-Server zulaessig."""
    candidate = host.strip().lower().strip("[]")
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


def default_onedrive_chain() -> Path:
    root = default_onedrive_root()
    candidates = [
        root / ".TOPICS" / "_control-center" / "_CONTROL" / "_DECISIONS",
        root / ".TOPICS" / "_control-center" / "_DECISIONS",
    ]
    for candidate in candidates:
        if candidate.is_dir():
            return candidate
    return candidates[0]


DEFAULT_CHAIN = default_onedrive_chain()


def state_dir() -> Path:
    """Nutzerordner ausserhalb der Kette (Backups, LocalStar-Datenbank)."""
    return Path(os.environ.get("DECISION_CLICKER_STATE_DIR") or Path.home() / ".decision-clicker")

# Ab dieser Länge warnt die Oberfläche vor einer Bestandsbereinigung. Der
# Ein-Dokument-Aktivvertrag erlaubt dennoch keinen nummerierten Folgeteil.
ACTIVE_DOCUMENT_WARNING_LINES = 900


@dataclass(frozen=True)
class Settings:
    chain_dir: Path
    host: str = DEFAULT_HOST
    port: int = DEFAULT_PORT
    backup_root: Path | None = None

    def __post_init__(self) -> None:
        """R29-7: Sicherungen duerfen nicht im Kettenordner liegen (sie waeren Kettenmutationen)."""
        if self.backup_root is not None:
            def norm(value: Path) -> Path:
                return Path(os.path.normcase(os.path.realpath(value)))
            try:
                norm(self.backup_root).relative_to(norm(self.chain_dir))
            except ValueError:
                return
            raise WriteError(f"backup_root {self.backup_root} liegt im Kettenordner — nicht erlaubt.")

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
        """Sicherungen landen NIE im Kettenordner (Polaris: Backups sind keine Kettenmutation)."""
        if self.backup_root is not None:
            return self.backup_root
        key = hashlib.sha256(str(Path(self.chain_dir)).encode("utf-8")).hexdigest()[:12]
        return state_dir() / "backups" / key

    @property
    def lock_file(self) -> Path:
        return self.chain_dir / "LOCK.decision-clicker.txt"


def load() -> Settings:
    return Settings(
        chain_dir=Path(os.environ.get("DECISION_CLICKER_CHAIN", str(DEFAULT_CHAIN))),
        host=os.environ.get("DECISION_CLICKER_HOST", DEFAULT_HOST),
        port=int(os.environ.get("DECISION_CLICKER_PORT", str(DEFAULT_PORT))),
        backup_root=Path(os.environ["DECISION_CLICKER_BACKUP_ROOT"]) if os.environ.get(
            "DECISION_CLICKER_BACKUP_ROOT") else None,
    )
