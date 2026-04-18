"""NetLogo MCP tools — 12 tools for controlling NetLogo from Claude."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from fastmcp import Context
from fastmcp.exceptions import ToolError
from fastmcp.utilities.types import Image

from . import comses as _comses
from .config import get_exports_dir, get_models_dir
from .server import mcp

# ── Helpers ──────────────────────────────────────────────────────────────────


def _nl(ctx: Context):  # type: ignore[type-arg]
    """Get the shared NetLogoLink instance from the lifespan context."""
    try:
        return ctx.request_context.lifespan_context["netlogo"]  # type: ignore[union-attr]
    except (AttributeError, KeyError) as exc:
        raise ToolError("NetLogo workspace is not initialized.") from exc


def _require_model(ctx: Context):
    """Raise ToolError if no model is currently loaded."""
    nl = _nl(ctx)
    try:
        # Use max-pxcor as a model-loaded check — it always works,
        # even before reset-ticks (unlike "ticks" which errors pre-setup).
        # Call directly (no wrapper) to avoid stdout/thread interference.
        nl.report("max-pxcor")
    except Exception as exc:
        msg = str(exc)
        if (
            "model" in msg.lower()
            or "observer" in msg.lower()
            or "Nothing has been loaded" in msg
        ):
            raise ToolError(
                "No model is loaded. Use open_model or create_model first."
            ) from exc
        raise ToolError(
            f"Model check failed: {msg}\n\nTry using open_model or create_model first."
        ) from exc
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
            msg = msg[len(prefix) :]

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
        raise _wrap_netlogo_error(e) from e

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
        raise _wrap_netlogo_error(e) from e
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
        raise _wrap_netlogo_error(e) from e
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
        raise _wrap_netlogo_error(e) from e

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
        # Escape backslashes and double quotes for NetLogo string literals
        escaped = value.replace("\\", "\\\\").replace('"', '\\"')
        nl_val = f'"{escaped}"'
    else:
        nl_val = str(value)

    try:
        nl.command(f"set {name} {nl_val}")
    except Exception as e:
        raise _wrap_netlogo_error(e) from e
    return f"OK: {name} = {nl_val}"


@mcp.tool()
async def get_world_state(ctx: Context) -> str:
    """Get the current world state: tick count, agent counts, world dimensions.

    Returns JSON with ticks, turtle/patch/link counts, and world bounds.
    """
    nl = _require_model(ctx)
    try:
        # ticks returns -1 before reset-ticks is called; guard against errors
        try:
            ticks_val = _json_safe(nl.report("ticks"))
        except Exception:
            ticks_val = -1  # model loaded but setup not yet run

        state = {
            "ticks": ticks_val,
            "turtle_count": _json_safe(nl.report("count turtles")),
            "patch_count": _json_safe(nl.report("count patches")),
            "link_count": _json_safe(nl.report("count links")),
            "min_pxcor": _json_safe(nl.report("min-pxcor")),
            "max_pxcor": _json_safe(nl.report("max-pxcor")),
            "min_pycor": _json_safe(nl.report("min-pycor")),
            "max_pycor": _json_safe(nl.report("max-pycor")),
        }
    except Exception as e:
        raise _wrap_netlogo_error(e) from e
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
        raise _wrap_netlogo_error(e) from e

    # patch_report returns a DataFrame indexed by (pxcor, pycor)
    grid = data.values.tolist() if isinstance(data, pd.DataFrame) else _json_safe(data)

    return json.dumps(grid)


@mcp.tool()
async def export_view(ctx: Context) -> Image:
    """Export the current NetLogo view as a PNG image.

    Returns the image so Claude can see the model visualization.
    """
    nl = _require_model(ctx)

    views_dir = get_exports_dir() / "views"
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    export_path = str(views_dir / f"view_{timestamp}.png").replace("\\", "/")

    try:
        nl.command(f'export-view "{export_path}"')
    except Exception as e:
        raise _wrap_netlogo_error(e) from e

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

    # Write to models directory and load
    models_dir = get_models_dir()
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    model_path = models_dir / f"_created_{timestamp}.nlogox"
    model_path.write_text(code, encoding="utf-8")

    try:
        nl.load_model(str(model_path).replace("\\", "/"))
    except Exception as e:
        raise _wrap_netlogo_error(e) from e

    return f"Model created and loaded: {model_path}"


def _wrap_nlogox(procedures: str) -> str:
    """Wrap raw NetLogo procedure code in a minimal .nlogox XML envelope."""
    # Escape XML special chars in the code for safe embedding
    import xml.sax.saxutils as saxutils

    escaped = saxutils.escape(procedures)

    return f"""<?xml version="1.0" encoding="utf-8"?>
<model version="NetLogo 7.0.3" snapToGrid="false">
  <code>{escaped}</code>
  <widgets>
    <view x="210" wrappingAllowedX="true" y="10" frameRate="30.0" minPycor="-16" height="430" showTickCounter="true" patchSize="13.0" fontSize="10" wrappingAllowedY="true" width="430" tickCounterLabel="ticks" maxPycor="16" updateMode="1" maxPxcor="16" minPxcor="-16"></view>
    <button x="10" y="10" width="190" height="45" kind="Observer" forever="false" disableUntilTicks="false" display="Setup">setup</button>
    <button x="10" y="65" width="190" height="45" kind="Observer" forever="true" disableUntilTicks="true" display="Go">go</button>
    <monitor x="10" y="130" width="190" height="45" fontSize="11" precision="0" display="Time Steps">ticks</monitor>
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
"""


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

    worlds_dir = get_exports_dir() / "worlds"
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    export_path = str(worlds_dir / f"world_{timestamp}.csv").replace("\\", "/")

    try:
        nl.command(f'export-world "{export_path}"')
    except Exception as e:
        raise _wrap_netlogo_error(e) from e

    return f"World exported to {export_path}"


# ── CoMSES Net integration ──────────────────────────────────────────────────
#
# Five tools + one prompt that let an AI client browse, inspect, download, and
# open models from https://www.comses.net (the Network for Computational
# Modeling in Social and Ecological Sciences). See docs/COMSES_PLAN.md for the
# full spec.


def _compact_search_result(entry: dict) -> dict:
    """Pull the fields an LLM actually needs out of a COMSES search result."""
    authors = []
    for c in entry.get("allContributors") or []:
        user = (c or {}).get("user") or {}
        name = (
            user.get("name")
            or (c.get("givenName", "") + " " + c.get("familyName", "")).strip()
            or c.get("name")
            or ""
        )
        if name:
            authors.append(name)

    # Language comes from the latest release's releaseLanguages, if present.
    language = _language_from_releases(entry.get("releases") or [])

    return {
        "identifier": entry.get("identifier"),
        "title": entry.get("title"),
        "description": (
            entry.get("summarizedDescription")
            or entry.get("description")
            or ""
        )[:500],
        "authors": authors,
        "latestVersion": entry.get("latestVersionNumber"),
        "tags": [t.get("name") if isinstance(t, dict) else t for t in entry.get("tags") or []],
        "language": language,
        "isPeerReviewed": entry.get("peerReviewed", False),
        "downloads": entry.get("downloadCount", 0),
        "doi": entry.get("doi"),
        "live": entry.get("live"),
    }


def _language_from_releases(releases: list) -> str | None:
    """Pick a language name from the release with the latest version, if any."""
    if not releases:
        return None
    # Prefer the release flagged as latest, else the last one.
    target = None
    for rel in releases:
        if (rel or {}).get("latestVersion"):
            target = rel
            break
    if target is None:
        target = releases[-1]
    langs = (target or {}).get("releaseLanguages") or []
    for lang in langs:
        pl = (lang or {}).get("programmingLanguage") or {}
        name = pl.get("name") or (lang or {}).get("name")
        if name:
            return str(name)
    # Fallback: programmingLanguageTags[] or platforms[]
    tags = (target or {}).get("programmingLanguageTags") or []
    if tags:
        first = tags[0]
        return first.get("name") if isinstance(first, dict) else str(first)
    return None


@mcp.tool()
async def search_comses(
    ctx: Context,
    query: str = "",
    page: int = 1,
) -> str:
    """Search the CoMSES Net computational model library.

    Args:
        query: Free-text search across title, description, authors, tags.
               Leave empty to browse all models.
        page: 1-indexed page number (10 results per page).

    Returns JSON with `count`, `page`, `numPages`, and a `results` list of
    compact entries (`identifier`, `title`, `description`, `authors`,
    `latestVersion`, `tags`, `language`, `isPeerReviewed`, `downloads`, `doi`,
    `live`).

    The `language` field (inferred from the latest release) lets the AI decide
    whether this is a NetLogo model it can load directly or a Python/R/etc.
    model that needs a different runtime. Results are NOT filtered by
    language — that's an AI/user decision.
    """
    if page < 1:
        raise ToolError("page must be >= 1")
    try:
        async with _comses.ComsesClient() as client:
            raw = await client.search(query=query, page=page)
    except _comses.ComsesError as e:
        raise ToolError(f"COMSES search failed: {e}") from e

    compact = {
        "count": raw.get("count", 0),
        "page": raw.get("currentPage", page),
        "numPages": raw.get("numPages", 1),
        "numResults": raw.get("numResults", len(raw.get("results") or [])),
        "results": [_compact_search_result(e) for e in (raw.get("results") or [])],
    }
    return json.dumps(compact, indent=2)


def _compact_codebase_detail(data: dict) -> dict:
    """Shape the codebase detail endpoint into the AI-friendly payload."""
    authors: list[dict] = []
    for c in data.get("allContributors") or []:
        user = (c or {}).get("user") or {}
        name = (
            user.get("name")
            or (c.get("givenName", "") + " " + c.get("familyName", "")).strip()
            or ""
        )
        authors.append(
            {
                "name": name,
                "affiliation": user.get("institutionName") or c.get("affiliation"),
                "orcid": user.get("orcid") or c.get("orcid"),
            }
        )

    releases = []
    for rel in data.get("releases") or []:
        releases.append(
            {
                "versionNumber": rel.get("versionNumber"),
                "live": rel.get("live"),
                "downloadable": bool(rel.get("submittedPackage")),
                "firstPublishedAt": rel.get("firstPublishedAt"),
                "lastPublishedOn": rel.get("lastPublishedOn"),
                "language": _language_from_releases([rel]),
                "license": (rel.get("license") or {}).get("name"),
                "doi": rel.get("doi"),
            }
        )

    return {
        "identifier": data.get("identifier"),
        "title": data.get("title"),
        "description": data.get("description") or "",
        "summarizedDescription": data.get("summarizedDescription") or "",
        "authors": authors,
        "tags": [
            t.get("name") if isinstance(t, dict) else t for t in data.get("tags") or []
        ],
        "releases": releases,
        "latestVersion": data.get("latestVersionNumber"),
        "doi": data.get("doi"),
        "repositoryUrl": data.get("repositoryUrl"),
        "downloadCount": data.get("downloadCount", 0),
        "peerReviewed": data.get("peerReviewed", False),
        "citation_text": data.get("citationText") or "",
    }


@mcp.tool()
async def get_comses_model(ctx: Context, identifier: str) -> str:
    """Get detailed metadata for a specific CoMSES model.

    Args:
        identifier: Full UUID from `search_comses` results.

    Returns JSON with title, description, all authors (name/affiliation/ORCID),
    all releases (version, language, license, downloadable flag), tags, DOI,
    repository URL, download counts, and a ready-to-use `citation_text`
    researchers can paste into papers.

    The `citation_text` is pulled from the latest release; call this before
    downloading to present the user with author/license/citation info.
    """
    if not identifier:
        raise ToolError("identifier is required")
    try:
        async with _comses.ComsesClient() as client:
            data = await client.get_codebase(identifier)
            # Citation lives on the release, not the codebase. Pull it from
            # the latest release if there is one.
            latest = data.get("latestVersionNumber")
            if latest:
                try:
                    rel = await client.get_release(identifier, str(latest))
                    if rel.get("citationText"):
                        data["citationText"] = rel["citationText"]
                    # Annotate the matching release in-place so detail shape
                    # stays consistent without a second request.
                    for r in data.get("releases") or []:
                        if r.get("versionNumber") == latest:
                            r["submittedPackage"] = rel.get("submittedPackage")
                            r["live"] = rel.get("live", r.get("live"))
                            r["license"] = rel.get("license", r.get("license"))
                            r["doi"] = rel.get("doi", r.get("doi"))
                except _comses.ComsesError:
                    # Non-fatal — fall back to what get_codebase returned.
                    pass
    except _comses.ComsesError as e:
        raise ToolError(f"COMSES get_comses_model failed: {e}") from e

    return json.dumps(_compact_codebase_detail(data), indent=2)
