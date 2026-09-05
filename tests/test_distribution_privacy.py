# SPDX-License-Identifier: MIT
"""Release-Artefakte dürfen keine lokale Real-Daten-Fixture enthalten."""
from __future__ import annotations

import subprocess
import sys
import tarfile
import zipfile
from pathlib import Path


def test_sdist_und_wheel_enthalten_nur_freigegebene_testdaten(tmp_path: Path):
    root = Path(__file__).resolve().parents[1]
    subprocess.run(
        [sys.executable, "-m", "build", "--no-isolation", "--outdir", str(tmp_path)],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    sdist = next(tmp_path.glob("*.tar.gz"))
    wheel = next(tmp_path.glob("*.whl"))
    with tarfile.open(sdist) as archiv:
        sdist_names = set(archiv.getnames())
    with zipfile.ZipFile(wheel) as archiv:
        wheel_names = set(archiv.namelist())

    forbidden = "tests/data/postfach_2026-08-07.txt"
    assert not any(name.endswith(forbidden) for name in sdist_names | wheel_names)
    assert any(name.endswith("tests/data/postfach_sample.txt") for name in sdist_names)
    assert any(name.endswith("tests/data/chain/TO-DECIDE-USER.txt") for name in sdist_names)
