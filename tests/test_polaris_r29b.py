# SPDX-License-Identifier: MIT
"""Polaris: Nachbesserungen nach dem Folge-Review R29b (Commit-Pflicht, Recovery journalisiert,
Fehlerpfade, Pfadwurzel, OneDrive-Wiederholungen, Journal-Validierung, echter Prozessabbruch)."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import textwrap
import time
from pathlib import Path

import pytest
from fake_lead import FakeLead
from test_polaris import SERVER_WORKER, expire_local_claims, first_open, service_env
from test_polaris_r29 import (
    ACTIVE,
    decide_with_loss,
    journals,
    make_link,
    next_op,
    plant_journal,
)

from decision_clicker import chain, journal, star, writer
from decision_clicker.api import DecisionClicker
from decision_clicker.config import Settings
from decision_clicker.errors import StarUnavailable

SRC = Path(__file__).resolve().parent.parent / "src"


# ---------------------------------------------------------------------------
# 1: commit_marker == False -> fail-closed, Journal bleibt
# ---------------------------------------------------------------------------
def test_commit_marker_with_a_foreign_open_journal_is_false_or_raises_and_keeps_it(kette):
    with star.transaction(kette) as tx:
        plant_journal(kette, "cafebabe")
        assert tx.commit_marker() is False
        with pytest.raises(StarUnavailable) as err:
            tx.commit_marker(required=True)
        assert err.value.reason == "journal_open"
    assert len(journals(kette)) == 1


def test_decide_with_a_foreign_journal_keeps_its_own_journal(kette, monkeypatch):
    real = journal.Journal.advance

    def advance(self, step):
        real(self, step)
        if step == "remove":
            plant_journal(kette, "cafebabe")  # ein fremdes Journal taucht vor dem Commit auf

    monkeypatch.setattr(journal.Journal, "advance", advance)
    with pytest.raises(StarUnavailable) as err:
        DecisionClicker(kette.chain_dir).decide(first_open(kette)["key"], "A")
    assert err.value.reason == "journal_open"
    assert len(journals(kette)) == 2  # das eigene Journal wurde NICHT geloescht


# ---------------------------------------------------------------------------
# 3: Fehlerpfade loeschen das Journal nur mit Beweis
# ---------------------------------------------------------------------------
def test_error_after_chain_writes_keeps_the_journal(kette, monkeypatch):
    real = journal.Journal.advance

    def advance(self, step):
        real(self, step)
        if step == "remove":
            raise RuntimeError("Fehler nach dem Kettenschreiben")

    monkeypatch.setattr(journal.Journal, "advance", advance)
    with pytest.raises(RuntimeError):
        DecisionClicker(kette.chain_dir).decide(first_open(kette)["key"], "A")
    assert len(journals(kette)) == 1  # Kette weder vorher noch zurueckgerollt: Beleg bleibt


def test_clean_rollback_closes_the_journal_and_leaves_a_consistent_chain(kette, monkeypatch):
    def broken(*args, **kwargs):
        raise ValueError("remove scheitert")

    monkeypatch.setattr(writer, "remove_entry", broken)
    with pytest.raises(ValueError):
        DecisionClicker(kette.chain_dir).decide(first_open(kette)["key"], "A")
    monkeypatch.undo()
    assert not journals(kette)  # Rollback vermerkt (aborted), Kette bewiesen, Journal weg
    next_op(kette)
    assert chain.build_index(kette)["active_contract"]["valid"] is True


def test_aborted_journal_left_behind_is_removed_by_the_next_holder(kette, monkeypatch):
    real = journal.Journal.mark_aborted

    def crash_after_mark(self):
        real(self)
        raise KeyboardInterrupt  # Prozess endet nach dem Rollback-Vermerk, vor dem Loeschen

    def broken(*args, **kwargs):
        raise ValueError("remove scheitert")

    with monkeypatch.context() as patch:
        patch.setattr(writer, "remove_entry", broken)
        patch.setattr(journal.Journal, "mark_aborted", crash_after_mark)
        with pytest.raises(KeyboardInterrupt):
            DecisionClicker(kette.chain_dir).decide(first_open(kette)["key"], "A")
    assert len(journals(kette)) == 1
    next_op(kette)
    assert not journals(kette)


# ---------------------------------------------------------------------------
# 4: _try_acquire gibt bei JEDER Ausnahme frei
# ---------------------------------------------------------------------------
def test_service_releases_the_hold_on_any_exception_from_classify(kette, monkeypatch):
    fake = FakeLead(ttl=30, server_workers={SERVER_WORKER})
    service_env(monkeypatch, fake)
    plant_journal(kette)
    calls = {"n": 0}
    real = journal._classify

    def classify(*args):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("unerwartet")
        return real(*args)

    monkeypatch.setattr(journal, "_classify", classify)
    try:
        service = writer.start_star_service(kette)
        assert service.status()["held"] is False and "unerwartet" in service.status()["error"]
        assert fake.claim is None
    finally:
        writer.stop_star_service(kette)
        fake.stop()


# ---------------------------------------------------------------------------
# 6: Pfadwurzel
# ---------------------------------------------------------------------------
def test_parent_link_of_the_chain_dir_is_allowed_and_resolved_once(kette, tmp_path):
    parent = tmp_path / "echt"
    parent.mkdir()
    real_chain = parent / "_DECISIONS"
    kette.chain_dir.rename(real_chain)
    alias = tmp_path / "OneDrive"
    make_link(alias, parent)  # wie ~/OneDrive -> ~/Library/CloudStorage/...
    settings = Settings(chain_dir=alias / "_DECISIONS")
    assert settings.chain_dir == Path(os.path.realpath(real_chain))
    assert DecisionClicker(settings.chain_dir).decide(first_open(settings)["key"], "A")["ok"]
    assert (real_chain / "DECIDED-AND-DONE.md").read_text(encoding="utf-8-sig").count("POLARIS-STAR:") >= 1


# ---------------------------------------------------------------------------
# 7: OneDrive-Sharing-Verletzungen
# ---------------------------------------------------------------------------
def test_replace_is_retried_on_permission_error_and_then_succeeds(kette, monkeypatch):
    real = os.replace
    calls = {"n": 0}

    def flaky(src, dst):
        calls["n"] += 1
        if calls["n"] <= 3:
            raise PermissionError("Sharing-Verletzung")
        return real(src, dst)

    assert sum(writer._RETRY_PAUSES) < 3
    monkeypatch.setattr(writer, "_RETRY_PAUSES", (0.01,) * 5)
    with writer.chain_transaction(kette):
        monkeypatch.setattr(os, "replace", flaky)
        writer._write(kette, kette.chain_dir / ACTIVE, "neu\n", False)
        monkeypatch.undo()
    assert calls["n"] == 4 and (kette.chain_dir / ACTIVE).read_text(encoding="utf-8") == "neu\n"
    assert not list(kette.chain_dir.rglob("*" + star.TMP_SUFFIX))


def test_persistent_permission_error_fails_closed_and_the_leftover_tmp_is_swept_next_time(kette, monkeypatch):
    before = (kette.chain_dir / ACTIVE).read_bytes()
    monkeypatch.setattr(writer, "_RETRY_PAUSES", (0.01,) * 5)
    real_unlink = Path.unlink

    def stuck(self, *args, **kwargs):
        if self.name.endswith(star.TMP_SUFFIX):
            raise PermissionError("gesperrt")
        return real_unlink(self, *args, **kwargs)

    def never(src, dst):
        raise PermissionError("Sharing-Verletzung")

    with writer.chain_transaction(kette):
        with monkeypatch.context() as patch:
            patch.setattr(os, "replace", never)
            patch.setattr(Path, "unlink", stuck)
            with pytest.raises(PermissionError):
                writer._write(kette, kette.chain_dir / ACTIVE, "neu\n", False)
    assert (kette.chain_dir / ACTIVE).read_bytes() == before  # fail-closed: Ziel unveraendert
    assert len(list(kette.chain_dir.rglob("*" + star.TMP_SUFFIX))) == 1  # tmp blieb liegen
    foreign = kette.chain_dir / f"{ACTIVE}.0badf00d-11223344@anderer-host{star.TMP_SUFFIX}"
    foreign.write_text("fremd", encoding="utf-8")
    next_op(kette)  # naechster Erwerb raeumt nur eigene tmp-Dateien abgeschlossener Transaktionen auf
    assert list(kette.chain_dir.rglob("*" + star.TMP_SUFFIX)) == [foreign]


# ---------------------------------------------------------------------------
# 8: Journal-Laden validiert Typen und Schrittfolge
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("changes", [
    {"steps": ["done", "fill", "remove"]},
    {"steps": ["fill", "done"]},
    {"op": "unbekannt"},
    {"done": ["done"]},
    {"done": "fill"},
    {"done": ["fill"], "hashes_after": {}},
    {"hashes_before": {"x": "y"}},
    {"hashes_before": None},
    {"params": []},
    {"entry_id": 7},
    {"pending": {"step": "fill", "file": "../boese", "hash": "0" * 64}},
    {"pending": "fill"},
    {"aborted": {"TO-DECIDE-USER.txt": 5, "DECIDED-AND-DONE.md": None}},
])
def test_journal_validation_rejects_wrong_types_and_step_order(kette, changes):
    plant_journal(kette, **changes)  # neu signiert: nur die Validierung kann es fangen
    with pytest.raises(StarUnavailable) as err:
        next_op(kette)
    assert err.value.reason == "journal_corrupt"


# ---------------------------------------------------------------------------
# 2 und 9: echter Prozessabbruch (os._exit im Kindprozess)
# ---------------------------------------------------------------------------
CHILD = textwrap.dedent('''
    import os, sys
    from pathlib import Path
    sys.path.insert(0, sys.argv[1])
    from decision_clicker import writer
    from decision_clicker.api import DecisionClicker
    from decision_clicker.config import Settings
    chain_dir, mode, target, action, key = Path(sys.argv[2]), sys.argv[3], sys.argv[4], sys.argv[5], sys.argv[6]
    real = os.replace
    hits = {"n": 0}
    def replace(src, dst):
        if Path(dst).name == target:
            hits["n"] += 1
            if hits["n"] == int(sys.argv[7]):
                if mode == "before":
                    os._exit(3)   # tmp geschrieben, nicht ersetzt
                real(src, dst)
                os._exit(4)       # ersetzt, Fortschrittsvermerk fehlt
        return real(src, dst)
    os.replace = replace
    if action == "decide":
        DecisionClicker(chain_dir).decide(key, "B")
    else:
        with writer.chain_transaction(Settings(chain_dir=chain_dir)):
            pass
    os._exit(0)
''')


def run_child(kette: Settings, mode: str, target: str, action: str, key: str = "", nth: int = 1) -> int:
    env = dict(os.environ, PYTHONPATH=str(SRC), PYTHONIOENCODING="utf-8")
    done = subprocess.run([sys.executable, "-c", CHILD, str(SRC), str(kette.chain_dir), mode, target, action,
                           key, str(nth)], env=env, capture_output=True, text=True, timeout=60)
    assert done.returncode in (3, 4), done.stderr
    return done.returncode


def test_process_killed_before_replace_leaves_the_chain_intact_and_recovery_discards(kette):
    DecisionClicker(kette.chain_dir).decide(first_open(kette)["key"], "A")
    key = first_open(kette)["key"]
    before = (kette.chain_dir / ACTIVE).read_bytes()
    assert run_child(kette, "before", ACTIVE, "decide", key) == 3
    assert (kette.chain_dir / ACTIVE).read_bytes() == before and len(journals(kette)) == 1
    assert list(kette.chain_dir.rglob("*" + star.TMP_SUFFIX))  # Reststueck des toten Prozesses
    expire_local_claims()  # die Frist des toten Halters laeuft ab
    next_op(kette)
    assert not journals(kette) and (kette.chain_dir / ACTIVE).read_bytes() == before
    next_op(kette)  # der naechste Erwerb raeumt das Reststueck auf (eigener Host, abgeschlossene Transaktion)
    assert not list(kette.chain_dir.rglob("*" + star.TMP_SUFFIX))


def test_process_killed_after_replace_is_completed_by_the_next_holder(kette):
    DecisionClicker(kette.chain_dir).decide(first_open(kette)["key"], "A")
    key = first_open(kette)["key"]
    assert run_child(kette, "after", ACTIVE, "decide", key) == 4  # "fill" ersetzt, Vermerk fehlt
    assert len(journals(kette)) == 1
    expire_local_claims()
    next_op(kette)
    assert not journals(kette)
    assert all(e["key"] != key for e in chain.open_entries(chain.build_index(kette)))
    assert "recovers=" in kette.done_file.read_text(encoding="utf-8-sig")


@pytest.mark.parametrize("mode", ["before", "after"])
def test_process_killed_in_the_middle_of_the_roll_forward_is_finished_by_a_second_recovery(kette, monkeypatch, mode):
    decide_with_loss(kette, monkeypatch, nth=4)  # "fill" geschrieben, Vermerk fehlt: Recovery steht an
    key_done = json.loads(journals(kette)[0].read_text(encoding="utf-8"))["entry_id"]
    expire_local_claims()
    # Die Recovery selbst stirbt beim Ersetzen von DECIDED-AND-DONE.md (Schritt "done")
    assert run_child(kette, mode, "DECIDED-AND-DONE.md", "recover") == (3 if mode == "before" else 4)
    data = json.loads(journals(kette)[0].read_text(encoding="utf-8"))
    assert data["pending"]["step"] == "done"  # die Recovery hat ihren Schritt vorab journalisiert
    expire_local_claims()
    time.sleep(0.05)
    next_op(kette)  # zweite Recovery schliesst ab
    assert not journals(kette)
    assert all(e["id"] != key_done for e in chain.open_entries(chain.build_index(kette)))
    text = kette.done_file.read_text(encoding="utf-8-sig")
    assert len(chain.DONE_HEADING_RE.findall(text)) == len({m for m in chain.DONE_HEADING_RE.findall(text)})
    assert key_done in text  # genau ein Beleg je ID, keine Doppelschreibung durch die zweite Recovery
