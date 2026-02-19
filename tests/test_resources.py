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
    monkeypatch.setattr(
        "netlogo_mcp.resources.get_models_dir", lambda: tmp_path
    )
    (tmp_path / "test.nlogo").write_text("to setup end")
    result = model_source("test")
    assert result == "to setup end"


def test_model_source_with_extension(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "netlogo_mcp.resources.get_models_dir", lambda: tmp_path
    )
    (tmp_path / "test.nlogo").write_text("to setup end")
    result = model_source("test.nlogo")
    assert result == "to setup end"
