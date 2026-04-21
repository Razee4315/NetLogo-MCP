"""Tests for config directory defaults."""

from __future__ import annotations

from pathlib import Path

from netlogo_mcp import config


def test_models_dir_defaults_to_current_working_directory(monkeypatch, tmp_path):
    monkeypatch.delenv("NETLOGO_MODELS_DIR", raising=False)
    monkeypatch.chdir(tmp_path)

    models_dir = config.get_models_dir()

    assert models_dir == Path(tmp_path) / "models"
    assert models_dir.is_dir()


def test_exports_dir_defaults_to_current_working_directory(monkeypatch, tmp_path):
    monkeypatch.delenv("NETLOGO_EXPORTS_DIR", raising=False)
    monkeypatch.chdir(tmp_path)

    exports_dir = config.get_exports_dir()

    assert exports_dir == Path(tmp_path) / "exports"
    assert (exports_dir / "views").is_dir()
    assert (exports_dir / "worlds").is_dir()
