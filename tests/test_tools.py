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
    get_agent_sample,
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
@pytest.mark.parametrize("bad_value", [float("nan"), float("inf"), float("-inf")])
async def test_set_parameter_rejects_non_finite_floats(
    mock_context, mock_nl, bad_value
):
    """nan/inf have no NetLogo literal — surface a clear error before
    interpolating them into a `set ...` command."""
    mock_nl._model_loaded = True
    with pytest.raises(Exception, match="finite"):
        await set_parameter("speed", bad_value, mock_context)


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


# ── get_agent_sample ─────────────────────────────────────────────────────────


@pytest.mark.asyncio
@pytest.mark.parametrize("bad_n", [0, -3, 201, 1000])
async def test_get_agent_sample_rejects_bad_n(mock_context, mock_nl, bad_n):
    mock_nl._model_loaded = True
    with pytest.raises(Exception, match="n must"):
        await get_agent_sample(mock_context, n=bad_n)


@pytest.mark.asyncio
@pytest.mark.parametrize("bad_breed", ["bad name", "1bad", "x;y", "../traversal"])
async def test_get_agent_sample_rejects_bad_breed(mock_context, mock_nl, bad_breed):
    mock_nl._model_loaded = True
    with pytest.raises(Exception, match="Invalid breed"):
        await get_agent_sample(mock_context, breed=bad_breed)


@pytest.mark.asyncio
async def test_get_agent_sample_rejects_bad_attribute(mock_context, mock_nl):
    mock_nl._model_loaded = True
    with pytest.raises(Exception, match="Invalid attribute"):
        await get_agent_sample(mock_context, attributes=["xcor", "bad name"])


@pytest.mark.asyncio
async def test_get_agent_sample_empty_attributes_rejected(mock_context, mock_nl):
    mock_nl._model_loaded = True
    with pytest.raises(Exception, match="attributes"):
        await get_agent_sample(mock_context, attributes=[])


@pytest.mark.asyncio
async def test_get_agent_sample_renders_table(mock_context, mock_nl):
    """When the mock returns a [count, rows] shape, the table is rendered."""
    mock_nl._model_loaded = True
    original_report = mock_nl.report

    def report_with_agents(reporter):
        if reporter.startswith("(list (count "):
            # Return shape: [total_count, [[v1,v2,...], ...]]
            return [3, [[0, 1.0, 2.0], [1, 3.0, 4.0], [2, 5.0, 6.0]]]
        return original_report(reporter)

    mock_nl.report = report_with_agents
    result = await get_agent_sample(
        mock_context, breed="turtles", n=10, attributes=["who", "xcor", "ycor"]
    )
    assert "| who | xcor | ycor |" in result
    assert "| 0 | 1.0 | 2.0 |" in result
    assert "Showed all 3" in result


@pytest.mark.asyncio
async def test_get_agent_sample_empty_agentset_returns_note(mock_context, mock_nl):
    mock_nl._model_loaded = True
    original_report = mock_nl.report

    def report_empty(reporter):
        if reporter.startswith("(list (count "):
            return [0, []]
        return original_report(reporter)

    mock_nl.report = report_empty
    result = await get_agent_sample(mock_context, breed="sheep")
    assert "empty" in result.lower()


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
    # code defines no `go` procedure, so no Go button is emitted —
    # a button pointing at a missing procedure breaks model load
    assert 'display="Go">go</button>' not in content
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


# ── lazy JVM startup (_ensure_netlogo) ───────────────────────────────────────


@pytest.mark.asyncio
async def test_ensure_netlogo_boots_once_and_caches(mock_nl):
    """First call boots via the factory; later calls reuse the workspace."""
    import asyncio
    from unittest.mock import MagicMock

    from netlogo_mcp.tools import _ensure_netlogo

    starts = []

    def factory():
        starts.append(1)
        return mock_nl, "NetLogo 7.0.3"

    ctx = MagicMock()
    state = {
        "netlogo": None,
        "netlogo_version": None,
        "start_netlogo": factory,
        "workspace_lock": asyncio.Lock(),
    }
    ctx.request_context.lifespan_context = state

    nl1 = await _ensure_netlogo(ctx)
    nl2 = await _ensure_netlogo(ctx)
    assert nl1 is mock_nl and nl2 is mock_nl
    assert starts == [1]
    assert state["netlogo_version"] == "NetLogo 7.0.3"


@pytest.mark.asyncio
async def test_ensure_netlogo_failure_is_wrapped(mock_nl):
    """A JVM boot failure surfaces as a readable ToolError, not a stack dump."""
    import asyncio
    from unittest.mock import MagicMock

    from fastmcp.exceptions import ToolError

    from netlogo_mcp.tools import _ensure_netlogo

    def factory():
        raise OSError("NETLOGO_HOME points nowhere")

    ctx = MagicMock()
    ctx.request_context.lifespan_context = {
        "netlogo": None,
        "netlogo_version": None,
        "start_netlogo": factory,
        "workspace_lock": asyncio.Lock(),
    }

    with pytest.raises(ToolError, match="NetLogo failed to start"):
        await _ensure_netlogo(ctx)


@pytest.mark.asyncio
async def test_command_before_jvm_boot_reports_no_model():
    """On a lazy server with no JVM yet, model-requiring tools say so clearly."""
    from unittest.mock import MagicMock

    from fastmcp.exceptions import ToolError

    ctx = MagicMock()
    ctx.request_context.lifespan_context = {
        "netlogo": None,
        "start_netlogo": lambda: None,
    }

    with pytest.raises(ToolError, match="No model is loaded"):
        await command("setup", ctx)


# ── widget generation (_wrap_nlogox / widgets param) ─────────────────────────


def test_wrap_nlogox_omits_buttons_for_missing_procedures():
    """A button pointing at a missing procedure breaks model load — only
    emit Setup/Go buttons when the code defines them."""
    from netlogo_mcp.tools import _wrap_nlogox

    xml = _wrap_nlogox("to wander\n  fd 1\nend")
    assert "<button" not in xml
    assert 'display="Time Steps">ticks</monitor>' in xml
    assert "<view " in xml


def test_wrap_nlogox_emits_only_defined_buttons():
    from netlogo_mcp.tools import _wrap_nlogox

    xml = _wrap_nlogox("to go\n  tick\nend")
    assert 'display="Go">go</button>' in xml
    assert 'display="Setup">setup</button>' not in xml


def test_wrap_nlogox_setup_prefix_is_not_setup():
    """`to setup-patches` must not count as defining `setup`."""
    from netlogo_mcp.tools import _wrap_nlogox

    xml = _wrap_nlogox("to setup-patches\n  ask patches [ set pcolor green ]\nend")
    assert "<button" not in xml


def test_wrap_nlogox_with_slider_and_switch():
    from netlogo_mcp.tools import _wrap_nlogox

    xml = _wrap_nlogox(
        "to setup\nend",
        widgets=[
            {
                "type": "slider",
                "variable": "num-sheep",
                "min": 0,
                "max": 250,
                "default": 100,
                "step": 5,
            },
            {"type": "switch", "variable": "trails?", "default": True},
            {"type": "button", "code": "setup", "label": "Setup"},
            {"type": "monitor", "code": "count turtles", "precision": 0},
        ],
    )
    assert 'variable="num-sheep"' in xml
    assert 'min="0.0"' in xml and 'max="250.0"' in xml
    assert 'default="100.0"' in xml and 'step="5.0"' in xml
    assert "<switch" in xml and 'on="true"' in xml and 'variable="trails?"' in xml
    assert 'display="Setup">setup</button>' in xml
    assert 'precision="0"' in xml and ">count turtles</monitor>" in xml
    # explicit widgets replace the auto Setup/Go column
    assert xml.count("<button") == 1


@pytest.mark.parametrize(
    "bad_widget,err_match",
    [
        ({"type": "dial", "variable": "x"}, "type must be one of"),
        ({"type": "slider", "variable": "2bad", "min": 0, "max": 1}, "identifier"),
        ({"type": "slider", "variable": "x", "min": 5, "max": 5}, "min"),
        ({"type": "slider", "variable": "x", "min": 0, "max": "z"}, "number"),
        ({"type": "button", "code": "   "}, "non-empty"),
        ({"type": "monitor", "code": "ticks", "precision": "high"}, "integer"),
    ],
)
def test_widget_spec_validation(bad_widget, err_match):
    from fastmcp.exceptions import ToolError

    from netlogo_mcp.tools import _wrap_nlogox

    with pytest.raises(ToolError, match=err_match):
        _wrap_nlogox("to setup\nend", widgets=[bad_widget])


@pytest.mark.asyncio
async def test_create_model_rejects_widgets_with_full_xml(mock_context):
    from fastmcp.exceptions import ToolError

    xml = '<?xml version="1.0"?><model version="NetLogo 7.0.3"><code>to setup end</code></model>'
    with pytest.raises(ToolError, match="widgets can only be used"):
        await create_model(
            xml, mock_context, widgets=[{"type": "button", "code": "go"}]
        )


@pytest.mark.asyncio
async def test_create_model_with_widgets(mock_context, mock_nl, tmp_path, monkeypatch):
    monkeypatch.setattr("netlogo_mcp.tools.get_models_dir", lambda: tmp_path)
    code = "to setup\n  clear-all\n  reset-ticks\nend"
    result = await create_model(
        code,
        mock_context,
        widgets=[
            {
                "type": "slider",
                "variable": "density",
                "min": 0,
                "max": 100,
                "default": 60,
            },
            {"type": "button", "code": "setup", "label": "Setup"},
        ],
    )
    assert "created" in result.lower()
    created = list(tmp_path.glob("_created_*.nlogox"))
    assert len(created) == 1
    content = created[0].read_text(encoding="utf-8")
    assert 'variable="density"' in content
    assert 'display="Setup">setup</button>' in content


@pytest.mark.asyncio
async def test_save_model_with_widgets(mock_context, tmp_path, monkeypatch):
    monkeypatch.setattr("netlogo_mcp.tools.get_models_dir", lambda: tmp_path)
    await save_model(
        "widgety",
        "to go\n  tick\nend",
        mock_context,
        widgets=[{"type": "switch", "variable": "wrap?", "default": False}],
    )
    content = (tmp_path / "widgety.nlogox").read_text(encoding="utf-8")
    assert 'variable="wrap?"' in content and 'on="false"' in content


# ── update_model ─────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_update_model_requires_loaded_model(mock_context):
    from fastmcp.exceptions import ToolError

    from netlogo_mcp.tools import update_model

    with pytest.raises(ToolError, match="No model is loaded"):
        await update_model("to setup\nend", mock_context)


@pytest.mark.asyncio
async def test_update_model_rewrites_in_place_and_keeps_widgets(
    mock_context, mock_nl, tmp_path, monkeypatch
):
    from netlogo_mcp.tools import update_model

    monkeypatch.setattr("netlogo_mcp.tools.get_models_dir", lambda: tmp_path)
    await create_model(
        "to setup\n  clear-all\nend",
        mock_context,
        widgets=[
            {
                "type": "slider",
                "variable": "density",
                "min": 0,
                "max": 100,
                "default": 60,
            },
            {"type": "button", "code": "setup", "label": "Setup"},
        ],
    )
    assert len(list(tmp_path.glob("*.nlogox"))) == 1

    result = await update_model(
        "to setup\n  clear-all\n  create-turtles density\nend", mock_context
    )
    assert "existing widgets kept" in result
    files = list(tmp_path.glob("*.nlogox"))
    assert len(files) == 1  # same file rewritten, no new _created_* clutter
    content = files[0].read_text(encoding="utf-8")
    assert "create-turtles density" in content  # new code in place
    assert 'variable="density"' in content  # slider survived the update


@pytest.mark.asyncio
async def test_update_model_replaces_widgets_when_given(
    mock_context, mock_nl, tmp_path, monkeypatch
):
    from netlogo_mcp.tools import update_model

    monkeypatch.setattr("netlogo_mcp.tools.get_models_dir", lambda: tmp_path)
    await create_model(
        "to setup\nend",
        mock_context,
        widgets=[{"type": "slider", "variable": "density", "min": 0, "max": 100}],
    )
    await update_model(
        "to setup\nend",
        mock_context,
        widgets=[{"type": "switch", "variable": "trails?", "default": True}],
    )
    content = next(tmp_path.glob("*.nlogox")).read_text(encoding="utf-8")
    assert 'variable="trails?"' in content
    assert 'variable="density"' not in content


@pytest.mark.asyncio
async def test_update_model_rejects_full_xml(
    mock_context, mock_nl, tmp_path, monkeypatch
):
    from fastmcp.exceptions import ToolError

    from netlogo_mcp.tools import update_model

    monkeypatch.setattr("netlogo_mcp.tools.get_models_dir", lambda: tmp_path)
    await create_model("to setup\nend", mock_context)
    with pytest.raises(ToolError, match="raw NetLogo procedures"):
        await update_model('<?xml version="1.0"?><model></model>', mock_context)


@pytest.mark.asyncio
async def test_update_model_rejects_legacy_nlogo(mock_context, mock_nl, tmp_path):
    from fastmcp.exceptions import ToolError

    from netlogo_mcp.tools import update_model

    legacy = tmp_path / "old.nlogo"
    legacy.write_text("to setup end")
    await open_model(str(legacy), mock_context)
    with pytest.raises(ToolError, match="legacy .nlogo"):
        await update_model("to setup\nend", mock_context)


# ── plot widgets ─────────────────────────────────────────────────────────────


def test_wrap_nlogox_with_plot_widget():
    from netlogo_mcp.tools import _wrap_nlogox

    xml = _wrap_nlogox(
        "to setup\nend",
        widgets=[
            {
                "type": "plot",
                "label": "populations",
                "x_axis": "time",
                "y_axis": "count",
                "pens": [
                    {"code": "plot count sheep", "label": "sheep", "color": "green"},
                    {"code": "plot count wolves"},  # default color from cycle
                ],
            }
        ],
    )
    assert 'display="populations"' in xml
    assert 'xAxis="time"' in xml and 'yAxis="count"' in xml
    assert "<update>plot count sheep</update>" in xml
    assert 'autoPlotX="true"' in xml and 'autoPlotY="true"' in xml
    # green palette entry (88,176,49) -> AWT signed int
    assert f'color="{((0xFF << 24) | (88 << 16) | (176 << 8) | 49) - (1 << 32)}"' in xml
    assert xml.count("<pen ") == 2


def test_plot_pen_color_accepts_raw_int():
    from netlogo_mcp.tools import _wrap_nlogox

    xml = _wrap_nlogox(
        "to setup\nend",
        widgets=[{"type": "plot", "pens": [{"code": "plot ticks", "color": -612749}]}],
    )
    assert 'color="-612749"' in xml


@pytest.mark.parametrize(
    "bad_plot,err_match",
    [
        ({"type": "plot", "pens": []}, "non-empty 'pens'"),
        ({"type": "plot", "pens": [{"label": "x"}]}, "needs NetLogo 'code'"),
        (
            {"type": "plot", "pens": [{"code": "plot 1", "color": "chartreuse"}]},
            "unknown color",
        ),
        ({"type": "plot", "pens": [{"code": "plot 1", "mode": 7}]}, "mode must be"),
    ],
)
def test_plot_widget_validation(bad_plot, err_match):
    from fastmcp.exceptions import ToolError

    from netlogo_mcp.tools import _wrap_nlogox

    with pytest.raises(ToolError, match=err_match):
        _wrap_nlogox("to setup\nend", widgets=[bad_plot])
