"""Tests for NetLogo MCP tools."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path
from unittest.mock import MagicMock

import pytest

# We test the tool functions directly — they're async, so use pytest-asyncio.
from netlogo_mcp.tools import (
    command,
    create_model,
    export_view,
    export_world,
    get_patch_data,
    get_world_state,
    list_models,
    open_model,
    report,
    run_simulation,
    save_model,
    set_parameter,
)


# ── open_model ───────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_open_model_success(mock_context, mock_nl, tmp_path):
    model_file = tmp_path / "test.nlogo"
    model_file.write_text("to setup end")

    result = await open_model(str(model_file), mock_context)
    assert "test.nlogo" in result
    assert mock_nl._model_loaded


@pytest.mark.asyncio
async def test_open_model_not_found(mock_context):
    with pytest.raises(Exception, match="not found"):
        await open_model("/nonexistent/model.nlogo", mock_context)


@pytest.mark.asyncio
async def test_open_model_wrong_extension(mock_context, tmp_path):
    bad_file = tmp_path / "test.txt"
    bad_file.write_text("not a model")
    with pytest.raises(Exception, match="Not a .nlogo"):
        await open_model(str(bad_file), mock_context)


# ── command ──────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_command_success(mock_context, mock_nl):
    mock_nl._model_loaded = True
    result = await command("setup", mock_context)
    assert result == "OK: setup"


@pytest.mark.asyncio
async def test_command_no_model(mock_context, mock_nl):
    mock_nl._model_loaded = False
    with pytest.raises(Exception):
        await command("setup", mock_context)


# ── report ───────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_report_success(mock_context, mock_nl):
    mock_nl._model_loaded = True
    result = await report("count turtles", mock_context)
    assert json.loads(result) == 100


@pytest.mark.asyncio
async def test_report_no_model(mock_context, mock_nl):
    mock_nl._model_loaded = False
    with pytest.raises(Exception):
        await report("count turtles", mock_context)


# ── run_simulation ───────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_run_simulation_success(mock_context, mock_nl):
    mock_nl._model_loaded = True
    result = await run_simulation(10, ["count turtles"], mock_context)
    assert "| tick |" in result
    assert "count turtles" in result


@pytest.mark.asyncio
async def test_run_simulation_bad_ticks(mock_context, mock_nl):
    mock_nl._model_loaded = True
    with pytest.raises(Exception, match="ticks must be"):
        await run_simulation(0, ["count turtles"], mock_context)


@pytest.mark.asyncio
async def test_run_simulation_empty_reporters(mock_context, mock_nl):
    mock_nl._model_loaded = True
    with pytest.raises(Exception, match="reporters"):
        await run_simulation(10, [], mock_context)


# ── set_parameter ────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_set_parameter_number(mock_context, mock_nl):
    mock_nl._model_loaded = True
    result = await set_parameter("speed", 5, mock_context)
    assert "speed" in result
    assert "5" in result


@pytest.mark.asyncio
async def test_set_parameter_bool(mock_context, mock_nl):
    mock_nl._model_loaded = True
    result = await set_parameter("show-energy?", True, mock_context)
    assert "true" in result


@pytest.mark.asyncio
async def test_set_parameter_string(mock_context, mock_nl):
    mock_nl._model_loaded = True
    result = await set_parameter("label-text", "hello", mock_context)
    assert '"hello"' in result


# ── get_world_state ──────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_get_world_state(mock_context, mock_nl):
    mock_nl._model_loaded = True
    result = await get_world_state(mock_context)
    state = json.loads(result)
    assert state["turtle_count"] == 100
    assert state["ticks"] == 0
    assert state["min_pxcor"] == -16


# ── get_patch_data ───────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_get_patch_data(mock_context, mock_nl):
    mock_nl._model_loaded = True
    result = await get_patch_data("pcolor", mock_context)
    grid = json.loads(result)
    assert isinstance(grid, list)
    assert grid[0] == [1, 2]


# ── create_model ─────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_create_model_raw_code(mock_context, mock_nl):
    code = "globals [x]\nto setup\n  clear-all\n  reset-ticks\nend\nto go\n  tick\nend"
    result = await create_model(code, mock_context)
    assert "created" in result.lower()
    assert mock_nl._model_loaded


@pytest.mark.asyncio
async def test_create_model_full_nlogo(mock_context, mock_nl):
    code = "to setup end\n@#$#@#$#@\ninterface\n@#$#@#$#@\ninfo"
    result = await create_model(code, mock_context)
    assert "created" in result.lower()


# ── list_models ──────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_list_models_empty(mock_context, tmp_path, monkeypatch):
    monkeypatch.setattr("netlogo_mcp.tools.get_models_dir", lambda: tmp_path)
    result = await list_models(mock_context)
    assert json.loads(result) == []


@pytest.mark.asyncio
async def test_list_models_with_files(mock_context, tmp_path, monkeypatch):
    monkeypatch.setattr("netlogo_mcp.tools.get_models_dir", lambda: tmp_path)
    (tmp_path / "model1.nlogo").write_text("code")
    (tmp_path / "model2.nlogo").write_text("code")
    result = await list_models(mock_context)
    models = json.loads(result)
    assert len(models) == 2
    names = {m["name"] for m in models}
    assert names == {"model1", "model2"}


# ── export_view (basic check — actual PNG needs real NetLogo) ────────────────


@pytest.mark.asyncio
async def test_export_view_calls_command(mock_context, mock_nl):
    mock_nl._model_loaded = True
    # export_view will call nl.command("export-view ...") which succeeds on mock
    # but Image(path=...) will point to a non-existent PNG — that's expected in mocks.
    # We just verify it doesn't crash before the Image creation step.
    # A full integration test requires real NetLogo.
    try:
        await export_view(mock_context)
    except FileNotFoundError:
        # Expected — mock doesn't create actual PNG files
        pass


# ── save_model ───────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_save_model_success(mock_context, tmp_path, monkeypatch):
    monkeypatch.setattr("netlogo_mcp.tools.get_models_dir", lambda: tmp_path)
    code = "to setup\n  clear-all\n  reset-ticks\nend"
    result = await save_model("my_model", code, mock_context)
    assert "saved" in result.lower()
    saved_file = tmp_path / "my_model.nlogox"
    assert saved_file.exists()
    content = saved_file.read_text(encoding="utf-8")
    assert "clear-all" in content
    assert "<?xml" in content  # envelope was added


@pytest.mark.asyncio
async def test_save_model_path_traversal(mock_context):
    with pytest.raises(Exception, match="path separators"):
        await save_model("../../evil", "to setup end", mock_context)


@pytest.mark.asyncio
async def test_save_model_preserves_xml(mock_context, tmp_path, monkeypatch):
    monkeypatch.setattr("netlogo_mcp.tools.get_models_dir", lambda: tmp_path)
    xml = '<?xml version="1.0"?><model version="NetLogo 7.0.3"><code>to setup end</code></model>'
    result = await save_model("full_xml", xml, mock_context)
    saved = (tmp_path / "full_xml.nlogox").read_text(encoding="utf-8")
    assert saved == xml  # raw XML preserved, no double-wrapping


# ── export_world ─────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_export_world(mock_context, mock_nl):
    mock_nl._model_loaded = True
    result = await export_world(mock_context)
    assert "exported" in result.lower()
    assert ".csv" in result
