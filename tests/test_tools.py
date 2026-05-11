"""Tests for NetLogo MCP tools."""

from __future__ import annotations

import json

import pytest

# We test the tool functions directly — they're async, so use pytest-asyncio.
from netlogo_mcp.tools import (
    close_model,
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
    server_info,
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


@pytest.mark.asyncio
@pytest.mark.parametrize("bad_reporter", ["", "  ", None, 5])
async def test_run_simulation_rejects_blank_or_non_string_reporters(
    mock_context, mock_nl, bad_reporter
):
    """Each reporter must be a non-empty string — guard against empties
    sneaking through and producing confusing NetLogo errors."""
    mock_nl._model_loaded = True
    with pytest.raises(Exception, match="reporters"):
        await run_simulation(10, ["count turtles", bad_reporter], mock_context)


# ── get_patch_data validation ────────────────────────────────────────────────


@pytest.mark.asyncio
@pytest.mark.parametrize("bad_attr", ["", "   "])
async def test_get_patch_data_rejects_blank_attribute(mock_context, mock_nl, bad_attr):
    mock_nl._model_loaded = True
    with pytest.raises(Exception, match="attribute"):
        await get_patch_data(bad_attr, mock_context)


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


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "bad_name",
    [
        "",  # empty
        "1bad-start",  # leading digit
        "name with space",
        "name;setup",  # ; — would let "set name; setup" inject the second cmd
        "$bad",
        "name\nsetup",  # newline injection
        "name\tsetup",
        "../traversal",
        "name) (",
    ],
)
async def test_set_parameter_rejects_invalid_name(mock_context, mock_nl, bad_name):
    """Variable names must be valid NetLogo identifiers — defense in depth
    against command injection via the `set <name> <value>` interpolation."""
    mock_nl._model_loaded = True
    with pytest.raises(Exception, match="Invalid parameter name"):
        await set_parameter(bad_name, 1, mock_context)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "good_name",
    [
        "speed",
        "initial-number-sheep",
        "show-energy?",
        "use_legacy",
        "x.y",
        "go!",
    ],
)
async def test_set_parameter_accepts_netlogo_identifiers(
    mock_context, mock_nl, good_name
):
    """Real NetLogo names — kebab-case, with `?` / `!` / `.` — must be
    accepted."""
    mock_nl._model_loaded = True
    result = await set_parameter(good_name, 1, mock_context)
    assert good_name in result


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


# ── close_model ──────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_close_model_clears_workspace(mock_context, mock_nl, tmp_path):
    """close_model issues clear-all and forgets the current model path."""
    mock_nl._model_loaded = True
    model_file = tmp_path / "test.nlogo"
    model_file.write_text("to setup end")
    await open_model(str(model_file), mock_context)
    assert (
        mock_context.request_context.lifespan_context["current_model_path"] is not None
    )

    result = await close_model(mock_context)
    assert "closed" in result.lower()
    assert mock_context.request_context.lifespan_context["current_model_path"] is None


@pytest.mark.asyncio
async def test_close_model_when_no_model_loaded(mock_context, mock_nl):
    """close_model errors cleanly when nothing is loaded."""
    mock_nl._model_loaded = True  # NetLogo workspace alive, but no model path tracked
    mock_context.request_context.lifespan_context.pop("current_model_path", None)
    with pytest.raises(Exception, match="No model"):
        await close_model(mock_context)


# ── server_info ──────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_server_info_basic_shape(mock_context, monkeypatch, tmp_path):
    """server_info returns config snapshot, even when NETLOGO_HOME is unset."""
    monkeypatch.delenv("NETLOGO_HOME", raising=False)
    monkeypatch.setenv("NETLOGO_MODELS_DIR", str(tmp_path / "models"))
    monkeypatch.setenv("NETLOGO_EXPORTS_DIR", str(tmp_path / "exports"))
    result = await server_info(mock_context)
    info = json.loads(result)
    assert "server_version" in info
    assert "gui_mode" in info
    assert "models_dir" in info
    assert "exports_dir" in info
    # NETLOGO_HOME unset → reported as null with an error message.
    assert info["netlogo_home"] is None
    assert "netlogo_home_error" in info
    assert info["headless_launcher"] is None


@pytest.mark.asyncio
async def test_server_info_includes_current_model(mock_context, mock_nl, tmp_path):
    """server_info echoes the path of whatever model is currently loaded."""
    mock_nl._model_loaded = True
    model_file = tmp_path / "test.nlogo"
    model_file.write_text("to setup end")
    await open_model(str(model_file), mock_context)
    result = await server_info(mock_context)
    info = json.loads(result)
    assert info["current_model_path"] is not None
    assert info["current_model_path"].endswith("test.nlogo")
