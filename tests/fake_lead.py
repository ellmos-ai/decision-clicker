# SPDX-License-Identifier: MIT
"""Fake-BACH-Lead mit dem Vertrag der Ressourcen-Lease-Routen (Polaris P1).

Hermetisch: das oeffentliche Paket darf fuer seine Tests kein BACH-Repository
voraussetzen. Der Fake bildet nur ab, was der ServerStar benutzt:
``POST /api/resources/{name}/lease[/renew|/release]`` und ``GET .../lease`` mit
Bearer-Token, Fence als Hochwassermarke, TTL, ``stale_resource_version`` /
``resource_version_required``, ``held`` und ``own`` nur mit passender lease_id.
Die einmalige Gegenprobe gegen den echten Lead steht in den Belegen des Pakets.
"""
from __future__ import annotations

import json
import threading
import uuid
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

TOKEN = "fake-device-token"
TTL = 120


def _fmt(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


class FakeLead:
    def __init__(self, resource: str = "decisions-chain", allowed: set[str] | None = None,
                 ttl: float = TTL, server_workers: set[str] | None = None) -> None:
        self.resource = resource
        self.allowed = allowed
        self.ttl = ttl
        self.server_workers = server_workers or set()  # nur diese duerfen rebaselinen
        self.inflight = False
        self.reject_acquire = False  # Test: Neuerwerb voruebergehend verweigern
        self.events: list[str] = []
        self.skew = timedelta(0)  # verschiebt die Lead-Uhr (Ablauf erzwingen)
        self.fence = 0
        self.claim: dict | None = None
        self.version: str | None = None
        self.requests: list[tuple[str, str]] = []
        self.lock = threading.Lock()
        self._server: ThreadingHTTPServer | None = None

    # -- Lebenszyklus ------------------------------------------------------
    def start(self) -> str:
        lead = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):  # noqa: D401
                pass

            def _answer(self, status: int, payload: dict) -> None:
                body = json.dumps(payload).encode("utf-8")
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def _handle(self, method: str) -> None:
                length = int(self.headers.get("Content-Length") or 0)
                raw = self.rfile.read(length) if length else b""
                if self.headers.get("Authorization") != f"Bearer {TOKEN}":
                    return self._answer(401, {"detail": "unauthorized"})
                prefix = f"/api/resources/{lead.resource}/lease"
                if not self.path.startswith(prefix):
                    return self._answer(404, {"detail": "Ressource nicht registriert"})
                suffix = self.path[len(prefix):]
                body = json.loads(raw) if raw else {}
                with lead.lock:
                    lead.requests.append((method, suffix or "/"))
                    status, payload = lead.dispatch(method, suffix, body, self.headers.get("X-Lease-Id"))
                self._answer(status, payload)

            def do_GET(self):  # noqa: N802
                self._handle("GET")

            def do_POST(self):  # noqa: N802
                self._handle("POST")

        self._server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=self._server.serve_forever, daemon=True).start()
        return f"http://127.0.0.1:{self._server.server_address[1]}"

    def stop(self) -> None:
        if self._server is not None:
            self._server.shutdown()
            self._server.server_close()
            self._server = None

    # -- Vertrag -----------------------------------------------------------
    def now(self) -> datetime:
        return datetime.now(timezone.utc) + self.skew

    def expire(self) -> None:
        """Lead-Uhr hinter den Ablauf der aktuellen Lease schieben."""
        self.skew += timedelta(seconds=self.ttl + 5)

    def _live(self, now: datetime) -> bool:
        return self.claim is not None and now < self.claim["expires"]

    def _ack(self, now: datetime) -> dict:
        c = self.claim
        assert c is not None
        return {"granted": True, "resource": self.resource, "lease_id": c["id"], "fence": self.fence,
                "worker_id": c["worker"], "host": c["host"], "issued_at": _fmt(c["issued"]),
                "expires_at": _fmt(c["expires"]), "ttl_profile": "POLARIS", "server_now": _fmt(now),
                "resource_version": self.version, "renew_after_seconds": 40,
                "margin_seconds": 15 if self.ttl >= 60 else 0.5}

    def _deny(self, reason: str, now: datetime, **extra) -> tuple[int, dict]:
        return 409, {"granted": False, "reason": reason, "resource": self.resource, **extra,
                     "server_now": _fmt(now)}

    def dispatch(self, method: str, suffix: str, body: dict, own_id: str | None) -> tuple[int, dict]:
        now = self.now()
        if method == "GET":
            payload = {"resource": self.resource, "leased": self._live(now), "fence": self.fence,
                       "resource_version": self.version, "server_now": _fmt(now),
                       "version_inflight": self.inflight}
            if self._live(now) and own_id and own_id == self.claim["id"]:
                payload["own"] = True
            return 200, payload
        if suffix == "":
            worker = body.get("worker_id", "")
            if self.allowed is not None and worker not in self.allowed:
                return self._deny("device_not_bound", now)
            if self._live(now) or self.reject_acquire:
                return self._deny("held", now)
            if self.version is not None and body.get("resource_version") is None:
                return self._deny("resource_version_required", now, expected_resource_version=self.version)
            if self.version is not None and body.get("resource_version") != self.version:
                if not (body.get("rebaseline") and worker in self.server_workers):
                    return self._deny("stale_resource_version", now, expected_resource_version=self.version)
                if self.inflight:
                    return self._deny("inflight_open", now, expected_resource_version=self.version)
                self.version, self.inflight = body["resource_version"], False
                self.events.append("rebaseline_external_change")
            self.fence += 1
            self.claim = {"id": str(uuid.uuid4()), "worker": worker, "host": body.get("host"),
                          "issued": now, "expires": now + timedelta(seconds=self.ttl)}
            return 200, self._ack(now)
        holder = self.claim
        if holder is None or body.get("lease_id") != holder["id"] or body.get("fence") != self.fence:
            return self._deny("stale_fence", now, fence=self.fence)
        if suffix == "/renew":
            if not self._live(now):
                return self._deny("expired", now)
            holder["expires"] = now + timedelta(seconds=self.ttl)
            if body.get("resource_version"):
                self.version, self.inflight = body["resource_version"], bool(body.get("inflight"))
            return 200, self._ack(now)
        if suffix == "/release":
            if body.get("resource_version") and self._live(now):
                self.version, self.inflight = body["resource_version"], False
            self.claim = None
            return 200, {"released": True, "resource": self.resource, "fence": self.fence,
                         "late": False, "resource_version": self.version, "server_now": _fmt(now)}
        return 404, {"detail": "not found"}
