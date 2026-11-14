# SPDX-License-Identifier: MIT
"""Stable version and evidence references for decision proposals.

The text chain remains the source of truth.  This module only defines the
small, deterministic value contract shared by the writer, index adapter and
human-facing API; it does not keep state of its own.
"""
from __future__ import annotations

import hashlib
import re
from collections.abc import Mapping

DEFAULT_VERSION = "1"
DEFAULT_EVIDENCE_STATE = "UNBEKANNT"
VERSION_RE = re.compile(r"^[1-9][0-9]*$")
LINE_BREAK_RE = re.compile(r"[\r\n\v\f\x1c-\x1e\x85\u2028\u2029]")


def normalise_version(value: object, field: str = "Version") -> str:
    """Return a positive integer version or raise a value error."""
    text = str(value or "").strip()
    if not text:
        return DEFAULT_VERSION
    if not VERSION_RE.fullmatch(text):
        raise ValueError(f"{field} muss eine positive ganze Zahl sein.")
    return text


def normalise_evidence_state(value: object) -> str:
    """Validate the single-line evidence state without claiming truth."""
    text = str(value or "").strip()
    if not text:
        return DEFAULT_EVIDENCE_STATE
    if LINE_BREAK_RE.search(text) or ";" in text:
        raise ValueError(
            "Evidenzstand darf keinen Zeilenumbruch oder Semikolon enthalten."
        )
    return text


def derive_evidence_state(*values: object) -> str:
    """Create a deterministic state reference from supplied evidence metadata."""
    material = "\n".join(str(value or "").strip() for value in values)
    if not material:
        return DEFAULT_EVIDENCE_STATE
    digest = hashlib.sha256(material.encode("utf-8")).hexdigest()
    return f"sha256:{digest}"


def content_fingerprint(value: object) -> str:
    """Fingerprint the normalized option/recommendation wording."""
    material = " ".join(str(value or "").split())
    digest = hashlib.sha256(material.encode("utf-8")).hexdigest()
    return f"sha256:{digest}"


def make_reference(
    optionen_version: object = DEFAULT_VERSION,
    empfehlung_version: object = DEFAULT_VERSION,
    evidenzstand: object = DEFAULT_EVIDENCE_STATE,
    optionen_fingerprint: str = "",
    empfehlung_fingerprint: str = "",
) -> str:
    """Build the exact reference carried by a human click and its receipt."""
    optionen = normalise_version(optionen_version, "Optionen-Version")
    empfehlung = normalise_version(empfehlung_version, "Empfehlungs-Version")
    evidence = normalise_evidence_state(evidenzstand)
    reference = f"optionen=v{optionen};empfehlung=v{empfehlung};evidenzstand={evidence}"
    if optionen_fingerprint or empfehlung_fingerprint:
        reference += (
            f";optionen-inhalt={optionen_fingerprint}"
            f";empfehlung-inhalt={empfehlung_fingerprint}"
        )
    return reference


def _value(fields: Mapping[str, object], *names: str) -> object:
    normalised = {
        str(key).casefold().replace("-", "_").replace(" ", "_"): value
        for key, value in fields.items()
    }
    for name in names:
        if name in normalised:
            return normalised[name]
    return ""


def from_fields(fields: Mapping[str, object]) -> dict[str, str]:
    """Resolve canonical values from parser fields or an index entry dict."""
    common = _value(fields, "version")
    optionen = _value(fields, "optionen_version", "options_version") or common
    empfehlung = _value(
        fields, "empfehlung_version", "recommendation_version") or common
    evidence = _value(
        fields, "evidenzstand", "evidence_state", "evidence")
    if not evidence:
        evidence = _value(fields, "kontext_fingerprint", "context_fingerprint")
    optionen_text = normalise_version(optionen, "Optionen-Version")
    empfehlung_text = normalise_version(empfehlung, "Empfehlungs-Version")
    evidence_text = normalise_evidence_state(evidence)
    optionen_fingerprint = str(
        _value(fields, "optionen_fingerprint", "options_fingerprint")
        or content_fingerprint(_value(fields, "optionen"))
    )
    empfehlung_fingerprint = str(
        _value(fields, "empfehlung_fingerprint", "recommendation_fingerprint")
        or content_fingerprint(_value(fields, "empfehlung"))
    )
    return {
        "optionen_version": optionen_text,
        "empfehlung_version": empfehlung_text,
        "evidenzstand": evidence_text,
        "version_reference": make_reference(optionen_text, empfehlung_text, evidence_text),
        "optionen_fingerprint": optionen_fingerprint,
        "options_fingerprint": optionen_fingerprint,
        "empfehlung_fingerprint": empfehlung_fingerprint,
        "recommendation_fingerprint": empfehlung_fingerprint,
    }


def from_entry(entry: Mapping[str, object]) -> dict[str, str]:
    """Resolve values from a JSON/index entry, retaining old-entry defaults."""
    values = from_fields(entry)
    explicit = str(entry.get("version_reference") or "").strip()
    if explicit:
        values["version_reference"] = explicit
    for name in (
        "optionen_fingerprint", "options_fingerprint",
        "empfehlung_fingerprint", "recommendation_fingerprint",
    ):
        if entry.get(name):
            values[name] = str(entry[name])
    if not explicit:
        values["version_reference"] = make_reference(
            values["optionen_version"], values["empfehlung_version"],
            values["evidenzstand"], values["optionen_fingerprint"],
            values["empfehlung_fingerprint"],
        )
    return values
