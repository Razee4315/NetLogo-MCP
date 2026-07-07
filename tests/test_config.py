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


def test_gui_mode_defaults_true_off_macos(monkeypatch):
    monkeypatch.delenv("NETLOGO_GUI", raising=False)
    monkeypatch.setattr(config.sys, "platform", "win32")

    assert config.gui_unavailable_reason() is None
    assert config.get_gui_mode() is True


def test_gui_mode_respects_env_off_macos(monkeypatch):
    monkeypatch.setenv("NETLOGO_GUI", "false")
    monkeypatch.setattr(config.sys, "platform", "linux")

    assert config.get_gui_mode() is False


def test_gui_forced_headless_on_macos(monkeypatch):
    """Issue #30: pynetlogo forces headless on macOS, so the server must not
    claim GUI mode — get_gui_mode is False and a reason is surfaced, even when
    NETLOGO_GUI=true is set explicitly."""
    monkeypatch.setenv("NETLOGO_GUI", "true")
    monkeypatch.setattr(config.sys, "platform", "darwin")

    assert config.get_gui_mode() is False
    reason = config.gui_unavailable_reason()
    assert reason is not None
    assert "macOS" in reason
