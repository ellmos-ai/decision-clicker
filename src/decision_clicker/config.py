# SPDX-License-Identifier: MIT
"""Pfade und Grundeinstellungen des Decision-Clickers.

Alles ist ueber Umgebungsvariablen ueberschreibbar, damit die Tests gegen
Kopien laufen koennen und niemals gegen die echte Kette.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

DEFAULT_CHAIN = Path(r"C:\Users\User\OneDrive\.TOPICS\_control-center\_DECISIONS")
DEFAULT_PORT = 8096
DEFAULT_HOST = "127.0.0.1"

# Neue Entscheidungen wandern immer in den letzten Kettenteil, solange er nicht
# ueberlaeuft. Cut-and-Clue greift ab dieser Zeilenzahl (Regel im Kettenkopf).
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
        return self.chain_dir / "LOCK.opus.decision-clicker.txt"


def load() -> Settings:
    return Settings(
        chain_dir=Path(os.environ.get("DECISION_CLICKER_CHAIN", str(DEFAULT_CHAIN))),
        host=os.environ.get("DECISION_CLICKER_HOST", DEFAULT_HOST),
        port=int(os.environ.get("DECISION_CLICKER_PORT", str(DEFAULT_PORT))),
    )
