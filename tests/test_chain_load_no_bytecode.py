# SPDX-License-Identifier: MIT
"""Das Laden des Indexwerkzeugs darf im Zielverzeichnis kein __pycache__ hinterlassen
und kein dort liegendes, veraltetes .pyc verwenden (Fund aus dem Review von PR #7)."""
from __future__ import annotations

import sys
from pathlib import Path

from decision_clicker import chain


def _tool(tmp_path: Path, marker: str) -> Path:
    script = tmp_path / "decisions_index.py"
    lines = [f"MARKER = {marker!r}", "def match_heading(x):", "    return x", ""]
    script.write_text(chr(10).join(lines), encoding="utf-8")
    return script


def test_laden_schreibt_kein_pycache(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(sys, "dont_write_bytecode", False)
    chain._load_index_tool.cache_clear()
    script = _tool(tmp_path, "a")
    module = chain._load_index_tool(script)
    assert module.MARKER == "a"
    assert not (tmp_path / "__pycache__").exists()


def test_laden_ignoriert_veraltetes_pyc(tmp_path: Path, monkeypatch) -> None:
    import py_compile

    monkeypatch.setattr(sys, "dont_write_bytecode", False)
    chain._load_index_tool.cache_clear()
    script = _tool(tmp_path, "alt")
    cached = Path(py_compile.compile(str(script), doraise=True))
    # Quelle aendern, aber mtime/Groesse so lassen, dass das alte .pyc als gueltig durchgeht
    stat = script.stat()
    script.write_text(script.read_text(encoding="utf-8").replace("alt", "neu"), encoding="utf-8")
    import os
    os.utime(script, ns=(stat.st_atime_ns, stat.st_mtime_ns))
    assert cached.is_file()
    assert chain._load_index_tool(script).MARKER == "neu"
