# SPDX-License-Identifier: MIT
"""Polaris: Nachbesserungen nach dem Zweitmodell-Review R29 (Festlegungen 1 bis 8).

Fixture-Ketten in tmp, LocalStar (SQLite im tmp-Statusordner) und ``fake_lead``; nie eine echte Kette.
"""
from __future__ import annotations

import json
import os
import sqlite3
import subprocess
import sys
import threading
import time
from types import SimpleNamespace

import pytest
from fake_lead import FakeLead
from test_polaris import (  # noqa: F401  (Fixtures und Helfer der Polaris-Suite)
    SERVER_WORKER,
    expire_local_claims,
    first_open,
    hand_edit,
    server_lead,
    service_env,
    snapshot,
)

from decision_clicker import chain, journal, star, writer
from decision_clicker.api import DecisionClicker
from decision_clicker.config import Settings, state_dir
from decision_clicker.errors import StarLost, StarUnavailable, WriteError

ACTIVE = "TO-DECIDE-USER.txt"


def local_row() -> tuple:
    conn = sqlite3.connect(str(state_dir() / "star.db"))
    try:
        return conn.execute("SELECT resource_version, inflight FROM local_star").fetchone()
    finally:
        conn.close()


def lose_star_at(monkeypatch, nth: int) -> None:
    """Sternverlust beim n-ten Guard-Aufruf (1 Journal, 2 intend, 3 Schreiben, 4 Fortschrittsvermerk, ...)."""
    real = star.Transaction.assert_valid
    counter = {"n": 0}

    def failing(self, margin=None):
        counter["n"] += 1
        if counter["n"] >= nth:
            expire_local_claims()
            raise StarLost("injiziert")
        return real(self, margin)

    monkeypatch.setattr(star.Transaction, "assert_valid", failing)


def decide_with_loss(kette: Settings, monkeypatch, nth: int) -> str:
    key = first_open(kette)["key"]
    DecisionClicker(kette.chain_dir).decide(key, "A")  # erster Commit setzt einen Stand
    key = first_open(kette)["key"]
    with monkeypatch.context() as patch:
        lose_star_at(patch, nth)
        with pytest.raises(StarLost):
            DecisionClicker(kette.chain_dir).decide(key, "B")
    return key


def journals(kette: Settings) -> list:
    folder = kette.chain_dir / star.JOURNAL_DIR
    return sorted(folder.glob("*.json")) if folder.is_dir() else []


def next_op(kette: Settings) -> None:
    with writer.chain_transaction(kette):
        pass


# ---------------------------------------------------------------------------
# R29-1: Commit-Marker vor dem Loeschen des Journals; Journal ausserhalb des Manifests
# ---------------------------------------------------------------------------
def test_journal_is_outside_the_manifest(kette):
    before = star.chain_manifest(kette)
    folder = kette.chain_dir / star.JOURNAL_DIR
    folder.mkdir()
    (folder / "x.json").write_text("{}", encoding="utf-8")
    assert star.chain_manifest(kette) == before
    assert star.JOURNAL_DIR not in star.CHAIN_PATHS


def test_commit_marker_is_reported_before_the_journal_is_deleted(kette, monkeypatch):
    seen = {}
    real_close = journal.Journal.close

    def close(self):
        seen["row"], seen["manifest"] = local_row(), star.chain_manifest(kette)
        real_close(self)

    monkeypatch.setattr(journal.Journal, "close", close)
    DecisionClicker(kette.chain_dir).decide(first_open(kette)["key"], "A")
    assert seen["row"] == (seen["manifest"], 0)  # Stand gemeldet, In-flight geloescht, Journal noch da
    assert not journals(kette)


def test_failed_commit_marker_keeps_the_journal_and_the_next_holder_finishes(kette, monkeypatch):
    DecisionClicker(kette.chain_dir).decide(first_open(kette)["key"], "A")
    key = first_open(kette)["key"]
    real = star.Transaction.commit_marker

    def failing(self, ignore=None):
        if ignore is not None:
            expire_local_claims()
            raise StarLost("injiziert")
        return real(self, ignore)

    with monkeypatch.context() as patch:
        patch.setattr(star.Transaction, "commit_marker", failing)
        with pytest.raises(StarLost):
            DecisionClicker(kette.chain_dir).decide(key, "B")
    assert len(journals(kette)) == 1 and local_row()[1] == 1  # In-flight offen, Wiederherstellungsdaten da
    next_op(kette)
    assert not journals(kette)
    assert local_row() == (star.chain_manifest(kette), 0)


def test_journal_without_inflight_marker_is_deleted_only_when_chain_equals_target(kette, monkeypatch):
    DecisionClicker(kette.chain_dir).decide(first_open(kette)["key"], "A")
    with monkeypatch.context() as patch:  # Commit gelungen, nur das Loeschen scheitert
        patch.setattr(journal.Journal, "close", lambda self: (_ for _ in ()).throw(OSError("injiziert")))
        with pytest.raises(OSError):
            DecisionClicker(kette.chain_dir).decide(first_open(kette)["key"], "B")
    assert len(journals(kette)) == 1 and local_row()[1] == 0
    next_op(kette)
    assert not journals(kette)


# ---------------------------------------------------------------------------
# R29-2: Recovery nur mit Beweis, sonst warten
# ---------------------------------------------------------------------------
def test_delayed_chain_copy_waits_and_never_discards_then_recovers(kette, monkeypatch):
    original_active = (kette.chain_dir / ACTIVE).read_bytes()
    DecisionClicker(kette.chain_dir).decide(first_open(kette)["key"], "A")
    key = decide_with_loss(kette, monkeypatch, nth=4)  # "fill" geschrieben, Fortschrittsvermerk fehlt
    synced = (kette.chain_dir / ACTIVE).read_bytes()
    (kette.chain_dir / ACTIVE).write_bytes(original_active)  # verzoegerte Kopie: Stand VOR der Transaktion
    with pytest.raises(StarUnavailable) as err:
        next_op(kette)
    assert err.value.reason == "journal_unmatched" and len(journals(kette)) == 1
    (kette.chain_dir / ACTIVE).write_bytes(synced)  # Kopie ist angekommen
    next_op(kette)
    assert not journals(kette)
    assert all(e["key"] != key for e in chain.open_entries(chain.build_index(kette)))
    assert "recovers=" in kette.done_file.read_text(encoding="utf-8-sig")


def test_journal_newer_than_the_chain_waits(kette, monkeypatch):
    decide_with_loss(kette, monkeypatch, nth=6)  # "fill" vermerkt, "done" fehlt
    before_done = kette.done_file.read_bytes()
    jfile = journals(kette)[0]
    data = json.loads(jfile.read_text(encoding="utf-8"))
    assert data["done"] == ["fill"]
    # Journal ist weiter als die lokale Kette: Aktivdatei auf den Stand VOR "fill" zuruecksetzen
    (kette.chain_dir / ACTIVE).write_text("# andere Kopie\n", encoding="utf-8")
    with pytest.raises(StarUnavailable) as err:
        next_op(kette)
    assert err.value.reason == "journal_unmatched" and kette.done_file.read_bytes() == before_done


def test_discard_only_when_nothing_was_written(kette, monkeypatch):
    decide_with_loss(kette, monkeypatch, nth=3)  # Verlust vor dem ersten Kettenschreiben
    assert len(journals(kette)) == 1
    next_op(kette)  # alle Hashes == vorher: nachweislich nichts geschrieben
    assert not journals(kette)


def test_orphan_partial_journal_is_not_deleted(kette, monkeypatch):
    decide_with_loss(kette, monkeypatch, nth=6)
    data = journal.open_journals(kette)[0]
    tx = SimpleNamespace(via="manifest")
    with pytest.raises(StarUnavailable) as err:
        journal._classify(kette, tx, data)
    assert err.value.reason == "journal_unmatched"


def test_inflight_marker_without_local_journal_is_journal_not_synced(kette, server_lead, monkeypatch):  # noqa: F811
    DecisionClicker(kette.chain_dir).decide(first_open(kette)["key"], "A")
    server_lead.version, server_lead.inflight = star.inflight_version("abcd1234"), True
    with pytest.raises(StarUnavailable) as err:
        next_op(kette)
    assert err.value.reason == "journal_not_synced"
    assert server_lead.events == []


# ---------------------------------------------------------------------------
# R29-3: Dienst fail-closed, stop() nimmt den Mutation-Lock
# ---------------------------------------------------------------------------
def test_service_recovery_failure_releases_the_hold(kette, monkeypatch):
    fake = FakeLead(ttl=30, server_workers={SERVER_WORKER})
    service_env(monkeypatch, fake)
    calls = {"n": 0}

    def failing(settings, tx):
        calls["n"] += 1
        if calls["n"] == 1:
            raise StarUnavailable("Recovery injiziert")

    monkeypatch.setattr(journal, "recover", failing)
    try:
        service = writer.start_star_service(kette)
        status = service.status()
        assert status["held"] is False and "Recovery injiziert" in status["error"]
        assert fake.claim is None  # Hold geloest, nicht gehalten
        with pytest.raises(StarUnavailable, match="nur lesbar"):
            DecisionClicker(kette.chain_dir).create("x", frage="f", optionen=["A — a"])
        deadline = time.time() + 15
        while time.time() < deadline and not service.status()["held"]:
            time.sleep(0.2)
        assert service.status()["held"]  # der Heartbeat versucht es erneut
    finally:
        writer.stop_star_service(kette)
        fake.stop()


def test_service_stop_waits_for_the_mutation_lock(kette, monkeypatch):
    fake = FakeLead(ttl=30, server_workers={SERVER_WORKER})
    service_env(monkeypatch, fake)
    try:
        service = writer.start_star_service(kette)
        assert service.status()["held"]
        entered, release = threading.Event(), threading.Event()

        def hold_lock():
            with writer.MUTATION_LOCK:
                entered.set()
                release.wait(10)

        holder = threading.Thread(target=hold_lock)
        holder.start()
        entered.wait(5)
        stopper = threading.Thread(target=service.stop)
        stopper.start()
        time.sleep(0.6)
        assert stopper.is_alive() and fake.claim is not None  # laufende Transaktion wird abgewartet
        release.set()
        holder.join(5)
        stopper.join(10)
        assert not stopper.is_alive() and fake.claim is None
    finally:
        star._services.pop(str(kette.chain_dir), None)
        fake.stop()


# ---------------------------------------------------------------------------
# R29-4: rebaseline mit Stabilitaetsfenster
# ---------------------------------------------------------------------------
def test_default_stability_window_is_60_seconds(kette, monkeypatch):
    monkeypatch.delenv("DECISION_CLICKER_REBASELINE_WINDOW")
    monkeypatch.setenv("DECISION_CLICKER_LEAD_URL", "http://127.0.0.1:1")
    monkeypatch.setenv("DECISION_CLICKER_DEVICE_TOKEN", "t")
    assert star.resolve(kette).stable_seconds == 60.0
    monkeypatch.setenv("DECISION_CLICKER_REBASELINE_WINDOW", "7")
    assert star.resolve(kette).stable_seconds == 7.0


def test_rebaseline_after_a_stable_window_reports_old_and_new_hash(kette, server_lead, monkeypatch):  # noqa: F811
    monkeypatch.setenv("DECISION_CLICKER_REBASELINE_WINDOW", "0.4")
    dc = DecisionClicker(kette.chain_dir)
    dc.decide(first_open(kette)["key"], "A")
    old = server_lead.version
    hand_edit(kette)
    started = time.monotonic()
    assert dc.create("y", frage="f", optionen=["A — a"])["ok"]
    assert time.monotonic() - started >= 0.4
    assert server_lead.events == ["rebaseline_external_change"]
    assert server_lead.event_details[-1]["previous_version"] == old
    assert server_lead.event_details[-1]["new_version"] != old


def test_rebaseline_is_refused_while_the_chain_still_changes(kette, server_lead, monkeypatch):  # noqa: F811
    monkeypatch.setenv("DECISION_CLICKER_REBASELINE_WINDOW", "0.6")
    dc = DecisionClicker(kette.chain_dir)
    dc.decide(first_open(kette)["key"], "A")
    hand_edit(kette)
    stop = threading.Event()

    def keep_syncing():  # teilweise Kopie: die Datei wird weiter beschrieben
        while not stop.is_set():
            with (kette.chain_dir / ACTIVE).open("ab") as handle:
                handle.write(b"\n")
            time.sleep(0.1)

    worker = threading.Thread(target=keep_syncing)
    worker.start()
    try:
        with pytest.raises(StarUnavailable) as err:
            dc.create("y", frage="f", optionen=["A — a"])
    finally:
        stop.set()
        worker.join()
    assert err.value.reason == "rebaseline_unstable" and server_lead.events == []


def test_no_rebaseline_with_an_open_journal(kette, server_lead):  # noqa: F811
    dc = DecisionClicker(kette.chain_dir)
    dc.decide(first_open(kette)["key"], "A")
    folder = kette.chain_dir / star.JOURNAL_DIR
    folder.mkdir(exist_ok=True)
    data = {"schema": journal.SCHEMA, "txid": "deadbeef", "op": "decide", "entry_id": "D-20260101-001",
            "hashes_before": {}, "hashes_after": {}, "steps": ["fill"], "done": [], "params": {}}
    data["checksum"] = journal._checksum(data)
    (folder / "deadbeef.json").write_text(json.dumps(data), encoding="utf-8")
    hand_edit(kette)
    with pytest.raises(StarUnavailable) as err:
        dc.create("y", frage="f", optionen=["A — a"])
    assert err.value.reason == "journal_open" and server_lead.events == []


# ---------------------------------------------------------------------------
# R29-5 steht im BACH-Test test_ensure_adds_missing_columns_additively_and_idempotently
# R29-6: Transport
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("url,ok", [
    ("https://lead.example.org", True), ("http://127.0.0.1:8000", True), ("http://localhost:8000", True),
    ("http://[::1]:8000", True), ("http://100.119.69.90:8000", True), ("http://100.64.0.1", True),
    ("http://100.127.255.254", True), ("http://mac-studio.tail1234.ts.net:8000", True),
    ("http://100.63.255.255", False), ("http://100.128.0.1", False), ("http://192.168.1.5:8000", False),
    ("http://lead.example.org", False), ("http://ts.net.evil.org", False), ("ftp://127.0.0.1", False),
    ("127.0.0.1:8000", False), ("http://", False)])
def test_transport_policy(url, ok):
    assert star.transport_ok(url) is ok


def test_plain_http_to_an_external_lead_is_refused_and_the_token_never_shows(kette, monkeypatch):
    secret = "geheim-token-xyz"
    monkeypatch.setenv("DECISION_CLICKER_LEAD_URL", "http://lead.example.org")
    monkeypatch.setenv("DECISION_CLICKER_DEVICE_TOKEN", secret)
    with pytest.raises(StarUnavailable, match="https://") as err:
        star.resolve(kette)
    assert secret not in str(err.value)
    monkeypatch.setenv("DECISION_CLICKER_LEAD_URL", "https://lead.example.org")
    cfg = star.resolve(kette)
    assert cfg.kind == "server" and secret not in repr(cfg) and secret not in str(star.describe(kette))


# ---------------------------------------------------------------------------
# R29-7: Scope
# ---------------------------------------------------------------------------
def make_link(link, target) -> None:
    """Junction (Windows, ohne Rechte) oder Symlink."""
    if sys.platform == "win32":
        done = subprocess.run(["cmd", "/c", "mklink", "/J", str(link), str(target)], capture_output=True)
        if done.returncode != 0:
            pytest.skip("Junction nicht anlegbar")
    else:
        os.symlink(target, link, target_is_directory=True)


def test_link_inside_the_chain_scope_is_refused_even_with_a_star(kette, tmp_path):
    outside = tmp_path / "ausserhalb"
    outside.mkdir()
    make_link(kette.chain_dir / "_archive", outside)
    target = kette.chain_dir / "_archive" / "x.md"
    with writer.chain_transaction(kette):
        with pytest.raises(WriteError, match="Symlink oder Junction"):
            writer._write(kette, target, "boese", False)
        with pytest.raises(WriteError):
            writer._unlink(kette, target)
    assert list(outside.iterdir()) == []
    with pytest.raises(WriteError):  # ohne Stern ebenso
        writer._write(kette, target, "boese", False)
    assert list(outside.iterdir()) == []


def test_path_reaching_the_chain_through_a_link_is_refused(kette, tmp_path):
    alias = tmp_path / "alias"
    make_link(alias, kette.chain_dir)
    with writer.chain_transaction(kette):
        with pytest.raises(WriteError):
            writer._write(kette, alias / ACTIVE, "boese", False)


def test_backup_root_must_not_lie_inside_the_chain(kette, tmp_path):
    with pytest.raises(WriteError, match="Kettenordner"):
        Settings(chain_dir=kette.chain_dir, backup_root=kette.chain_dir / "bak")
    assert Settings(chain_dir=kette.chain_dir, backup_root=tmp_path / "bak").backup_dir == tmp_path / "bak"


def test_lock_files_stay_outside_the_manifest(kette):
    before = star.chain_manifest(kette)
    (kette.chain_dir / "LOCK.fremd.txt").write_text("fremder Agent", encoding="utf-8")
    assert star.chain_manifest(kette) == before


# ---------------------------------------------------------------------------
# R29-8: Atomik, korruptes Journal, Rundlaeufe
# ---------------------------------------------------------------------------
def test_abort_between_tmp_and_replace_leaves_the_target_untouched(kette, monkeypatch):
    before = snapshot(kette)
    manifest = star.chain_manifest(kette)

    def broken(src, dst):
        raise OSError("Prozessabbruch injiziert")

    with writer.chain_transaction(kette):
        monkeypatch.setattr(os, "replace", broken)
        with pytest.raises(OSError):
            writer._write(kette, kette.chain_dir / ACTIVE, "neuer Inhalt", False)
        monkeypatch.undo()
    assert snapshot(kette) == before and not list(kette.chain_dir.rglob("*" + star.TMP_SUFFIX))
    assert star.chain_manifest(kette) == manifest


def test_leftover_tmp_files_do_not_count_to_the_manifest(kette):
    before = star.chain_manifest(kette)
    (kette.chain_dir / "_decision-archive" / ("x.md.1234abcd" + star.TMP_SUFFIX)).write_text("halb", encoding="utf-8")
    assert star.chain_manifest(kette) == before


@pytest.mark.parametrize("damage", ["truncate", "tamper", "garbage"])
def test_corrupt_journal_fails_closed(kette, monkeypatch, damage):
    decide_with_loss(kette, monkeypatch, nth=6)
    jfile = journals(kette)[0]
    raw = jfile.read_text(encoding="utf-8")
    if damage == "truncate":
        jfile.write_text(raw[: len(raw) // 2], encoding="utf-8")
    elif damage == "tamper":
        jfile.write_text(raw.replace('"fill"', '"done"', 1), encoding="utf-8")
    else:
        jfile.write_bytes(b"\x00\xff nicht json")
    before = snapshot(kette)
    with pytest.raises(StarUnavailable) as err:
        next_op(kette)
    assert err.value.reason == "journal_corrupt" and snapshot(kette) == before  # nur lesbar, kein Raten


def test_journal_is_written_atomically_with_checksum(kette, monkeypatch):
    decide_with_loss(kette, monkeypatch, nth=6)
    data = json.loads(journals(kette)[0].read_text(encoding="utf-8"))
    assert data["checksum"] == journal._checksum(data) and set(data["hashes_before"]) == {ACTIVE, "DECIDED-AND-DONE.md"}
    assert not list(kette.chain_dir.rglob("*" + star.TMP_SUFFIX))


def test_decide_undo_roundtrip_keeps_the_original_block_and_parser_contracts(kette):
    dc = DecisionClicker(kette.chain_dir)
    tool = chain._load_index_tool(kette.index_script)
    entry = first_open(kette)
    original_block = dc.raw_text(entry)
    ids_before = sorted(e["id"] for e in tool.build_index(kette.chain_dir)["entries"] if e["domain"] == "active")
    dc.decide(entry["key"], "B", "Rundlauf")
    dc.undo(entry["key"])
    after = tool.build_index(kette.chain_dir)
    assert sorted(e["id"] for e in after["entries"] if e["domain"] == "active") == ids_before
    restored = next(e for e in chain.open_entries(chain.build_index(kette)) if e["id"] == entry["id"])
    assert dc.raw_text(restored) == original_block  # Byte fuer Byte
    assert chain.build_index(kette)["active_contract"]["valid"] is True
    text = kette.done_file.read_text(encoding="utf-8-sig")
    assert text.count("POLARIS-STAR:") >= 2  # Stempel im Beleg und im Rueckgaengig-Vermerk
