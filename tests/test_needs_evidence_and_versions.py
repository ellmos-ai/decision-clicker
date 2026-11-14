# SPDX-License-Identifier: MIT
"""Synthetische Regressionen für Klärungsstatus und Versionsbelege."""
from __future__ import annotations

from pathlib import Path

import pytest

from decision_clicker import __main__ as cli
from decision_clicker import chain, ui, writer
from decision_clicker.api import DecisionClicker
from decision_clicker.chain_tools import materialize
from decision_clicker.config import Settings


def _synthetic_chain(tmp_path: Path, active: str) -> Settings:
    root = tmp_path / "_DECISIONS"
    materialize(root)
    (root / "TO-DECIDE-USER.txt").write_text(active, encoding="utf-8")
    (root / "DECIDED-AND-DONE.md").write_text(
        "# Synthetisches Entscheidungsregister\n", encoding="utf-8")
    return Settings(chain_dir=root)


def test_needs_evidence_bleibt_sichtbar_aber_unklickbar(tmp_path: Path) -> None:
    settings = _synthetic_chain(
        tmp_path,
        """D-20990101-001 — Widersprüchliche Vorlage

STATUS: needs_evidence
EVIDENZSTAND: Review-unklar
ENTSCHEIDUNG DES USERS: [HIER EINTRAGEN]

---
""",
    )

    index = chain.build_index(settings)
    entry = chain.find(index, "D-20990101-001")
    assert entry is not None
    assert entry["status_class"] == chain.STATUS_NEEDS_EVIDENCE
    assert entry["needs_evidence"] is True
    assert entry["decision_ready"] is False
    assert index["active_contract"]["valid"] is True
    assert chain.open_entries(index) == []
    assert chain.needs_evidence_entries(index) == [entry]
    assert chain.counts(index)["needs_evidence"] == 1

    clicker = DecisionClicker(settings.chain_dir)
    with pytest.raises(writer.WriteError, match="nicht entscheidungsreif"):
        clicker.decide(entry["key"], "A")

    html = ui.home(chain.counts(index), [], klaerung=[entry]).decode("utf-8")
    assert "Klärung nötig" in html
    assert entry["key"] in html
    assert f'/klick?key={entry["key"]}' not in html


def test_proposal_status_sanitizes_answered_state_but_allows_clarification(
    tmp_path: Path,
) -> None:
    settings = _synthetic_chain(tmp_path, "")
    (settings.chain_dir / "TO-DECIDE-USER.txt").write_text("", encoding="utf-8")

    clicker = DecisionClicker(settings.chain_dir)
    clarification = clicker.create(
        "Noch zu klären",
        status="needs_evidence",
        evidenzstand="widersprüchliche Quelle",
    )
    index = chain.build_index(settings)
    assert chain.find(index, clarification["id"])["status_class"] == chain.STATUS_NEEDS_EVIDENCE
    assert clarification["id"] not in {item["key"] for item in chain.open_entries(index)}

    safe_open = clicker.create(
        "Nur Vorschlag",
        frage="Welche Variante?",
        optionen=["A — ja", "B — nein"],
        status="DONE",
    )
    safe_entry = chain.find(chain.build_index(settings), safe_open["id"])
    assert safe_entry["status_class"] == chain.STATUS_OPEN
    assert "STATUS: DONE" not in Path(safe_entry["source_path"]).read_text(encoding="utf-8")


def test_cli_trägt_klärungsstatus_und_versionen_in_den_kanon(tmp_path: Path, capsys) -> None:
    settings = _synthetic_chain(tmp_path, "")
    assert cli.main([
        "add", "CLI-Klärung", "--status", "needs_evidence",
        "--optionen-version", "2", "--empfehlung-version", "4",
        "--evidenzstand", "Review-CLI", "--chain", str(settings.chain_dir), "--json",
    ]) == 0
    result = capsys.readouterr().out
    assert '"ok": true' in result
    index = chain.build_index(settings)
    entry = next(item for item in index["entries"] if item["title"] == "CLI-Klärung")
    assert entry["status_class"] == chain.STATUS_NEEDS_EVIDENCE
    assert entry["optionen_version"] == "2"
    assert entry["empfehlung_version"] == "4"


def test_versions_evidenzstand_stale_click_and_undo_are_provenance_bound(
    tmp_path: Path,
) -> None:
    settings = _synthetic_chain(tmp_path, "")
    clicker = DecisionClicker(settings.chain_dir)
    created = clicker.create(
        "Versionierte Auswahl",
        frage="Welche Variante?",
        optionen=["A — erster Weg", "B — zweiter Weg"],
        empfehlung="A — prüfbarer",
        optionen_version=2,
        empfehlung_version=3,
        evidenzstand="Review-2026-09-20",
    )

    index = chain.build_index(settings)
    entry = chain.find(index, created["id"])
    assert entry is not None
    assert entry["optionen_version"] == "2"
    assert entry["empfehlung_version"] == "3"
    assert entry["evidenzstand"] == "Review-2026-09-20"
    reference = entry["version_reference"]
    detail = clicker.detail(entry["key"])
    assert "OPTIONEN-VERSION: 2" in detail["raw"]
    assert "EMPFEHLUNG-VERSION: 3" in detail["raw"]
    assert "EVIDENZSTAND: Review-2026-09-20" in detail["raw"]
    assert detail["version_reference"] == reference

    html = ui.klick(
        dict(detail, _raw=detail["raw"], _optionen=[("A", "erster Weg"), ("B", "zweiter Weg")]),
        1,
        confirmation="synthetic-confirmation",
    ).decode("utf-8")
    assert reference in html
    assert 'name="version_reference"' in html

    path = Path(entry["source_path"])
    changed = path.read_text(encoding="utf-8").replace(
        "OPTIONEN-VERSION: 2", "OPTIONEN-VERSION: 4", 1
    ).replace(
        "EMPFEHLUNG: A — prüfbarer", "EMPFEHLUNG: B — neu geprüft", 1
    )
    path.write_text(changed, encoding="utf-8")
    with pytest.raises(writer.WriteError, match="veraltete"):
        clicker.decide(created["id"], "A", version_reference=reference)

    current = chain.find(chain.build_index(settings), created["id"])
    fresh_reference = current["version_reference"]
    clicker.decide(created["id"], "A", version_reference=fresh_reference)
    done = settings.done_file.read_text(encoding="utf-8")
    assert "OPTIONEN-VERSION: 4" in done
    assert "EMPFEHLUNG-VERSION: 3" in done
    assert "EVIDENZSTAND: Review-2026-09-20" in done
    assert fresh_reference in done

    clicker.undo(created["id"], "synthetischer Versions-Undo")
    restored = chain.find(chain.build_index(settings), created["id"])
    assert restored is not None
    assert restored["version_reference"] == fresh_reference
    assert restored["status_class"] == chain.STATUS_OPEN
