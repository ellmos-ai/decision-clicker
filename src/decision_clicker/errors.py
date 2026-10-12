# SPDX-License-Identifier: MIT
"""Gemeinsame Fehlertypen (writer und star importieren beide, keiner den anderen)."""
from __future__ import annotations


class WriteError(RuntimeError):
    """Der Schreibvorgang wurde abgebrochen — die Datei ist unveraendert."""


class StarUnavailable(WriteError):
    """Kein gueltiger Polaris star: die Kette ist nur lesbar (HTTP 409 in der Clicker-API)."""


class StarLost(StarUnavailable):
    """Der Polaris star ging waehrend einer Transaktion verloren: stoppen, kein Auto-Revert."""
