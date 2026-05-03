"""Tests for NetLogo MCP tools."""

from __future__ import annotations

import json

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
    with pytest.raises(Exception, match="No model is loaded"):
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
    with pytest.raises(Exception, match="No model is loaded"):
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


@pytest.mark.asyncio
async def test_run_simulation_summary_only_returns_compact_table(mock_context, mock_nl):
    """summary_only=True returns one row per reporter, not one per tick."""
    mock_nl._model_loaded = True
    result = await run_simulation(
        100, ["count turtles", "ticks"], mock_context, summary_only=True
    )
    # One header line + one separator line + one row per reporter
    lines = result.split("\n")
    assert lines[0].startswith("| reporter | min | mean | max | std | final |")
    # Two reporters → exactly 2 data rows
    data_rows = [ln for ln in lines if ln.startswith("|") and "---" not in ln][1:]
    assert len(data_rows) == 2
    # Should NOT contain a per-tick "tick" header
    assert "| tick |" not in result


@pytest.mark.asyncio
async def test_run_simulation_max_rows_decimates(mock_context, mock_nl):
    """max_rows shrinks long output but always keeps the last tick."""
    mock_nl._model_loaded = True
    result = await run_simulation(100, ["count turtles"], mock_context, max_rows=10)
    # Header + separator + ≤ 10 data rows, last row's tick should be 99
    lines = [ln for ln in result.split("\n") if ln.startswith("|")]
    data = [ln for ln in lines if "---" not in ln][1:]
    assert len(data) <= 11  # decimation may add the final row on top of the cap
    # The final row's tick column equals the last index from the mock (range(100))
    assert data[-1].split("|")[1].strip() == "99"


@pytest.mark.asyncio
async def test_run_simulation_negative_max_rows_rejected(mock_context, mock_nl):
    mock_nl._model_loaded = True
    with pytest.raises(Exception, match="max_rows"):
        await run_simulation(10, ["count turtles"], mock_context, max_rows=-5)


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


@pytest.mark.asyncio
async def test_set_parameter_string_with_quotes(mock_context, mock_nl):
    """Embedded quotes should be escaped for NetLogo."""
    mock_nl._model_loaded = True
    result = await set_parameter("label", 'say "hi"', mock_context)
    assert r"\"hi\"" in result


@pytest.mark.asyncio
async def test_set_parameter_string_with_backslash(mock_context, mock_nl):
    """Backslashes should be escaped for NetLogo."""
    mock_nl._model_loaded = True
    result = await set_parameter("path", r"C:\temp", mock_context)
    assert r"C:\\temp" in result


# ── get_world_state ──────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_get_world_state(mock_context, mock_nl):
    mock_nl._model_loaded = True
    result = await get_world_state(mock_context)
    state = json.loads(result)
    assert state["turtle_count"] == 100
    assert state["ticks"] == 0
    assert state["min_pxcor"] == -16


@pytest.mark.asyncio
async def test_get_world_state_pre_setup(mock_context, mock_nl):
    """get_world_state should return ticks=-1 when ticks errors (pre-setup)."""
    mock_nl._model_loaded = True
    original_report = mock_nl.report

    def report_with_ticks_error(reporter):
        if reporter == "ticks":
            raise RuntimeError("Tick counter has not been started yet.")
        return original_report(reporter)

    mock_nl.report = report_with_ticks_error
    result = await get_world_state(mock_context)
    state = json.loads(result)
    assert state["ticks"] == -1
    assert state["turtle_count"] == 100  # other fields still work


# ── get_patch_data ───────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_get_patch_data(mock_context, mock_nl):
    mock_nl._model_loaded = True
    result = await get_patch_data("pcolor", mock_context)
    grid = json.loads(result)
    assert isinstance(grid, list)
    assert grid[0] == [1, 2]


@pytest.mark.asyncio
async def test_get_patch_data_summary_only(mock_context, mock_nl):
    mock_nl._model_loaded = True
    result = await get_patch_data("pcolor", mock_context, summary_only=True)
    payload = json.loads(result)
    # Mock returns 2x2 grid [[1,2],[3,4]]
    assert payload["attribute"] == "pcolor"
    assert payload["rows"] == 2
    assert payload["cols"] == 2
    assert payload["total_cells"] == 4
    assert payload["min"] == 1
    assert payload["max"] == 4
    assert payload["mean"] == 2.5
    assert payload["unique_values"] == 4
    # The full grid must NOT be in the summary response
    assert "values" not in payload


# ── create_model ─────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_create_model_raw_code(mock_context, mock_nl, tmp_path, monkeypatch):
    monkeypatch.setattr("netlogo_mcp.tools.get_models_dir", lambda: tmp_path)
    code = "globals [x]\nto setup\n  clear-all\n  reset-ticks\nend\nto go\n  tick\nend"
    result = await create_model(code, mock_context)
    assert "created" in result.lower()
    assert mock_nl._model_loaded
    created_files = list(tmp_path.glob("_created_*.nlogox"))
    assert len(created_files) == 1
    content = created_files[0].read_text(encoding="utf-8")
    assert 'display="Setup">setup</button>' in content
    assert 'display="Go">go</button>' in content
    assert 'display="Time Steps">ticks</monitor>' in content


@pytest.mark.asyncio
async def test_create_model_full_xml(mock_context, mock_nl, tmp_path, monkeypatch):
    """When full .nlogox XML is provided, it should be preserved as-is."""
    monkeypatch.setattr("netlogo_mcp.tools.get_models_dir", lambda: tmp_path)
    code = '<?xml version="1.0"?><model version="NetLogo 7.0.3"><code>to setup end</code></model>'
    result = await create_model(code, mock_context)
    assert "created" in result.lower()
    created_files = list(tmp_path.glob("_created_*.nlogox"))
    assert len(created_files) == 1
    content = created_files[0].read_text(encoding="utf-8")
    assert content == code  # XML should be preserved, not double-wrapped


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
    assert 'display="Setup">setup</button>' in content
    assert 'display="Go">go</button>' in content
    assert 'display="Time Steps">ticks</monitor>' in content


@pytest.mark.asyncio
async def test_save_model_path_traversal(mock_context):
    with pytest.raises(Exception, match="path separators"):
        await save_model("../../evil", "to setup end", mock_context)


@pytest.mark.asyncio
async def test_save_model_preserves_xml(mock_context, tmp_path, monkeypatch):
    monkeypatch.setattr("netlogo_mcp.tools.get_models_dir", lambda: tmp_path)
    xml = '<?xml version="1.0"?><model version="NetLogo 7.0.3"><code>to setup end</code></model>'
    await save_model("full_xml", xml, mock_context)
    saved = (tmp_path / "full_xml.nlogox").read_text(encoding="utf-8")
    assert saved == xml  # raw XML preserved, no double-wrapping


# ── export_world ─────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_export_world(mock_context, mock_nl):
    mock_nl._model_loaded = True
    result = await export_world(mock_context)
    assert "exported" in result.lower()
    assert ".csv" in result
