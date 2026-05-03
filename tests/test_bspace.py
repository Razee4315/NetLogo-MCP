"""Unit tests for src/netlogo_mcp/bspace.py.

Covers everything that does NOT require a live JVM or NetLogo install:
- ExperimentVariable expansion (enumerated and stepped)
- ExperimentSpec round-trip via XML build → string parse
- count_runs combinatorics
- BehaviorSpace setup-file XML build (DOCTYPE + structure)
- parse_experiments on a fixture .nlogox blob
- parse_table_csv / read_table_metadata on a synthesized BehaviorSpace
  table CSV
- summarize_results aggregation
- locate_headless_launcher discovery on Windows / POSIX layouts
- run_headless: subprocess error path (timeout, missing launcher)
- safe_output_name sanitization
"""

from __future__ import annotations

from pathlib import Path  # noqa: TC003 — runtime use in fixtures

import pytest

from netlogo_mcp import bspace

# ── Variables ─────────────────────────────────────────────────────────────────


def test_enumerated_expanded_values_returns_list_copy():
    v = bspace.ExperimentVariable(
        name="density", kind="enumerated", values=[10, 20, 30]
    )
    assert v.expanded_values() == [10, 20, 30]
    # Returned list is independent of internal state.
    out = v.expanded_values()
    out.append(99)
    assert v.expanded_values() == [10, 20, 30]


def test_stepped_expanded_values_inclusive_integers():
    v = bspace.ExperimentVariable(name="n", kind="stepped", first=1, step=1, last=5)
    assert v.expanded_values() == [1, 2, 3, 4, 5]


def test_stepped_expanded_values_inclusive_floats():
    v = bspace.ExperimentVariable(
        name="rate", kind="stepped", first=0.1, step=0.05, last=0.3
    )
    out = v.expanded_values()
    # Should be [0.1, 0.15, 0.2, 0.25, 0.3] — verify count, endpoints, monotone.
    assert len(out) == 5
    assert out[0] == pytest.approx(0.1)
    assert out[-1] == pytest.approx(0.3)
    diffs = [out[i + 1] - out[i] for i in range(len(out) - 1)]
    for d in diffs:
        assert d == pytest.approx(0.05)


def test_stepped_keeps_ints_when_endpoints_integral():
    v = bspace.ExperimentVariable(name="X", kind="stepped", first=10, step=5, last=25)
    out = v.expanded_values()
    assert out == [10, 15, 20, 25]
    assert all(isinstance(x, int) for x in out)


def test_stepped_rejects_zero_step():
    v = bspace.ExperimentVariable(name="X", kind="stepped", first=0, step=0, last=10)
    with pytest.raises(bspace.BSpaceError, match="step > 0"):
        v.expanded_values()


def test_stepped_requires_all_three_endpoints():
    v = bspace.ExperimentVariable(name="X", kind="stepped", first=0, step=1, last=None)
    with pytest.raises(bspace.BSpaceError, match="first/step/last"):
        v.expanded_values()


def test_unknown_variable_kind_raises():
    v = bspace.ExperimentVariable(name="X", kind="bogus")
    with pytest.raises(bspace.BSpaceError):
        v.expanded_values()


def test_variable_from_dict_enumerated():
    v = bspace.variable_from_dict({"name": "d", "values": [1, 2]})
    assert v.kind == "enumerated"
    assert v.values == [1, 2]


def test_variable_from_dict_stepped():
    v = bspace.variable_from_dict({"name": "g", "first": 0.1, "step": 0.1, "last": 0.4})
    assert v.kind == "stepped"
    assert v.first == 0.1 and v.step == 0.1 and v.last == 0.4


def test_variable_from_dict_rejects_missing_name():
    with pytest.raises(bspace.BSpaceError):
        bspace.variable_from_dict({"values": [1, 2]})


def test_variable_from_dict_rejects_no_shape():
    with pytest.raises(bspace.BSpaceError):
        bspace.variable_from_dict({"name": "x"})


def test_variable_from_dict_rejects_empty_values():
    with pytest.raises(bspace.BSpaceError):
        bspace.variable_from_dict({"name": "x", "values": []})


# ── Run counting ──────────────────────────────────────────────────────────────


def test_count_runs_no_variables_uses_repetitions():
    spec = bspace.ExperimentSpec(name="x", repetitions=7, metrics=["count turtles"])
    assert bspace.count_runs(spec) == 7


def test_count_runs_combinatorial():
    spec = bspace.ExperimentSpec(
        name="x",
        repetitions=2,
        metrics=["m"],
        variables=[
            bspace.ExperimentVariable(name="a", kind="enumerated", values=[1, 2, 3]),
            bspace.ExperimentVariable(
                name="b", kind="stepped", first=0.0, step=0.5, last=1.5
            ),
        ],
    )
    # |a| = 3, |b| = 4, reps = 2  → 24 total runs
    assert bspace.count_runs(spec) == 24


# ── XML build (setup file) ────────────────────────────────────────────────────


def test_build_setup_file_xml_includes_doctype_and_required_fields():
    spec = bspace.ExperimentSpec(
        name="my-exp",
        repetitions=5,
        time_limit=2000,
        setup_commands="setup",
        go_commands="go",
        metrics=["count turtles"],
        variables=[
            bspace.ExperimentVariable(
                name="density", kind="enumerated", values=[10, 20]
            ),
            bspace.ExperimentVariable(
                name="rate", kind="stepped", first=0.1, step=0.1, last=0.3
            ),
        ],
        run_metrics_every_step=False,
    )
    xml = bspace.build_setup_file_xml(spec)
    assert xml.startswith("<?xml")
    assert "behaviorspace.dtd" in xml
    assert '<experiment name="my-exp"' in xml
    assert 'repetitions="5"' in xml
    assert 'timeLimit="2000"' in xml
    assert 'runMetricsEveryStep="false"' in xml
    assert "<setup>setup</setup>" in xml
    assert "<go>go</go>" in xml
    assert "<metric>count turtles</metric>" in xml
    assert "<enumeratedValueSet" in xml and 'variable="density"' in xml
    assert "<steppedValueSet" in xml and 'variable="rate"' in xml


def test_build_setup_file_xml_escapes_special_chars():
    spec = bspace.ExperimentSpec(
        name="exp&name",
        metrics=['count turtles with [color = "red"]'],
        repetitions=1,
        time_limit=0,
    )
    xml = bspace.build_setup_file_xml(spec)
    assert 'name="exp&amp;name"' in xml
    # The metric body contains double quotes; we wrap in single-quoted attr
    # only for value attributes, but the metric tag content is just escaped.
    assert "&quot;red&quot;" in xml or '"red"' in xml  # tolerant to either


def test_build_setup_file_xml_omits_optional_blocks_when_unset():
    spec = bspace.ExperimentSpec(name="x", metrics=["m"], repetitions=1, time_limit=0)
    xml = bspace.build_setup_file_xml(spec)
    assert "<preExperiment>" not in xml
    assert "<postExperiment>" not in xml
    assert "<exitCondition>" not in xml
    # No variables -> no <constants> wrapper
    assert "<constants>" not in xml


# ── Parse <experiments> from a real .nlogox blob ──────────────────────────────


_NLOGOX_FIXTURE = """<?xml version="1.0" encoding="utf-8"?>
<model version="NetLogo 7.0.3">
  <code>; pretend code</code>
  <widgets/>
  <info><![CDATA[Test model]]></info>
  <experiments>
    <experiment name="Sweep1" repetitions="3" sequentialRunOrder="true" runMetricsEveryStep="false" timeLimit="1500">
      <setup>setup</setup>
      <go>go</go>
      <metrics>
        <metric>count turtles</metric>
        <metric>mean [energy] of turtles</metric>
      </metrics>
      <constants>
        <enumeratedValueSet variable="initial-pop">
          <value value="50"/>
          <value value="100"/>
        </enumeratedValueSet>
        <steppedValueSet variable="growth" first="0.1" step="0.1" last="0.5"/>
      </constants>
    </experiment>
    <experiment name="QuickCheck" repetitions="1" runMetricsEveryStep="true" timeLimit="100">
      <setup>setup</setup>
      <go>go</go>
      <metrics>
        <metric>count turtles</metric>
      </metrics>
    </experiment>
  </experiments>
</model>
"""


def test_parse_experiments_extracts_two_experiments(tmp_path: Path):
    p = tmp_path / "test.nlogox"
    p.write_text(_NLOGOX_FIXTURE, encoding="utf-8")
    specs = bspace.parse_experiments(p)
    assert len(specs) == 2

    sweep = specs[0]
    assert sweep.name == "Sweep1"
    assert sweep.repetitions == 3
    assert sweep.time_limit == 1500
    assert sweep.run_metrics_every_step is False
    assert sweep.metrics == ["count turtles", "mean [energy] of turtles"]
    assert len(sweep.variables) == 2
    enum_var = next(v for v in sweep.variables if v.kind == "enumerated")
    assert enum_var.name == "initial-pop"
    assert enum_var.values == [50, 100]
    step_var = next(v for v in sweep.variables if v.kind == "stepped")
    assert step_var.name == "growth"
    assert step_var.first == pytest.approx(0.1)
    assert step_var.last == pytest.approx(0.5)

    quick = specs[1]
    assert quick.name == "QuickCheck"
    assert quick.repetitions == 1
    assert quick.variables == []


def test_parse_experiments_returns_empty_when_no_section(tmp_path: Path):
    p = tmp_path / "no-bspace.nlogox"
    p.write_text(
        "<?xml version='1.0'?><model><code>; nope</code></model>", encoding="utf-8"
    )
    assert bspace.parse_experiments(p) == []


def test_parse_experiments_raises_on_missing_file(tmp_path: Path):
    with pytest.raises(bspace.BSpaceError, match="model not found"):
        bspace.parse_experiments(tmp_path / "missing.nlogox")


def test_parse_experiments_handles_legacy_timeLimit_element(tmp_path: Path):
    legacy = """<?xml version="1.0"?>
<model>
  <experiments>
    <experiment name="legacy" repetitions="2" runMetricsEveryStep="true">
      <setup>setup</setup>
      <go>go</go>
      <timeLimit steps="500"/>
      <metric>count turtles</metric>
    </experiment>
  </experiments>
</model>
"""
    p = tmp_path / "legacy.nlogo"
    p.write_text(legacy, encoding="utf-8")
    specs = bspace.parse_experiments(p)
    assert len(specs) == 1
    assert specs[0].time_limit == 500
    assert specs[0].metrics == ["count turtles"]


# ── Round-trip: spec → XML → parse ───────────────────────────────────────────


def test_spec_xml_round_trip_preserves_essentials(tmp_path: Path):
    spec = bspace.ExperimentSpec(
        name="round-trip",
        repetitions=4,
        time_limit=750,
        setup_commands="setup",
        go_commands="go",
        metrics=["count turtles", "ticks"],
        variables=[
            bspace.ExperimentVariable(name="A", kind="enumerated", values=[1, 2, 3]),
            bspace.ExperimentVariable(
                name="B", kind="stepped", first=0.0, step=0.25, last=1.0
            ),
        ],
        run_metrics_every_step=False,
    )
    xml = bspace.build_setup_file_xml(spec)
    # Strip DOCTYPE so ElementTree (used inside parse_experiments) can read it
    # — parse_experiments only needs the <experiments> ... </experiments> block.
    no_doctype = "\n".join(
        ln for ln in xml.splitlines() if not ln.startswith("<!DOCTYPE")
    )
    p = tmp_path / "round.nlogox"
    p.write_text(no_doctype, encoding="utf-8")
    parsed = bspace.parse_experiments(p)
    assert len(parsed) == 1
    parsed_spec = parsed[0]
    assert parsed_spec.name == spec.name
    assert parsed_spec.repetitions == spec.repetitions
    assert parsed_spec.time_limit == spec.time_limit
    assert parsed_spec.metrics == spec.metrics
    assert len(parsed_spec.variables) == 2


# ── Table CSV parsing ────────────────────────────────────────────────────────


def _write_fake_table_csv(path: Path, *, model_name: str = "test.nlogox") -> None:
    """Write a CSV mimicking BehaviorSpace's --table format (6 metadata rows
    + header + data).
    """
    header_metadata = [
        '"BehaviorSpace results (NetLogo 7.0.3)"',
        f'"{model_name}"',
        '"my-exp"',
        '"01/15/2026 12:34:56:789 -0500"',
        '"min-pxcor","max-pxcor","min-pycor","max-pycor"',
        '"0","11","0","11"',
        '"[run number]","[step]","density","count turtles"',
        '"1","100","50","42"',
        '"1","200","50","51"',
        '"2","100","75","60"',
        '"2","200","75","58"',
    ]
    path.write_text("\n".join(header_metadata) + "\n", encoding="utf-8")


def test_parse_table_csv_skips_metadata_and_renames_bracket_columns(tmp_path):
    p = tmp_path / "table.csv"
    _write_fake_table_csv(p)
    df = bspace.parse_table_csv(p)
    assert "run_number" in df.columns
    assert "step" in df.columns
    assert "density" in df.columns
    assert "count turtles" in df.columns
    assert len(df) == 4


def test_read_table_metadata_extracts_banner_fields(tmp_path):
    p = tmp_path / "table.csv"
    _write_fake_table_csv(p, model_name="cool.nlogox")
    md = bspace.read_table_metadata(p)
    assert "header" in md
    assert "model" in md and md["model"].endswith("cool.nlogox")
    assert "experiment" in md
    assert md.get("world", {}).get("max-pxcor") == "11"


def test_summarize_results_groups_by_parameters(tmp_path):
    p = tmp_path / "table.csv"
    _write_fake_table_csv(p)
    df = bspace.parse_table_csv(p)
    spec = bspace.ExperimentSpec(
        name="my-exp",
        metrics=["count turtles"],
        variables=[
            bspace.ExperimentVariable(
                name="density", kind="enumerated", values=[50, 75]
            )
        ],
    )
    summary = bspace.summarize_results(df, spec)
    assert summary["runs"] == 2
    assert summary["total_rows"] == 4
    assert "count turtles" in summary["metrics_summary"]
    # per_combination should have one entry for density=50, one for 75
    assert len(summary["per_combination"]) == 2
    combos = sorted(c["parameters"]["density"] for c in summary["per_combination"])
    assert combos == [50, 75]


def test_summarize_empty_returns_zeros():
    import pandas as pd

    df = pd.DataFrame()
    spec = bspace.ExperimentSpec(name="empty", metrics=["m"])
    out = bspace.summarize_results(df, spec)
    assert out["runs"] == 0
    assert out["total_rows"] == 0


# ── Launcher discovery ───────────────────────────────────────────────────────


def test_locate_headless_launcher_finds_console_when_present(tmp_path, monkeypatch):
    home = tmp_path / "NL"
    home.mkdir()
    # Simulate Windows install
    monkeypatch.setattr(bspace.platform, "system", lambda: "Windows")
    (home / "NetLogo_Console.exe").write_text("dummy")
    out = bspace.locate_headless_launcher(str(home))
    assert out.name == "NetLogo_Console.exe"


def test_locate_headless_launcher_falls_back_to_bat(tmp_path, monkeypatch):
    home = tmp_path / "NL"
    home.mkdir()
    monkeypatch.setattr(bspace.platform, "system", lambda: "Windows")
    (home / "netlogo-headless.bat").write_text("dummy")
    out = bspace.locate_headless_launcher(str(home))
    assert out.name == "netlogo-headless.bat"


def test_locate_headless_launcher_finds_console_on_posix(tmp_path, monkeypatch):
    home = tmp_path / "NL"
    home.mkdir()
    monkeypatch.setattr(bspace.platform, "system", lambda: "Linux")
    (home / "NetLogo_Console").write_text("dummy")
    out = bspace.locate_headless_launcher(str(home))
    assert out.name == "NetLogo_Console"


def test_locate_headless_launcher_raises_when_missing(tmp_path):
    home = tmp_path / "empty"
    home.mkdir()
    with pytest.raises(bspace.BSpaceError, match="Could not find"):
        bspace.locate_headless_launcher(str(home))


def test_locate_headless_launcher_raises_for_missing_dir(tmp_path):
    with pytest.raises(bspace.BSpaceError, match="does not exist"):
        bspace.locate_headless_launcher(str(tmp_path / "no-such"))


# ── run_headless error paths (don't actually execute Java) ───────────────────


def test_run_headless_raises_when_launcher_missing(tmp_path):
    with pytest.raises(bspace.BSpaceError, match="launcher not found"):
        bspace.run_headless(
            launcher=tmp_path / "nope.exe",
            model_path=tmp_path,
            table_csv=tmp_path / "out.csv",
        )


def test_run_headless_raises_when_model_missing(tmp_path):
    fake_launcher = tmp_path / "NetLogo_Console.exe"
    fake_launcher.write_text("dummy")
    with pytest.raises(bspace.BSpaceError, match="model not found"):
        bspace.run_headless(
            launcher=fake_launcher,
            model_path=tmp_path / "missing.nlogox",
            table_csv=tmp_path / "out.csv",
        )


def test_run_headless_timeout_preserves_partial_csv_written_during_run(
    tmp_path, monkeypatch
):
    """Patch subprocess.run to (a) write a partial table CSV mid-flight and
    (b) raise TimeoutExpired. The runner should report timed_out=True and
    still count the rows the launcher wrote before being killed.
    """
    import subprocess as _sp

    fake_launcher = tmp_path / "NetLogo_Console.exe"
    fake_launcher.write_text("dummy")
    fake_model = tmp_path / "m.nlogox"
    fake_model.write_text("<?xml version='1.0'?><model></model>")
    table = tmp_path / "out.csv"

    def fake_run(*args, **kwargs):
        # Simulate the launcher writing a partial CSV before being killed.
        table.write_text(
            "\n".join(
                [
                    '"BehaviorSpace results"',
                    '"m.nlogox"',
                    '"e"',
                    '"now"',
                    '"min-pxcor"',
                    '"0"',
                    '"[run number]","[step]","x"',
                    '"1","1","0"',
                ]
            )
        )
        raise _sp.TimeoutExpired(cmd=args[0], timeout=kwargs.get("timeout", 1))

    monkeypatch.setattr(bspace.subprocess, "run", fake_run)

    out = bspace.run_headless(
        launcher=fake_launcher,
        model_path=fake_model,
        table_csv=table,
        timeout_seconds=1,
    )
    assert out.timed_out is True
    assert out.success is False
    # _count_data_rows skips the 7-line header and counts row 8 onward.
    assert out.rows_returned == 1


# ── safe_output_name / quote helpers ─────────────────────────────────────────


def test_safe_output_name_strips_unsafe_chars():
    assert bspace.safe_output_name("Wolf/Sheep:Predation!") == "Wolf_Sheep_Predation"
    assert bspace.safe_output_name("") == "experiment"
    assert bspace.safe_output_name("Hello world 123") == "Hello_world_123"
    # Leading/trailing punctuation is stripped to keep filenames tidy.
    assert bspace.safe_output_name("__foo__") == "foo"
    # All-junk falls back to the default name.
    assert bspace.safe_output_name("!!!") == "experiment"


def test_quote_for_cmd_handles_spaces_and_quotes():
    # Internal helper, but worth exercising — used on Windows .bat invocation.
    assert bspace._quote_for_cmd("simple") == "simple"
    assert bspace._quote_for_cmd("with spaces") == '"with spaces"'
    assert bspace._quote_for_cmd('has"quote') == '"has\\"quote"'
    assert bspace._quote_for_cmd("") == '""'
