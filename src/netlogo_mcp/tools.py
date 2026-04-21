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
from .config import (
    get_comses_cache_dir,
    get_comses_max_download_mb,
    get_exports_dir,
    get_models_dir,
)
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

    # Language: search results don't include releaseLanguages, so we fall back
    # to a text heuristic over title + description + tags. This is surfaced as
    # a hint only — the authoritative language lives on get_comses_model.
    language = _language_from_releases(entry.get("releases") or [])
    if not language:
        language = _language_hint_from_text(entry)

    return {
        "identifier": entry.get("identifier"),
        "title": entry.get("title"),
        "description": (
            entry.get("summarizedDescription") or entry.get("description") or ""
        )[:500],
        "authors": authors,
        "latestVersion": entry.get("latestVersionNumber"),
        "tags": [
            t.get("name") if isinstance(t, dict) else t for t in entry.get("tags") or []
        ],
        "language": language,
        "isPeerReviewed": entry.get("peerReviewed", False),
        "downloads": entry.get("downloadCount", 0),
        "doi": entry.get("doi"),
        "live": entry.get("live"),
    }


def _language_from_releases(releases: list) -> str | None:
    """Pick a language name from a release detail, if the field is populated.

    Real COMSES search results do NOT include `releaseLanguages` on nested
    releases — that data is only on `/releases/{version}/?format=json`.
    This helper still handles the full shape for detail responses and
    mocked tests; callers that only have search results should also try
    `_language_hint_from_text`.
    """
    if not releases:
        return None
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
    tags = (target or {}).get("programmingLanguageTags") or []
    if tags:
        first = tags[0]
        return first.get("name") if isinstance(first, dict) else str(first)
    return None


# Keyword → display name, scanned case-insensitively against title /
# description / tags. Keep multi-word and ambiguous keywords out of this
# list so we don't mis-tag ecology models as "R".
_LANGUAGE_TEXT_HINTS: tuple[tuple[str, str], ...] = (
    ("netlogo", "NetLogo"),
    ("mesa", "Python"),
    ("repast", "Repast"),
    ("python", "Python"),
    ("julia", "Julia"),
    ("matlab", "MATLAB"),
    ("gama platform", "GAMA"),
    ("gama-platform", "GAMA"),
)


def _language_hint_from_text(entry: dict) -> str | None:
    """Cheap heuristic: scan title + description + tags for a known language."""
    parts: list[str] = [
        str(entry.get("title") or ""),
        str(entry.get("summarizedDescription") or ""),
        str(entry.get("description") or ""),
    ]
    for t in entry.get("tags") or []:
        parts.append(str(t.get("name") if isinstance(t, dict) else t))
    haystack = " ".join(parts).lower()
    for needle, label in _LANGUAGE_TEXT_HINTS:
        if needle in haystack:
            return label
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


def _outcome_to_payload(outcome: _comses.DownloadOutcome) -> dict:
    """Shape a DownloadOutcome into the JSON the MCP tool returns."""
    extracted = outcome.extracted_path
    rel = lambda p: p.relative_to(extracted).as_posix() if p else None  # noqa: E731
    return {
        "identifier": outcome.identifier,
        "resolved_version": outcome.resolved_version,
        "extracted_path": str(extracted).replace("\\", "/"),
        "cached": outcome.cached,
        "language": outcome.language,
        "title": outcome.title,
        "license": outcome.license_name,
        "all_netlogo_files": [rel(p) for p in outcome.netlogo_files],
        "loaded_netlogo_file": rel(outcome.selected_netlogo_file),
        "code_files": [rel(p) for p in outcome.code_files],
        "odd_doc": rel(outcome.odd_doc),
        # Non-text ODD (PDF/DOCX) — read_comses_files cannot read it, but
        # the AI should surface the path so the user can open it manually.
        "odd_doc_binary": rel(outcome.odd_doc_binary),
    }


@mcp.tool()
async def download_comses_model(
    ctx: Context,
    identifier: str,
    version: str = "latest",
    max_mb: float = 0.0,
) -> str:
    """Download and safely extract a COMSES model archive.

    Standalone "fetch but don't open" tool. Most AI flows should use
    `open_comses_model` instead — it subsumes this tool and also loads
    NetLogo models into the workspace.

    Safety guarantees:
    - `version="latest"` is resolved to a concrete version BEFORE any cache
      path is computed. Cache dirs are named by the resolved version.
    - HEAD request screens oversize archives before streaming.
    - Stream enforces the byte cap mid-download; overruns abort and delete
      the partial file.
    - Zip members are validated against path traversal before extraction.
    - Uncompressed total is checked against 2 × cap to reject zip bombs.
    - Extract happens in a temp directory; only a successful extract is
      moved atomically into the cache. A `.comses_complete` marker is
      written on success; future calls only trust cached dirs with the marker.

    Args:
        identifier: Full model UUID (from `search_comses`).
        version: Version string (e.g. "1.2.0") or "latest".
        max_mb: Size cap in MB. Pass 0 or omit to use
            the `COMSES_MAX_DOWNLOAD_MB` env var (default 50 MB).

    Returns JSON with: `identifier`, `resolved_version`, `extracted_path`,
    `cached`, `language`, `title`, `license`, `all_netlogo_files`,
    `loaded_netlogo_file` (deterministic pick per plan Section 4.4),
    `code_files`, and `odd_doc`.
    """
    if not identifier:
        raise ToolError("identifier is required")
    cap_mb = max_mb if max_mb and max_mb > 0 else get_comses_max_download_mb()
    max_bytes = int(cap_mb * 1024 * 1024)
    cache_root = get_comses_cache_dir()
    try:
        async with _comses.ComsesClient() as client:
            outcome = await _comses.download_release(
                client,
                identifier,
                version,
                cache_root=cache_root,
                max_bytes=max_bytes,
            )
    except _comses.ComsesSafetyError as e:
        raise ToolError(f"COMSES archive rejected for safety reasons: {e}") from e
    except _comses.ComsesError as e:
        raise ToolError(f"COMSES download failed: {e}") from e

    return json.dumps(_outcome_to_payload(outcome), indent=2)


@mcp.tool()
async def open_comses_model(
    ctx: Context,
    identifier: str,
    version: str = "latest",
    max_mb: float = 0.0,
) -> str:
    """Download (or reuse cache), then open a COMSES model ready to use.

    This is the **single entry point** most AI flows should call.

    Behavior:
    - Resolves `"latest"` to a concrete version BEFORE any cache path is
      computed. The returned `resolved_version` is what every follow-up
      `read_comses_files` call MUST pass — never re-pass `"latest"` in the
      same flow, or you risk inspecting a different cache slot than the
      model you just loaded.
    - If the cache for `(identifier, resolved_version)` is already complete
      (has `.comses_complete`), skips download.
    - Otherwise, downloads + extracts safely (same logic as
      `download_comses_model`).
    - If the model is NetLogo, picks one `.nlogo` / `.nlogox` per Section
      4.4 rules (exactly one → use it; else prefer `code/`; else prefer
      `.nlogox`; else lex-largest relative path — a deterministic
      tie-breaker, NOT semver-aware).
    - If NetLogo, loads it into the workspace.
    - If not NetLogo, returns structured info for manual follow-up.

    Returns JSON with:
    - `status`: "loaded_netlogo", "not_runnable_in_netlogo", or "no_netlogo_file".
    - `resolved_version`: concrete version string (never "latest").
    - `identifier`, `title`, `language`, `license`, `cached`.
    - `extracted_path`: absolute path to cached model directory.
    - `all_netlogo_files`: list of every NetLogo file found.
    - `loaded_netlogo_file`: the one selected (if any).
    - `code_files`: source files by extension.
    - `odd_doc`: ODD / README path, if any.
    - `message`: short text for the AI to show the user.

    Args:
        identifier: Full model UUID.
        version: Version string or "latest".
        max_mb: Max download size in MB. Pass 0 or omit to use the env default.
    """
    if not identifier:
        raise ToolError("identifier is required")
    cap_mb = max_mb if max_mb and max_mb > 0 else get_comses_max_download_mb()
    max_bytes = int(cap_mb * 1024 * 1024)
    cache_root = get_comses_cache_dir()
    try:
        async with _comses.ComsesClient() as client:
            outcome = await _comses.download_release(
                client,
                identifier,
                version,
                cache_root=cache_root,
                max_bytes=max_bytes,
            )
    except _comses.ComsesSafetyError as e:
        raise ToolError(f"COMSES archive rejected for safety reasons: {e}") from e
    except _comses.ComsesError as e:
        raise ToolError(f"COMSES open failed: {e}") from e

    payload = _outcome_to_payload(outcome)
    language = outcome.language or ""
    is_netlogo = language.lower() == "netlogo" or bool(outcome.selected_netlogo_file)

    if not is_netlogo:
        payload["status"] = "not_runnable_in_netlogo"
        payload["message"] = (
            f"This model is in {language or 'a non-NetLogo language'}, "
            "not NetLogo. The source is saved locally at extracted_path. "
            "Use read_comses_files to inspect it. Translating it to NetLogo "
            "is possible but not automatic — ask explicitly if that's what "
            "you want."
        )
        return json.dumps(payload, indent=2)

    if outcome.selected_netlogo_file is None:
        payload["status"] = "no_netlogo_file"
        payload["message"] = (
            "Language looks like NetLogo but no .nlogo / .nlogox file was "
            "found in the archive. Use read_comses_files to investigate."
        )
        return json.dumps(payload, indent=2)

    # Load into the NetLogo workspace using the forward-slash path form that
    # pynetlogo expects on Windows.
    nl = _nl(ctx)
    path_str = str(outcome.selected_netlogo_file.resolve()).replace("\\", "/")
    try:
        nl.load_model(path_str)
    except Exception as e:
        raise _wrap_netlogo_error(e) from e

    payload["status"] = "loaded_netlogo"
    payload["message"] = (
        f"Loaded NetLogo model: {outcome.selected_netlogo_file.name} "
        f"({'cached' if outcome.cached else 'downloaded'}). "
        f"Pin resolved_version={outcome.resolved_version!r} for any "
        "follow-up read_comses_files calls."
    )
    return json.dumps(payload, indent=2)


# ── read_comses_files ────────────────────────────────────────────────────────


_READ_DEFAULT_EXTS = (
    ".nlogo",
    ".nlogox",
    ".py",
    ".r",
    ".R",
    ".java",
    ".jl",
    ".md",
    ".txt",
)


def _priority_rank(rel_path: str) -> int:
    """Plan Section 4.5 priority ordering. Lower = read earlier."""
    name = rel_path.lower()
    # 1) ODD docs under docs/ or root README
    if name.startswith("docs/odd") or "/odd" in name or name.startswith("odd"):
        return 0
    if name.startswith("docs/documentation") or name.startswith("documentation"):
        return 0
    if name.startswith("docs/readme") or name.startswith("readme"):
        return 1
    # 2) NetLogo source
    if name.endswith(".nlogo") or name.endswith(".nlogox"):
        return 2
    # 3) Other code by extension
    if name.endswith((".py", ".r", ".java", ".jl")):
        return 3
    # 4) Other .md / .txt outside docs/
    if name.endswith((".md", ".txt")) and not name.startswith("docs/"):
        return 4
    return 5


@mcp.tool()
async def read_comses_files(
    ctx: Context,
    identifier: str,
    version: str = "latest",
    extensions: list[str] | None = None,
    max_total_bytes: int = 50_000,
) -> str:
    """Return text contents of source and documentation files from a
    downloaded COMSES model.

    The model MUST already be downloaded by `open_comses_model` or
    `download_comses_model`. If the cache is absent, this tool returns an
    error telling the AI to call one of those first.

    The AI should pass the `resolved_version` it captured from
    `open_comses_model` — not the literal string `"latest"` — or it risks
    inspecting a different cache slot than the model it just loaded.
    When `version="latest"` is passed, this tool calls the COMSES API to
    resolve it (so it works standalone) and surfaces the concrete version
    in the `resolved_version` field of the response.

    Behavior:
    - Files are UTF-8 decoded with `errors="replace"` so binary junk never
      aborts the call. Every file that matches `extensions` is returned as
      a string (may contain replacement characters for non-text bytes).
    - Files are included in priority order: ODD docs → NetLogo source →
      other code → other .md/.txt → everything else matching extensions.
    - Total body is capped at `max_total_bytes` (default 50 KB — sized to
      fit in a single conversational-LLM tool response). When the cap is
      hit mid-file, that file is truncated at a line boundary; subsequent
      files are listed in `omitted_files` with reason `byte_cap_reached`.
      For larger pulls, pass a higher value explicitly.
    - Files matching no `extensions` filter are listed in `omitted_files`
      with reason `extension_not_in_filter`.

    Args:
        identifier: Full model UUID.
        version: Concrete version (preferred) or "latest". Always surfaced
            back in `resolved_version`.
        extensions: List of file suffixes (with dot) to include. Defaults
            to NetLogo + common ABM languages + .md + .txt.
        max_total_bytes: Cap on total returned content.

    Returns JSON with:
      - `resolved_version`
      - `files`: {relpath: {content, full_size, returned_size, truncated}}
      - `omitted_files`: [relpath, ...]
      - `omitted_reason_by_file`: {relpath: reason}
      - `total_returned_bytes`
      - `any_truncated`
    """
    if not identifier:
        raise ToolError("identifier is required")
    exts = tuple(extensions or _READ_DEFAULT_EXTS)
    cache_root = get_comses_cache_dir()

    # Resolve version (may hit network only if "latest" was passed).
    try:
        async with _comses.ComsesClient() as client:
            resolved = await client.resolve_latest(identifier, version)
    except _comses.ComsesError as e:
        raise ToolError(f"Could not resolve version {version!r}: {e}") from e

    cache_dir = cache_root / identifier / resolved
    if not _comses.is_cache_trusted(cache_dir):
        raise ToolError(
            f"Cache for {identifier} version {resolved} is missing or "
            "incomplete. Call open_comses_model or download_comses_model first."
        )

    # Collect every candidate file with its priority + path.
    all_files: list[Path] = [p for p in cache_dir.rglob("*") if p.is_file()]
    # Never return the completion marker.
    all_files = [p for p in all_files if p.name != _comses.COMPLETION_MARKER]

    selected: list[tuple[int, str, Path]] = []
    omitted: dict[str, str] = {}
    for p in all_files:
        rel = p.relative_to(cache_dir).as_posix()
        if p.suffix not in exts:
            omitted[rel] = "extension_not_in_filter"
            continue
        selected.append((_priority_rank(rel), rel, p))
    selected.sort(key=lambda tup: (tup[0], tup[1]))

    files_out: dict[str, dict[str, object]] = {}
    remaining = max_total_bytes
    any_truncated = False
    total_returned = 0

    for _, rel, path in selected:
        raw = path.read_bytes()
        full_size = len(raw)
        text = raw.decode("utf-8", errors="replace")

        if remaining <= 0:
            omitted[rel] = "byte_cap_reached"
            continue

        if full_size <= remaining:
            files_out[rel] = {
                "content": text,
                "full_size": full_size,
                "returned_size": full_size,
                "truncated": False,
            }
            remaining -= full_size
            total_returned += full_size
            continue

        # Truncate to a line boundary within `remaining` bytes.
        cut_bytes = raw[:remaining]
        last_nl = cut_bytes.rfind(b"\n")
        if last_nl >= 0:
            cut_bytes = cut_bytes[: last_nl + 1]
        cut_text = cut_bytes.decode("utf-8", errors="replace")
        returned_size = len(cut_bytes)
        files_out[rel] = {
            "content": cut_text,
            "full_size": full_size,
            "returned_size": returned_size,
            "truncated": True,
        }
        any_truncated = True
        total_returned += returned_size
        remaining = 0

    return json.dumps(
        {
            "resolved_version": resolved,
            "files": files_out,
            "omitted_files": sorted(omitted.keys()),
            "omitted_reason_by_file": omitted,
            "total_returned_bytes": total_returned,
            "any_truncated": any_truncated,
        },
        indent=2,
    )
