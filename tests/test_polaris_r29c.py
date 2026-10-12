# SPDX-License-Identifier: MIT
"""Polaris: Nachbesserungen nach R29c (Sweep mit Link-Guard und Worker-ID, Journal-Validierung,
Heartbeat-Lock, Operatorpfad ``polaris journal``, Registry-Schluessel)."""
from __future__ import annotations

import json
import sys
import threading

import pytest
from fake_lead import FakeLead
from test_polaris import SERVER_WORKER, expire_local_claims, first_open, service_env
from test_polaris_r29 import (
    ACTIVE,
    journals,
    lose_star_at,
    make_link,
    next_op,
    plant_journal,
)
from test_polaris_r29b import SRC  # noqa: F401

from decision_clicker import __main__ as cli
from decision_clicker import chain, journal, star, writer
from decision_clicker.api import DecisionClicker
from decision_clicker.config import Settings
from decision_clicker.errors import StarUnavailable, WriteError


# ---------------------------------------------------------------------------
# 1: Sweep -- Link-Guard und Worker-ID
# ---------------------------------------------------------------------------
def own_tag(kette) -> str:
    return star.worker_tag(star.resolve(kette))


def test_sweep_uses_the_worker_id_not_the_bare_host(kette):
    own = kette.chain_dir / f"{ACTIVE}.0badf00d-11223344@{own_tag(kette)}{star.TMP_SUFFIX}"
    host = own_tag(kette).split("@")[-1]
    same_host_other_agent = kette.chain_dir / f"{ACTIVE}.0badf00d-11223344@anderer-agent@{host}{star.TMP_SUFFIX}"
    own.write_text("x", encoding="utf-8")
    same_host_other_agent.write_text("x", encoding="utf-8")
    next_op(kette)
    assert not own.exists() and same_host_other_agent.exists()


def test_sweep_never_deletes_through_a_link_inside_the_chain(kette, tmp_path, monkeypatch):
    outside = tmp_path / "ausserhalb"
    outside.mkdir()
    victim = outside / f"x.0badf00d-11223344@{own_tag(kette)}{star.TMP_SUFFIX}"
    victim.write_text("gehoert mir nicht", encoding="utf-8")
    make_link(kette.chain_dir / "_archive", outside)
    via_link = kette.chain_dir / "_archive" / victim.name
    monkeypatch.setattr(type(victim), "rglob", lambda self, pattern: iter([via_link]))  # Fund ueber den Link
    next_op(kette)
    monkeypatch.undo()
    assert victim.exists()


# ---------------------------------------------------------------------------
# 2: Journal-Validierung
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("changes", [
    {"hashes_before": {"TO-DECIDE-USER.txt": "G" * 64, "DECIDED-AND-DONE.md": None}},  # nicht hex
    {"hashes_before": {"TO-DECIDE-USER.txt": "A" * 64, "DECIDED-AND-DONE.md": None}},  # Grossbuchstaben
    {"pending": {"step": "done", "file": "DECIDED-AND-DONE.md", "hash": "a" * 64}},  # nicht der naechste Schritt
    {"pending": {"step": "fill", "file": "DECIDED-AND-DONE.md", "hash": "a" * 64}},  # falsche Datei
    {"pending": {"step": "fill", "file": "TO-DECIDE-USER.txt", "hash": "zz" * 32}},
    {"done": ["fill", "done", "remove"], "pending": {"step": "fill", "file": "TO-DECIDE-USER.txt",
                                                      "hash": "a" * 64}},
    {"aborted": {"TO-DECIDE-USER.txt": "b" * 64, "DECIDED-AND-DONE.md": None}},  # Aktivdatei != vorher
])
def test_journal_validation_r29c(kette, changes):
    if changes.get("done") == ["fill", "done", "remove"]:
        h = journal.chain_hashes(kette)
        changes = dict(changes, hashes_after={k: h for k in changes["done"]})
    plant_journal(kette, **changes)
    with pytest.raises(StarUnavailable) as err:
        next_op(kette)
    assert err.value.reason == "journal_corrupt"


def test_valid_pending_and_aborted_are_accepted(kette):
    h = journal.chain_hashes(kette)
    plant_journal(kette, pending={"step": "fill", "file": "TO-DECIDE-USER.txt", "hash": "a" * 64})
    path = journals(kette)[0]
    journal._validate(json.loads(path.read_text(encoding="utf-8")), path)
    aborted = dict(h, **{"DECIDED-AND-DONE.md": "c" * 64})  # Register darf Rollback-Vermerke tragen
    plant_journal(kette, txid="feedface", aborted=aborted)
    path = kette.chain_dir / star.JOURNAL_DIR / "feedface.json"
    journal._validate(json.loads(path.read_text(encoding="utf-8")), path)


# ---------------------------------------------------------------------------
# 3: Heartbeat und Transaktions-Renew nebenlaeufig
# ---------------------------------------------------------------------------
def test_heartbeat_and_transaction_renew_run_concurrently_and_stay_consistent(kette, monkeypatch):
    fake = FakeLead(ttl=30, server_workers={SERVER_WORKER})
    service_env(monkeypatch, fake)
    errors = []
    try:
        service = writer.start_star_service(kette)
        assert service.status()["held"]
        stop = threading.Event()

        def heartbeat():
            while not stop.is_set():
                try:
                    service.renew_hold()
                except Exception as exc:  # noqa: BLE001
                    errors.append(exc)
                    return

        thread = threading.Thread(target=heartbeat)
        thread.start()
        dc = DecisionClicker(kette.chain_dir)
        try:
            for index in range(3):
                assert dc.create(f"n{index}", frage="f", optionen=["A — a"])["ok"]
            dc.decide(first_open(kette)["key"], "A")
        finally:
            stop.set()
            thread.join(10)
        assert not errors and service.status()["held"] and service.status()["fence"] == 1
        assert fake.version == star.chain_manifest(kette) and fake.inflight is False
    finally:
        writer.stop_star_service(kette)
        fake.stop()


def test_hold_lock_is_not_the_mutation_lock(kette, monkeypatch):
    fake = FakeLead(ttl=30, server_workers={SERVER_WORKER})
    service_env(monkeypatch, fake)
    try:
        service = writer.start_star_service(kette)
        assert service._hold_lock is not writer.MUTATION_LOCK
        with writer.MUTATION_LOCK:  # renew_hold braucht den Mutation-Lock nicht: keine neue Sperrreihenfolge
            assert service.renew_hold().fence == 1
    finally:
        writer.stop_star_service(kette)
        fake.stop()


# ---------------------------------------------------------------------------
# 5: Registry-Schluessel
# ---------------------------------------------------------------------------
@pytest.mark.skipif(sys.platform != "win32", reason="Schreibweisen-Gleichheit gilt unter Windows")
def test_registry_key_ignores_spelling_differences(kette, monkeypatch):
    upper = Settings(chain_dir=type(kette.chain_dir)(str(kette.chain_dir).upper()))
    lower = Settings(chain_dir=type(kette.chain_dir)(str(kette.chain_dir).lower()))
    assert star.chain_key(upper) == star.chain_key(lower) == star.chain_key(kette)
    fake = FakeLead(ttl=30, server_workers={SERVER_WORKER})
    service_env(monkeypatch, fake)
    try:
        writer.start_star_service(kette)
        assert star.describe(upper)["mode"] == "service"  # andere Schreibweise findet denselben Dienst
    finally:
        writer.stop_star_service(upper)
        fake.stop()


# ---------------------------------------------------------------------------
# 4: Operatorpfad polaris journal list | show | resolve
# ---------------------------------------------------------------------------
def blocked_chain(kette, monkeypatch) -> tuple[str, bytes]:
    """Offenes Journal ("fill" vermerkt) und eine Kette, die nicht dazu passt: Dauerblock."""
    DecisionClicker(kette.chain_dir).decide(first_open(kette)["key"], "A")
    before = (kette.chain_dir / ACTIVE).read_bytes()
    key = first_open(kette)["key"]
    with monkeypatch.context() as patch:
        lose_star_at(patch, 6)
        with pytest.raises(StarUnavailable):
            DecisionClicker(kette.chain_dir).decide(key, "B")
    expire_local_claims()
    return journals(kette)[0].stem, before


def run(kette, *args) -> int:
    return cli.main([*args, "--chain", str(kette.chain_dir)])


def test_list_and_show_work_without_a_star(kette, tmp_path, capsys, monkeypatch):
    txid, _ = blocked_chain(kette, monkeypatch)
    eco = tmp_path / "x" / "_CONTROL" / "_DECISIONS"  # Oekosystem-Kette ohne Lead: kein Stern moeglich
    eco.parent.mkdir(parents=True)
    kette.chain_dir.rename(eco)
    monkeypatch.setenv("DECISION_CLICKER_CHAIN", str(eco))
    ecos = Settings(chain_dir=eco)
    with pytest.raises(StarUnavailable):
        star.resolve(ecos)
    assert cli.main(["polaris", "journal", "list", "--chain", str(eco)]) == 0
    assert txid in capsys.readouterr().out
    assert cli.main(["polaris", "journal", "show", txid, "--chain", str(eco)]) == 0
    shown = json.loads(capsys.readouterr().out)
    assert shown["tx"] == txid and shown["valid"] is True and "local_hashes" in shown
    assert cli.main(["polaris", "journal", "resolve", txid, "--keep-current", "--chain", str(eco)]) == 2
    assert (eco / star.JOURNAL_DIR / f"{txid}.json").exists()  # ohne Stern bleibt alles unberuehrt


def test_resolve_keep_current_backs_up_logs_and_unblocks(kette, monkeypatch, capsys):
    txid, _ = blocked_chain(kette, monkeypatch)
    (kette.chain_dir / ACTIVE).write_text("# fremde Kopie\n", encoding="utf-8")
    with pytest.raises(StarUnavailable):
        next_op(kette)  # Dauerblock: journal_unmatched
    assert run(kette, "polaris", "journal", "resolve", txid, "--keep-current", "--operator", "tester") == 0
    out = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert out["decision"] == "keep-current" and out["operator"] == "tester" and out["tx"] == txid
    saved = kette.backup_dir / out["backup"].split("\\")[-1].split("/")[-1]
    assert (saved / ACTIVE).read_text(encoding="utf-8") == "# fremde Kopie\n"  # Sicherung VOR der Aufloesung
    assert (saved / f"{txid}.json").exists()
    log = (kette.backup_dir / "polaris-resolve.log").read_text(encoding="utf-8").splitlines()
    assert json.loads(log[-1])["tx"] == txid
    assert not journals(kette)
    next_op(kette)  # entsperrt
    assert (kette.chain_dir / ACTIVE).read_text(encoding="utf-8") == "# fremde Kopie\n"


def test_resolve_restore_before_brings_back_the_chain_from_backups(kette, monkeypatch):
    DecisionClicker(kette.chain_dir).decide(first_open(kette)["key"], "A")
    snapshot_active = (kette.chain_dir / ACTIVE).read_bytes()
    snapshot_done = kette.done_file.read_bytes()
    key = first_open(kette)["key"]
    with monkeypatch.context() as patch:
        lose_star_at(patch, 6)
        with pytest.raises(StarUnavailable):
            DecisionClicker(kette.chain_dir).decide(key, "B")
    expire_local_claims()
    txid = journals(kette)[0].stem
    assert (kette.chain_dir / ACTIVE).read_bytes() != snapshot_active
    assert run(kette, "polaris", "journal", "resolve", txid, "--restore-before") == 0
    assert (kette.chain_dir / ACTIVE).read_bytes() == snapshot_active
    assert kette.done_file.read_bytes() == snapshot_done
    assert not journals(kette)
    assert any(e["key"] == key for e in chain.open_entries(chain.build_index(kette)))


def test_restore_before_without_a_matching_backup_changes_nothing(kette, monkeypatch):
    txid, _ = blocked_chain(kette, monkeypatch)
    for item in kette.backup_dir.rglob("*"):
        if item.is_file():
            item.unlink()  # keine Sicherung mit dem Vorher-Hash
    before = {p.name: p.read_bytes() for p in kette.chain_dir.glob("*") if p.is_file()}
    with pytest.raises(WriteError, match="Keine Sicherung"):
        journal.resolve(kette, txid, "restore-before")
    assert {p.name: p.read_bytes() for p in kette.chain_dir.glob("*") if p.is_file()} == before
    assert journals(kette)


def test_resolve_of_a_corrupt_journal_only_allows_keep_current(kette, monkeypatch):
    txid, _ = blocked_chain(kette, monkeypatch)
    journals(kette)[0].write_text("kaputt", encoding="utf-8")
    with pytest.raises(WriteError, match="beschaedigt"):
        journal.resolve(kette, txid, "restore-before")
    journal.resolve(kette, txid, "keep-current", operator="t")
    assert not journals(kette)


@pytest.mark.parametrize("bad", ["..\\x", "../x", "/etc/passwd", "C:\\x", "deadbee", "DEADBEEF", "deadbeef.json", ""])
def test_txid_is_validated_before_any_path_is_built(kette, bad):
    secret = kette.chain_dir.parent / "x.json"
    secret.write_text("{}", encoding="utf-8")
    for call in (lambda: journal.show(kette, bad), lambda: journal.resolve(kette, bad, "keep-current")):
        with pytest.raises(WriteError, match="Ungueltige Transaktions-ID"):
            call()
    assert cli.main(["polaris", "journal", "show", bad, "--chain", str(kette.chain_dir)]) == 2
    assert secret.exists()
