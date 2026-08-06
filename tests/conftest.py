# SPDX-License-Identifier: MIT
"""Testfixtures: gearbeitet wird ausschliesslich auf KOPIEN der echten Kette.

Kein Test fasst `C:\\Users\\User\\OneDrive\\...\\_DECISIONS` an. Die Kopie ist
trotzdem echt — nur so beweist der Roundtrip-Test etwas ueber die echten
Dateien (CRLF in Teil 4, LF in Teil 1-3, gemischte Eintragsstile).
"""
from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from decision_clicker.config import DEFAULT_CHAIN, Settings

QUELLE = DEFAULT_CHAIN


def pytest_configure(config):
    config.addinivalue_line("markers", "echt: braucht die echte Kette als Vorlage")


@pytest.fixture(scope="session")
def hat_kette() -> bool:
    return QUELLE.is_dir() and (QUELLE / "_tools" / "decisions_index.py").is_file()


@pytest.fixture
def kette(tmp_path: Path, hat_kette: bool) -> Settings:
    """Vollstaendige Kopie der echten Kette in einem Temp-Ordner."""
    if not hat_kette:
        pytest.skip(f"Echte Kette nicht vorhanden: {QUELLE}")
    ziel = tmp_path / "_DECISIONS"
    shutil.copytree(
        QUELLE, ziel,
        ignore=shutil.ignore_patterns("__pycache__", ".pytest_cache", "*.pyc"),
    )
    return Settings(chain_dir=ziel)


@pytest.fixture
def original_bytes(kette: Settings) -> dict[str, bytes]:
    """Byte-Abzug aller Kettendateien VOR dem Test.

    Schluessel ist der RELATIVE Pfad, nicht der Dateiname: `README.md` gibt es
    sowohl in der Wurzel als auch in `_tools/`.
    """
    return {
        p.relative_to(kette.chain_dir).as_posix(): p.read_bytes()
        for p in sorted(kette.chain_dir.rglob("*"))
        if p.is_file() and p.suffix in (".txt", ".md")
    }
