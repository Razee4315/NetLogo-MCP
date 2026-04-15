"""Tests for NetLogo MCP resources."""

from __future__ import annotations

import pytest

from netlogo_mcp.resources import (
    model_source,
    primitives_reference,
    programming_guide,
)


def test_primitives_reference_returns_string():
    result = primitives_reference()
    assert isinstance(result, str)
    assert len(result) > 100
    assert "turtle" in result.lower() or "create" in result.lower()


def test_programming_guide_returns_string():
    result = programming_guide()
    assert isinstance(result, str)
    assert len(result) > 100
    assert "breed" in result.lower() or "setup" in result.lower()


def test_model_source_not_found():
    with pytest.raises(Exception, match="not found"):
        model_source("nonexistent_model")


def test_model_source_path_traversal_dots():
    with pytest.raises(Exception, match="path traversal"):
        model_source("../../etc/passwd")


def test_model_source_path_traversal_slash():
    with pytest.raises(Exception, match="path traversal"):
        model_source("subdir/model")


def test_model_source_path_traversal_backslash():
    with pytest.raises(Exception, match="path traversal"):
        model_source("subdir\\model")


def test_model_source_success(tmp_path, monkeypatch):
    monkeypatch.setattr("netlogo_mcp.resources.get_models_dir", lambda: tmp_path)
    (tmp_path / "test.nlogo").write_text("to setup end")
    result = model_source("test")
    assert result == "to setup end"


def test_model_source_with_extension(tmp_path, monkeypatch):
    monkeypatch.setattr("netlogo_mcp.resources.get_models_dir", lambda: tmp_path)
    (tmp_path / "test.nlogo").write_text("to setup end")
    result = model_source("test.nlogo")
    assert result == "to setup end"


# ── .nlogox support ─────────────────────────────────────────────────────────


def test_model_source_nlogox_by_name(tmp_path, monkeypatch):
    """Bare name should find .nlogox when .nlogo doesn't exist."""
    monkeypatch.setattr("netlogo_mcp.resources.get_models_dir", lambda: tmp_path)
    (tmp_path / "mymodel.nlogox").write_text("<model>xml</model>")
    result = model_source("mymodel")
    assert result == "<model>xml</model>"


def test_model_source_nlogox_with_extension(tmp_path, monkeypatch):
    """Explicit .nlogox extension should work."""
    monkeypatch.setattr("netlogo_mcp.resources.get_models_dir", lambda: tmp_path)
    (tmp_path / "mymodel.nlogox").write_text("<model>xml</model>")
    result = model_source("mymodel.nlogox")
    assert result == "<model>xml</model>"


def test_model_source_prefers_nlogo_over_nlogox(tmp_path, monkeypatch):
    """When both .nlogo and .nlogox exist, bare name returns .nlogo."""
    monkeypatch.setattr("netlogo_mcp.resources.get_models_dir", lambda: tmp_path)
    (tmp_path / "dual.nlogo").write_text("nlogo content")
    (tmp_path / "dual.nlogox").write_text("nlogox content")
    result = model_source("dual")
    assert result == "nlogo content"
