# SPDX-License-Identifier: MIT
"""Testfixtures: gearbeitet wird ausschliesslich auf KOPIEN der echten Kette.

Kein Test fasst `C:\\Users\\User\\OneDrive\\...\\_DECISIONS` an. Die Kopie ist
trotzdem echt — nur so beweist der Roundtrip-Test etwas ueber die echten
Dateien (CRLF in Teil 4, LF in Teil 1-3, gemischte Eintragsstile).
"""
from __future__ import annotations

import re
import shutil
from pathlib import Path

import pytest

from decision_clicker import intake
from decision_clicker.config import DEFAULT_CHAIN, Settings

QUELLE = DEFAULT_CHAIN
POSTFACH_VORLAGE = Path(__file__).parent / "data" / "postfach_2026-08-07.txt"


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


@pytest.fixture
def postfach(tmp_path: Path, monkeypatch) -> Path:
    """Eingefrorener Originalstand des Desktop-Postfachs — zum Erkennen."""
    kopie = tmp_path / "TO-DECIDE-USER.txt"
    shutil.copy2(POSTFACH_VORLAGE, kopie)
    monkeypatch.setattr(intake, "DEFAULT_SOURCES", (kopie,))
    return kopie


@pytest.fixture
def frisches_postfach(tmp_path: Path, monkeypatch) -> Path:
    """Derselbe Stand mit unverbrauchten IDs — zum Uebernehmen.

    Die Original-IDs liegen inzwischen in der echten Kette; ein Uebernahmetest
    darauf traefe nur noch den Dedup-Zweig. Umdatiert wird von 2026 auf 2099
    unter Beibehaltung von Monat, Tag und laufender Nummer — Struktur und
    Formate bleiben exakt die der echten Datei.
    """
    kopie = tmp_path / "TO-DECIDE-USER.txt"
    roh = POSTFACH_VORLAGE.read_bytes().decode("utf-8-sig")
    kopie.write_bytes(re.sub(r"D-2026(\d{4})-", r"D-2099\1-", roh).encode("utf-8"))
    monkeypatch.setattr(intake, "DEFAULT_SOURCES", (kopie,))
    return kopie
