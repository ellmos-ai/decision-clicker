# SPDX-License-Identifier: MIT
"""Polaris (Polarstern) im decision-clicker: nur der Halter des star schreibt.

Alle Tests laufen auf Fixture-Ketten in tmp, nie auf einer echten Kette. Der
ServerStar spricht mit ``fake_lead`` (derselbe Vertrag wie die BACH-Routen,
hermetisch); LocalStar nutzt eine SQLite im tmp-Statusordner.
"""
from __future__ import annotations

import hashlib
import multiprocessing
import os
import re
import shutil
import sqlite3
import sys
import threading
import time
from pathlib import Path

import pytest
from fake_lead import TOKEN, FakeLead

from decision_clicker import chain, journal, star, writer
from decision_clicker.api import DecisionClicker
from decision_clicker.config import Settings, state_dir
from decision_clicker.errors import StarLost, StarUnavailable, WriteError

STAMP_RE = re.compile(r"(?m)^POLARIS-STAR:.*\n")
MARK_RE = re.compile(r" — POLARIS-STAR:.*")


def normalized(path: Path) -> str:
    text = path.read_text(encoding="utf-8-sig")
    return MARK_RE.sub("", STAMP_RE.sub("", text))


def snapshot(settings: Settings) -> dict[str, bytes]:
    return {p.relative_to(settings.chain_dir).as_posix(): p.read_bytes()
            for p in sorted(settings.chain_dir.rglob("*")) if p.is_file()}


def first_open(settings: Settings) -> dict:
    return chain.open_entries(chain.build_index(settings))[0]


def expire_local_claims() -> None:
    conn = sqlite3.connect(str(state_dir() / "star.db"))
    conn.execute("UPDATE local_star SET expires = 0")
    conn.commit()
    conn.close()


@pytest.fixture
def lead(monkeypatch):
    fake = FakeLead()
    url = fake.start()
    monkeypatch.setenv("DECISION_CLICKER_LEAD_URL", url)
    monkeypatch.setenv("DECISION_CLICKER_DEVICE_TOKEN", TOKEN)
    monkeypatch.setenv("DECISION_CLICKER_WORKER", "decision-writer@host-a")
    yield fake
    fake.stop()


# ---------------------------------------------------------------------------
# Auswahl und Konfiguration
# ---------------------------------------------------------------------------
def test_manifest_contract_vector(tmp_path):
    (tmp_path / "a.txt").write_bytes(b"x")
    expected = hashlib.sha256(
        f"a.txt\t1\t{hashlib.sha256(b'x').hexdigest()}\nb.txt\tMISSING\n".encode()).hexdigest()
    assert star.manifest_version(tmp_path, ["b.txt", "a.txt"]) == expected  # = BACH lease_core.manifest_version
    (tmp_path / "leer").mkdir()  # leerer Ordner == fehlender Ordner (Hosts duerfen sich darin nicht unterscheiden)
    empty = star.manifest_version(tmp_path, ["leer"])
    missing = hashlib.sha256(b"leer\tMISSING\n").hexdigest()
    assert empty == missing


def test_selection_rules(kette, tmp_path, monkeypatch):
    assert star.resolve(kette).kind == "local"  # nicht geteilte Kette -> LocalStar
    eco = Settings(chain_dir=tmp_path / "x" / "_CONTROL" / "_DECISIONS")
    with pytest.raises(StarUnavailable, match="BACH-Lead"):
        star.resolve(eco)  # Oekosystem-Kette ohne Lead: nur lesbar
    monkeypatch.setenv("DECISION_CLICKER_STAR", "local")
    with pytest.raises(StarUnavailable, match="nur fuer nicht geteilte"):
        star.resolve(eco)
    monkeypatch.setenv("DECISION_CLICKER_STAR", "off")
    with pytest.raises(StarUnavailable, match="off"):
        star.resolve(kette)  # es gibt keinen off-Schalter
    monkeypatch.setenv("DECISION_CLICKER_STAR", "server")
    with pytest.raises(StarUnavailable):
        star.resolve(kette)  # server ohne Lead/Token
    monkeypatch.setenv("DECISION_CLICKER_STAR", "auto")
    monkeypatch.setenv("DECISION_CLICKER_LEAD_URL", "http://127.0.0.1:1")
    with pytest.raises(StarUnavailable, match="Token"):
        star.resolve(kette)  # Lead konfiguriert -> registriert -> ServerStar Pflicht
    monkeypatch.setenv("DECISION_CLICKER_DEVICE_TOKEN", "t")
    assert star.resolve(kette).kind == "server"


def test_backups_and_state_never_inside_chain(kette):
    DecisionClicker(kette.chain_dir).decide(first_open(kette)["key"], "A")
    assert not kette.backup_dir.resolve().is_relative_to(kette.chain_dir.resolve())
    assert any(kette.backup_dir.iterdir())
    assert not [p for p in kette.chain_dir.rglob("*") if "_bak" in p.parts]


# ---------------------------------------------------------------------------
# Ohne Stern: nur lesbar, Dateien byte-gleich; Choke-Point
# ---------------------------------------------------------------------------
def make_readonly(kette: Settings, tmp_path: Path) -> Settings:
    eco = tmp_path / "eco" / "_CONTROL" / "_DECISIONS"
    shutil.copytree(kette.chain_dir, eco)
    return Settings(chain_dir=eco)


def test_without_star_every_mutation_is_blocked_and_files_stay_byte_equal(kette, tmp_path):
    ro = make_readonly(kette, tmp_path)
    before = snapshot(ro)
    entry = first_open(ro)  # Lesen bleibt moeglich
    active = ro.chain_dir / "TO-DECIDE-USER.txt"
    ro.lock_file.write_text("x", encoding="utf-8")
    before = snapshot(ro)
    calls = [
        lambda: writer.fill_decision(ro, active, entry["source_line"], "A"),
        lambda: writer.revert_decision(ro, active, entry["source_line"]),
        lambda: writer.remove_entry(ro, active, entry["source_line"], expected_id=entry["id"]),
        lambda: writer.mark_decision_undone(ro, entry["id"], "x"),
        lambda: writer.append_entry(ro, active, writer.render_entry("D-20990101-001", "t", frage="f",
                                                                    optionen=["A — a"])),
        lambda: writer.append_done(ro, entry, "A"),
        lambda: writer.append_done_block(ro, ["", "## D-20990101-002 — t"]),
        lambda: writer.decide_entry(ro, entry, "A"),
        lambda: writer.restore_decision(ro, entry["id"], "x"),
        lambda: writer.write_lock(ro, "test"),
        lambda: writer.release_lock(ro),
        lambda: DecisionClicker(ro.chain_dir).decide(entry["key"], "A"),
        lambda: DecisionClicker(ro.chain_dir).create("neu", frage="f", optionen=["A — a"]),
        lambda: DecisionClicker(ro.chain_dir).undo("D-20260806-001"),
    ]
    for call in calls:
        with pytest.raises(StarUnavailable, match="nur lesbar"):
            call()
        assert snapshot(ro) == before
    assert StarUnavailable.__mro__[1] is WriteError  # HTTP 409 der Clicker-API (WriteError-Mapping)
    status = DecisionClicker(ro.chain_dir).status()
    assert status["star"]["available"] is False and "nur lesbar" in status["star"]["error"]


def test_choke_point_negative_control(kette, tmp_path, monkeypatch):
    """Ohne Pruefung im Choke-Point schreibt dieselbe Aktion durch -> der Sperr-Test waere rot."""
    ro = make_readonly(kette, tmp_path)
    active = ro.chain_dir / "TO-DECIDE-USER.txt"
    before = active.read_bytes()
    with pytest.raises(StarUnavailable):
        writer._write(ro, active, "kaputt", False)  # ohne Transaktion/Stern
    assert active.read_bytes() == before
    monkeypatch.setattr(writer, "_guard", lambda settings, path: None)  # Mutant: Pruefung entfernt
    writer._write(ro, active, "kaputt", False)
    assert active.read_bytes() == b"kaputt"


def test_unreachable_lead_keeps_chain_readonly(kette, monkeypatch):
    monkeypatch.setenv("DECISION_CLICKER_LEAD_URL", "http://127.0.0.1:9")
    monkeypatch.setenv("DECISION_CLICKER_DEVICE_TOKEN", TOKEN)
    before = snapshot(kette)
    with pytest.raises(StarUnavailable, match="nicht erreichbar"):
        DecisionClicker(kette.chain_dir).decide(first_open(kette)["key"], "A")
    assert snapshot(kette) == before


# ---------------------------------------------------------------------------
# Stempel, Journal-Ort, Manifest
# ---------------------------------------------------------------------------
def test_stamps_chain_contract_and_commit_marker(kette, lead):
    dc = DecisionClicker(kette.chain_dir)
    new = dc.create("Stempel", frage="Passt?", optionen=["A — ja", "B — nein"], empfehlung="A")
    active = (kette.chain_dir / "TO-DECIDE-USER.txt").read_text(encoding="utf-8-sig").splitlines()
    heading = next(i for i, line in enumerate(active) if line.startswith(new["id"]))
    assert re.fullmatch(r"POLARIS-STAR: decisions-chain#1 host-a tx=[0-9a-f]{8}", active[heading + 1])
    dc.decide(first_open(kette)["key"], "A", "ok")
    done = kette.done_file.read_text(encoding="utf-8-sig")
    assert re.search(r"(?m)^POLARIS-STAR: decisions-chain#\d+ host-a tx=[0-9a-f]{8}$", done)
    index = chain.build_index(kette)
    assert index["active_contract"]["valid"] is True  # Parser-Vertrag haelt mit Stempeln
    assert index["counts"]["id_collisions"] == 0
    # Commit-Marker: der Lead kennt den Manifest-Hash des abgeschlossenen Standes, kein Journal liegt mehr
    assert lead.version == star.chain_manifest(kette) and lead.claim is None
    assert not (kette.chain_dir / star.JOURNAL_DIR).exists() or not any((kette.chain_dir / star.JOURNAL_DIR).iterdir())


def test_journal_location_content_and_cleanup(kette, monkeypatch):
    seen = {}
    original = journal.Journal.advance

    def spy(self, step):
        original(self, step)
        seen[step] = (self.path.parent.name, self.path.is_file(), list(self.data["done"]))

    monkeypatch.setattr(journal.Journal, "advance", spy)
    DecisionClicker(kette.chain_dir).decide(first_open(kette)["key"], "A")
    assert [s for s in seen] == ["fill", "done", "remove"]
    assert seen["fill"][0] == star.JOURNAL_DIR and seen["remove"][2] == ["fill", "done", "remove"]
    assert not list((kette.chain_dir / star.JOURNAL_DIR).glob("*.json"))


# ---------------------------------------------------------------------------
# Sternverlust zwischen jedem Schritt
# ---------------------------------------------------------------------------
def count_guard_calls(monkeypatch, run) -> int:
    calls = {"n": 0}
    original = star.Transaction.assert_valid

    def counting(self, margin=None):
        calls["n"] += 1
        return original(self, margin)

    monkeypatch.setattr(star.Transaction, "assert_valid", counting)
    run()
    monkeypatch.setattr(star.Transaction, "assert_valid", original)
    return calls["n"]


def test_star_loss_between_every_decide_step_keeps_journal_and_next_holder_finishes(kette, tmp_path, monkeypatch):
    template = tmp_path / "template"
    shutil.copytree(kette.chain_dir, template)
    key = first_open(kette)["key"]
    # Referenz: sauberer Lauf
    ref = Settings(chain_dir=tmp_path / "ref")
    shutil.copytree(template, ref.chain_dir)
    total = count_guard_calls(monkeypatch, lambda: DecisionClicker(ref.chain_dir).decide(key, "A", "n"))
    assert total >= 7
    reference = {n: normalized(ref.chain_dir / n) for n in ("TO-DECIDE-USER.txt", "DECIDED-AND-DONE.md")}
    original = {n: (template / n).read_text(encoding="utf-8-sig") for n in reference}
    assert reference != original

    for k in range(1, total + 1):
        case = Settings(chain_dir=tmp_path / f"case{k}")
        shutil.copytree(template, case.chain_dir)
        real = star.Transaction.assert_valid
        counter = {"n": 0}

        def failing(self, margin=None, _k=k, _c=counter, _real=real):
            _c["n"] += 1
            if _c["n"] >= _k:
                expire_local_claims()  # der Stern ist weg (z. B. abgelaufen und neu vergeben)
                raise StarLost("injiziert")
            return _real(self, margin)

        monkeypatch.setattr(star.Transaction, "assert_valid", failing)
        with pytest.raises(StarLost):
            DecisionClicker(case.chain_dir).decide(key, "A", "n")
        monkeypatch.setattr(star.Transaction, "assert_valid", real)
        jdir = case.chain_dir / star.JOURNAL_DIR
        wrote_content = any(
            (case.chain_dir / n).read_bytes() != (template / n).read_bytes() for n in reference)
        if k >= 2:
            assert list(jdir.glob("*.json")), f"Schritt {k}: Journal muss liegen bleiben"
        # kein Auto-Revert: Teilzustand bleibt bis zum naechsten Halter stehen
        # Der naechste Halter (beliebige Operation) schliesst das Journal ab, bevor er Neues schreibt
        with writer.chain_transaction(case):
            pass
        assert not list(jdir.glob("*.json")) if jdir.exists() else True
        expected = reference if wrote_content else original
        for name, text in expected.items():
            assert normalized(case.chain_dir / name) == text, f"Schritt {k}: {name}"
        assert chain.build_index(case)["active_contract"]["valid"] is True


def test_loss_between_journal_write_and_inflight_report_is_rebaselined_by_server_role(kette, monkeypatch):
    """Frueheres Restfenster: Verlust genau zwischen Journalschreiben und In-flight-Meldung.
    Die Server-Rolle (hier LocalStar, einziger Host) erwirbt per rebaseline, das Journal wird verworfen."""
    original = star.Transaction.report
    DecisionClicker(kette.chain_dir).decide(first_open(kette)["key"], "A")  # erster Commit setzt einen Stand

    def boom(self, version, inflight=False):
        expire_local_claims()
        raise StarLost("injiziert")

    monkeypatch.setattr(star.Transaction, "report", boom)
    with pytest.raises(StarLost):
        DecisionClicker(kette.chain_dir).decide(first_open(kette)["key"], "A")
    monkeypatch.setattr(star.Transaction, "report", original)
    result = DecisionClicker(kette.chain_dir).decide(first_open(kette)["key"], "B")
    assert result["ok"]
    assert not list((kette.chain_dir / star.JOURNAL_DIR).glob("*.json"))


@pytest.mark.parametrize("loss_at", [4, 5])  # 4: Restore geschrieben, Vermerk fehlt (pending); 5: vor dem Beleg
def test_restore_loss_is_completed_by_next_holder(kette, monkeypatch, loss_at):
    dc = DecisionClicker(kette.chain_dir)
    key = first_open(kette)["key"]
    dc.decide(key, "A")
    ref_active = None
    real = star.Transaction.assert_valid
    counter = {"n": 0}

    def failing(self, margin=None):
        counter["n"] += 1
        if counter["n"] >= loss_at:
            expire_local_claims()
            raise StarLost("injiziert")
        return real(self, margin)

    monkeypatch.setattr(star.Transaction, "assert_valid", failing)
    with pytest.raises(StarLost):
        dc.undo(key)
    monkeypatch.setattr(star.Transaction, "assert_valid", real)
    assert list((kette.chain_dir / star.JOURNAL_DIR).glob("*.json"))
    with writer.chain_transaction(kette):
        pass
    done = normalized(kette.done_file)
    assert "ZURÜCKGESETZT AM" in done and len(re.findall(r"ZURÜCKGESETZT AM", done)) == 1
    assert any(e["key"] == key for e in chain.open_entries(chain.build_index(kette)))
    assert ref_active is None


# ---------------------------------------------------------------------------
# ServerStar: zwei Hosts, pausierter Alt-Halter, partielle Kopie
# ---------------------------------------------------------------------------
def switch_host(monkeypatch, host: str) -> None:
    monkeypatch.setenv("DECISION_CLICKER_WORKER", f"decision-writer@{host}")


def test_paused_old_holder_is_detected_and_new_holder_wins(kette, lead, monkeypatch):
    key = first_open(kette)["key"]
    stale_flag = {}
    real = star.Transaction.assert_valid

    def pause_then_lose(self, margin=None):
        if "done" not in stale_flag:
            stale_flag["done"] = True
            lead.expire()                       # der Lead laesst die Lease ablaufen ...
            switch_host(monkeypatch, "host-b")  # ... und host-b uebernimmt (auf dem Lead-Stand)
            other = star.make_provider(star.resolve(kette))
            lead.version = star.chain_manifest(kette)  # host-b sieht denselben synchronen Stand
            stale_flag["hold"] = other.acquire(lead.version)
            switch_host(monkeypatch, "host-a")
        return real(self, margin)  # der pausierte Alt-Halter prueft nur lokal -> merkt es (noch) nicht

    monkeypatch.setattr(star.Transaction, "assert_valid", pause_then_lose)
    with pytest.raises(StarLost):  # erkannt spaetestens beim Commit-Marker / Renew, gemeldet
        DecisionClicker(kette.chain_dir).decide(key, "A")
    assert stale_flag["hold"].fence == 2
    assert lead.claim["worker"] == "decision-writer@host-b" and lead.claim["id"] == stale_flag["hold"].lease_id


def test_clock_jump_forces_online_check(kette, lead, monkeypatch):
    with pytest.raises(StarLost):  # Zeitluecke -> online neu pruefen -> verloren
        with star.transaction(kette) as tx:
            tx.assert_valid()
            lead.expire()
            monkeypatch.setattr(time, "time", lambda: time.monotonic() + 10_000)  # Wanduhr springt (Suspend)
            tx.assert_valid()


def test_partial_copy_gives_stale_resource_version_then_synced_copy_acquires(kette, lead, tmp_path, monkeypatch):
    host_b = Settings(chain_dir=tmp_path / "hostB")
    shutil.copytree(kette.chain_dir, host_b.chain_dir)  # veraltete/verzoegerte Kopie
    key = first_open(kette)["key"]
    DecisionClicker(kette.chain_dir).decide(key, "A")  # host-a schreibt und meldet den Stand
    switch_host(monkeypatch, "host-b")
    before = snapshot(host_b)
    with pytest.raises(StarUnavailable, match="synchronisiert"):
        DecisionClicker(host_b.chain_dir).decide(first_open(host_b)["key"], "A")
    assert snapshot(host_b) == before  # nur lesbar, Dateien byte-gleich
    # Teilkopie: nur die Aktivdatei angekommen
    shutil.copy2(kette.chain_dir / "TO-DECIDE-USER.txt", host_b.chain_dir / "TO-DECIDE-USER.txt")
    with pytest.raises(StarUnavailable, match="synchronisiert"):
        DecisionClicker(host_b.chain_dir).create("x", frage="f", optionen=["A — a"])
    # vollstaendige Kopie
    for src in kette.chain_dir.rglob("*"):
        if src.is_file():
            target = host_b.chain_dir / src.relative_to(kette.chain_dir)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, target)
    result = DecisionClicker(host_b.chain_dir).create("x", frage="f", optionen=["A — a"])
    assert result["ok"] and lead.fence == 2


# ---------------------------------------------------------------------------
# Zwei Prozesse
# ---------------------------------------------------------------------------
def _contender(env, chain_dir, barrier, queue, hold_seconds):  # laeuft in eigenem Prozess
    os.environ.update(env)
    sys.path.insert(0, str(Path(__file__).parent.parent / "src"))
    from decision_clicker import star as child_star
    from decision_clicker.config import Settings as ChildSettings
    settings = ChildSettings(chain_dir=Path(chain_dir))
    barrier.wait()
    try:
        with child_star.transaction(settings) as tx:
            queue.put(("ok", tx.fence))
            time.sleep(hold_seconds)
    except Exception as exc:  # noqa: BLE001
        queue.put(("err", type(exc).__name__, getattr(exc, "reason", str(exc))))


@pytest.mark.parametrize("kind", ["local", "server"])
def test_two_processes_exactly_one_gets_the_star(kind, kette, tmp_path, monkeypatch):
    env_base = {"DECISION_CLICKER_STATE_DIR": os.environ["DECISION_CLICKER_STATE_DIR"]}
    fake = None
    if kind == "server":
        fake = FakeLead()
        env_base |= {"DECISION_CLICKER_LEAD_URL": fake.start(), "DECISION_CLICKER_DEVICE_TOKEN": TOKEN}
    try:
        ctx = multiprocessing.get_context("spawn")
        barrier, queue = ctx.Barrier(2), ctx.Queue()
        procs = [ctx.Process(target=_contender, args=(
            env_base | {"DECISION_CLICKER_WORKER": f"decision-writer@proc-{i}"},
            str(kette.chain_dir), barrier, queue, 2.0)) for i in (1, 2)]
        for proc in procs:
            proc.start()
        results = [queue.get(timeout=120) for _ in procs]
        for proc in procs:
            proc.join(timeout=60)
            assert proc.exitcode == 0
    finally:
        if fake:
            fake.stop()
    assert sorted(r[0] for r in results) == ["err", "ok"], results
    loser = next(r for r in results if r[0] == "err")
    assert loser[1:] == ("StarUnavailable", "held")


def test_mutation_lock_is_outermost_and_threads_serialize(kette):
    order = []

    def worker(n):
        with writer.chain_transaction(kette):
            order.append(("in", n))
            time.sleep(0.1)
            order.append(("out", n))

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(3)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    kinds = [k for k, _ in order]
    assert kinds == ["in", "out"] * 3  # nie verschraenkt


# ---------------------------------------------------------------------------
# HTTP: ohne Stern 409, Lesen bleibt
# ---------------------------------------------------------------------------
from test_server import hole, sende, server  # noqa: E402,F401,I001


def test_http_api_answers_409_without_star_and_still_reads(server, monkeypatch):  # noqa: F811
    url, kette = server
    key = first_open(kette)["key"]
    monkeypatch.setenv("DECISION_CLICKER_STAR", "server")  # Lead fehlt -> kein Stern moeglich
    before = snapshot(kette)
    status, body = sende(f"{url}/api/decide", {"key": key, "choice": "A"})
    assert status == 409 and "nur lesbar" in body
    status, _ = sende(f"{url}/api/new", {"title": "x", "frage": "f", "optionen": "A — a"})
    assert status == 409
    assert snapshot(kette) == before
    assert hole(f"{url}/")[0] == 200  # Lesen funktioniert weiter


# ---------------------------------------------------------------------------
# rebaseline (nur Server-Rolle) und Dienstbetrieb
# ---------------------------------------------------------------------------
SERVER_WORKER = "decision-writer@mac-studio"


@pytest.fixture
def server_lead(monkeypatch):
    fake = FakeLead(server_workers={SERVER_WORKER})
    url = fake.start()
    monkeypatch.setenv("DECISION_CLICKER_LEAD_URL", url)
    monkeypatch.setenv("DECISION_CLICKER_DEVICE_TOKEN", TOKEN)
    monkeypatch.setenv("DECISION_CLICKER_WORKER", SERVER_WORKER)
    monkeypatch.setenv("DECISION_CLICKER_STAR_ROLE", "server")
    yield fake
    fake.stop()


def hand_edit(settings: Settings) -> None:
    """Ein Agent haengt direkt an TO-DECIDE-USER.txt an (README _DECISIONS)."""
    path = settings.chain_dir / "TO-DECIDE-USER.txt"
    path.write_bytes(path.read_bytes() + b"\n<!-- externer Anhang -->\n")


def test_external_edit_server_role_rebaselines_standby_stays_exact(kette, server_lead, monkeypatch):
    dc = DecisionClicker(kette.chain_dir)
    dc.decide(first_open(kette)["key"], "A")
    hand_edit(kette)
    # Standby (gleicher Lead, keine Server-Rolle): exakter Abgleich, nur lesbar, byte-gleich
    monkeypatch.setenv("DECISION_CLICKER_STAR_ROLE", "standby")
    monkeypatch.setenv("DECISION_CLICKER_WORKER", "decision-writer@host-b")
    before = snapshot(kette)
    with pytest.raises(StarUnavailable, match="synchronisiert"):
        dc.create("x", frage="f", optionen=["A — a"])
    assert snapshot(kette) == before
    # Server-Rolle: rebaseline, Ereignis protokolliert, Kette laeuft weiter
    monkeypatch.setenv("DECISION_CLICKER_STAR_ROLE", "server")
    monkeypatch.setenv("DECISION_CLICKER_WORKER", SERVER_WORKER)
    assert dc.create("y", frage="f", optionen=["A — a"])["ok"]
    assert server_lead.events == ["rebaseline_external_change"]
    assert server_lead.version == star.chain_manifest(kette)


def test_open_inflight_marker_blocks_even_the_server_until_recovery(kette, server_lead):
    dc = DecisionClicker(kette.chain_dir)
    dc.decide(first_open(kette)["key"], "A")
    real = star.Transaction.assert_valid
    counter = {"n": 0}

    def failing(self, margin=None):
        counter["n"] += 1
        if counter["n"] >= 3:
            server_lead.expire()
            raise StarLost("injiziert")
        return real(self, margin)

    star.Transaction.assert_valid = failing
    try:
        with pytest.raises(StarLost):
            dc.decide(first_open(kette)["key"], "B")
    finally:
        star.Transaction.assert_valid = real
    assert server_lead.inflight is True
    journals = list((kette.chain_dir / star.JOURNAL_DIR).glob("*.json"))
    assert journals
    hidden = journals[0].read_bytes()
    journals[0].unlink()  # Journal (noch) nicht synchron: kein Marker ableitbar
    active = kette.chain_dir / "TO-DECIDE-USER.txt"
    before_edit = active.read_bytes()
    hand_edit(kette)
    with pytest.raises(StarUnavailable) as err:
        dc.create("z", frage="f", optionen=["A — a"])  # blockiert auch die Server-Rolle (R29-2a)
    assert err.value.reason == "journal_not_synced"
    assert "rebaseline_external_change" not in server_lead.events
    journals[0].write_bytes(hidden)
    with pytest.raises(StarUnavailable) as err:  # Journal da, Kette passt nicht dazu: warten, nie verwerfen (R29-2b)
        dc.create("z", frage="f", optionen=["A — a"])
    assert err.value.reason == "journal_unmatched" and journals[0].exists()
    active.write_bytes(before_edit)  # Journal ist da: Recovery ueber den In-flight-Marker
    assert dc.create("z", frage="f", optionen=["A — a"])["ok"]
    assert server_lead.inflight is False


def service_env(monkeypatch, fake: FakeLead) -> None:
    monkeypatch.setenv("DECISION_CLICKER_LEAD_URL", fake.start())
    monkeypatch.setenv("DECISION_CLICKER_DEVICE_TOKEN", TOKEN)
    monkeypatch.setenv("DECISION_CLICKER_WORKER", SERVER_WORKER)
    monkeypatch.setenv("DECISION_CLICKER_STAR_ROLE", "server")
    monkeypatch.setenv("DECISION_CLICKER_STAR_RENEW", "1")
    monkeypatch.setenv("DECISION_CLICKER_STAR_MARGIN", "0.5")


def test_service_holds_star_without_clicks_beyond_server_down_after(kette, monkeypatch):
    fake = FakeLead(ttl=3, server_workers={SERVER_WORKER})
    service_env(monkeypatch, fake)
    try:
        service = writer.start_star_service(kette)
        assert service is not None and service.status()["held"] and fake.fence == 1
        time.sleep(4.5)  # laenger als die TTL: nur der Heartbeat haelt den star
        assert fake.claim is not None and fake.fence == 1 and service.status()["fence"] == 1
        # Standby wird abgelehnt, solange der Dienst haelt
        monkeypatch.setenv("DECISION_CLICKER_STAR_ROLE", "standby")
        monkeypatch.setenv("DECISION_CLICKER_WORKER", "decision-writer@host-b")
        with pytest.raises(StarUnavailable) as err:
            star.make_provider(star.resolve(kette)).acquire(star.chain_manifest(kette))
        assert err.value.reason == "held"
        # eine Transaktion nutzt den gehaltenen star und gibt ihn NICHT zurueck
        monkeypatch.setenv("DECISION_CLICKER_STAR_ROLE", "server")
        monkeypatch.setenv("DECISION_CLICKER_WORKER", SERVER_WORKER)
        assert DecisionClicker(kette.chain_dir).create("s", frage="f", optionen=["A — a"])["ok"]
        assert fake.claim is not None and fake.fence == 1 and fake.version == star.chain_manifest(kette)
        assert DecisionClicker(kette.chain_dir).status()["star"]["held"] is True
    finally:
        writer.stop_star_service(kette)
    assert fake.claim is None and fake.version == star.chain_manifest(kette)  # beim Beenden zurueckgegeben
    fake.stop()


def test_service_loss_stops_writes_shows_status_and_reacquires(kette, monkeypatch):
    fake = FakeLead(ttl=3, server_workers={SERVER_WORKER})
    service_env(monkeypatch, fake)
    try:
        service = writer.start_star_service(kette)
        assert service is not None and fake.fence == 1
        fake.reject_acquire = True  # Neuerwerb noch nicht moeglich
        fake.expire()  # Lease des Dienstes laeuft ab: der naechste Heartbeat verliert den star
        deadline = time.time() + 20
        while time.time() < deadline and service.status()["held"]:
            time.sleep(0.2)
        status = DecisionClicker(kette.chain_dir).status()["star"]
        assert status["held"] is False and status["lost_count"] >= 1 and status["error"]
        before = snapshot(kette)
        with pytest.raises(StarUnavailable, match="nur lesbar"):
            DecisionClicker(kette.chain_dir).create("x", frage="f", optionen=["A — a"])
        assert snapshot(kette) == before
        fake.reject_acquire = False  # der Heartbeat erwirbt neu
        deadline = time.time() + 20
        while time.time() < deadline and not service.status()["held"]:
            time.sleep(0.2)
        assert service.status()["held"] and service.status()["fence"] == 2
        assert DecisionClicker(kette.chain_dir).create("x", frage="f", optionen=["A — a"])["ok"]
    finally:
        writer.stop_star_service(kette)
        fake.stop()


#: Gemeinsamer Vektor mit BACH ``tests/test_resource_lease.py`` (lease_core.manifest_version).
SHARED_MANIFEST_VECTOR = "025c824ad9189e559d0844f99372867f61b3b56b7c8d5e5b6d8266e2b86dea47"


def test_manifest_shared_vector_with_bach(tmp_path):
    (tmp_path / "a.txt").write_bytes(b"x")
    (tmp_path / "leer").mkdir()  # leerer Ordner == fehlend
    assert star.manifest_version(tmp_path, ["leer", "b.txt", "a.txt"]) == SHARED_MANIFEST_VECTOR
    (tmp_path / "leer").rmdir()
    assert star.manifest_version(tmp_path, ["leer", "b.txt", "a.txt"]) == SHARED_MANIFEST_VECTOR
