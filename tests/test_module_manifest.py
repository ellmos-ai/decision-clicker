# SPDX-License-Identifier: MIT
"""Vertragstest fuer ellmos-module.v2.json (Ticket T-20260824-474639761)."""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "ellmos-module.v2.json"


def test_manifest_exists_and_is_valid_json():
    assert MANIFEST.is_file(), "ellmos-module.v2.json fehlt"
    data = json.loads(MANIFEST.read_text(encoding="utf-8"))
    assert data["schema"] == "ellmos.module.v2"
    assert data["id"] == "decision-clicker"


def test_manifest_stays_private_until_the_publication_gate_opens():
    """PRIVATE.txt gate: solange es existiert, muss visibility 'private' bleiben."""
    data = json.loads(MANIFEST.read_text(encoding="utf-8"))
    if (ROOT / "PRIVATE.txt").exists():
        assert data["visibility"] == "private"


def test_manifest_declares_policy_registry_as_an_optional_data_seam():
    """decision-clicker bleibt manuell startbar: keine feste Bundle-Bindung."""
    data = json.loads(MANIFEST.read_text(encoding="utf-8"))
    assert "policy.registry" in data["optional"]
    assert "policy.registry" not in data["requires"]
    seams = [a for a in data["adapters"] if a.get("target") == "policy-registry"]
    assert len(seams) == 1
    assert seams[0]["type"] == "seam"
    assert seams[0]["status"] == "optional"


def test_manifest_version_matches_pyproject():
    try:
        import tomllib
    except ModuleNotFoundError:  # pragma: no cover - Python < 3.11
        import tomli as tomllib

    with (ROOT / "pyproject.toml").open("rb") as handle:
        pyproject = tomllib.load(handle)

    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    assert manifest["version"] == pyproject["project"]["version"]
