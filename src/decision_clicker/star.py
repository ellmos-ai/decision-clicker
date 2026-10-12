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
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .config import Settings, state_dir
from .errors import StarLost, StarUnavailable

RESOURCE = "decisions-chain"
TTL_PROFILE = "POLARIS"
DEFAULT_MARGIN = 15.0
DEFAULT_MAX_RESPONSE = 5.0
DEFAULT_TIMEOUT = 8.0
LOCAL_TTL = 120.0
JOURNAL_DIR = "_polaris-journal"
#: Ressourcenumfang (Festlegung 4): Kettendateien samt Journal. Backups gehoeren nicht dazu.
CHAIN_PATHS = ("TO-DECIDE-USER.txt", "DECIDED-AND-DONE.md", "_decision-archive", "_archive", JOURNAL_DIR)
MODES = ("auto", "server", "local")
_WORKER_HOST_RE = re.compile(r"[^A-Za-z0-9._-]")


# ---------------------------------------------------------------------------
# Manifest (Sync-Schranke) -- identisch zu BACH ``lease_core.manifest_version``
# ---------------------------------------------------------------------------
def manifest_version(root: Path | str, paths: Iterable[str]) -> str:
    """SHA-256 ueber sortierte relative Pfade (``/``), Groesse und SHA-256 jeder
    Datei; fehlende Dateien gehen als ``MISSING`` ein, Ordner rekursiv. Ein leerer Ordner zaehlt
    wie ein fehlender (sonst unterschiede sich der Stand je nachdem, ob ein Host einen leeren
    Journal-Ordner angelegt hat)."""
    base = Path(root)
    entries: dict[str, str] = {}
    for rel in paths:
        target = base / rel
        files = sorted(p for p in target.rglob("*") if p.is_file()) if target.is_dir() else []
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
    token: str = ""
    margin: float = DEFAULT_MARGIN
    timeout: float = DEFAULT_TIMEOUT
    max_response: float = DEFAULT_MAX_RESPONSE
    chain_key: str = ""


def is_ecosystem_chain(settings: Settings, env: dict[str, str] | None = None) -> bool:
    """Registrierte Kette: BACH-Lead konfiguriert oder die Kette ``_CONTROL/_DECISIONS``."""
    env = os.environ if env is None else env
    if env.get("DECISION_CLICKER_LEAD_URL") or env.get("BACH_LEAD_URL"):
        return True
    parts = [p.lower() for p in Path(settings.chain_dir).parts]
    return any(a == "_control" and b == "_decisions" for a, b in zip(parts, parts[1:], strict=False))


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
    if mode == "local" and eco:
        raise StarUnavailable(
            "LocalStar gilt nur fuer nicht geteilte Ketten; diese Kette ist im Oekosystem "
            "registriert (BACH-Lead/_CONTROL/_DECISIONS) — Kette ist nur lesbar.")
    if mode == "server" or eco:
        url = (env.get("DECISION_CLICKER_LEAD_URL") or env.get("BACH_LEAD_URL") or "").rstrip("/")
        token = env.get("DECISION_CLICKER_DEVICE_TOKEN") or env.get("BACH_DEVICE_TOKEN") or ""
        scheme_ok = url.startswith(("http://", "https://"))
        if not url or not scheme_ok or not token:
            raise StarUnavailable(
                "Oekosystem-Kette ohne konfigurierten BACH-Lead (DECISION_CLICKER_LEAD_URL) "
                "oder Geraete-Token — Kette ist nur lesbar.")
        return StarConfig("server", resource, worker, host, url, token, margin)
    key = "local:" + str(Path(settings.chain_dir).resolve())
    return StarConfig("local", resource, worker, host, margin=margin, chain_key=key)


def describe(settings: Settings) -> dict[str, Any]:
    """Zustand der Konfiguration fuer Status/UI (ohne Netzzugriff)."""
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
}


def _denied(reason: str) -> StarUnavailable:
    error = StarUnavailable(f"Kein Polaris star: {_DENIED_TEXT.get(reason, reason)} — Kette ist nur lesbar.")
    error.reason = reason  # type: ignore[attr-defined]
    return error


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

    def acquire(self, version: str | None) -> Hold:
        status, data, mono, wall = self._request("POST", "", {
            "worker_id": self.cfg.worker_id, "host": self.cfg.host, "request_id": "req-" + uuid.uuid4().hex,
            "ttl_profile": TTL_PROFILE, "intent": "decision-clicker", "resource_version": version})
        if status != 200:
            raise _denied(str(data.get("reason") or f"http_{status}"))
        return self._hold(data, mono, wall)

    def renew(self, hold: Hold, version: str | None = None) -> Hold:
        status, data, mono, wall = self._request("POST", "/renew", {
            "lease_id": hold.lease_id, "fence": hold.fence, "resource_version": version})
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
                     "expires REAL, fence INTEGER NOT NULL DEFAULT 0, resource_version TEXT)")
        conn.commit()
        return conn

    def _row(self, conn: sqlite3.Connection) -> tuple:
        conn.execute("INSERT OR IGNORE INTO local_star (resource) VALUES (?)", (self.cfg.chain_key,))
        return conn.execute("SELECT claim_id, expires, fence, resource_version FROM local_star "
                            "WHERE resource = ?", (self.cfg.chain_key,)).fetchone()

    def _hold(self, claim: str, fence: int, sent_mono: float, sent_wall: float) -> Hold:
        return Hold(self.cfg.resource, claim, fence, LOCAL_TTL, LOCAL_TTL, sent_mono, sent_wall, self.cfg.margin)

    def acquire(self, version: str | None) -> Hold:
        mono, wall = time.monotonic(), time.time()
        conn = self._connect()
        try:
            conn.execute("BEGIN IMMEDIATE")
            claim, expires, fence, stored = self._row(conn)
            now = time.time()
            if claim and expires is not None and now < expires:
                conn.rollback()
                raise _denied("held")
            if stored is not None and version != stored:
                conn.rollback()
                raise _denied("stale_resource_version" if version else "resource_version_required")
            new = uuid.uuid4().hex
            done = conn.execute("UPDATE local_star SET claim_id = ?, expires = ?, fence = fence + 1 "
                                "WHERE resource = ? AND fence = ?",
                                (new, now + LOCAL_TTL, self.cfg.chain_key, fence))
            if done.rowcount != 1:
                conn.rollback()
                raise _denied("conflict")
            conn.commit()
            return self._hold(new, fence + 1, mono, wall)
        finally:
            conn.close()

    def renew(self, hold: Hold, version: str | None = None) -> Hold:
        mono, wall = time.monotonic(), time.time()
        conn = self._connect()
        try:
            conn.execute("BEGIN IMMEDIATE")
            claim, expires, fence, _stored = self._row(conn)
            now = time.time()
            if claim != hold.lease_id or fence != hold.fence or expires is None or now >= expires:
                conn.rollback()
                raise StarLost("Polaris star verloren — sofort stoppen, kein Auto-Revert.")
            conn.execute("UPDATE local_star SET expires = ?, resource_version = COALESCE(?, resource_version) "
                         "WHERE resource = ? AND claim_id = ? AND fence = ?",
                         (now + LOCAL_TTL, version, self.cfg.chain_key, claim, fence))
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
            claim, expires, fence, _stored = self._row(conn)
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
    """Ein erworbener star waehrend einer Kettentransaktion."""

    def __init__(self, settings: Settings, cfg: StarConfig, provider: ServerStar | LocalStar) -> None:
        self.settings, self.cfg, self.provider = settings, cfg, provider
        self.txid = uuid.uuid4().hex[:8]
        self.hold: Hold | None = None

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
        if hold.needs_online_check(margin=margin):
            self.hold = self.provider.renew(hold)  # Zeitluecke: online neu pruefen (StarLost bei Verlust)
        elif hold.remaining() < hold.ttl / 2:
            self.hold = self.provider.renew(hold)

    def report(self, version: str) -> None:
        """Version beim Lead melden (renew) -- Commit-Marker oder In-flight-Marker."""
        assert self.hold is not None
        self.hold = self.provider.renew(self.hold, version)

    def commit_marker(self) -> None:
        """Letzter Schritt einer abgeschlossenen Transaktion: Manifest-Hash per renew melden."""
        assert self.hold is not None
        self.hold = self.provider.renew(self.hold, chain_manifest(self.settings))


def _acquire(settings: Settings, provider: ServerStar | LocalStar) -> Hold:
    """Erwerb mit Sync-Schranke. Nach einem Sternverlust mitten in einer journalisierten
    Transaktion passt der lokale Stand nicht zum letzten Commit; dann gilt der In-flight-Marker
    des offenen Journals (gemeldet vom abgestuerzten Halter)."""
    try:
        return provider.acquire(chain_manifest(settings))
    except StarUnavailable as exc:
        if getattr(exc, "reason", None) != "stale_resource_version":
            raise
        folder = Path(settings.chain_dir) / JOURNAL_DIR
        for path in sorted(folder.glob("*.json")) if folder.is_dir() else []:
            try:
                return provider.acquire(inflight_version(path.stem))
            except StarUnavailable as again:
                if getattr(again, "reason", None) != "stale_resource_version":
                    raise
        raise


_tls = threading.local()


def active_transaction(settings: Settings) -> Transaction | None:
    return getattr(_tls, "active", {}).get(str(Path(settings.chain_dir)))


@contextmanager
def transaction(settings: Settings, *, on_acquired: Callable[[Transaction], None] | None = None):
    """Star erwerben (Sync-Schranke), Block ausfuehren, Commit-Marker melden, zurueckgeben.

    Verschachtelte Aufrufe nutzen die aeussere Transaktion. Sternverlust
    (``StarLost``) stoppt ohne Revert; ein offenes Journal bleibt liegen.
    """
    existing = active_transaction(settings)
    if existing is not None:
        yield existing
        return
    cfg = resolve(settings)
    tx = Transaction(settings, cfg, make_provider(cfg))
    tx.hold = _acquire(settings, tx.provider)
    registry = _tls.__dict__.setdefault("active", {})
    key = str(Path(settings.chain_dir))
    registry[key] = tx
    lost = False
    try:
        if on_acquired is not None:
            on_acquired(tx)
        yield tx
    except StarLost:
        lost = True
        raise
    except BaseException:
        _finish(tx, quiet=True)
        raise
    else:
        _finish(tx, quiet=False)
    finally:
        registry.pop(key, None)
        if lost:
            pass  # Stern verloren: nichts mehr melden oder freigeben


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
