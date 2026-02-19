"""NetLogo MCP tools — 12 tools for controlling NetLogo from Claude."""

from __future__ import annotations

import json
import tempfile
import traceback
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from fastmcp import Context
from fastmcp.exceptions import ToolError
from fastmcp.utilities.types import Image

from .config import get_models_dir
from .server import mcp

# ── Helpers ──────────────────────────────────────────────────────────────────


def _nl(ctx: Context):
    """Get the shared NetLogoLink instance from the lifespan context."""
    try:
        return ctx.request_context.lifespan_context["netlogo"]
    except (AttributeError, KeyError):
        raise ToolError("NetLogo workspace is not initialized.")


def _require_model(ctx: Context):
    """Raise ToolError if no model is currently loaded."""
    nl = _nl(ctx)
    try:
        # Use max-pxcor as a model-loaded check — it always works,
        # even before reset-ticks (unlike "ticks" which errors pre-setup).
        nl.report("max-pxcor")
    except Exception:
        raise ToolError(
            "No model is loaded. Use open_model or create_model first."
        )
    return nl


def _wrap_netlogo_error(e: Exception) -> ToolError:
    """Convert a Java/NetLogo exception to a readable ToolError."""
    msg = str(e)
    # Strip Java exception wrapper noise
    for prefix in (
        "org.nlogo.core.CompilerException: ",
        "org.nlogo.nvm.RuntimePrimitiveException: ",
        "org.nlogo.api.LogoException: ",
    ):
        if msg.startswith(prefix):
            msg = msg[len(prefix):]

    hint = (
        "\n\nTip: consult the netlogo://docs/primitives resource "
        "for correct NetLogo syntax."
    )
    return ToolError(f"NetLogo error: {msg}{hint}")


def _json_safe(value: Any) -> Any:
    """Make a value JSON-serializable (handles numpy/Java types)."""
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating,)):
        return float(value)
    if isinstance(value, np.ndarray):
        return value.tolist()
    if isinstance(value, pd.DataFrame):
        return value.to_dict(orient="list")
    if isinstance(value, pd.Series):
        return value.tolist()
    return value


# ── Tools ────────────────────────────────────────────────────────────────────


@mcp.tool()
async def open_model(path: str, ctx: Context) -> str:
    """Open an existing .nlogo model file.

    Args:
        path: Path to the .nlogo file. Can be absolute, or relative to the
              configured models directory.
    """
    nl = _nl(ctx)
    p = Path(path)
    if not p.is_absolute():
        p = get_models_dir() / p

    p = p.resolve()
    if not p.exists():
        raise ToolError(f"Model file not found: {p}")
    if p.suffix not in (".nlogo", ".nlogox"):
        raise ToolError(f"Not a .nlogo/.nlogox file: {p}")

    try:
        nl.load_model(str(p).replace("\\", "/"))
    except Exception as e:
        raise _wrap_netlogo_error(e)

    return f"Model loaded: {p.name}"


@mcp.tool()
async def command(netlogo_command: str, ctx: Context) -> str:
    """Execute a NetLogo command (e.g. 'setup', 'go', 'create-turtles 10').

    Args:
        netlogo_command: The NetLogo command string to execute.
    """
    nl = _require_model(ctx)
    try:
        nl.command(netlogo_command)
    except Exception as e:
        raise _wrap_netlogo_error(e)
    return f"OK: {netlogo_command}"


@mcp.tool()
async def report(reporter: str, ctx: Context) -> str:
    """Evaluate a NetLogo reporter expression and return its value.

    Args:
        reporter: A NetLogo reporter expression (e.g. 'count turtles',
                  'mean [energy] of turtles').
    """
    nl = _require_model(ctx)
    try:
        result = nl.report(reporter)
    except Exception as e:
        raise _wrap_netlogo_error(e)
    return json.dumps(_json_safe(result))


@mcp.tool()
async def run_simulation(
    ticks: int,
    reporters: list[str],
    ctx: Context,
    go_command: str = "go",
) -> str:
    """Run the simulation for N ticks and collect reporter data each tick.

    Args:
        ticks: Number of ticks to run (1-10000).
        reporters: List of NetLogo reporter expressions to collect each tick.
        go_command: The go command to use (default: "go").

    Returns:
        A markdown table of tick-by-tick data.
    """
    if ticks < 1 or ticks > 10000:
        raise ToolError("ticks must be between 1 and 10000.")
    if not reporters:
        raise ToolError("reporters list cannot be empty.")

    nl = _require_model(ctx)

    try:
        results = nl.repeat_report(reporters, ticks, go=go_command)
    except Exception as e:
        raise _wrap_netlogo_error(e)

    # results is a DataFrame with reporters as columns, ticks as index
    if isinstance(results, pd.DataFrame):
        df = results
    else:
        # Single reporter returns a Series
        df = pd.DataFrame({reporters[0]: results})

    # Build markdown table
    lines = ["| tick | " + " | ".join(df.columns) + " |"]
    lines.append("| --- | " + " | ".join(["---"] * len(df.columns)) + " |")
    for tick, row in df.iterrows():
        vals = " | ".join(str(_json_safe(v)) for v in row)
        lines.append(f"| {tick} | {vals} |")

    return "\n".join(lines)


@mcp.tool()
async def set_parameter(name: str, value: Any, ctx: Context) -> str:
    """Set a NetLogo global variable / slider / switch value.

    Args:
        name: Name of the global variable (e.g. 'initial-number-sheep').
        value: The value to set. Numbers, strings, booleans accepted.
    """
    nl = _require_model(ctx)
    # Format the value for NetLogo
    if isinstance(value, bool):
        nl_val = "true" if value else "false"
    elif isinstance(value, str):
        nl_val = f'"{value}"'
    else:
        nl_val = str(value)

    try:
        nl.command(f"set {name} {nl_val}")
    except Exception as e:
        raise _wrap_netlogo_error(e)
    return f"OK: {name} = {nl_val}"


@mcp.tool()
async def get_world_state(ctx: Context) -> str:
    """Get the current world state: tick count, agent counts, world dimensions.

    Returns JSON with ticks, turtle/patch/link counts, and world bounds.
    """
    nl = _require_model(ctx)
    try:
        state = {
            "ticks": _json_safe(nl.report("ticks")),
            "turtle_count": _json_safe(nl.report("count turtles")),
            "patch_count": _json_safe(nl.report("count patches")),
            "link_count": _json_safe(nl.report("count links")),
            "min_pxcor": _json_safe(nl.report("min-pxcor")),
            "max_pxcor": _json_safe(nl.report("max-pxcor")),
            "min_pycor": _json_safe(nl.report("min-pycor")),
            "max_pycor": _json_safe(nl.report("max-pycor")),
        }
    except Exception as e:
        raise _wrap_netlogo_error(e)
    return json.dumps(state, indent=2)


@mcp.tool()
async def get_patch_data(attribute: str, ctx: Context) -> str:
    """Get patch data as a 2D grid (useful for heatmaps / spatial analysis).

    Args:
        attribute: The patch variable to report (e.g. 'pcolor', 'grass').

    Returns:
        JSON 2D array (rows = y descending, cols = x ascending).
    """
    nl = _require_model(ctx)
    try:
        data = nl.patch_report(attribute)
    except Exception as e:
        raise _wrap_netlogo_error(e)

    # patch_report returns a DataFrame indexed by (pxcor, pycor)
    if isinstance(data, pd.DataFrame):
        grid = data.values.tolist()
    else:
        grid = _json_safe(data)

    return json.dumps(grid)


@mcp.tool()
async def export_view(ctx: Context) -> Image:
    """Export the current NetLogo view as a PNG image.

    Returns the image so Claude can see the model visualization.
    """
    nl = _require_model(ctx)

    tmp = tempfile.NamedTemporaryFile(suffix=".png", delete=False)
    tmp.close()
    export_path = tmp.name.replace("\\", "/")

    try:
        nl.command(f'export-view "{export_path}"')
    except Exception as e:
        raise _wrap_netlogo_error(e)

    return Image(path=export_path)


@mcp.tool()
async def create_model(code: str, ctx: Context) -> str:
    """Create a new NetLogo model from code and load it.

    Args:
        code: NetLogo model code. Can be just the procedures (globals, breeds,
              setup, go, etc.) — the .nlogox envelope will be added automatically.
              Or provide a full .nlogox XML file.
    """
    nl = _nl(ctx)

    # If user provided raw procedures (not XML), wrap in .nlogox envelope
    if not code.strip().startswith("<?xml") and "<model" not in code[:200]:
        code = _wrap_nlogox(code)

    # Write to a temp file and load
    tmp = tempfile.NamedTemporaryFile(
        suffix=".nlogox", delete=False, mode="w", encoding="utf-8"
    )
    tmp.write(code)
    tmp.close()

    try:
        nl.load_model(tmp.name.replace("\\", "/"))
    except Exception as e:
        raise _wrap_netlogo_error(e)

    return "Model created and loaded from temp file."


def _wrap_nlogox(procedures: str) -> str:
    """Wrap raw NetLogo procedure code in a minimal .nlogox XML envelope."""
    # Escape XML special chars in the code for safe embedding
    import xml.sax.saxutils as saxutils
    escaped = saxutils.escape(procedures)

    return f'''<?xml version="1.0" encoding="utf-8"?>
<model version="NetLogo 7.0.3" snapToGrid="false">
  <code>{escaped}</code>
  <widgets>
    <view x="210" wrappingAllowedX="true" y="10" frameRate="30.0" minPycor="-16" height="430" showTickCounter="true" patchSize="13.0" fontSize="10" wrappingAllowedY="true" width="430" tickCounterLabel="ticks" maxPycor="16" updateMode="1" maxPxcor="16" minPxcor="-16"></view>
  </widgets>
  <info><![CDATA[## WHAT IS IT?

A model created via NetLogo MCP Server.]]></info>
  <turtleShapes>
    <shape name="default" rotatable="true" editableColorIndex="0">
      <polygon color="-1920102913" filled="true" marked="true">
        <point x="150" y="5"></point>
        <point x="40" y="250"></point>
        <point x="150" y="205"></point>
        <point x="260" y="250"></point>
      </polygon>
    </shape>
    <shape name="circle" rotatable="false" editableColorIndex="0">
      <circle color="-1920102913" filled="true" marked="true" x="0" y="0" diameter="300"></circle>
    </shape>
  </turtleShapes>
  <linkShapes>
    <shape name="default" curviness="0.0">
      <lines>
        <line x="-0.2" visible="false">
          <dash value="0.0"></dash>
          <dash value="1.0"></dash>
        </line>
        <line x="0.0" visible="true">
          <dash value="1.0"></dash>
          <dash value="0.0"></dash>
        </line>
        <line x="0.2" visible="false">
          <dash value="0.0"></dash>
          <dash value="1.0"></dash>
        </line>
      </lines>
      <indicator>
        <shape name="link direction" rotatable="true" editableColorIndex="0">
          <line endX="90" startY="150" marked="true" color="-1920102913" endY="180" startX="150"></line>
          <line endX="210" startY="150" marked="true" color="-1920102913" endY="180" startX="150"></line>
        </shape>
      </indicator>
    </shape>
  </linkShapes>
</model>
'''


@mcp.tool()
async def list_models(ctx: Context) -> str:
    """List all .nlogo model files in the configured models directory.

    Returns a JSON array of {name, path, size_kb} objects.
    """
    models_dir = get_models_dir()
    files = sorted(
        list(models_dir.rglob("*.nlogo")) + list(models_dir.rglob("*.nlogox"))
    )
    result = []
    for f in files:
        result.append(
            {
                "name": f.stem,
                "path": str(f),
                "size_kb": round(f.stat().st_size / 1024, 1),
            }
        )
    return json.dumps(result, indent=2)


@mcp.tool()
async def save_model(name: str, code: str, ctx: Context) -> str:
    """Save NetLogo model code to a .nlogox file in the models directory.

    This saves the model so you can open it in the NetLogo desktop app
    for live visualization with GUI, sliders, and real-time animation.

    Args:
        name: Filename for the model (without extension).
        code: NetLogo model code (procedures only — envelope added automatically).
              Or provide a full .nlogox XML file.
    """
    if ".." in name or "/" in name or "\\" in name:
        raise ToolError("Invalid model name (no path separators allowed).")

    models_dir = get_models_dir()

    # Wrap in .nlogox envelope if raw procedures
    if not code.strip().startswith("<?xml") and "<model" not in code[:200]:
        code = _wrap_nlogox(code)

    file_path = models_dir / f"{name}.nlogox"
    file_path.write_text(code, encoding="utf-8")

    return f"Model saved to {file_path}\nYou can open this file in NetLogo desktop for live visualization."


@mcp.tool()
async def export_world(ctx: Context) -> str:
    """Export the full world state to a CSV file.

    Saves all turtle, patch, and link data. Useful for checkpointing
    a simulation or analyzing the complete state offline.

    Returns the path to the exported CSV file.
    """
    nl = _require_model(ctx)

    tmp = tempfile.NamedTemporaryFile(suffix=".csv", delete=False, mode="w")
    tmp.close()
    export_path = tmp.name.replace("\\", "/")

    try:
        nl.command(f'export-world "{export_path}"')
    except Exception as e:
        raise _wrap_netlogo_error(e)

    return f"World exported to {export_path}"
