"""BehaviorSpace integration — build, parse, and run NetLogo BehaviorSpace
experiments via the headless launcher.

The MCP server runs its own NetLogo JVM with a model loaded for interactive
work. BehaviorSpace, by contrast, is intentionally run as a *separate*
subprocess (`netlogo-headless.bat` / `NetLogo_Console`):

- The headless launcher is the canonical, version-stable way to run
  BehaviorSpace and is the only path that supports BehaviorSpace's parallel
  run scheduling and its standard output formats.
- It works against any installed NetLogo 6.x or 7.x, with no dependency on
  the (unbundled) `bspace` extension.
- Running in a separate JVM keeps the MCP server's interactive workspace
  alive and uncontaminated.

Public surface used by tools.py:
    ExperimentVariable, ExperimentSpec, RunOutcome
    parse_experiments(model_path)        — read <experiments> from a .nlogox/.nlogo
    build_setup_file_xml(spec)           — write a standalone setup-file XML
    count_runs(spec)                     — total runs without executing
    locate_headless_launcher(netlogo_home) — find the launcher binary
    run_headless(...)                    — run subprocess + capture table CSV
    parse_table_csv(path)                — DataFrame from a BehaviorSpace table CSV
    summarize_results(df, metrics, vars) — final-tick stats per parameter combo
"""

from __future__ import annotations

import csv
import os
import platform
import shlex
import subprocess
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from xml.sax.saxutils import escape as xml_escape

import pandas as pd
from defusedxml import ElementTree as DefusedET


class BSpaceError(Exception):
    """Raised for any BehaviorSpace orchestration failure."""


# ── Data classes ─────────────────────────────────────────────────────────────


@dataclass
class ExperimentVariable:
    """A BehaviorSpace parameter to vary.

    Use `kind="enumerated"` with `values=[...]` for explicit value lists, or
    `kind="stepped"` with `first` / `step` / `last` for a numeric range.
    """

    name: str
    kind: str  # "enumerated" | "stepped"
    values: list[Any] | None = None
    first: float | None = None
    step: float | None = None
    last: float | None = None

    def expanded_values(self) -> list[Any]:
        """Return the concrete list of values this variable will take."""
        if self.kind == "enumerated":
            return list(self.values or [])
        if self.kind == "stepped":
            if self.first is None or self.step is None or self.last is None:
                raise BSpaceError(
                    f"stepped variable {self.name!r} needs first/step/last"
                )
            if self.step <= 0:
                raise BSpaceError(f"stepped variable {self.name!r} needs step > 0")
            out: list[Any] = []
            v = float(self.first)
            # Inclusive of `last` within a small epsilon.
            eps = self.step * 1e-9
            while v <= float(self.last) + eps:
                # Coerce integers if step+endpoints are integer-valued.
                if (
                    float(self.first).is_integer()
                    and float(self.step).is_integer()
                    and float(self.last).is_integer()
                ):
                    out.append(int(round(v)))
                else:
                    out.append(round(v, 10))
                v += float(self.step)
            return out
        raise BSpaceError(f"unknown variable kind: {self.kind!r}")


@dataclass
class ExperimentSpec:
    """A complete BehaviorSpace experiment definition."""

    name: str
    repetitions: int = 1
    time_limit: int = 1000
    setup_commands: str = "setup"
    go_commands: str = "go"
    stop_condition: str | None = None
    metrics: list[str] = field(default_factory=list)
    variables: list[ExperimentVariable] = field(default_factory=list)
    run_metrics_every_step: bool = True
    sequential_run_order: bool = True
    pre_experiment_commands: str | None = None
    post_experiment_commands: str | None = None
    post_run_commands: str | None = None


@dataclass
class RunOutcome:
    """Result returned by `run_headless`."""

    success: bool
    return_code: int
    duration_seconds: float
    table_csv_path: Path
    rows_returned: int
    timed_out: bool
    stderr_tail: str
    command: list[str]


# ── Variable helpers ─────────────────────────────────────────────────────────


def variable_from_dict(data: dict[str, Any]) -> ExperimentVariable:
    """Build an ExperimentVariable from a JSON-friendly dict.

    Accepted shapes::

        {"name": "X", "values": [1, 2, 3]}                 # enumerated
        {"name": "X", "first": 1, "step": 0.5, "last": 3}  # stepped
    """
    name = str(data.get("name") or "").strip()
    if not name:
        raise BSpaceError("variable is missing 'name'")
    if "values" in data and data["values"] is not None:
        vals = list(data["values"])
        if not vals:
            raise BSpaceError(f"variable {name!r}: 'values' must not be empty")
        return ExperimentVariable(name=name, kind="enumerated", values=vals)
    if "first" in data and "step" in data and "last" in data:
        return ExperimentVariable(
            name=name,
            kind="stepped",
            first=float(data["first"]),
            step=float(data["step"]),
            last=float(data["last"]),
        )
    raise BSpaceError(
        f"variable {name!r} must have either 'values' or 'first'/'step'/'last'"
    )


def count_runs(spec: ExperimentSpec) -> int:
    """Total runs = repetitions × |all parameter combinations|.

    Parameter expansion is the Cartesian product of each variable's expanded
    values — matches BehaviorSpace's combinatorial behavior.
    """
    if not spec.variables:
        return max(1, spec.repetitions)
    sizes = [len(v.expanded_values()) for v in spec.variables]
    combos = 1
    for s in sizes:
        combos *= max(1, s)
    return combos * max(1, spec.repetitions)


# ── XML build (setup-file format) ────────────────────────────────────────────


def _format_value(v: Any) -> str:
    """Render a parameter value the way BehaviorSpace's XML reader expects."""
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, (int, float)):
        # NetLogo accepts numeric literals; keep ints as ints.
        if isinstance(v, float) and v.is_integer():
            return str(int(v))
        return repr(v) if isinstance(v, float) else str(v)
    return f"&quot;{xml_escape(str(v))}&quot;"  # string with quotes for NetLogo


def _variable_to_xml(var: ExperimentVariable) -> str:
    if var.kind == "stepped":
        return (
            f'    <steppedValueSet variable="{xml_escape(var.name)}" '
            f'first="{var.first}" step="{var.step}" last="{var.last}"/>'
        )
    # enumerated
    inner = "\n".join(
        f"      <value value={_quote_attr(_format_value(v))}/>"
        for v in (var.values or [])
    )
    return (
        f'    <enumeratedValueSet variable="{xml_escape(var.name)}">\n'
        f"{inner}\n"
        f"    </enumeratedValueSet>"
    )


def _quote_attr(value: str) -> str:
    """Wrap an XML attribute value, picking single quotes if it contains ``\"``.

    BehaviorSpace's NetLogo-string syntax embeds literal double quotes inside
    XML attribute values. The DTD permits ``'value'`` with a single-quote
    delimiter, so we switch when needed and otherwise default to ``"value"``.
    """
    if '"' in value and "'" not in value:
        return f"'{value}'"
    return f'"{value}"'


def build_setup_file_xml(spec: ExperimentSpec) -> str:
    """Construct a standalone setup-file XML for ``--setup-file``.

    Includes the DOCTYPE the headless launcher requires.
    """
    parts: list[str] = []
    parts.append('<?xml version="1.0" encoding="UTF-8"?>')
    parts.append('<!DOCTYPE experiments SYSTEM "behaviorspace.dtd">')
    parts.append("<experiments>")
    attrs = [
        f'name="{xml_escape(spec.name)}"',
        f'repetitions="{int(spec.repetitions)}"',
        f'sequentialRunOrder="{"true" if spec.sequential_run_order else "false"}"',
        f'runMetricsEveryStep="{"true" if spec.run_metrics_every_step else "false"}"',
    ]
    if spec.time_limit and spec.time_limit > 0:
        attrs.append(f'timeLimit="{int(spec.time_limit)}"')
    parts.append(f"  <experiment {' '.join(attrs)}>")
    if spec.pre_experiment_commands:
        parts.append(
            f"    <preExperiment>{xml_escape(spec.pre_experiment_commands)}</preExperiment>"
        )
    parts.append(f"    <setup>{xml_escape(spec.setup_commands)}</setup>")
    parts.append(f"    <go>{xml_escape(spec.go_commands)}</go>")
    if spec.post_run_commands:
        parts.append(f"    <postRun>{xml_escape(spec.post_run_commands)}</postRun>")
    if spec.post_experiment_commands:
        parts.append(
            f"    <postExperiment>{xml_escape(spec.post_experiment_commands)}</postExperiment>"
        )
    if spec.stop_condition:
        parts.append(
            f"    <exitCondition>{xml_escape(spec.stop_condition)}</exitCondition>"
        )
    if spec.metrics:
        parts.append("    <metrics>")
        for m in spec.metrics:
            parts.append(f"      <metric>{xml_escape(m)}</metric>")
        parts.append("    </metrics>")
    if spec.variables:
        parts.append("    <constants>")
        for var in spec.variables:
            parts.append(_variable_to_xml(var))
        parts.append("    </constants>")
    parts.append("  </experiment>")
    parts.append("</experiments>")
    return "\n".join(parts) + "\n"


# ── XML parse (extract experiments from a .nlogox/.nlogo) ─────────────────────


def parse_experiments(model_path: Path) -> list[ExperimentSpec]:
    """Read a .nlogox or .nlogo file and return its BehaviorSpace experiments.

    For .nlogox the experiments live inside an ``<experiments>`` element near
    the end of the model XML. For .nlogo (legacy) experiments live in their
    own section delimited by ``@#$#@#$#@`` markers near the file end. Both
    formats use the same ``<experiment>`` shape inside, so we look for the
    XML and parse it the same way.
    """
    if not model_path.exists():
        raise BSpaceError(f"model not found: {model_path}")
    text = model_path.read_text(encoding="utf-8", errors="replace")

    # Find the <experiments> ... </experiments> XML block. ElementTree
    # doesn't accept partial documents cleanly, so we string-extract first.
    start = text.find("<experiments>")
    end = text.find("</experiments>", start) if start >= 0 else -1
    if start < 0 or end < 0:
        return []
    xml_blob = text[start : end + len("</experiments>")]
    try:
        # Use defusedxml: model files may originate from CoMSES (untrusted).
        # Guards against entity-expansion / billion-laughs / external-DTD attacks.
        root = DefusedET.fromstring(xml_blob)
    except ET.ParseError as exc:
        raise BSpaceError(f"could not parse <experiments> XML: {exc}") from exc

    out: list[ExperimentSpec] = []
    for exp in root.findall("experiment"):
        out.append(_experiment_from_element(exp))
    return out


def _experiment_from_element(exp: ET.Element) -> ExperimentSpec:
    name = exp.get("name") or ""
    repetitions = int(exp.get("repetitions") or "1")
    run_metrics_every_step = (exp.get("runMetricsEveryStep") or "true") == "true"
    sequential = (exp.get("sequentialRunOrder") or "true") == "true"
    # `timeLimit` may live on the attribute (NetLogo 7) or as a <timeLimit
    # steps="N"/> child element (legacy NetLogo 6.x export). Tolerate both.
    time_limit_attr = exp.get("timeLimit")
    if time_limit_attr is not None:
        time_limit = int(time_limit_attr)
    else:
        tl_el = exp.find("timeLimit")
        time_limit = int(tl_el.get("steps") or "0") if tl_el is not None else 0

    setup = (exp.findtext("setup") or "setup").strip()
    go = (exp.findtext("go") or "go").strip()
    stop = exp.findtext("exitCondition")
    if stop is not None:
        stop = stop.strip() or None

    pre_exp = exp.findtext("preExperiment")
    post_exp = exp.findtext("postExperiment")
    post_run = exp.findtext("postRun")

    metrics: list[str] = []
    metrics_el = exp.find("metrics")
    if metrics_el is not None:
        for m in metrics_el.findall("metric"):
            txt = (m.text or "").strip()
            if txt:
                metrics.append(txt)
    else:
        # Legacy NetLogo 6.x exports place <metric> directly under <experiment>.
        for m in exp.findall("metric"):
            txt = (m.text or "").strip()
            if txt:
                metrics.append(txt)

    variables: list[ExperimentVariable] = []
    constants_el = exp.find("constants")
    if constants_el is None:
        constants_el = exp
    for vs in constants_el.findall("enumeratedValueSet"):
        vals: list[Any] = []
        for v in vs.findall("value"):
            raw = v.get("value")
            if raw is None:
                continue
            vals.append(_coerce_xml_value(raw))
        variables.append(
            ExperimentVariable(
                name=vs.get("variable") or "", kind="enumerated", values=vals
            )
        )
    for vs in constants_el.findall("steppedValueSet"):
        variables.append(
            ExperimentVariable(
                name=vs.get("variable") or "",
                kind="stepped",
                first=_safe_float(vs.get("first")),
                step=_safe_float(vs.get("step")),
                last=_safe_float(vs.get("last")),
            )
        )

    return ExperimentSpec(
        name=name,
        repetitions=repetitions,
        time_limit=time_limit,
        setup_commands=setup,
        go_commands=go,
        stop_condition=stop,
        metrics=metrics,
        variables=variables,
        run_metrics_every_step=run_metrics_every_step,
        sequential_run_order=sequential,
        pre_experiment_commands=(pre_exp or None),
        post_experiment_commands=(post_exp or None),
        post_run_commands=(post_run or None),
    )


def _safe_float(v: str | None) -> float | None:
    try:
        return None if v is None else float(v)
    except ValueError:
        return None


def _coerce_xml_value(raw: str) -> Any:
    """Best-effort numeric/bool coercion for enumeratedValueSet values."""
    s = raw.strip()
    if s.lower() == "true":
        return True
    if s.lower() == "false":
        return False
    # NetLogo string literals come back wrapped in double quotes.
    if len(s) >= 2 and s[0] == '"' and s[-1] == '"':
        return s[1:-1]
    try:
        if "." in s or "e" in s.lower():
            return float(s)
        return int(s)
    except ValueError:
        return s


def spec_to_dict(spec: ExperimentSpec) -> dict[str, Any]:
    """JSON-friendly view of an ExperimentSpec for tool responses."""
    return {
        "name": spec.name,
        "repetitions": spec.repetitions,
        "time_limit": spec.time_limit,
        "setup_commands": spec.setup_commands,
        "go_commands": spec.go_commands,
        "stop_condition": spec.stop_condition,
        "run_metrics_every_step": spec.run_metrics_every_step,
        "sequential_run_order": spec.sequential_run_order,
        "metrics": list(spec.metrics),
        "variables": [
            {
                "name": v.name,
                "kind": v.kind,
                "values": v.values if v.kind == "enumerated" else None,
                "first": v.first if v.kind == "stepped" else None,
                "step": v.step if v.kind == "stepped" else None,
                "last": v.last if v.kind == "stepped" else None,
                "expanded_size": len(v.expanded_values()),
            }
            for v in spec.variables
        ],
        "total_runs": count_runs(spec),
    }


# ── Headless launcher discovery ───────────────────────────────────────────────


def locate_headless_launcher(netlogo_home: str) -> Path:
    """Return the path to the headless launcher script for this install.

    Order of preference: ``NetLogo_Console`` (NetLogo ≥ 6.3) → legacy
    ``netlogo-headless.bat`` / ``netlogo-headless.sh``.
    """
    home = Path(netlogo_home)
    if not home.is_dir():
        raise BSpaceError(f"NETLOGO_HOME does not exist: {netlogo_home}")

    is_windows = platform.system() == "Windows"
    candidates = (
        [home / "NetLogo_Console.exe", home / "netlogo-headless.bat"]
        if is_windows
        else [home / "NetLogo_Console", home / "netlogo-headless.sh"]
    )
    for c in candidates:
        if c.exists():
            return c
    raise BSpaceError(
        "Could not find a NetLogo headless launcher in "
        f"{home}. Expected NetLogo_Console or netlogo-headless.{'bat' if is_windows else 'sh'}"
    )


# ── Subprocess runner ─────────────────────────────────────────────────────────


def run_headless(
    *,
    launcher: Path,
    model_path: Path,
    table_csv: Path,
    setup_file: Path | None = None,
    experiment_name: str | None = None,
    threads: int | None = None,
    is_3d: bool = False,
    timeout_seconds: int | None = None,
) -> RunOutcome:
    """Spawn the headless launcher and capture its table output.

    The caller MUST pass a writable ``table_csv`` path. Only ``--table`` is
    used so that runs are checkpointed to disk incrementally and a partial
    file remains on timeout.

    The launcher inherits its own ``--headless`` invocation; we always pass
    that flag for ``NetLogo_Console`` (the ``.bat`` script doesn't need it
    but accepts it harmlessly).
    """
    import time as _time

    if not launcher.exists():
        raise BSpaceError(f"launcher not found: {launcher}")
    if not model_path.exists():
        raise BSpaceError(f"model not found: {model_path}")

    safe_name = _sanitize_experiment_name(experiment_name) if experiment_name else None

    args: list[str] = [str(launcher)]
    if launcher.name.lower().startswith("netlogo_console"):
        args.append("--headless")
    args += ["--model", str(model_path)]
    if setup_file is not None:
        args += ["--setup-file", str(setup_file)]
    if safe_name:
        args += ["--experiment", safe_name]
    args += ["--table", str(table_csv)]
    if threads is not None and threads > 0:
        args += ["--threads", str(threads)]
    if is_3d:
        args.append("--3D")

    # On Windows, `.bat` files need a shell to resolve. Use cmd.exe /c with
    # shell=False so Python passes argv directly — no hand-rolled cmd quoting,
    # no metacharacter risk from third-party experiment names in CoMSES models.
    if launcher.suffix.lower() == ".bat":
        args = ["cmd.exe", "/c"] + args

    table_csv.parent.mkdir(parents=True, exist_ok=True)
    # Wipe any previous run for this exact target — NetLogo will refuse or
    # produce confusing output if the file already exists.
    if table_csv.exists():
        try:
            table_csv.unlink()
        except OSError:
            pass

    start = _time.monotonic()
    timed_out = False
    return_code = -1
    stderr_tail = ""

    try:
        proc = subprocess.run(
            args,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
            env=os.environ.copy(),
        )
        return_code = proc.returncode
        stderr_tail = (proc.stderr or "")[-2000:]
    except subprocess.TimeoutExpired as exc:
        timed_out = True
        return_code = -1
        stderr_tail = (exc.stderr or "")[-2000:] if isinstance(exc.stderr, str) else ""
    duration = _time.monotonic() - start

    rows = 0
    if table_csv.exists():
        rows = _count_data_rows(table_csv)

    success = (not timed_out) and return_code == 0 and rows > 0
    return RunOutcome(
        success=success,
        return_code=return_code,
        duration_seconds=duration,
        table_csv_path=table_csv,
        rows_returned=rows,
        timed_out=timed_out,
        stderr_tail=stderr_tail,
        command=args,
    )


def _sanitize_experiment_name(name: str) -> str:
    """Restrict a BehaviorSpace experiment name to a safe charset for `--experiment`.

    Saved-experiment names can originate from CoMSES model XML (untrusted).
    BehaviorSpace itself is happy with reasonably free-form names, but we
    keep the surface that lands on a child process's argv to ``[A-Za-z0-9
    _\\- .]+`` — every char outside that set is replaced with ``_``.
    Pure-empty results fall back to ``"experiment"``.
    """
    cleaned = "".join(c if (c.isalnum() or c in "-_ .") else "_" for c in name)
    # Trim surrounding whitespace / underscores so an all-junk input
    # ("@@@") collapses to the fallback instead of "___".
    cleaned = cleaned.strip(" _")
    return cleaned or "experiment"


# ── Table CSV parsing ─────────────────────────────────────────────────────────


def _count_data_rows(path: Path) -> int:
    """Count data rows in a BehaviorSpace table CSV (after the 6 header rows
    and the column header row).
    """
    try:
        with path.open("r", encoding="utf-8", errors="replace", newline="") as fh:
            n = 0
            for i, _ in enumerate(fh):
                if i >= 7:
                    n += 1
            return n
    except OSError:
        return 0


def parse_table_csv(path: Path) -> pd.DataFrame:
    """Parse a NetLogo BehaviorSpace ``--table`` CSV.

    The first six rows are metadata (BehaviorSpace banner, model name,
    experiment name, run start time, world dimension labels, world dimension
    values). Row seven (1-indexed) is the column header — ``[run number]``,
    ``[step]``, then one column per varied parameter, then one column per
    metric. Subsequent rows are data.
    """
    if not path.exists():
        raise BSpaceError(f"table CSV not found: {path}")
    try:
        df = pd.read_csv(path, skiprows=6)
    except Exception as exc:
        raise BSpaceError(f"could not parse table CSV: {exc}") from exc
    # NetLogo's table CSV uses ``[run number]`` and ``[step]`` literally.
    rename_map: dict[str, str] = {}
    for c in df.columns:
        if c.strip().lower() in ("[run number]", "run number"):
            rename_map[c] = "run_number"
        elif c.strip().lower() in ("[step]", "step"):
            rename_map[c] = "step"
    if rename_map:
        df = df.rename(columns=rename_map)
    return df


def read_table_metadata(path: Path) -> dict[str, Any]:
    """Extract the six metadata rows from a BehaviorSpace table CSV."""
    if not path.exists():
        raise BSpaceError(f"table CSV not found: {path}")
    rows: list[list[str]] = []
    with path.open("r", encoding="utf-8", errors="replace", newline="") as fh:
        reader = csv.reader(fh)
        for i, row in enumerate(reader):
            if i >= 6:
                break
            rows.append(row)
    out: dict[str, Any] = {}
    if len(rows) >= 1 and rows[0]:
        out["header"] = rows[0][0]
    if len(rows) >= 2 and rows[1]:
        out["model"] = rows[1][0]
    if len(rows) >= 3 and rows[2]:
        out["experiment"] = rows[2][0]
    if len(rows) >= 4 and rows[3]:
        out["start_time"] = rows[3][0]
    if len(rows) >= 6 and len(rows[4]) >= 1 and len(rows[5]) >= 1:
        try:
            out["world"] = dict(zip(rows[4], rows[5], strict=False))
        except Exception:
            pass
    return out


def summarize_results(df: pd.DataFrame, spec: ExperimentSpec) -> dict[str, Any]:
    """Aggregate a BehaviorSpace results DataFrame.

    Returns a dict with per-parameter-combination final-step values and
    summary stats per metric. The shape is intentionally compact — we trim
    intermediate-step rows; the AI can re-read the CSV via the path if it
    needs the full time series.
    """
    if df.empty:
        return {
            "total_rows": 0,
            "runs": 0,
            "metrics_summary": {},
            "per_combination": [],
        }

    var_cols = [v.name for v in spec.variables if v.name in df.columns]
    metric_cols = [m for m in spec.metrics if m in df.columns]

    # Pick the final step for each run.
    if "step" in df.columns and "run_number" in df.columns:
        finals = df.sort_values(["run_number", "step"]).groupby("run_number").tail(1)
    else:
        finals = df

    per_combo: list[dict[str, Any]] = []
    if var_cols:
        for combo, sub in finals.groupby(var_cols, dropna=False):
            combo_dict = (
                dict(zip(var_cols, combo, strict=False))
                if isinstance(combo, tuple)
                else {var_cols[0]: combo}
            )
            entry: dict[str, Any] = {"parameters": combo_dict, "n_runs": len(sub)}
            entry["metrics"] = {}
            for m in metric_cols:
                vals = pd.to_numeric(sub[m], errors="coerce").dropna()
                entry["metrics"][m] = _stats_block(vals)
            per_combo.append(entry)
    else:
        entry = {"parameters": {}, "n_runs": len(finals)}
        entry["metrics"] = {
            m: _stats_block(pd.to_numeric(finals[m], errors="coerce").dropna())
            for m in metric_cols
        }
        per_combo.append(entry)

    # Top-level metric summary across all runs (final-step).
    top_summary: dict[str, Any] = {}
    for m in metric_cols:
        vals = pd.to_numeric(finals[m], errors="coerce").dropna()
        top_summary[m] = _stats_block(vals)

    return {
        "total_rows": int(len(df)),
        "runs": int(finals["run_number"].nunique())
        if "run_number" in finals.columns
        else int(len(finals)),
        "metrics_summary": top_summary,
        "per_combination": per_combo,
    }


def _stats_block(series: pd.Series) -> dict[str, float | None]:
    if series.empty:
        return {"mean": None, "std": None, "min": None, "max": None, "count": 0}
    return {
        "mean": float(series.mean()),
        "std": float(series.std(ddof=1)) if len(series) > 1 else 0.0,
        "min": float(series.min()),
        "max": float(series.max()),
        "count": int(series.count()),
    }


# ── Convenience: make a sanitized output filename ────────────────────────────


def safe_output_name(name: str) -> str:
    """Sanitize an experiment / output name for use in filenames."""
    cleaned = "".join(
        c if (c.isalnum() or c in "-_") else "_" for c in (name or "experiment")
    )
    return cleaned.strip("_") or "experiment"


# Re-export shlex for tests that want to format a launch command for inspection.
__all__ = [
    "BSpaceError",
    "ExperimentSpec",
    "ExperimentVariable",
    "RunOutcome",
    "build_setup_file_xml",
    "count_runs",
    "locate_headless_launcher",
    "parse_experiments",
    "parse_table_csv",
    "read_table_metadata",
    "run_headless",
    "safe_output_name",
    "shlex",
    "spec_to_dict",
    "summarize_results",
    "variable_from_dict",
]
