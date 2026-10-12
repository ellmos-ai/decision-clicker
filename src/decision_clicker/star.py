# SPDX-License-Identifier: MIT
"""Polaris (Polarstern): nur der Halter des "star" schreibt in die Kette.

Die Kettendateien haben genau einen Schreiber. Wer schreiben will, haelt den
Polaris star: einen Lease mit Fence, vergeben von der BACH-Authority
(``ServerStar``, HTTP mit Geraete-Token) oder, nur fuer eine nicht geteilte
Kette im Einzelbetrieb, von einer lokalen SQLite im Nutzerordner
(``LocalStar``). Einen ``off``-Schalter gibt es nicht.

Ehrliche Garantie: Das schliesst aus, dass zwei Writer *gleichzeitig gueltig*
schreiben duerfen. Ein angehaltener Alt-Halter (VM-Suspend, blockierte
Platte), der nach einer Uebernahme noch schreibt, ist ohne Compare-and-Set im
Dateisystem nicht zu verhindern. Er wird erkannt (Fence-Stempel, Journal,
Nachpruefung) und der Schaden begrenzt.

Auswahl (Konfiguration, ``DECISION_CLICKER_STAR`` = ``auto`` | ``server`` | ``local``):

* Oekosystem-Kette (BACH-Lead konfiguriert oder Pfad ``.../_CONTROL/_DECISIONS``):
  ServerStar ist Pflicht. Ohne erreichbaren Lead ist die Kette nur lesbar.
* Alle anderen Ketten: ``auto`` waehlt LocalStar.

Eine Transaktion haelt den star von Beginn bis Ende (``transaction``): erwerben
mit dem Manifest-Hash des lokalen Standes (Sync-Schranke), schreiben, den Hash
als Commit-Marker per renew melden, zurueckgeben.
"""
from __future__ import annotations

import hashlib
import ipaddress
import json
import os
import re
import socket
import sqlite3
import threading
import time
import urllib.error
import urllib.request
import uuid
from collections.abc import Callable, Iterable
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from .config import Settings, state_dir
from .errors import StarLost, StarUnavailable

RESOURCE = "decisions-chain"
TTL_PROFILE = "POLARIS"
DEFAULT_MARGIN = 15.0
DEFAULT_MAX_RESPONSE = 5.0
DEFAULT_TIMEOUT = 8.0
LOCAL_TTL = 120.0
JOURNAL_DIR = "_polaris-journal"
#: Ressourcenumfang: Kettendateien. Das Journal (R29-1) und Backups gehoeren nicht dazu; LOCK-Dateien
#: bewusst auch nicht (fremde Agenten legen sie staendig an, siehe docs/POLARIS.md).
CHAIN_PATHS = ("TO-DECIDE-USER.txt", "DECIDED-AND-DONE.md", "_decision-archive", "_archive")
TMP_SUFFIX = ".polaris-tmp"
DEFAULT_STABLE_SECONDS = 60.0
MODES = ("auto", "server", "local")
_WORKER_HOST_RE = re.compile(r"[^A-Za-z0-9._-]")


# ---------------------------------------------------------------------------
# Manifest (Sync-Schranke) -- identisch zu BACH ``lease_core.manifest_version``
# ---------------------------------------------------------------------------
def manifest_version(root: Path | str, paths: Iterable[str]) -> str:
    """SHA-256 ueber sortierte relative Pfade (``/``), Groesse und SHA-256 jeder
    Datei; fehlende Dateien gehen als ``MISSING`` ein, Ordner rekursiv. Ein leerer Ordner zaehlt
    wie ein fehlender. Temporaere Schreibdateien (``.polaris-tmp``) zaehlen nicht."""
    base = Path(root)
    entries: dict[str, str] = {}
    for rel in paths:
        target = base / rel
        files = sorted(p for p in target.rglob("*")
                       if p.is_file() and not p.name.endswith(TMP_SUFFIX)) if target.is_dir() else []
        if files:
            for sub in files:
                entries[sub.relative_to(base).as_posix()] = _file_line(sub)
        elif target.is_file():
            entries[Path(rel).as_posix()] = _file_line(target)
        else:
            entries[Path(rel).as_posix()] = "MISSING"
    body = "".join(f"{key}\t{entries[key]}\n" for key in sorted(entries))
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


def _file_line(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return f"{path.stat().st_size}\t{digest.hexdigest()}"


def chain_manifest(settings: Settings) -> str:
    return manifest_version(settings.chain_dir, CHAIN_PATHS)


def _snapshot(settings: Settings) -> tuple[str, tuple]:
    """Manifest plus Datei-mtimes im Kettenumfang (Stabilitaetsfenster)."""
    base = Path(settings.chain_dir)
    times = []
    for rel in CHAIN_PATHS:
        target = base / rel
        for item in ([target] if target.is_file() else sorted(target.rglob("*")) if target.is_dir() else []):
            if item.is_file() and not item.name.endswith(TMP_SUFFIX):
                times.append((item.relative_to(base).as_posix(), item.stat().st_mtime_ns))
    return chain_manifest(settings), tuple(times)


def stable_manifest(settings: Settings, seconds: float) -> str:
    """Manifest erst melden, wenn es ``seconds`` lang unveraendert blieb (R29-4, Teilkopie-Schutz)."""
    if seconds <= 0:
        return chain_manifest(settings)
    first = _snapshot(settings)
    time.sleep(seconds)
    second = _snapshot(settings)
    if first != second:
        raise _denied("rebaseline_unstable")
    return second[0]


# ---------------------------------------------------------------------------
# Konfiguration
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class StarConfig:
    kind: str  # "server" | "local"
    resource: str
    worker_id: str
    host: str
    lead_url: str = ""
    token: str = field(default="", repr=False)  # nie in Logs, Fehlertexten oder Reprs
    margin: float = DEFAULT_MARGIN
    timeout: float = DEFAULT_TIMEOUT
    max_response: float = DEFAULT_MAX_RESPONSE
    chain_key: str = ""
    role: str = "standby"  # "server" darf bei externer Aenderung rebaselinen (nur ServerStar-Rolle am Lead)
    renew_seconds: float = 40.0
    stable_seconds: float = DEFAULT_STABLE_SECONDS  # Stabilitaetsfenster vor rebaseline


def is_ecosystem_chain(settings: Settings, env: dict[str, str] | None = None) -> bool:
    """Registrierte Kette: BACH-Lead konfiguriert oder die Kette ``_CONTROL/_DECISIONS``."""
    env = os.environ if env is None else env
    if env.get("DECISION_CLICKER_LEAD_URL") or env.get("BACH_LEAD_URL"):
        return True
    parts = [p.lower() for p in Path(settings.chain_dir).parts]
    return any(a == "_control" and b == "_decisions" for a, b in zip(parts, parts[1:], strict=False))


def transport_ok(url: str) -> bool:
    """https:// immer; http:// nur fuer IP-Literale: Loopback (v4/v6) und Tailscale 100.64.0.0/10
    (WireGuard verschluesselt den Weg). Hostnamen nur mit https: eine Aufloesung waere nicht an die
    Zieladresse gebunden."""
    parts = urlsplit(url)
    host = (parts.hostname or "").lower()
    if parts.scheme == "https":
        return bool(host)
    if parts.scheme != "http" or not host:
        return False
    try:
        addr = ipaddress.ip_address(host)
    except ValueError:
        return False
    return addr.is_loopback or addr in ipaddress.ip_network("100.64.0.0/10")


def resolve(settings: Settings, env: dict[str, str] | None = None) -> StarConfig:
    """Konfiguration auswaehlen. Wirft ``StarUnavailable`` (= nur lesbar), nie ein Fallback auf 'ohne star'."""
    env = os.environ if env is None else env
    mode = (env.get("DECISION_CLICKER_STAR") or "auto").strip().lower()
    if mode not in MODES:
        raise StarUnavailable(
            f"DECISION_CLICKER_STAR={mode!r} ist ungueltig (erlaubt: auto, server, local; "
            "einen 'off'-Schalter gibt es nicht) — Kette ist nur lesbar.")
    eco = is_ecosystem_chain(settings, env)
    raw_host = env.get("DECISION_CLICKER_HOST_ID") or socket.gethostname()
    host = _WORKER_HOST_RE.sub("-", raw_host).strip("-.").lower() or "host"
    worker = env.get("DECISION_CLICKER_WORKER") or f"decision-writer@{host}"
    if "@" in worker:
        host = worker.rsplit("@", 1)[1]
    resource = env.get("DECISION_CLICKER_STAR_RESOURCE") or RESOURCE
    margin = float(env.get("DECISION_CLICKER_STAR_MARGIN") or DEFAULT_MARGIN)
    role = (env.get("DECISION_CLICKER_STAR_ROLE") or "standby").strip().lower()
    if role not in ("server", "standby"):
        raise StarUnavailable(f"DECISION_CLICKER_STAR_ROLE={role!r} ist ungueltig (server | standby).")
    renew_seconds = float(env.get("DECISION_CLICKER_STAR_RENEW") or 40)
    window = env.get("DECISION_CLICKER_REBASELINE_WINDOW")
    stable = DEFAULT_STABLE_SECONDS if window in (None, "") else max(0.0, float(window))
    if mode == "local" and eco:
        raise StarUnavailable(
            "LocalStar gilt nur fuer nicht geteilte Ketten; diese Kette ist im Oekosystem "
            "registriert (BACH-Lead/_CONTROL/_DECISIONS) — Kette ist nur lesbar.")
    if mode == "server" or eco:
        url = (env.get("DECISION_CLICKER_LEAD_URL") or env.get("BACH_LEAD_URL") or "").rstrip("/")
        token = env.get("DECISION_CLICKER_DEVICE_TOKEN") or env.get("BACH_DEVICE_TOKEN") or ""
        if not url or not token:
            raise StarUnavailable(
                "Oekosystem-Kette ohne konfigurierten BACH-Lead (DECISION_CLICKER_LEAD_URL) "
                "oder Geraete-Token — Kette ist nur lesbar.")
        if not transport_ok(url):
            raise StarUnavailable(
                "Der BACH-Lead muss per https:// erreichbar sein (http:// nur fuer IP-Literale: Loopback "
                "und Tailscale 100.64.0.0/10) — Kette ist nur lesbar.")
        return StarConfig("server", resource, worker, host, url, token, margin, role=role,
                          renew_seconds=renew_seconds, stable_seconds=stable)
    key = "local:" + str(Path(settings.chain_dir).resolve())
    return StarConfig("local", resource, worker, host, margin=margin, chain_key=key, role="server",
                      renew_seconds=renew_seconds, stable_seconds=0.0)  # ein Host: kein Sync-Rennen


def describe(settings: Settings) -> dict[str, Any]:
    """Zustand fuer Status/UI (ohne Netzzugriff): Dienst-Stern oder Konfiguration."""
    service = _services.get(chain_key(settings))
    if service is not None:
        return service.status()
    try:
        cfg = resolve(settings)
    except StarUnavailable as exc:
        return {"available": False, "error": str(exc)}
    return {"available": True, "kind": cfg.kind, "resource": cfg.resource, "worker": cfg.worker_id}


# ---------------------------------------------------------------------------
# Hold und Provider
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class Hold:
    """Gehaltener star. Die Frist beginnt beim SENDEN der Anfrage (monotonic)."""

    resource: str
    lease_id: str
    fence: int
    ttl: float
    remaining0: float
    sent_mono: float
    sent_wall: float
    margin: float

    def remaining(self, now_mono: float | None = None) -> float:
        return self.remaining0 - ((time.monotonic() if now_mono is None else now_mono) - self.sent_mono)

    def valid(self, margin: float | None = None, now_mono: float | None = None) -> bool:
        return self.remaining(now_mono) > (self.margin if margin is None else margin)

    def needs_online_check(self, now_mono: float | None = None, now_wall: float | None = None,
                           margin: float | None = None) -> bool:
        """Wanduhr und Monoton-Takt laufen um mehr als die Marge auseinander (Suspend, Zeitsprung)."""
        mono = (time.monotonic() if now_mono is None else now_mono) - self.sent_mono
        wall = (time.time() if now_wall is None else now_wall) - self.sent_wall
        return abs(wall - mono) > (self.margin if margin is None else margin)


_DENIED_TEXT = {
    "stale_resource_version": "Kette ist noch nicht mit dem Stand des letzten Halters synchronisiert "
                              "(stale_resource_version) — spaeter erneut versuchen",
    "resource_version_required": "Manifest-Stand fehlt (resource_version_required)",
    "held": "der Polaris star wird gerade von einem anderen Schreiber gehalten (held)",
    "already_held_by_caller": "der Polaris star wird bereits gehalten (already_held_by_caller)",
    "server_active": "der Server-Schreiber ist aktiv (server_active)",
    "server_unknown": "kein Server-Schreiber bekannt, Uebernahme durch Standby nicht erlaubt (server_unknown)",
    "device_not_bound": "dieses Geraet darf nicht als dieser Worker schreiben (device_not_bound)",
    "worker_not_allowed": "dieser Worker ist fuer die Ressource nicht zugelassen (worker_not_allowed)",
    "server_priority": "der Server-Schreiber hat Vorrang angemeldet (server_priority)",
    "journal_not_synced": "eine Transaktion ist beim Lead offen, ihr Journal ist auf diesem Host noch nicht "
                          "angekommen (journal_not_synced) — spaeter erneut versuchen",
    "journal_unmatched": "Journal und Kette passen noch nicht zusammen, vermutlich nicht synchron "
                         "(journal_unmatched) — spaeter erneut versuchen",
    "journal_corrupt": "ein Journal ist beschaedigt oder unvollstaendig (journal_corrupt)",
    "rebaseline_unstable": "die Kette aendert sich noch (Sync laeuft?), Stabilitaetsfenster nicht erreicht "
                           "(rebaseline_unstable) — spaeter erneut versuchen",
    "journal_open": "ein Journal liegt offen, kein rebaseline (journal_open)",
}


def _denied(reason: str, detail: str = "", inflight: bool = False) -> StarUnavailable:
    text = f"{_DENIED_TEXT.get(reason, reason)}{' [' + detail + ']' if detail else ''}"
    error = StarUnavailable(f"Kein Polaris star: {text} — Kette ist nur lesbar.")
    error.reason = reason  # type: ignore[attr-defined]
    error.inflight = inflight  # type: ignore[attr-defined]
    return error


def worker_tag(cfg: StarConfig) -> str:
    """Kennung des Schreibers (Worker-ID ``agent@host``) fuer tmp-Dateinamen."""
    return re.sub(r"[^A-Za-z0-9@._-]", "-", cfg.worker_id)


def inflight_version(txid: str) -> str:
    """Versionsmarker einer laufenden journalisierten Transaktion (gueltiger SHA-256-Wert).

    Der Halter meldet ihn nach dem Journalschreiben. So kann der naechste Halter nach einem
    Sternverlust erwerben, obwohl die Kette den Manifest-Stand mitten in der Transaktion hat."""
    return hashlib.sha256(f"polaris-inflight:{txid}".encode()).hexdigest()


def _wire_time(value: Any) -> datetime:
    try:
        stamp = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        raise StarUnavailable("Lead lieferte einen ungueltigen Zeitstempel — Kette ist nur lesbar.") from None
    if stamp.tzinfo is None:
        raise StarUnavailable("Lead lieferte einen Zeitstempel ohne Zeitzone — Kette ist nur lesbar.")
    return stamp.astimezone(timezone.utc)


class ServerStar:
    """HTTP zum BACH-Lead (Authority), Geraete-Token als Bearer."""

    def __init__(self, cfg: StarConfig) -> None:
        self.cfg = cfg

    def _request(self, method: str, suffix: str, payload: dict | None = None,
                 headers: dict | None = None) -> tuple[int, dict, float, float]:
        url = f"{self.cfg.lead_url}/api/resources/{self.cfg.resource}/lease{suffix}"
        head = {"Accept": "application/json", "Authorization": f"Bearer {self.cfg.token}"}
        head.update(headers or {})
        data = None
        if payload is not None:
            data = json.dumps(payload).encode("utf-8")
            head["Content-Type"] = "application/json"
        request = urllib.request.Request(url, data=data, headers=head, method=method)
        sent_mono, sent_wall = time.monotonic(), time.time()
        try:
            with urllib.request.urlopen(request, timeout=self.cfg.timeout) as response:
                status, body = response.status, response.read().decode("utf-8")
        except urllib.error.HTTPError as err:
            status, body = err.code, err.read().decode("utf-8", "replace")
        except (urllib.error.URLError, TimeoutError, OSError):
            raise StarUnavailable(
                "BACH-Lead nicht erreichbar — keine Uebernahme, Kette ist nur lesbar.") from None
        if time.monotonic() - sent_mono > self.cfg.max_response:
            raise StarUnavailable("Antwort des Lead zu spaet — fail-closed, Kette ist nur lesbar.")
        try:
            parsed = json.loads(body) if body else {}
        except ValueError:
            raise StarUnavailable("Lead lieferte kein gueltiges JSON — Kette ist nur lesbar.") from None
        if not isinstance(parsed, dict):
            raise StarUnavailable("Lead-Antwort ist kein Objekt — Kette ist nur lesbar.")
        if status in (401, 403):
            raise StarUnavailable("Geraete-Token vom Lead abgelehnt — Kette ist nur lesbar.")
        if status == 404:
            raise StarUnavailable(f"Ressource {self.cfg.resource!r} ist beim Lead nicht registriert — "
                                  "Kette ist nur lesbar.")
        if status >= 500 or status == 422:
            raise StarUnavailable(f"Lead verweigert die Operation (HTTP {status}) — Kette ist nur lesbar.")
        return status, parsed, sent_mono, sent_wall

    def _hold(self, data: dict, sent_mono: float, sent_wall: float) -> Hold:
        try:
            issued, now, expires = (_wire_time(data[k]) for k in ("issued_at", "server_now", "expires_at"))
            lease_id, fence = str(data["lease_id"]), data["fence"]
        except KeyError as exc:
            raise StarUnavailable(f"Lead-ACK unvollstaendig ({exc}) — Kette ist nur lesbar.") from None
        if type(fence) is not int or fence <= 0 or not issued <= now < expires:
            raise StarUnavailable("Ungueltiger Lead-ACK — Kette ist nur lesbar.")
        margin = max(self.cfg.margin, float(data.get("margin_seconds") or 0))
        return Hold(self.cfg.resource, lease_id, fence, (expires - issued).total_seconds(),
                    (expires - now).total_seconds(), sent_mono, sent_wall, margin)

    def acquire(self, version: str | None, rebaseline: bool = False) -> Hold:
        payload = {
            "worker_id": self.cfg.worker_id, "host": self.cfg.host, "request_id": "req-" + uuid.uuid4().hex,
            "ttl_profile": TTL_PROFILE, "intent": "decision-clicker", "resource_version": version}
        if rebaseline:
            payload["rebaseline"] = True
        status, data, mono, wall = self._request("POST", "", payload)
        if status != 200:
            raise _denied(str(data.get("reason") or f"http_{status}"),
                          inflight=bool(data.get("version_inflight")))
        return self._hold(data, mono, wall)

    def renew(self, hold: Hold, version: str | None = None, inflight: bool = False) -> Hold:
        payload = {"lease_id": hold.lease_id, "fence": hold.fence, "resource_version": version}
        if inflight:
            payload["inflight"] = True
        status, data, mono, wall = self._request("POST", "/renew", payload)
        if status != 200:
            raise StarLost(f"Polaris star verloren ({data.get('reason') or status}) — sofort stoppen, "
                           "kein Auto-Revert.")
        return self._hold(data, mono, wall)

    def release(self, hold: Hold) -> None:
        self._request("POST", "/release", {"lease_id": hold.lease_id, "fence": hold.fence})

    def verify(self, hold: Hold) -> None:
        status, data, _m, _w = self._request("GET", "", None, {"X-Lease-Id": hold.lease_id})
        if not (status == 200 and data.get("leased") and data.get("own") and data.get("fence") == hold.fence):
            raise StarLost("Polaris star verloren (Nachpruefung) — sofort stoppen, kein Auto-Revert.")


class LocalStar:
    """Einzelbetrieb: Lease in lokaler SQLite im Nutzerordner. NUR fuer nicht geteilte Ketten."""

    def __init__(self, cfg: StarConfig) -> None:
        self.cfg = cfg
        self.path = state_dir() / "star.db"

    def _connect(self) -> sqlite3.Connection:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(self.path), timeout=10.0)
        conn.execute("CREATE TABLE IF NOT EXISTS local_star (resource TEXT PRIMARY KEY, claim_id TEXT, "
                     "expires REAL, fence INTEGER NOT NULL DEFAULT 0, resource_version TEXT, "
                     "inflight INTEGER NOT NULL DEFAULT 0)")
        if "inflight" not in {r[1] for r in conn.execute("PRAGMA table_info(local_star)")}:
            conn.execute("ALTER TABLE local_star ADD COLUMN inflight INTEGER NOT NULL DEFAULT 0")
        conn.commit()
        return conn

    def _row(self, conn: sqlite3.Connection) -> tuple:
        conn.execute("INSERT OR IGNORE INTO local_star (resource) VALUES (?)", (self.cfg.chain_key,))
        return conn.execute("SELECT claim_id, expires, fence, resource_version, inflight FROM local_star "
                            "WHERE resource = ?", (self.cfg.chain_key,)).fetchone()

    def _hold(self, claim: str, fence: int, sent_mono: float, sent_wall: float) -> Hold:
        return Hold(self.cfg.resource, claim, fence, LOCAL_TTL, LOCAL_TTL, sent_mono, sent_wall, self.cfg.margin)

    def acquire(self, version: str | None, rebaseline: bool = False) -> Hold:
        mono, wall = time.monotonic(), time.time()
        conn = self._connect()
        try:
            conn.execute("BEGIN IMMEDIATE")
            claim, expires, fence, stored, inflight = self._row(conn)
            now = time.time()
            if claim and expires is not None and now < expires:
                conn.rollback()
                raise _denied("held")
            rebased = False
            if stored is not None and version != stored:
                if not (rebaseline and version is not None) or inflight:
                    conn.rollback()
                    raise _denied("stale_resource_version" if version else "resource_version_required",
                                  inflight=bool(inflight))
                rebased = True  # der einzige Host ist die Server-Rolle: externer Edit -> neuer Stand
            new = uuid.uuid4().hex
            done = conn.execute("UPDATE local_star SET claim_id = ?, expires = ?, fence = fence + 1, "
                                "resource_version = CASE WHEN ? THEN ? ELSE resource_version END, "
                                "inflight = CASE WHEN ? THEN 0 ELSE inflight END "
                                "WHERE resource = ? AND fence = ?",
                                (new, now + LOCAL_TTL, int(rebased), version, int(rebased),
                                 self.cfg.chain_key, fence))
            if done.rowcount != 1:
                conn.rollback()
                raise _denied("conflict")
            conn.commit()
            return self._hold(new, fence + 1, mono, wall)
        finally:
            conn.close()

    def renew(self, hold: Hold, version: str | None = None, inflight: bool = False) -> Hold:
        mono, wall = time.monotonic(), time.time()
        conn = self._connect()
        try:
            conn.execute("BEGIN IMMEDIATE")
            claim, expires, fence, _stored, _flag = self._row(conn)
            now = time.time()
            if claim != hold.lease_id or fence != hold.fence or expires is None or now >= expires:
                conn.rollback()
                raise StarLost("Polaris star verloren — sofort stoppen, kein Auto-Revert.")
            conn.execute("UPDATE local_star SET expires = ?, resource_version = COALESCE(?, resource_version), "
                         "inflight = CASE WHEN ? IS NULL THEN inflight ELSE ? END "
                         "WHERE resource = ? AND claim_id = ? AND fence = ?",
                         (now + LOCAL_TTL, version, version, int(inflight), self.cfg.chain_key, claim, fence))
            conn.commit()
            return self._hold(claim, fence, mono, wall)
        finally:
            conn.close()

    def release(self, hold: Hold) -> None:
        conn = self._connect()
        try:
            conn.execute("BEGIN IMMEDIATE")
            conn.execute("UPDATE local_star SET claim_id = NULL, expires = NULL WHERE resource = ? "
                         "AND claim_id = ? AND fence = ?", (self.cfg.chain_key, hold.lease_id, hold.fence))
            conn.commit()
        finally:
            conn.close()

    def verify(self, hold: Hold) -> None:
        conn = self._connect()
        try:
            claim, expires, fence, _stored, _flag = self._row(conn)
            conn.commit()
        finally:
            conn.close()
        if claim != hold.lease_id or fence != hold.fence or expires is None or time.time() >= expires:
            raise StarLost("Polaris star verloren (Nachpruefung) — sofort stoppen, kein Auto-Revert.")


def make_provider(cfg: StarConfig) -> ServerStar | LocalStar:
    return ServerStar(cfg) if cfg.kind == "server" else LocalStar(cfg)


# ---------------------------------------------------------------------------
# Transaktion
# ---------------------------------------------------------------------------
class Transaction:
    """Ein erworbener star waehrend einer Kettentransaktion (eigener Erwerb oder Dienst-Stern)."""

    def __init__(self, settings: Settings, cfg: StarConfig, provider: ServerStar | LocalStar,
                 service: Service | None = None) -> None:
        self.settings, self.cfg, self.provider, self.service = settings, cfg, provider, service
        self.txid = uuid.uuid4().hex[:8]
        self._hold: Hold | None = None
        self.via = "manifest"  # wie erworben: manifest | inflight:<txid> | rebaseline
        self.journal: Any = None  # offenes Journal dieser Transaktion (vermerkt Hashes vor dem Schreiben)

    @property
    def hold(self) -> Hold | None:
        return self.service.hold if self.service is not None else self._hold

    @hold.setter
    def hold(self, value: Hold | None) -> None:
        if self.service is not None:
            self.service.hold = value
        else:
            self._hold = value

    @property
    def fence(self) -> int:
        assert self.hold is not None
        return self.hold.fence

    def stamp(self) -> str:
        """Fence-Stempel einer vom Writer geschriebenen Eintragsstelle (eigener Absatz, siehe docs)."""
        return f"POLARIS-STAR: {self.cfg.resource}#{self.fence} {self.cfg.host} tx={self.txid}"

    def assert_valid(self, margin: float | None = None) -> None:
        """Fail-closed Pruefung unmittelbar vor JEDER Kettenschreibung."""
        hold = self.hold
        if hold is None or not hold.valid(margin):
            raise StarLost("Polaris star abgelaufen oder verloren — sofort stoppen, kein Auto-Revert.")
        if hold.needs_online_check(margin=margin) or hold.remaining() < hold.ttl / 2:
            self._renew()  # Zeitluecke bzw. halbe Frist: online erneuern (StarLost bei Verlust)

    def _renew(self, version: str | None = None, inflight: bool = False) -> None:
        if self.service is not None:
            self.service.renew_hold(version, inflight)
        else:
            assert self._hold is not None
            self._hold = self.provider.renew(self._hold, version, inflight)

    def report(self, version: str, inflight: bool = False) -> None:
        """Version beim Lead melden (renew) -- Commit-Marker oder In-flight-Marker."""
        assert self.hold is not None
        self._renew(version, inflight)

    def commit_marker(self, ignore: str | None = None, required: bool = False) -> bool:
        """Manifest-Hash per renew melden (loescht den In-flight-Marker). Liegt ein anderes Journal als
        ``ignore`` offen, wird NICHT gemeldet: der In-flight-Marker bleibt, die Recovery gehoert dem Journal.
        ``required``: statt ``False`` ein ``StarUnavailable`` (der Aufrufer behaelt sein Journal)."""
        folder = Path(self.settings.chain_dir) / JOURNAL_DIR
        if any(p.stem != ignore for p in (folder.glob("*.json") if folder.is_dir() else [])):
            if required:
                raise _denied("journal_open", "Commit-Marker nicht meldbar, fremdes Journal offen")
            return False
        self.report(chain_manifest(self.settings))
        return True


def _acquire(settings: Settings, provider: ServerStar | LocalStar, cfg: StarConfig,
             ignore_journals: bool = False) -> tuple[Hold, str]:
    """Erwerb mit Sync-Schranke. Liefert den star und den Weg (``Transaction.via``).

    1. lokaler Manifest-Hash; 2. nach Sternverlust in einer journalisierten Transaktion: In-flight-Marker
    eines lokal vorhandenen Journals (ohne lokales Journal: ``journal_not_synced``, warten); 3. nur die
    Server-Rolle, nur ohne Journal und ohne In-flight, nur nach dem Stabilitaetsfenster: ``rebaseline``
    (externe Aenderung). Der Standby braucht immer den exakten Abgleich."""
    local = chain_manifest(settings)
    try:
        return provider.acquire(local), "manifest"
    except StarUnavailable as exc:
        if getattr(exc, "reason", None) != "stale_resource_version":
            raise
        stale = exc
    folder = Path(settings.chain_dir) / JOURNAL_DIR
    journals = sorted(folder.glob("*.json")) if folder.is_dir() else []
    for path in journals:
        try:
            return provider.acquire(inflight_version(path.stem)), f"inflight:{path.stem}"
        except StarUnavailable as again:
            if getattr(again, "reason", None) != "stale_resource_version":
                raise
    if getattr(stale, "inflight", False):
        raise _denied("journal_not_synced")
    if cfg.role != "server":
        raise stale
    if journals and not ignore_journals:  # ignore_journals: nur der Operatorpfad ``polaris journal resolve``
        raise _denied("journal_open")
    stable = stable_manifest(settings, cfg.stable_seconds)
    return provider.acquire(stable, rebaseline=True), "rebaseline"


# ---------------------------------------------------------------------------
# Dienstbetrieb: der Stern wird beim Start erworben, erneuert und beim Beenden zurueckgegeben
# ---------------------------------------------------------------------------
class Service:
    """Laufender Dienst (Clicker-Server): haelt den star dauerhaft, alle ``renew_seconds`` erneuert.

    Verliert er ihn, stoppen Schreibaktionen (``StarUnavailable``), der Status zeigt es, und der
    Heartbeat erwirbt neu (Journal-Wiederaufnahme inklusive). Einmalige CLI-Aufrufe und LocalStar
    erwerben dagegen pro Transaktion."""

    def __init__(self, settings: Settings, cfg: StarConfig, provider: ServerStar | LocalStar,
                 recover: Callable[[Transaction], None] | None, mutation_lock) -> None:
        self.settings, self.cfg, self.provider = settings, cfg, provider
        self.recover, self.mutation_lock = recover, mutation_lock
        self.hold: Hold | None = None
        self.last_error: str | None = None
        self.lost_count = 0
        self._hold_lock = threading.Lock()  # nur fuer self.hold (kein MUTATION_LOCK: keine neue Sperrreihenfolge)
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        self._try_acquire()
        self._thread = threading.Thread(target=self._loop, name="polaris-heartbeat", daemon=True)
        self._thread.start()

    def _try_acquire(self) -> None:
        try:
            with self.mutation_lock:
                hold, via = _acquire(self.settings, self.provider, self.cfg)
                self.hold, self.last_error = hold, None
                if self.recover is not None:
                    tx = Transaction(self.settings, self.cfg, self.provider, service=self)
                    tx.via = via
                    registry = _tls.__dict__.setdefault("active", {})
                    key = chain_key(self.settings)
                    registry[key] = tx
                    try:
                        self.recover(tx)
                    finally:
                        registry.pop(key, None)
        except Exception as exc:  # noqa: BLE001  jede Ausnahme: fail-closed, der Heartbeat versucht es erneut
            self.last_error = str(exc) or type(exc).__name__
            held, self.hold = self.hold, None  # ohne gelungene Recovery kein gehaltener star
            if held is not None and not isinstance(exc, StarLost):
                try:
                    self.provider.release(held)  # ohne Version: ein offener In-flight-Marker bleibt
                except Exception:  # noqa: BLE001
                    pass

    def renew_hold(self, version: str | None = None, inflight: bool = False) -> Hold:
        """Lesen-Erneuern-Schreiben von ``self.hold`` als eine Einheit (Heartbeat und Transaktionen)."""
        with self._hold_lock:
            hold = self.hold
            if hold is None:
                raise StarLost("Polaris star verloren — sofort stoppen, kein Auto-Revert.")
            self.hold = self.provider.renew(hold, version, inflight)
            return self.hold

    def _loop(self) -> None:
        while not self._stop.wait(self.cfg.renew_seconds):
            if self.hold is not None:
                try:
                    self.renew_hold()
                except StarUnavailable as exc:
                    self.mark_lost(f"Polaris star verloren ({exc})")
            if self.hold is None:
                self._try_acquire()

    def mark_lost(self, reason: str) -> None:
        with self._hold_lock:
            self.hold = None
            self.last_error = reason
            self.lost_count += 1

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=5)
        if not self.mutation_lock.acquire(timeout=30):  # laufende Transaktion zu Ende fuehren lassen
            self.hold = None  # nichts melden oder freigeben: die Frist laeuft fail-closed ab
            return
        try:
            hold, self.hold = self.hold, None
            if hold is not None:
                try:
                    tx = Transaction(self.settings, self.cfg, self.provider)
                    tx.hold = hold
                    if tx.commit_marker():
                        hold = tx.hold
                    self.provider.release(hold)
                except StarUnavailable:
                    pass
        finally:
            self.mutation_lock.release()

    def status(self) -> dict[str, Any]:
        hold = self.hold
        return {"available": hold is not None, "kind": self.cfg.kind, "mode": "service",
                "resource": self.cfg.resource, "worker": self.cfg.worker_id, "held": hold is not None,
                "fence": hold.fence if hold else None, "lost_count": self.lost_count,
                "error": self.last_error}


_services: dict[str, Service] = {}
_tls = threading.local()


def chain_key(settings: Settings) -> str:
    """Schluessel der Dienst- und Transaktions-Registry: aufgeloest und schreibweisen-normalisiert
    (Windows: ``C:\\Kette`` und ``c:\\kette`` sind dieselbe Kette)."""
    return os.path.normcase(os.path.realpath(settings.chain_dir))


def start_service(settings: Settings, *, recover: Callable[[Transaction], None] | None = None,
                  mutation_lock=None) -> Service | None:
    """Dienst-Stern starten (nur ServerStar). Gibt None zurueck, wenn die Kette im Einzelbetrieb laeuft."""
    cfg = resolve(settings)
    if cfg.kind != "server":
        return None
    key = chain_key(settings)
    service = Service(settings, cfg, make_provider(cfg), recover, mutation_lock or threading.RLock())
    _services[key] = service
    service.start()
    return service


def stop_service(settings: Settings) -> None:
    service = _services.pop(chain_key(settings), None)
    if service is not None:
        service.stop()


def active_transaction(settings: Settings) -> Transaction | None:
    return getattr(_tls, "active", {}).get(chain_key(settings))


@contextmanager
def transaction(settings: Settings, *, on_acquired: Callable[[Transaction], None] | None = None,
                ignore_journals: bool = False):
    """Block unter dem Polaris star ausfuehren.

    Mit laufendem Dienst: dessen gehaltener star wird genutzt, nichts erworben oder zurueckgegeben.
    Sonst: erwerben (Sync-Schranke), ausfuehren, Commit-Marker melden, zurueckgeben.
    Verschachtelte Aufrufe nutzen die aeussere Transaktion. Sternverlust (``StarLost``) stoppt ohne
    Revert; ein offenes Journal bleibt liegen."""
    existing = active_transaction(settings)
    if existing is not None:
        yield existing
        return
    key = chain_key(settings)
    registry = _tls.__dict__.setdefault("active", {})
    service = _services.get(key)
    if service is not None:
        if service.hold is None:
            raise StarUnavailable("Der Dienst hält den Polaris star gerade nicht (Neuerwerb läuft): "
                                  f"{service.last_error or 'unbekannt'} — Kette ist nur lesbar.")
        tx = Transaction(settings, service.cfg, service.provider, service=service)
        registry[key] = tx
        try:
            yield tx
        except StarLost as exc:
            service.mark_lost(f"Polaris star verloren ({exc})")
            raise
        else:
            tx.commit_marker()
        finally:
            registry.pop(key, None)
        return
    cfg = resolve(settings)
    provider = make_provider(cfg)
    tx = Transaction(settings, cfg, provider)
    tx.hold, tx.via = _acquire(settings, provider, cfg, ignore_journals)
    registry[key] = tx
    try:
        if on_acquired is not None:
            on_acquired(tx)
        yield tx
    except StarLost:
        raise  # Stern verloren: nichts mehr melden oder freigeben
    except BaseException:
        _finish(tx, quiet=True)
        raise
    else:
        _finish(tx, quiet=False)
    finally:
        registry.pop(key, None)


def _finish(tx: Transaction, *, quiet: bool) -> None:
    try:
        tx.commit_marker()
        tx.provider.release(tx.hold)  # type: ignore[arg-type]
    except StarUnavailable:
        if not quiet:
            raise
    except Exception:  # noqa: BLE001
        if not quiet:
            raise
