# SPDX-License-Identifier: MIT
"""Selbstständige Test-Fixtures für eine synthetische Entscheidungskette.

Kein Test liest oder verändert persönliche Entscheidungsdaten. Die Fixture
bildet den veröffentlichten Parser-Vertrag und mehrere Eintragsstile ab.
"""
from __future__ import annotations

import re
import shutil
from pathlib import Path

import pytest

from decision_clicker import intake
from decision_clicker.config import Settings

DATEN = Path(__file__).parent / "data"
KETTEN_VORLAGE = DATEN / "chain"
POSTFACH_VORLAGE = DATEN / "postfach_sample.txt"


@pytest.fixture
def kette(tmp_path: Path) -> Settings:
    """Vollständige Kopie der synthetischen Vertrags-Fixture."""
    ziel = tmp_path / "_DECISIONS"
    shutil.copytree(KETTEN_VORLAGE, ziel)
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
    """Synthetisches Postfach mit beiden unterstützten Eintragsformaten."""
    kopie = tmp_path / "TO-DECIDE-USER.txt"
    shutil.copy2(POSTFACH_VORLAGE, kopie)
    monkeypatch.setattr(intake, "DEFAULT_SOURCES", (kopie,))
    return kopie


@pytest.fixture
def frisches_postfach(tmp_path: Path, monkeypatch) -> Path:
    """Derselbe Stand mit unverbrauchten IDs — zum Übernehmen.

    Die 2026-IDs liegen bereits in der synthetischen Kette und prüfen den
    Dedup-Zweig. Für Übernahmetests werden sie deterministisch auf 2099
    umdatiert; Struktur und Formate bleiben identisch.
    """
    kopie = tmp_path / "TO-DECIDE-USER.txt"
    roh = POSTFACH_VORLAGE.read_bytes().decode("utf-8-sig")
    kopie.write_bytes(re.sub(r"D-2026(\d{4})-", r"D-2099\1-", roh).encode("utf-8"))
    monkeypatch.setattr(intake, "DEFAULT_SOURCES", (kopie,))
    return kopie
