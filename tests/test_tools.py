"""Tests for NetLogo MCP tools."""

from __future__ import annotations

import json

import pytest

# We test the tool functions directly — they're async, so use pytest-asyncio.
from netlogo_mcp.tools import (
    _workspace_model_path,
    command,
    create_model,
    export_all_plots,
    export_output,
    export_plot,
    export_view,
    export_world,
    get_patch_data,
    get_server_status,
    get_world_state,
    import_world,
    list_models,
    open_library_model,
    open_model,
    report,
    run_simulation,
    save_model,
    search_models_library,
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


@pytest.mark.asyncio
async def test_open_model_rejects_relative_traversal(mock_context, tmp_path, monkeypatch):
    models_dir = tmp_path / "models"
    models_dir.mkdir()
    (tmp_path / "outside.nlogo").write_text("code")
    monkeypatch.setattr("netlogo_mcp.tools.get_models_dir", lambda: models_dir)

    with pytest.raises(Exception, match="Invalid model path"):
        await open_model("../outside.nlogo", mock_context)


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
    assert "| 10 |" in result
    assert mock_nl.commands.count("go") == 10
    assert mock_context.report_progress.await_count == 2


@pytest.mark.asyncio
async def test_run_simulation_multiple_reporters(mock_context, mock_nl):
    mock_nl._model_loaded = True
    result = await run_simulation(3, ["count sheep", "count wolves"], mock_context)
    assert "count sheep" in result
    assert "count wolves" in result
    assert "| 0 |" in result
    assert "| 3 |" in result


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


@pytest.mark.asyncio
async def test_search_models_library_filters_results(tmp_path, monkeypatch):
    library = tmp_path / "models"
    (library / "Sample Models").mkdir(parents=True)
    (library / "Code Examples").mkdir(parents=True)
    (library / "Sample Models" / "Wolf Sheep.nlogo").write_text("code")
    (library / "Code Examples" / "Ants.nlogo").write_text("code")

    monkeypatch.setattr("netlogo_mcp.tools.get_netlogo_home", lambda: str(tmp_path))

    result = await search_models_library("wolf", limit=10)
    data = json.loads(result)
    assert len(data) == 1
    assert data[0]["relative_path"] == "Sample Models/Wolf Sheep.nlogo"


@pytest.mark.asyncio
async def test_search_models_library_limit_validation(tmp_path, monkeypatch):
    monkeypatch.setattr("netlogo_mcp.tools.get_netlogo_home", lambda: str(tmp_path))
    with pytest.raises(Exception, match="limit must be"):
        await search_models_library(limit=0)


@pytest.mark.asyncio
async def test_open_library_model_success(mock_context, mock_nl, tmp_path, monkeypatch):
    library = tmp_path / "models" / "Sample Models"
    library.mkdir(parents=True)
    (library / "Wolf Sheep.nlogo").write_text("code")
    monkeypatch.setattr("netlogo_mcp.tools.get_netlogo_home", lambda: str(tmp_path))

    result = await open_library_model("Sample Models/Wolf Sheep.nlogo", mock_context)
    assert "loaded" in result.lower()
    assert mock_nl._model_loaded


@pytest.mark.asyncio
async def test_open_library_model_rejects_traversal(
    mock_context, mock_nl, tmp_path, monkeypatch
):
    monkeypatch.setattr("netlogo_mcp.tools.get_netlogo_home", lambda: str(tmp_path))
    mock_nl._model_loaded = True

    with pytest.raises(Exception, match="Invalid library model path"):
        await open_library_model("../bad.nlogo", mock_context)


@pytest.mark.asyncio
async def test_get_server_status(mock_context, mock_nl, tmp_path, monkeypatch):
    netlogo_home = tmp_path / "NetLogo"
    (netlogo_home / "models").mkdir(parents=True)
    models_dir = tmp_path / "session-models"
    exports_dir = tmp_path / "session-exports"
    cache_dir = tmp_path / "session-cache"
    mock_nl.load_model(str(models_dir / "loaded.nlogox"))

    monkeypatch.setattr("netlogo_mcp.tools.get_netlogo_home", lambda: str(netlogo_home))
    monkeypatch.setattr("netlogo_mcp.tools.get_models_dir", lambda: models_dir)
    monkeypatch.setattr("netlogo_mcp.tools.get_exports_dir", lambda: exports_dir)
    monkeypatch.setattr("netlogo_mcp.tools.get_comses_cache_dir", lambda: cache_dir)
    monkeypatch.setattr("netlogo_mcp.tools.get_jvm_path", lambda: "C:/Java/jvm.dll")
    monkeypatch.setattr("netlogo_mcp.tools.get_gui_mode", lambda: True)

    status = json.loads(await get_server_status(mock_context))
    assert status["model_loaded"] is True
    assert status["gui_mode"] is True
    assert status["models_library_exists"] is True
    assert status["model_path"].endswith("loaded.nlogox")


def test_workspace_model_path_reads_java_workspace_model_path():
    class FakeWorkspace:
        def getModelPath(self):
            return "C:/models/wolf.nlogox"

    class FakeField:
        def setAccessible(self, _value):
            return None

        def get(self, _link):
            return FakeWorkspace()

    class FakeClass:
        def getDeclaredField(self, name):
            assert name == "workspace"
            return FakeField()

    class FakeLink:
        def getClass(self):
            return FakeClass()

    fake_nl = type("FakeNL", (), {"link": FakeLink()})()
    assert _workspace_model_path(fake_nl) == "C:/models/wolf.nlogox"


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


@pytest.mark.asyncio
async def test_import_world_absolute_path(mock_context, mock_nl, tmp_path):
    mock_nl._model_loaded = True
    world_file = tmp_path / "state.csv"
    world_file.write_text("dummy")

    result = await import_world(str(world_file), mock_context)
    assert "imported" in result.lower()
    assert "state.csv" in result


@pytest.mark.asyncio
async def test_import_world_relative_to_exports_dir(
    mock_context, mock_nl, tmp_path, monkeypatch
):
    mock_nl._model_loaded = True
    monkeypatch.setattr("netlogo_mcp.tools.get_exports_dir", lambda: tmp_path)
    worlds_dir = tmp_path / "worlds"
    worlds_dir.mkdir(parents=True, exist_ok=True)
    (worlds_dir / "saved.csv").write_text("dummy")

    result = await import_world("saved.csv", mock_context)
    assert "saved.csv" in result


@pytest.mark.asyncio
async def test_import_world_rejects_relative_traversal(
    mock_context, mock_nl, tmp_path, monkeypatch
):
    mock_nl._model_loaded = True
    monkeypatch.setattr("netlogo_mcp.tools.get_exports_dir", lambda: tmp_path)
    (tmp_path / "escape.csv").write_text("dummy")

    with pytest.raises(Exception, match="Invalid world path"):
        await import_world("../escape.csv", mock_context)


@pytest.mark.asyncio
async def test_import_world_not_found(mock_context, mock_nl):
    mock_nl._model_loaded = True
    with pytest.raises(Exception, match="not found"):
        await import_world("missing.csv", mock_context)


@pytest.mark.asyncio
async def test_import_world_requires_csv(mock_context, mock_nl, tmp_path):
    mock_nl._model_loaded = True
    world_file = tmp_path / "state.txt"
    world_file.write_text("dummy")

    with pytest.raises(Exception, match=r"\.csv"):
        await import_world(str(world_file), mock_context)


@pytest.mark.asyncio
async def test_export_plot(mock_context, mock_nl):
    mock_nl._model_loaded = True
    result = await export_plot("Population", mock_context)
    assert "Population" in result
    assert ".csv" in result


@pytest.mark.asyncio
async def test_export_plot_rejects_empty_name(mock_context, mock_nl):
    mock_nl._model_loaded = True
    with pytest.raises(Exception, match="cannot be empty"):
        await export_plot("", mock_context)


@pytest.mark.asyncio
async def test_export_all_plots(mock_context, mock_nl):
    mock_nl._model_loaded = True
    result = await export_all_plots(mock_context)
    assert "all plots" in result.lower()
    assert ".csv" in result


@pytest.mark.asyncio
async def test_export_output(mock_context, mock_nl):
    mock_nl._model_loaded = True
    result = await export_output(mock_context)
    assert "output exported" in result.lower()
    assert ".txt" in result
