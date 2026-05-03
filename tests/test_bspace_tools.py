"""Tests for the BehaviorSpace MCP tools (list / preview / run).

These exercise the tool wrappers without spawning Java. The runner
subprocess is monkey-patched to simulate a successful run that drops a
synthesized BehaviorSpace table CSV at the configured output path.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from netlogo_mcp import bspace, tools

_NLOGOX_FIXTURE = """<?xml version="1.0" encoding="utf-8"?>
<model version="NetLogo 7.0.3">
  <code>; pretend code</code>
  <experiments>
    <experiment name="Saved Sweep" repetitions="2" sequentialRunOrder="true" runMetricsEveryStep="false" timeLimit="100">
      <setup>setup</setup>
      <go>go</go>
      <metrics>
        <metric>count turtles</metric>
      </metrics>
      <constants>
        <enumeratedValueSet variable="density">
          <value value="50"/>
          <value value="75"/>
        </enumeratedValueSet>
      </constants>
    </experiment>
  </experiments>
</model>
"""


@pytest.fixture
def loaded_model_path(tmp_path: Path, mock_context) -> Path:
    """Write a fixture .nlogox to disk and register it as the current model."""
    p = tmp_path / "fixture.nlogox"
    p.write_text(_NLOGOX_FIXTURE, encoding="utf-8")
    mock_context.request_context.lifespan_context["current_model_path"] = str(p)
    return p


def _write_fake_table(path: Path) -> None:
    """Write a 4-row BehaviorSpace --table CSV (2 runs × 2 ticks)."""
    rows = [
        '"BehaviorSpace results (NetLogo 7.0.3)"',
        '"fixture.nlogox"',
        '"Saved Sweep"',
        '"01/15/2026 12:34:56:789 -0500"',
        '"min-pxcor","max-pxcor","min-pycor","max-pycor"',
        '"0","11","0","11"',
        '"[run number]","[step]","density","count turtles"',
        '"1","100","50","42"',
        '"1","200","50","51"',
        '"2","100","75","60"',
        '"2","200","75","58"',
    ]
    path.write_text("\n".join(rows) + "\n", encoding="utf-8")


# ── list_experiments ─────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_list_experiments_returns_saved_specs(mock_context, loaded_model_path):
    result_str = await tools.list_experiments(mock_context)
    payload = json.loads(result_str)
    assert payload["model_path"].endswith("fixture.nlogox")
    assert len(payload["experiments"]) == 1
    spec = payload["experiments"][0]
    assert spec["name"] == "Saved Sweep"
    assert spec["repetitions"] == 2
    assert spec["total_runs"] == 4  # 2 reps × 2 density values
    assert any(v["name"] == "density" for v in spec["variables"])


@pytest.mark.asyncio
async def test_list_experiments_explicit_path_overrides_current(
    mock_context, loaded_model_path, tmp_path
):
    other = tmp_path / "no-experiments.nlogox"
    other.write_text("<?xml version='1.0'?><model></model>", encoding="utf-8")
    result_str = await tools.list_experiments(mock_context, model_path=str(other))
    payload = json.loads(result_str)
    assert payload["experiments"] == []


@pytest.mark.asyncio
async def test_list_experiments_errors_when_no_model(mock_context, tmp_path):
    # Default lifespan has no current_model_path.
    with pytest.raises(Exception, match="No model is loaded"):
        await tools.list_experiments(mock_context)


# ── preview_experiment ───────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_preview_experiment_by_name(mock_context, loaded_model_path):
    result_str = await tools.preview_experiment(
        mock_context, experiment_name="Saved Sweep"
    )
    payload = json.loads(result_str)
    assert payload["spec"]["name"] == "Saved Sweep"
    assert payload["total_runs"] == 4
    assert "estimated_seconds_lower_bound" in payload


@pytest.mark.asyncio
async def test_preview_experiment_inline_variables(mock_context, loaded_model_path):
    result_str = await tools.preview_experiment(
        mock_context,
        metrics=["count turtles"],
        variables=[
            {"name": "density", "values": [10, 20, 30]},
            {"name": "rate", "first": 0.1, "step": 0.1, "last": 0.4},
        ],
        repetitions=2,
        time_limit=100,
    )
    payload = json.loads(result_str)
    # 3 × 4 × 2 = 24
    assert payload["total_runs"] == 24


@pytest.mark.asyncio
async def test_preview_experiment_unknown_name_lists_available(
    mock_context, loaded_model_path
):
    with pytest.raises(Exception, match="not found"):
        await tools.preview_experiment(mock_context, experiment_name="Doesn't exist")


@pytest.mark.asyncio
async def test_preview_experiment_inline_requires_metrics(
    mock_context, loaded_model_path
):
    with pytest.raises(Exception, match="metrics is required"):
        await tools.preview_experiment(mock_context, repetitions=1)


# ── run_experiment ───────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_run_experiment_happy_path(mock_context, loaded_model_path, monkeypatch):
    captured: dict = {}

    def fake_locate(home: str) -> Path:
        return Path(home) / "NetLogo_Console.exe"

    def fake_run_headless(**kwargs):
        captured.update(kwargs)
        # Pretend the launcher wrote the table CSV.
        _write_fake_table(kwargs["table_csv"])
        return bspace.RunOutcome(
            success=True,
            return_code=0,
            duration_seconds=1.5,
            table_csv_path=kwargs["table_csv"],
            rows_returned=4,
            timed_out=False,
            stderr_tail="",
            command=["NetLogo_Console.exe", "--headless"],
        )

    monkeypatch.setattr(bspace, "locate_headless_launcher", fake_locate)
    monkeypatch.setattr(bspace, "run_headless", fake_run_headless)
    monkeypatch.setenv("NETLOGO_HOME", str(loaded_model_path.parent))
    # locate_headless_launcher in tools.py is called via bspace, but tools.py
    # also calls `get_netlogo_home()` which needs a valid dir on disk.
    monkeypatch.setattr(
        tools, "get_netlogo_home", lambda: str(loaded_model_path.parent)
    )

    result_str = await tools.run_experiment(mock_context, experiment_name="Saved Sweep")
    payload = json.loads(result_str)
    assert payload["status"] == "ok"
    assert payload["runs"] == 2
    assert payload["total_rows"] == 4
    assert "metrics_summary" in payload
    assert any(c["parameters"].get("density") == 50 for c in payload["per_combination"])
    # Confirm the launcher would have been called with the right args.
    assert captured["experiment_name"] == "Saved Sweep"
    assert captured["model_path"] == loaded_model_path
    assert captured["table_csv"].suffix == ".csv"


@pytest.mark.asyncio
async def test_run_experiment_refuses_when_total_runs_exceeds_cap(
    mock_context, loaded_model_path, monkeypatch
):
    monkeypatch.setattr(
        tools, "get_netlogo_home", lambda: str(loaded_model_path.parent)
    )
    with pytest.raises(Exception, match="exceeds max_total_runs"):
        await tools.run_experiment(
            mock_context,
            metrics=["count turtles"],
            variables=[{"name": "density", "first": 0, "step": 1, "last": 100}],
            repetitions=10,
            time_limit=100,
            max_total_runs=50,
        )


@pytest.mark.asyncio
async def test_run_experiment_reports_failure_when_outcome_failed(
    mock_context, loaded_model_path, monkeypatch
):
    def fake_locate(home: str) -> Path:
        return Path(home) / "NetLogo_Console.exe"

    def fake_run_headless(**kwargs):
        return bspace.RunOutcome(
            success=False,
            return_code=2,
            duration_seconds=0.1,
            table_csv_path=kwargs["table_csv"],
            rows_returned=0,
            timed_out=False,
            stderr_tail="java.lang.RuntimeException: setup failed",
            command=["fake"],
        )

    monkeypatch.setattr(bspace, "locate_headless_launcher", fake_locate)
    monkeypatch.setattr(bspace, "run_headless", fake_run_headless)
    monkeypatch.setattr(
        tools, "get_netlogo_home", lambda: str(loaded_model_path.parent)
    )

    result_str = await tools.run_experiment(mock_context, experiment_name="Saved Sweep")
    payload = json.loads(result_str)
    assert payload["status"] == "failed"
    assert "stderr_tail" in payload
    assert "RuntimeException" in payload["stderr_tail"]


@pytest.mark.asyncio
async def test_run_experiment_reports_timeout(
    mock_context, loaded_model_path, monkeypatch
):
    def fake_locate(home: str) -> Path:
        return Path(home) / "NetLogo_Console.exe"

    def fake_run_headless(**kwargs):
        return bspace.RunOutcome(
            success=False,
            return_code=-1,
            duration_seconds=600.0,
            table_csv_path=kwargs["table_csv"],
            rows_returned=2,
            timed_out=True,
            stderr_tail="",
            command=["fake"],
        )

    monkeypatch.setattr(bspace, "locate_headless_launcher", fake_locate)
    monkeypatch.setattr(bspace, "run_headless", fake_run_headless)
    monkeypatch.setattr(
        tools, "get_netlogo_home", lambda: str(loaded_model_path.parent)
    )

    result_str = await tools.run_experiment(
        mock_context, experiment_name="Saved Sweep", timeout_seconds=1
    )
    payload = json.loads(result_str)
    assert payload["status"] == "timed_out"
    assert payload["timed_out"] is True


@pytest.mark.asyncio
async def test_run_experiment_unknown_named_experiment(
    mock_context, loaded_model_path, monkeypatch
):
    monkeypatch.setattr(
        tools, "get_netlogo_home", lambda: str(loaded_model_path.parent)
    )
    with pytest.raises(Exception, match="not found"):
        await tools.run_experiment(mock_context, experiment_name="ghost")


@pytest.mark.asyncio
async def test_run_experiment_explicit_model_path_overrides_current(
    tmp_path, mock_context, loaded_model_path, monkeypatch
):
    other = tmp_path / "alt.nlogox"
    other.write_text(_NLOGOX_FIXTURE, encoding="utf-8")

    captured: dict = {}

    def fake_locate(home: str) -> Path:
        return Path(home) / "NetLogo_Console.exe"

    def fake_run_headless(**kwargs):
        captured.update(kwargs)
        _write_fake_table(kwargs["table_csv"])
        return bspace.RunOutcome(
            success=True,
            return_code=0,
            duration_seconds=0.1,
            table_csv_path=kwargs["table_csv"],
            rows_returned=4,
            timed_out=False,
            stderr_tail="",
            command=["fake"],
        )

    monkeypatch.setattr(bspace, "locate_headless_launcher", fake_locate)
    monkeypatch.setattr(bspace, "run_headless", fake_run_headless)
    monkeypatch.setattr(
        tools, "get_netlogo_home", lambda: str(loaded_model_path.parent)
    )

    await tools.run_experiment(
        mock_context, experiment_name="Saved Sweep", model_path=str(other)
    )
    assert captured["model_path"].name == "alt.nlogox"


# ── current_model_path tracking ──────────────────────────────────────────────


@pytest.mark.asyncio
async def test_open_model_records_current_path(mock_context, tmp_path):
    p = tmp_path / "trackme.nlogo"
    p.write_text("to setup end")
    await tools.open_model(str(p), mock_context)
    recorded = mock_context.request_context.lifespan_context.get("current_model_path")
    assert recorded is not None
    assert Path(recorded).name == "trackme.nlogo"


@pytest.mark.asyncio
async def test_create_model_records_current_path(mock_context, tmp_path, monkeypatch):
    monkeypatch.setattr(tools, "get_models_dir", lambda: tmp_path)
    await tools.create_model("to setup end", mock_context)
    recorded = mock_context.request_context.lifespan_context.get("current_model_path")
    assert recorded is not None
    assert recorded.endswith(".nlogox")
