# SPDX-License-Identifier: MIT
"""Portable path and environment configuration."""
from __future__ import annotations

import os
from pathlib import Path

from decision_clicker import intake
from decision_clicker.config import Settings, default_onedrive_root, is_loopback_host, load


def test_onedrive_environment_wins_without_personal_path(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("OneDrive", str(tmp_path))
    monkeypatch.delenv("OneDriveCommercial", raising=False)
    monkeypatch.delenv("OneDriveConsumer", raising=False)
    assert default_onedrive_root() == tmp_path


def test_load_respects_explicit_chain_host_and_port(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("DECISION_CLICKER_CHAIN", str(tmp_path))
    monkeypatch.setenv("DECISION_CLICKER_HOST", "localhost")
    monkeypatch.setenv("DECISION_CLICKER_PORT", "18096")
    assert load() == Settings(chain_dir=tmp_path, host="localhost", port=18096)


def test_inbox_environment_supports_multiple_paths(tmp_path: Path, monkeypatch):
    first = tmp_path / "first.txt"
    second = tmp_path / "second.txt"
    monkeypatch.setenv("DECISION_CLICKER_INBOX", os.pathsep.join((str(first), str(second))))
    assert intake._default_sources() == (first, second)


def test_lock_name_is_agent_neutral(tmp_path: Path):
    assert Settings(chain_dir=tmp_path).lock_file == tmp_path / "LOCK.decision-clicker.txt"


def test_server_host_muss_loopback_sein():
    assert is_loopback_host("127.0.0.1")
    assert is_loopback_host("127.23.4.5")
    assert is_loopback_host("localhost")
    assert is_loopback_host("::1")
    assert not is_loopback_host("0.0.0.0")
    assert not is_loopback_host("192.168.1.10")
    assert not is_loopback_host("example.com")
