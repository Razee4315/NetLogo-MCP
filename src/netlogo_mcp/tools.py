"""NetLogo MCP tools — interactive NetLogo control + CoMSES integration +
BehaviorSpace experiment runner."""

from __future__ import annotations

import asyncio
import json
import math
import re
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, TypeVar

if TYPE_CHECKING:
    from collections.abc import Callable

import numpy as np
import pandas as pd
from fastmcp import Context
from fastmcp.exceptions import ToolError
from fastmcp.utilities.types import Image

from . import bspace as _bspace
from . import comses as _comses
from .config import (
    get_comses_cache_dir,
    get_comses_max_download_mb,
    get_exports_dir,
    get_exports_max_files,
    get_gui_mode,
    get_models_dir,
    get_netlogo_home,
)
from .server import mcp

# NetLogo identifiers may contain letters, digits, and the punctuation
# characters NetLogo permits in variable / breed names: ``- _ . ? !``.
# We reject anything else to prevent command injection through `set_parameter`
# (the value is escaped, but the name is interpolated literally into a
# `set <name> <value>` command).
_NETLOGO_IDENTIFIER_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_\-.?!]*$")

# ── Helpers ──────────────────────────────────────────────────────────────────


def _lifespan(ctx: Context) -> dict[str, Any]:
    """Return the lifespan context dict (for `netlogo`, `current_model_path`)."""
    try:
        ls = ctx.request_context.lifespan_context  # type: ignore[union-attr]
    except AttributeError as exc:
        raise ToolError("NetLogo workspace is not initialized.") from exc
    if not isinstance(ls, dict):
        raise ToolError("NetLogo workspace is not initialized.")
    return ls


def _nl(ctx: Context):  # type: ignore[type-arg]
    """Get the shared NetLogoLink instance from the lifespan context.

    Raises if the JVM hasn't started yet — tools that may be the first to
    touch the workspace must use ``_ensure_netlogo`` instead.
    """
    try:
        nl = _lifespan(ctx)["netlogo"]
    except KeyError as exc:
        raise ToolError("NetLogo workspace is not initialized.") from exc
    if nl is None:
        raise ToolError(
            "NetLogo has not started yet. Use open_model or create_model "
            "first — the first call boots the JVM (30-60s)."
        )
    return nl


async def _ensure_netlogo(ctx: Context):  # type: ignore[type-arg]
    """Return the live NetLogoLink, booting the JVM on first use.

    Startup is serialized under the workspace lock and runs on a worker
    thread, so the event loop (and MCP heartbeats) stay responsive during
    the 30-60s JVM boot. Concurrent callers wait on the lock and reuse the
    workspace the winner created.
    """
    ls = _lifespan(ctx)
    nl = ls.get("netlogo")
    if nl is not None:
        return nl

    factory = ls.get("start_netlogo")
    if factory is None:
        raise ToolError("NetLogo workspace is not initialized.")

    async with _workspace_lock(ctx):
        nl = ls.get("netlogo")  # re-check: another call may have won the race
        if nl is not None:
            return nl
        try:
            nl, version = await asyncio.to_thread(factory)
        except Exception as e:
            raise ToolError(
                f"NetLogo failed to start: {e}\n\nCheck NETLOGO_HOME and "
                "JAVA_HOME, then try again."
            ) from e
        ls["netlogo"] = nl
        ls["netlogo_version"] = version
        return nl


def _set_current_model_path(ctx: Context, path: Path | str | None) -> None:
    """Record the path of the currently loaded model so later tools (like
    BehaviorSpace) can run against the same file the AI just loaded."""
    try:
        ls = _lifespan(ctx)
    except ToolError:
        return
    ls["current_model_path"] = str(path) if path is not None else None


def _current_model_path(ctx: Context) -> str | None:
    try:
        return _lifespan(ctx).get("current_model_path")
    except ToolError:
        return None


_NLOGOX_VERSION_FALLBACK = "NetLogo 7.0.3"


_T = TypeVar("_T")


class _NoopAsyncLock:
    """No-op stand-in used when a context has no workspace_lock (e.g. unit tests)."""

    async def __aenter__(self) -> _NoopAsyncLock:
        return self

    async def __aexit__(self, *exc_info: object) -> None:
        return None


_NOOP_LOCK = _NoopAsyncLock()


def _workspace_lock(ctx: Context):  # type: ignore[no-untyped-def]
    """Return the lifespan's workspace lock, or a no-op for test contexts."""
    try:
        ls = _lifespan(ctx)
    except ToolError:
        return _NOOP_LOCK
    lock = ls.get("workspace_lock")
    return lock if lock is not None else _NOOP_LOCK


def _prune_exports(dir_path: Path, *, glob: str) -> None:
    """Rotate the oldest export files out once the cap is hit.

    Looks only at files matching ``glob`` in ``dir_path`` (no recursion).
    Best-effort: any IO error is silently ignored — retention is a
    convenience, not a correctness property.
    """
    cap = get_exports_max_files()
    if cap <= 0:
        return
    try:
        files = sorted(dir_path.glob(glob), key=lambda p: p.stat().st_mtime)
    except OSError:
        return
    excess = len(files) - cap
    if excess <= 0:
        return
    for old in files[:excess]:
        try:
            old.unlink()
        except OSError:
            pass


def _check_restricted(netlogo_source: str) -> None:
    """Reject dangerous NetLogo primitives when NETLOGO_MCP_RESTRICTED=true.

    Filled in by the restricted-mode patch — kept as a no-op by default so
    the unrestricted product flow is unchanged. The check scans for primitive
    names that grant host I/O or shell escape (file-*, import-world, etc.).
    """
    import os as _os

    if _os.environ.get("NETLOGO_MCP_RESTRICTED", "").lower() not in (
        "true",
        "1",
        "yes",
    ):
        return
    # Tokenize once on whitespace + punctuation that NetLogo treats as
    # separators; match against an allowlist-by-negation list of bad prims.
    blocked = {
        "file-open",
        "file-close",
        "file-close-all",
        "file-delete",
        "file-write",
        "file-print",
        "file-read",
        "file-read-line",
        "file-read-characters",
        "file-at-end?",
        "file-flush",
        "file-show",
        "file-type",
        "import-world",
        "import-pcolors",
        "import-pcolors-rgb",
        "import-drawing",
        "export-world",
        "export-view",
        "export-interface",
        "export-output",
        "export-plot",
        "export-all-plots",
        "set-current-directory",
        "user-input",
        "user-yes-or-no?",
        "user-one-of",
        "user-message",
        "user-new-file",
        "user-file",
        "user-directory",
        # Common extension entry points that escape the sandbox.
        "sh:exec",
        "py:run",
        "py:runresult",
        "py:set",
        "web:get",
        "web:post",
    }
    tokens = re.findall(r"[A-Za-z0-9_\-?!:.]+", netlogo_source.lower())
    hits = [t for t in tokens if t in blocked]
    if hits:
        raise ToolError(
            "NETLOGO_MCP_RESTRICTED=true blocks dangerous NetLogo primitives: "
            f"{', '.join(sorted(set(hits)))}. Unset the env var or rewrite the "
            "command without those prims."
        )


async def _jvm_call(
    ctx: Context, fn: Callable[..., _T], *args: Any, **kwargs: Any
) -> _T:
    """Run a blocking JVM call under the workspace lock, off the event loop.

    Combines two concerns:
    - Workspace serialization: pynetlogo's NetLogoLink is a shared singleton;
      concurrent calls race on the workspace's mutable state. The lock keeps
      tool dispatch single-flight on the JVM.
    - Event loop responsiveness: NetLogo's JNI calls block the calling thread
      for the full duration (a 10k-tick run is seconds-to-minutes). Running
      them via ``asyncio.to_thread`` keeps the MCP heartbeat alive.
    """
    async with _workspace_lock(ctx):
        return await asyncio.to_thread(fn, *args, **kwargs)


def _nlogox_version(ctx: Context) -> str:
    """Return the NetLogo version string for embedding in a .nlogox envelope.

    Prefers the live workspace's ``netlogo-version`` (captured at lifespan
    start) so generated files match the actually-installed NetLogo. Falls
    back to a hardcoded recent version when the workspace state isn't
    populated (mostly: unit tests that build a context by hand).
    """
    try:
        v = _lifespan(ctx).get("netlogo_version")
    except ToolError:
        return _NLOGOX_VERSION_FALLBACK
    if isinstance(v, str) and v.strip():
        return v.strip()
    return _NLOGOX_VERSION_FALLBACK


def _require_model(ctx: Context):
    """Raise ToolError if no model is currently loaded.

    Fast path: trust ``current_model_path`` (set by our own open_model /
    create_model / open_comses_model). Avoids a JVM round-trip per tool call.
    Slow path (path unknown): probe with ``max-pxcor`` — it always works on a
    loaded model, even before reset-ticks. Necessary when the workspace was
    populated outside our tool surface (e.g. tests calling tools directly).
    """
    ls = _lifespan(ctx)
    if ls.get("netlogo") is None and "start_netlogo" in ls:
        # Lazy server, JVM not booted yet — by definition no model is loaded.
        raise ToolError("No model is loaded. Use open_model or create_model first.")
    nl = _nl(ctx)
    if _current_model_path(ctx) is not None:
        return nl
    try:
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


def _polish_gui_window(title: str) -> None:
    """Best-effort: title the NetLogo window and bring it to front.

    Posts the work to the Swing event thread via ``invokeLater``. Silently a
    no-op when headless (``App.app()`` is unset), when the JVM isn't up, or
    when NetLogo internals change — window polish must never fail a load.
    """
    try:
        import jpype

        if not jpype.isJVMStarted():
            return
        frame = jpype.JClass("org.nlogo.app.App").app().frame()

        def _apply() -> None:
            try:
                frame.setTitle(title)
                frame.toFront()
            except Exception:  # cosmetic only — never propagate
                pass

        runnable = jpype.JProxy("java.lang.Runnable", dict={"run": _apply})
        jpype.JClass("java.awt.EventQueue").invokeLater(runnable)
    except Exception:
        return


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
    if isinstance(value, np.integer):
        return int(value)
    if isinstance(value, np.floating):
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
    nl = await _ensure_netlogo(ctx)
    p = Path(path)
    if not p.is_absolute():
        p = get_models_dir() / p

    p = p.resolve()
    if not p.exists():
        raise ToolError(f"Model file not found: {p}")
    if p.suffix not in (".nlogo", ".nlogox"):
        raise ToolError(f"Not a .nlogo/.nlogox file: {p}")

    try:
        await _jvm_call(ctx, nl.load_model, str(p).replace("\\", "/"))
    except Exception as e:
        raise _wrap_netlogo_error(e) from e

    _set_current_model_path(ctx, p)
    _polish_gui_window(f"NetLogo — {p.stem}")
    return f"Model loaded: {p.name}"


@mcp.tool()
async def command(netlogo_command: str, ctx: Context) -> str:
    """Execute a NetLogo command (e.g. 'setup', 'go', 'create-turtles 10').

    Args:
        netlogo_command: The NetLogo command string to execute.
    """
    nl = _require_model(ctx)
    _check_restricted(netlogo_command)
    try:
        await _jvm_call(ctx, nl.command, netlogo_command)
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
        result = await _jvm_call(ctx, nl.report, reporter)
    except Exception as e:
        raise _wrap_netlogo_error(e) from e
    return json.dumps(_json_safe(result))


@mcp.tool()
async def run_simulation(
    ticks: int,
    reporters: list[str],
    ctx: Context,
    go_command: str = "go",
    summary_only: bool = False,
    max_rows: int = 0,
) -> str:
    """Run the simulation for N ticks and collect reporter data each tick.

    Args:
        ticks: Number of ticks to run (1-10000).
        reporters: List of NetLogo reporter expressions to collect each tick.
        go_command: The go command to use (default: "go").
        summary_only: If True, return only min/mean/max/std/final per
            reporter — much smaller than the full per-tick table. Use this
            when you don't need the time series, e.g. parameter sweeps that
            only care about the final state.
        max_rows: If > 0 and the run produces more rows than this, the
            output is decimated by evenly-spaced sampling (always keeps
            the final tick). Use to keep a long run's output below the
            client's context budget without losing the shape.

    Returns:
        A markdown table — full per-tick data by default, decimated if
        `max_rows` set, or a compact summary table if `summary_only=True`.
    """
    if ticks < 1 or ticks > 10000:
        raise ToolError("ticks must be between 1 and 10000.")
    if not reporters:
        raise ToolError("reporters list cannot be empty.")
    for i, r in enumerate(reporters):
        if not isinstance(r, str) or not r.strip():
            raise ToolError(f"reporters[{i}] must be a non-empty string (got {r!r}).")
    if max_rows < 0:
        raise ToolError("max_rows must be >= 0 (0 = no cap).")

    nl = _require_model(ctx)
    _check_restricted(go_command)

    try:
        results = await _jvm_call(
            ctx, nl.repeat_report, reporters, ticks, go=go_command
        )
    except Exception as e:
        raise _wrap_netlogo_error(e) from e

    if isinstance(results, pd.DataFrame):
        df = results
    else:
        df = pd.DataFrame({reporters[0]: results})

    if summary_only:
        return _summary_table(df)

    # Decimate if requested.
    if max_rows > 0 and len(df) > max_rows:
        df = _decimate_keep_last(df, max_rows)

    lines = ["| tick | " + " | ".join(df.columns) + " |"]
    lines.append("| --- | " + " | ".join(["---"] * len(df.columns)) + " |")
    for tick, row in df.iterrows():
        vals = " | ".join(str(_json_safe(v)) for v in row)
        lines.append(f"| {tick} | {vals} |")

    return "\n".join(lines)


@mcp.tool()
async def watch_simulation(
    ticks: int,
    ctx: Context,
    delay_ms: int = 150,
    go_command: str = "go",
) -> str:
    """Run the simulation SLOWLY so a human can watch it in the GUI window.

    Unlike run_simulation (full speed, returns data), this steps `go` once
    per tick with a pause between steps — use it for demos and teaching when
    the user wants to see the dynamics unfold live. In headless mode it
    works but there's nothing to watch; prefer run_simulation there.

    Args:
        ticks: Steps to run (1-2000).
        delay_ms: Pause between steps in milliseconds (10-2000, default 150).
            ticks x delay_ms must stay under 120 seconds — chain calls for
            longer demos.
        go_command: The command to run each step (default "go").
    """
    if not 1 <= ticks <= 2000:
        raise ToolError("ticks must be between 1 and 2000.")
    if not 10 <= delay_ms <= 2000:
        raise ToolError("delay_ms must be between 10 and 2000.")
    if ticks * delay_ms > 120_000:
        raise ToolError(
            f"ticks x delay_ms = {ticks * delay_ms}ms exceeds the 120s cap — "
            "lower one of them and chain calls for longer demos."
        )
    nl = _require_model(ctx)
    _check_restricted(go_command)

    for _ in range(ticks):
        try:
            await _jvm_call(ctx, nl.command, go_command)
        except Exception as e:
            raise _wrap_netlogo_error(e) from e
        await asyncio.sleep(delay_ms / 1000)

    return f"Watched {ticks} steps at {delay_ms}ms per step."


def _decimate_keep_last(df: pd.DataFrame, max_rows: int) -> pd.DataFrame:
    """Return at most `max_rows` evenly-spaced rows; always include the last."""
    if len(df) <= max_rows:
        return df
    step = max(1, len(df) // max_rows)
    sampled = df.iloc[::step]
    if df.index[-1] not in sampled.index:
        sampled = pd.concat([sampled, df.iloc[[-1]]])
    return sampled


def _summary_table(df: pd.DataFrame) -> str:
    """Compact min/mean/max/std/final markdown table for a per-tick DataFrame."""
    if df.empty:
        return "(no data — model produced 0 rows)"
    lines = ["| reporter | min | mean | max | std | final |"]
    lines.append("| --- | --- | --- | --- | --- | --- |")
    for col in df.columns:
        series = pd.to_numeric(df[col], errors="coerce")
        if series.notna().any():
            mn = float(series.min())
            mx = float(series.max())
            mean = float(series.mean())
            std = float(series.std(ddof=1)) if len(series.dropna()) > 1 else 0.0
            final = _json_safe(df[col].iloc[-1])
            lines.append(f"| {col} | {mn:g} | {mean:g} | {mx:g} | {std:g} | {final} |")
        else:
            # Non-numeric reporter — just show first/last
            lines.append(f"| {col} | — | — | — | — | {_json_safe(df[col].iloc[-1])} |")
    return "\n".join(lines)


@mcp.tool()
async def set_parameter(name: str, value: Any, ctx: Context) -> str:
    """Set a NetLogo global variable / slider / switch value.

    Args:
        name: Name of the global variable (e.g. 'initial-number-sheep').
              Must be a valid NetLogo identifier — letters, digits, and any
              of ``- _ . ? !`` only. Names with whitespace or shell/NetLogo
              meta-characters are rejected to prevent command injection.
        value: The value to set. Numbers, strings, booleans accepted.
    """
    if not isinstance(name, str) or not _NETLOGO_IDENTIFIER_RE.match(name):
        raise ToolError(
            f"Invalid parameter name: {name!r}. "
            "Must start with a letter and contain only letters, digits, "
            "or any of '-', '_', '.', '?', '!' (NetLogo's identifier rules)."
        )
    # Reject non-finite floats up front — NetLogo has no nan/inf literal and
    # would otherwise emit a cryptic "Nothing named NAN has been defined".
    if isinstance(value, float) and not math.isfinite(value):
        raise ToolError(
            f"value must be a finite number, got {value!r}. NetLogo has no "
            "nan/inf literal."
        )
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
        await _jvm_call(ctx, nl.command, f"set {name} {nl_val}")
    except Exception as e:
        raise _wrap_netlogo_error(e) from e
    return f"OK: {name} = {nl_val}"


@mcp.tool()
async def get_world_state(ctx: Context) -> str:
    """Get the current world state: tick count, agent counts, world dimensions.

    Returns JSON with ticks, turtle/patch/link counts, and world bounds.
    """
    nl = _require_model(ctx)

    def _collect_state() -> dict[str, Any]:
        # ticks returns -1 before reset-ticks is called; guard against errors
        try:
            ticks_val = _json_safe(nl.report("ticks"))
        except Exception:
            ticks_val = -1  # model loaded but setup not yet run
        return {
            "ticks": ticks_val,
            "turtle_count": _json_safe(nl.report("count turtles")),
            "patch_count": _json_safe(nl.report("count patches")),
            "link_count": _json_safe(nl.report("count links")),
            "min_pxcor": _json_safe(nl.report("min-pxcor")),
            "max_pxcor": _json_safe(nl.report("max-pxcor")),
            "min_pycor": _json_safe(nl.report("min-pycor")),
            "max_pycor": _json_safe(nl.report("max-pycor")),
        }

    try:
        # Batch the 8 reports into a single workspace-locked thread hop
        # instead of 8 separate JVM round-trips.
        state = await _jvm_call(ctx, _collect_state)
    except Exception as e:
        raise _wrap_netlogo_error(e) from e
    return json.dumps(state, indent=2)


@mcp.tool()
async def get_patch_data(
    attribute: str,
    ctx: Context,
    summary_only: bool = False,
    max_cells: int = 10000,
) -> str:
    """Get patch data as a 2D grid (useful for heatmaps / spatial analysis).

    Args:
        attribute: The patch variable to report (e.g. 'pcolor', 'grass').
        summary_only: If True, return shape + min/mean/max/std/unique-count
            instead of the full 2D grid. For a 100×100 world this trims
            ~10k cells of JSON to ~6 numbers — useful when you just want
            to know "is this attribute distributed widely?" without
            enumerating every patch.
        max_cells: Upper bound on the number of grid cells returned in
            full-grid mode. When the world exceeds the cap, rows and
            columns are evenly downsampled (nearest-neighbor) to fit;
            the response includes a ``downsampled_from`` field so the AI
            knows it's seeing a subsample. Default 10000 (≈ 100×100).
            Set to 0 to disable the cap (not recommended for large worlds).

    Returns:
        JSON 2D array (rows = y descending, cols = x ascending) by default,
        or a compact summary dict if `summary_only=True`. The full-grid
        response may include a ``_meta`` sibling describing downsampling.
    """
    if not isinstance(attribute, str) or not attribute.strip():
        raise ToolError("attribute must be a non-empty string.")
    if max_cells < 0:
        raise ToolError("max_cells must be >= 0 (0 = no cap).")
    nl = _require_model(ctx)
    try:
        data = await _jvm_call(ctx, nl.patch_report, attribute)
    except Exception as e:
        raise _wrap_netlogo_error(e) from e

    grid = data.values if isinstance(data, pd.DataFrame) else data

    if summary_only:
        flat = (
            pd.Series(grid.flatten()) if hasattr(grid, "flatten") else pd.Series(grid)
        )
        numeric = pd.to_numeric(flat, errors="coerce").dropna()
        rows = len(grid) if hasattr(grid, "__len__") else None
        cols = len(grid[0]) if rows and hasattr(grid[0], "__len__") else None
        summary: dict[str, Any] = {
            "attribute": attribute,
            "rows": rows,
            "cols": cols,
            "total_cells": int(len(flat)),
            "unique_values": int(flat.nunique()),
        }
        if not numeric.empty:
            summary.update(
                {
                    "min": float(numeric.min()),
                    "max": float(numeric.max()),
                    "mean": float(numeric.mean()),
                    "std": float(numeric.std(ddof=1)) if len(numeric) > 1 else 0.0,
                }
            )
        return json.dumps(summary, indent=2)

    grid_list = grid.tolist() if hasattr(grid, "tolist") else _json_safe(grid)

    # Downsample if the full grid would exceed max_cells. Nearest-neighbor
    # row/col slicing preserves the spatial structure well enough for the
    # AI to reason about heatmaps without blowing the context budget.
    if (
        max_cells > 0
        and isinstance(grid_list, list)
        and grid_list
        and isinstance(grid_list[0], list)
    ):
        rows = len(grid_list)
        cols = len(grid_list[0])
        total = rows * cols
        if total > max_cells:
            scale = (max_cells / total) ** 0.5
            new_rows = max(1, int(rows * scale))
            new_cols = max(1, int(cols * scale))
            row_step = max(1, rows // new_rows)
            col_step = max(1, cols // new_cols)
            sampled = [row[::col_step] for row in grid_list[::row_step]]
            return json.dumps(
                {
                    "grid": sampled,
                    "_meta": {
                        "downsampled_from": [rows, cols],
                        "returned_shape": [len(sampled), len(sampled[0])],
                        "max_cells": max_cells,
                        "note": (
                            "Grid was downsampled to stay under max_cells. "
                            "Use summary_only=True for stats only, or raise "
                            "max_cells to see more cells."
                        ),
                    },
                }
            )
    return json.dumps(grid_list)


# Default attributes returned by get_agent_sample when none are specified.
_DEFAULT_AGENT_ATTRS: tuple[str, ...] = ("who", "xcor", "ycor", "color", "heading")


@mcp.tool()
async def get_agent_sample(
    ctx: Context,
    breed: str | None = None,
    n: int = 10,
    attributes: list[str] | None = None,
) -> str:
    """Return a sample of agents with selected variables as a markdown table.

    Filling the gap between ``get_world_state`` (aggregates only) and
    hand-crafted ``report`` calls. Picks N random agents from the named
    breed (or all turtles when ``breed`` is None) and reports the requested
    per-agent attributes.

    Args:
        breed: Agentset name, e.g. ``"sheep"``, ``"wolves"``. ``None`` means
            ``turtles``. Must be a valid NetLogo identifier — letters,
            digits, ``-``, ``_``, ``.``, ``?``, ``!`` — same rule as
            ``set_parameter``.
        n: Number of agents to sample (1-200). When N exceeds the agentset
            size, every agent is returned.
        attributes: Per-agent variables to report. Each entry must also be a
            valid NetLogo identifier. Defaults to ``who``, ``xcor``, ``ycor``,
            ``color``, ``heading``.

    Returns:
        Markdown table with one row per sampled agent and one column per
        attribute. Empty agentsets return a one-line note.
    """
    if n < 1 or n > 200:
        raise ToolError("n must be between 1 and 200.")

    agentset = breed if breed is not None else "turtles"
    if not _NETLOGO_IDENTIFIER_RE.match(agentset):
        raise ToolError(
            f"Invalid breed name: {agentset!r}. Use a valid NetLogo identifier."
        )

    # `None` ⇒ defaults. Explicit empty list ⇒ user error (silent fallback to
    # defaults would mask a typo'd call).
    if attributes is None:
        attrs: tuple[str, ...] = _DEFAULT_AGENT_ATTRS
    else:
        if not attributes:
            raise ToolError("attributes list cannot be empty.")
        attrs = tuple(attributes)
    for a in attrs:
        if not isinstance(a, str) or not _NETLOGO_IDENTIFIER_RE.match(a):
            raise ToolError(
                f"Invalid attribute name: {a!r}. Use a valid NetLogo identifier."
            )

    nl = _require_model(ctx)
    # Build a single reporter that returns [count, [[v1,v2,...], ...]] so we
    # pay one JVM round-trip instead of one per attribute per agent.
    attr_list = " ".join(attrs)
    reporter = (
        f"(list (count {agentset}) "
        f"(map [a -> [(list {attr_list})] of a] "
        f"(n-of (min (list {n} (count {agentset}))) {agentset})))"
    )
    try:
        result = await _jvm_call(ctx, nl.report, reporter)
    except Exception as e:
        raise _wrap_netlogo_error(e) from e

    # NetLogo returns nested Java lists / numpy arrays; coerce to plain Python.
    safe = _json_safe(result)
    try:
        total = int(safe[0])
        rows = list(safe[1])
    except (IndexError, TypeError, ValueError):
        return f"(could not parse agent sample for `{agentset}`: {safe!r})"

    if total == 0:
        return f"(agentset `{agentset}` is empty)"

    lines = [
        "| " + " | ".join(attrs) + " |",
        "| " + " | ".join(["---"] * len(attrs)) + " |",
    ]
    for row in rows:
        # Each row may itself be a single-element list-of-lists from the
        # NetLogo `[(list ...)] of a` shape — flatten one level if needed.
        if isinstance(row, list) and len(row) == 1 and isinstance(row[0], list):
            row = row[0]
        if not isinstance(row, list):
            row = [row]
        cells = " | ".join(str(_json_safe(v)) for v in row)
        lines.append(f"| {cells} |")

    sampled = len(rows)
    if sampled < total:
        lines.append(f"\n_Sampled {sampled} of {total} `{agentset}`._")
    else:
        lines.append(f"\n_Showed all {total} `{agentset}`._")
    return "\n".join(lines)


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
        await _jvm_call(ctx, nl.command, f'export-view "{export_path}"')
    except Exception as e:
        raise _wrap_netlogo_error(e) from e

    _prune_exports(views_dir, glob="view_*.png")

    return Image(path=export_path)


def _validate_widgets_usage(code: str, widgets: list[dict[str, Any]] | None) -> bool:
    """Return True if code is a full .nlogox document (envelope not needed)."""
    is_xml = code.strip().startswith("<?xml") or "<model" in code[:200]
    if is_xml and widgets:
        raise ToolError(
            "widgets can only be used with raw procedure code — the full "
            ".nlogox XML you passed already contains a <widgets> section."
        )
    return is_xml


@mcp.tool()
async def create_model(
    code: str, ctx: Context, widgets: list[dict[str, Any]] | None = None
) -> str:
    """Create a new NetLogo model from code and load it.

    Args:
        code: NetLogo model code. Can be just the procedures (globals, breeds,
              setup, go, etc.) — the .nlogox envelope will be added automatically.
              Or provide a full .nlogox XML file.
        widgets: Optional interface widgets. Each item is an object:
            {"type": "slider", "variable": "num-sheep", "min": 0, "max": 250,
             "default": 100, "step": 1, "label"?, "units"?}
            {"type": "switch", "variable": "show-trails?", "default": false}
            {"type": "button", "code": "setup", "label"?, "forever"?: false}
            {"type": "monitor", "code": "count sheep", "label"?, "precision"?: 0}
            {"type": "plot", "label"?: "populations", "x_axis"?, "y_axis"?,
             "pens": [{"code": "plot count sheep", "label"?,
                       "color"?: "green", "mode"?: 0, "interval"?: 1}]}
            Plot pens redraw on every tick (and on update-plots). Pen colors:
            palette names (black/gray/white/red/orange/brown/yellow/green/
            lime/turquoise/cyan/sky/blue/violet/magenta/pink) or AWT ints.
            IMPORTANT: slider/switch widgets DEFINE their variable — do NOT
            also declare it in `globals [...]` or the model won't compile.
            Include setup/go buttons yourself when passing widgets. When
            omitted, Setup/Go buttons are auto-added for procedures that
            exist in the code.
    """
    is_xml = _validate_widgets_usage(code, widgets)
    nl = await _ensure_netlogo(ctx)

    # If user provided raw procedures (not XML), wrap in .nlogox envelope
    if not is_xml:
        code = _wrap_nlogox(code, _nlogox_version(ctx), widgets=widgets)

    # Write to models directory and load
    models_dir = get_models_dir()
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    model_path = models_dir / f"_created_{timestamp}.nlogox"
    model_path.write_text(code, encoding="utf-8")

    try:
        await _jvm_call(ctx, nl.load_model, str(model_path).replace("\\", "/"))
    except Exception as e:
        raise _wrap_netlogo_error(e) from e

    _set_current_model_path(ctx, model_path)
    _polish_gui_window(f"NetLogo — {model_path.stem}")
    return f"Model created and loaded: {model_path}"


def _replace_in_nlogox(
    path: Path, code: str, widgets: list[dict[str, Any]] | None
) -> str:
    """Rewrite the ``<code>`` (and optionally ``<widgets>``) of a .nlogox file.

    Everything else — info tab, shapes, existing widgets when ``widgets`` is
    None — is preserved, so iterating on procedures doesn't clobber an
    interface the user (or an earlier call) already set up.
    """
    import xml.etree.ElementTree as ET

    try:
        tree = ET.parse(path)
    except ET.ParseError as exc:
        raise ToolError(f"Could not parse {path.name} as .nlogox XML: {exc}") from exc
    root = tree.getroot()

    code_el = root.find("code")
    if code_el is None:
        code_el = ET.Element("code")
        root.insert(0, code_el)
    code_el.text = code

    if widgets is not None:
        new_widgets = ET.fromstring(
            f"<widgets>{_render_widgets(code, widgets)}</widgets>"
        )
        old_widgets = root.find("widgets")
        if old_widgets is not None:
            idx = list(root).index(old_widgets)
            root.remove(old_widgets)
            root.insert(idx, new_widgets)
        else:
            root.insert(1, new_widgets)

    body = ET.tostring(root, encoding="unicode")
    return f'<?xml version="1.0" encoding="utf-8"?>\n{body}\n'


@mcp.tool()
async def update_model(
    code: str, ctx: Context, widgets: list[dict[str, Any]] | None = None
) -> str:
    """Update the currently loaded model's code in place and reload it.

    Prefer this over create_model when iterating on an existing model: the
    same .nlogox file is rewritten and reloaded, so the NetLogo window stays
    on one model and the models directory doesn't grow a new file per
    iteration.

    Args:
        code: New NetLogo procedures — a FULL replacement of the code tab,
              not a diff. Raw procedures only (no .nlogox XML).
        widgets: Optional new interface widgets (same schema as
              create_model). When omitted, the model's existing widgets are
              preserved unchanged — sliders keep their positions and values.
    """
    current = _current_model_path(ctx)
    if current is None:
        raise ToolError("No model is loaded. Use create_model or open_model first.")
    path = Path(current)
    if path.suffix != ".nlogox":
        raise ToolError(
            f"update_model only supports .nlogox models; {path.name} is a "
            "legacy .nlogo file. Use create_model to make an editable copy."
        )
    if code.strip().startswith("<?xml") or "<model" in code[:200]:
        raise ToolError(
            "update_model takes raw NetLogo procedures, not a full .nlogox "
            "document — pass full XML to create_model instead."
        )

    nl = _nl(ctx)  # a model is loaded, so the JVM is already up

    new_xml = _replace_in_nlogox(path, code, widgets)
    path.write_text(new_xml, encoding="utf-8")

    try:
        await _jvm_call(ctx, nl.load_model, str(path).replace("\\", "/"))
    except Exception as e:
        raise _wrap_netlogo_error(e) from e

    _polish_gui_window(f"NetLogo — {path.stem}")
    kept = "existing widgets kept" if widgets is None else "widgets replaced"
    return f"Model updated and reloaded: {path.name} ({kept})"


# ── Widget generation ────────────────────────────────────────────────────────
# Widgets stack in a left column; the view sits to their right at x=210.
_WIDGET_X = 10
_WIDGET_WIDTH = 190
_WIDGET_GAP = 10
_WIDGET_HEIGHTS = {"button": 45, "slider": 50, "switch": 40, "monitor": 60, "plot": 160}

# AWT signed-int pen colors, mirroring NetLogo's swatch palette.
_PEN_COLORS = {
    "black": (0, 0, 0),
    "gray": (140, 140, 140),
    "white": (255, 255, 255),
    "red": (215, 50, 41),
    "orange": (241, 106, 14),
    "brown": (156, 109, 70),
    "yellow": (237, 237, 49),
    "green": (88, 176, 49),
    "lime": (0, 205, 101),
    "turquoise": (64, 224, 208),
    "cyan": (84, 196, 196),
    "sky": (47, 132, 220),
    "blue": (52, 93, 169),
    "violet": (143, 107, 177),
    "magenta": (217, 80, 152),
    "pink": (255, 167, 179),
}

# When pens don't specify a color, cycle through visually-distinct ones.
_DEFAULT_PEN_CYCLE = [
    "blue",
    "red",
    "green",
    "orange",
    "violet",
    "brown",
    "cyan",
    "magenta",
]


def _pen_color(value: Any, i: int, j: int) -> int:
    """Resolve a pen color (palette name or raw AWT int) to a signed int32."""
    if isinstance(value, bool):
        raise ToolError(f"widgets[{i}].pens[{j}]: 'color' must be a name or int.")
    if isinstance(value, int):
        if not -(1 << 31) <= value < (1 << 31):
            raise ToolError(
                f"widgets[{i}].pens[{j}]: color int {value} out of int32 range."
            )
        return value
    if isinstance(value, str) and value.lower() in _PEN_COLORS:
        r, g, b = _PEN_COLORS[value.lower()]
        return ((0xFF << 24) | (r << 16) | (g << 8) | b) - (1 << 32)
    raise ToolError(
        f"widgets[{i}].pens[{j}]: unknown color {value!r}. Use one of "
        f"{sorted(_PEN_COLORS)} or a raw AWT integer."
    )


# Widgets that would overflow this column height wrap to a new column.
_COLUMN_BUDGET = 450


def _view_xml(x: int) -> str:
    """The world view, placed to the right of the widget column(s)."""
    return (
        f'<view x="{x}" wrappingAllowedX="true" y="10" frameRate="30.0"'
        ' minPycor="-16" height="430" showTickCounter="true" patchSize="13.0"'
        ' fontSize="10" wrappingAllowedY="true" width="430"'
        ' tickCounterLabel="ticks" maxPycor="16" updateMode="1" maxPxcor="16"'
        ' minPxcor="-16"></view>'
    )


_VIEW_XML = _view_xml(210)


def _has_procedure(code: str, name: str) -> bool:
    """True if the code defines ``to <name>`` (whole-word, line-anchored)."""
    return re.search(rf"(?im)^\s*to\s+{re.escape(name)}(?=\s|$)", code) is not None


def _require_finite_number(spec: dict[str, Any], key: str, i: int) -> float:
    val = spec.get(key)
    if isinstance(val, bool) or not isinstance(val, int | float):
        raise ToolError(f"widgets[{i}]: {key!r} must be a number, got {val!r}.")
    if not math.isfinite(val):
        raise ToolError(f"widgets[{i}]: {key!r} must be finite, got {val!r}.")
    return float(val)


def _widget_spec_to_xml(
    spec: dict[str, Any], i: int, y: int, x: int = _WIDGET_X
) -> str:
    """Render one declarative widget spec to .nlogox XML (NetLogo 7 schema)."""
    import xml.sax.saxutils as saxutils

    if not isinstance(spec, dict):
        raise ToolError(f"widgets[{i}] must be an object, got {type(spec).__name__}.")
    wtype = spec.get("type")
    if wtype not in _WIDGET_HEIGHTS:
        raise ToolError(
            f"widgets[{i}]: type must be one of "
            f"{sorted(_WIDGET_HEIGHTS)}, got {wtype!r}."
        )
    w, h = _WIDGET_WIDTH, _WIDGET_HEIGHTS[wtype]

    if wtype in ("slider", "switch"):
        variable = spec.get("variable")
        if not isinstance(variable, str) or not _NETLOGO_IDENTIFIER_RE.match(variable):
            raise ToolError(
                f"widgets[{i}]: {wtype} needs a 'variable' that is a valid "
                f"NetLogo identifier, got {variable!r}."
            )
        var_attr = saxutils.quoteattr(variable)
        display_attr = saxutils.quoteattr(spec.get("label", variable))
        if wtype == "slider":
            lo = _require_finite_number(spec, "min", i)
            hi = _require_finite_number(spec, "max", i)
            if lo >= hi:
                raise ToolError(
                    f"widgets[{i}]: slider min ({lo}) must be < max ({hi})."
                )
            default = (
                _require_finite_number(spec, "default", i) if "default" in spec else lo
            )
            step = _require_finite_number(spec, "step", i) if "step" in spec else 1.0
            units = spec.get("units")
            units_attr = (
                f" units={saxutils.quoteattr(units)}"
                if isinstance(units, str) and units
                else ""
            )
            return (
                f'<slider x="{x}" y="{y}" width="{w}" height="{h}"'
                f" display={display_attr} variable={var_attr}"
                f' min="{lo}" max="{hi}" default="{default}" step="{step}"'
                f' direction="Horizontal"{units_attr}></slider>'
            )
        on = "true" if spec.get("default", False) else "false"
        return (
            f'<switch x="{x}" y="{y}" width="{w}" height="{h}"'
            f' on="{on}" variable={var_attr} display={display_attr}></switch>'
        )

    if wtype == "plot":
        pens = spec.get("pens")
        if not isinstance(pens, list) or not pens:
            raise ToolError(
                f"widgets[{i}]: plot needs a non-empty 'pens' list, e.g. "
                '[{"code": "plot count sheep", "color": "green"}].'
            )
        display_attr = saxutils.quoteattr(spec.get("label", "plot"))
        x_axis = saxutils.quoteattr(spec.get("x_axis", "time"))
        y_axis = saxutils.quoteattr(spec.get("y_axis", ""))
        pen_parts = []
        for j, pen in enumerate(pens):
            if not isinstance(pen, dict):
                raise ToolError(f"widgets[{i}].pens[{j}] must be an object.")
            pen_code = pen.get("code")
            if not isinstance(pen_code, str) or not pen_code.strip():
                raise ToolError(
                    f"widgets[{i}].pens[{j}]: each pen needs NetLogo 'code' "
                    '(e.g. "plot count sheep").'
                )
            mode = pen.get("mode", 0)
            if mode not in (0, 1, 2):
                raise ToolError(
                    f"widgets[{i}].pens[{j}]: mode must be 0 (line), 1 (bar), "
                    f"or 2 (point), got {mode!r}."
                )
            interval = (
                _require_finite_number(pen, "interval", i) if "interval" in pen else 1.0
            )
            color = _pen_color(
                pen.get("color", _DEFAULT_PEN_CYCLE[j % len(_DEFAULT_PEN_CYCLE)]),
                i,
                j,
            )
            pen_label = saxutils.quoteattr(pen.get("label", pen_code.strip()))
            pen_parts.append(
                f'<pen interval="{interval}" mode="{mode}" display={pen_label}'
                f' color="{color}" legend="true"><setup></setup>'
                f"<update>{saxutils.escape(pen_code.strip())}</update></pen>"
            )
        return (
            f'<plot x="{x}" y="{y}" width="{w}" height="{h}"'
            f" display={display_attr} xAxis={x_axis} yAxis={y_axis}"
            f' xMin="0.0" xMax="10.0" yMin="0.0" yMax="10.0"'
            f' autoPlotX="true" autoPlotY="true" legend="true">'
            f"<setup></setup><update></update>{''.join(pen_parts)}</plot>"
        )

    code = spec.get("code")
    if not isinstance(code, str) or not code.strip():
        raise ToolError(
            f"widgets[{i}]: {wtype} needs non-empty NetLogo 'code' (got {code!r})."
        )
    body = saxutils.escape(code.strip())
    display_attr = saxutils.quoteattr(spec.get("label", code.strip()))

    if wtype == "button":
        forever = "true" if spec.get("forever", False) else "false"
        return (
            f'<button x="{x}" y="{y}" width="{w}" height="{h}"'
            f' kind="Observer" forever="{forever}"'
            f' disableUntilTicks="false" display={display_attr}>{body}</button>'
        )

    precision = spec.get("precision", 2)
    if isinstance(precision, bool) or not isinstance(precision, int):
        raise ToolError(
            f"widgets[{i}]: monitor 'precision' must be an integer, got {precision!r}."
        )
    return (
        f'<monitor x="{x}" y="{y}" width="{w}" height="{h}" fontSize="11"'
        f' precision="{precision}" display={display_attr}>{body}</monitor>'
    )


def _render_widgets(procedures: str, widgets: list[dict[str, Any]] | None) -> str:
    """Render the <widgets> children: the view plus stacked widget columns.

    Widgets fill a column top-to-bottom; when one would overflow the column
    height budget it wraps to a new column, and the world view shifts right
    to sit beside the last column. With no explicit widget specs, Setup/Go
    buttons are emitted only when the code actually defines those
    procedures — a button pointing at a missing procedure makes the whole
    model fail to load.
    """
    column_pitch = _WIDGET_WIDTH + _WIDGET_GAP
    y = _WIDGET_X  # top margin matches the left margin

    if widgets is None:
        lines = []
        if _has_procedure(procedures, "setup"):
            lines.append(
                f'<button x="{_WIDGET_X}" y="{y}" width="{_WIDGET_WIDTH}"'
                ' height="45" kind="Observer" forever="false"'
                ' disableUntilTicks="false" display="Setup">setup</button>'
            )
            y += 45 + _WIDGET_GAP
        if _has_procedure(procedures, "go"):
            lines.append(
                f'<button x="{_WIDGET_X}" y="{y}" width="{_WIDGET_WIDTH}"'
                ' height="45" kind="Observer" forever="true"'
                ' disableUntilTicks="true" display="Go">go</button>'
            )
            y += 45 + _WIDGET_GAP
        lines.append(
            f'<monitor x="{_WIDGET_X}" y="{y}" width="{_WIDGET_WIDTH}"'
            ' height="45" fontSize="11" precision="0"'
            ' display="Time Steps">ticks</monitor>'
        )
        return "\n    ".join([_VIEW_XML, *lines])

    lines = []
    column = 0
    for i, spec in enumerate(widgets):
        wtype = spec.get("type") if isinstance(spec, dict) else None
        h = _WIDGET_HEIGHTS.get(wtype, 45)  # type: ignore[arg-type]
        if y > _WIDGET_X and y + h > _COLUMN_BUDGET:
            column += 1
            y = _WIDGET_X
        x = _WIDGET_X + column * column_pitch
        lines.append(_widget_spec_to_xml(spec, i, y, x=x))
        y += h + _WIDGET_GAP

    view_x = _WIDGET_X + (column + 1) * column_pitch
    return "\n    ".join([_view_xml(view_x), *lines])


def _wrap_nlogox(
    procedures: str,
    version: str = _NLOGOX_VERSION_FALLBACK,
    widgets: list[dict[str, Any]] | None = None,
) -> str:
    """Wrap raw NetLogo procedure code in a minimal .nlogox XML envelope.

    The ``version`` attribute is interpolated from the live workspace's
    ``netlogo-version`` when available so saved files don't lie about what
    NetLogo they were authored against. ``widgets`` (optional) replaces the
    default Setup/Go/ticks column with declaratively specified widgets.
    """
    # Escape XML special chars in the code and version for safe embedding
    import xml.sax.saxutils as saxutils

    escaped = saxutils.escape(procedures)
    version_attr = saxutils.quoteattr(version)
    widgets_block = _render_widgets(procedures, widgets)

    return f"""<?xml version="1.0" encoding="utf-8"?>
<model version={version_attr} snapToGrid="false">
  <code>{escaped}</code>
  <widgets>
    {widgets_block}
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
async def save_model(
    name: str, code: str, ctx: Context, widgets: list[dict[str, Any]] | None = None
) -> str:
    """Save NetLogo model code to a .nlogox file in the models directory.

    This saves the model so you can open it in the NetLogo desktop app
    for live visualization with GUI, sliders, and real-time animation.

    Args:
        name: Filename for the model (without extension).
        code: NetLogo model code (procedures only — envelope added automatically).
              Or provide a full .nlogox XML file.
        widgets: Optional interface widgets — same schema as create_model
            (slider/switch/button/monitor). Slider/switch widgets DEFINE
            their variable; don't also declare it in `globals [...]`.
    """
    if ".." in name or "/" in name or "\\" in name:
        raise ToolError("Invalid model name (no path separators allowed).")

    models_dir = get_models_dir()

    # Wrap in .nlogox envelope if raw procedures
    if not _validate_widgets_usage(code, widgets):
        code = _wrap_nlogox(code, _nlogox_version(ctx), widgets=widgets)

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
        await _jvm_call(ctx, nl.command, f'export-world "{export_path}"')
    except Exception as e:
        raise _wrap_netlogo_error(e) from e

    _prune_exports(worlds_dir, glob="world_*.csv")

    return f"World exported to {export_path}"


@mcp.tool()
async def close_model(ctx: Context) -> str:
    """Unload the currently loaded model and reset the workspace.

    Useful when you want to discard pending state (mid-run agents, set
    parameters, pending plots) and start fresh, or before opening a new
    model file from disk to make sure cached compilation state isn't carried
    forward.

    Note: this does NOT shut down the JVM or NetLogo workspace — only the
    model. The next `open_model` / `create_model` call will reuse the same
    JVM (no 30-60s warmup).
    """
    if _current_model_path(ctx) is None:
        raise ToolError("No model is currently loaded.")
    nl = _nl(ctx)
    try:
        # NetLogo doesn't expose an explicit "close model" primitive; the
        # closest stable equivalent is `clear-all`, which wipes turtles,
        # patches, ticks, plots, and globals. We then forget the path so
        # subsequent BehaviorSpace / world-state tools refuse to run until
        # a new model is loaded.
        await _jvm_call(ctx, nl.command, "clear-all")
    except Exception as e:
        raise _wrap_netlogo_error(e) from e
    _set_current_model_path(ctx, None)
    return "Model closed. World cleared. Open another model to continue."


@mcp.tool()
async def server_info(ctx: Context) -> str:
    """Return a snapshot of the running NetLogo MCP server's configuration.

    Useful as a no-cost health check for the AI / user — returns the server
    version, configured paths, GUI mode, currently-loaded model, and whether
    a NetLogo headless launcher is reachable for BehaviorSpace runs.

    No JVM round-trip; this is a pure config / filesystem inspection so it
    works even before the workspace is fully initialized.
    """
    from . import __version__

    try:
        jvm_started = _lifespan(ctx).get("netlogo") is not None
    except ToolError:
        jvm_started = False

    info: dict[str, Any] = {
        "server_version": __version__,
        "gui_mode": get_gui_mode(),
        "jvm_started": jvm_started,
        "models_dir": str(get_models_dir()),
        "exports_dir": str(get_exports_dir()),
        "comses_cache_dir": str(get_comses_cache_dir()),
        "comses_max_download_mb": get_comses_max_download_mb(),
        "current_model_path": _current_model_path(ctx),
    }
    try:
        info["netlogo_home"] = get_netlogo_home()
    except OSError as exc:
        info["netlogo_home"] = None
        info["netlogo_home_error"] = str(exc)

    if info.get("netlogo_home"):
        try:
            launcher = _bspace.locate_headless_launcher(info["netlogo_home"])
            info["headless_launcher"] = str(launcher)
        except _bspace.BSpaceError as exc:
            info["headless_launcher"] = None
            info["headless_launcher_error"] = str(exc)
    else:
        info["headless_launcher"] = None

    return json.dumps(info, indent=2)


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
    nl = await _ensure_netlogo(ctx)
    path_str = str(outcome.selected_netlogo_file.resolve()).replace("\\", "/")
    try:
        await _jvm_call(ctx, nl.load_model, path_str)
    except Exception as e:
        raise _wrap_netlogo_error(e) from e

    _set_current_model_path(ctx, outcome.selected_netlogo_file.resolve())
    _polish_gui_window(f"NetLogo — {outcome.selected_netlogo_file.stem}")
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
    # Never return the completion marker or our metadata sidecar.
    _internal_names = {_comses.COMPLETION_MARKER, _comses.METADATA_SIDECAR}
    all_files = [p for p in all_files if p.name not in _internal_names]

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


# ── BehaviorSpace ────────────────────────────────────────────────────────────
#
# Three tools — `list_experiments`, `preview_experiment`, `run_experiment` —
# that drive NetLogo's BehaviorSpace via the canonical headless launcher
# (`NetLogo_Console` / `netlogo-headless.bat`). The launcher runs in a
# separate JVM so the MCP server's interactive workspace stays untouched.
#
# Long-run handling: every run path enforces a `max_total_runs` ceiling and
# a wall-clock `timeout_seconds`. The launcher writes the table CSV
# incrementally, so timeouts preserve partial results.


def _resolve_model_path_for_bspace(ctx: Context, model_path: str | None) -> Path:
    """Return an existing on-disk model path for BehaviorSpace.

    Order of preference:
    1. Explicit `model_path` argument (resolved against the models dir if
       relative).
    2. The path of the model the AI most recently opened/created.
    """
    if model_path:
        p = Path(model_path)
        if not p.is_absolute():
            p = get_models_dir() / p
        p = p.resolve()
    else:
        current = _current_model_path(ctx)
        if not current:
            raise ToolError(
                "No model is loaded. Open a model first (open_model, "
                "create_model, or open_comses_model) — or pass model_path "
                "explicitly."
            )
        p = Path(current).resolve()
    if not p.exists():
        raise ToolError(f"Model file not found on disk: {p}")
    if p.suffix.lower() not in (".nlogo", ".nlogox", ".nlogox3d", ".nlogo3d"):
        raise ToolError(f"Not a NetLogo model file: {p}")
    return p


def _spec_from_inline_args(
    *,
    name: str,
    repetitions: int,
    time_limit: int,
    setup_commands: str,
    go_commands: str,
    stop_condition: str | None,
    metrics: list[str] | None,
    variables: list[dict] | None,
    run_metrics_every_step: bool,
    sequential_run_order: bool,
) -> _bspace.ExperimentSpec:
    if repetitions < 1:
        raise ToolError("repetitions must be >= 1")
    if time_limit < 0:
        raise ToolError("time_limit must be >= 0 (use 0 for no limit)")
    if not metrics:
        raise ToolError(
            "metrics is required — at least one reporter to collect each run."
        )
    parsed_vars: list[_bspace.ExperimentVariable] = []
    for raw in variables or []:
        if not isinstance(raw, dict):
            raise ToolError(f"variable entry is not an object: {raw!r}")
        try:
            parsed_vars.append(_bspace.variable_from_dict(raw))
        except _bspace.BSpaceError as e:
            raise ToolError(str(e)) from e
    return _bspace.ExperimentSpec(
        name=name or "mcp-experiment",
        repetitions=int(repetitions),
        time_limit=int(time_limit),
        setup_commands=setup_commands or "setup",
        go_commands=go_commands or "go",
        stop_condition=stop_condition or None,
        metrics=list(metrics),
        variables=parsed_vars,
        run_metrics_every_step=bool(run_metrics_every_step),
        sequential_run_order=bool(sequential_run_order),
    )


@mcp.tool()
async def list_experiments(ctx: Context, model_path: str | None = None) -> str:
    """List BehaviorSpace experiments saved inside a NetLogo model file.

    Reads the `<experiments>` section of a `.nlogox` (or `.nlogo`) without
    starting a JVM, so it's instant. By default it inspects the model the
    AI most recently loaded; pass `model_path` to inspect a specific file.

    Returns JSON: `{"model_path": ..., "experiments": [<spec>...]}` where
    each spec includes `name`, `repetitions`, `time_limit`,
    `setup_commands`, `go_commands`, `metrics`, `variables` (with
    `expanded_size` per variable), and `total_runs`. An empty list means
    the file has no saved experiments — you can still pass an inline
    spec to `run_experiment`.
    """
    p = _resolve_model_path_for_bspace(ctx, model_path)
    try:
        specs = _bspace.parse_experiments(p)
    except _bspace.BSpaceError as e:
        raise ToolError(str(e)) from e
    return json.dumps(
        {
            "model_path": str(p),
            "experiments": [_bspace.spec_to_dict(s) for s in specs],
        },
        indent=2,
    )


@mcp.tool()
async def preview_experiment(
    ctx: Context,
    experiment_name: str | None = None,
    metrics: list[str] | None = None,
    variables: list[dict] | None = None,
    repetitions: int = 1,
    time_limit: int = 1000,
    setup_commands: str = "setup",
    go_commands: str = "go",
    stop_condition: str | None = None,
    run_metrics_every_step: bool = True,
    sequential_run_order: bool = True,
    model_path: str | None = None,
) -> str:
    """Show the run plan for a BehaviorSpace experiment WITHOUT executing it.

    Use this before `run_experiment` to verify the parameter combinations,
    total runs, and rough time estimate. Two modes:

    - **By name:** pass `experiment_name` (must match a saved experiment in
      the model file). The other args are ignored.
    - **Inline:** omit `experiment_name` and pass `metrics` + (optionally)
      `variables`, `repetitions`, `time_limit`, `setup_commands`,
      `go_commands`, `stop_condition`.

    Returns JSON with the resolved spec, `total_runs`, and a coarse
    `estimated_seconds_lower_bound` derived from `time_limit × total_runs`
    assuming roughly 1k ticks/s per run (real models are usually slower).
    """
    p = _resolve_model_path_for_bspace(ctx, model_path)
    spec = await _resolve_spec(
        ctx,
        p,
        experiment_name=experiment_name,
        metrics=metrics,
        variables=variables,
        repetitions=repetitions,
        time_limit=time_limit,
        setup_commands=setup_commands,
        go_commands=go_commands,
        stop_condition=stop_condition,
        run_metrics_every_step=run_metrics_every_step,
        sequential_run_order=sequential_run_order,
    )
    total_runs = _bspace.count_runs(spec)
    # Very rough lower bound: assume ~1k ticks per second per run, single-thread.
    ticks_total = max(1, spec.time_limit) * total_runs
    estimate_seconds = ticks_total / 1000.0
    return json.dumps(
        {
            "model_path": str(p),
            "spec": _bspace.spec_to_dict(spec),
            "total_runs": total_runs,
            "estimated_seconds_lower_bound": round(estimate_seconds, 1),
            "note": (
                "Estimate assumes ~1000 ticks/s per run. Real models — "
                "especially those with many agents or complex updates — "
                "can be 10-100x slower. Use --threads in run_experiment "
                "to parallelise."
            ),
        },
        indent=2,
    )


async def _resolve_spec(
    ctx: Context,
    model_path: Path,
    *,
    experiment_name: str | None,
    metrics: list[str] | None,
    variables: list[dict] | None,
    repetitions: int,
    time_limit: int,
    setup_commands: str,
    go_commands: str,
    stop_condition: str | None,
    run_metrics_every_step: bool,
    sequential_run_order: bool,
) -> _bspace.ExperimentSpec:
    """Pick a saved experiment by name OR build one from inline args."""
    if experiment_name:
        try:
            specs = _bspace.parse_experiments(model_path)
        except _bspace.BSpaceError as e:
            raise ToolError(str(e)) from e
        match = next((s for s in specs if s.name == experiment_name), None)
        if match is None:
            names = [s.name for s in specs]
            raise ToolError(
                f"experiment {experiment_name!r} not found in {model_path.name}. "
                f"Available: {names or '(none defined)'}"
            )
        return match
    return _spec_from_inline_args(
        name="mcp-experiment",
        repetitions=repetitions,
        time_limit=time_limit,
        setup_commands=setup_commands,
        go_commands=go_commands,
        stop_condition=stop_condition,
        metrics=metrics,
        variables=variables,
        run_metrics_every_step=run_metrics_every_step,
        sequential_run_order=sequential_run_order,
    )


@mcp.tool()
async def run_experiment(
    ctx: Context,
    experiment_name: str | None = None,
    metrics: list[str] | None = None,
    variables: list[dict] | None = None,
    repetitions: int = 1,
    time_limit: int = 1000,
    setup_commands: str = "setup",
    go_commands: str = "go",
    stop_condition: str | None = None,
    run_metrics_every_step: bool = False,
    sequential_run_order: bool = True,
    threads: int = 0,
    max_total_runs: int = 200,
    timeout_seconds: int = 600,
    model_path: str | None = None,
    output_name: str | None = None,
) -> str:
    """Run a BehaviorSpace experiment headlessly and return summarized results.

    Two ways to specify the experiment:

    - **By name** — pass `experiment_name` matching a saved experiment in
      the loaded model (.nlogox `<experiments>` section). All other
      experiment-shape args are ignored.
    - **Inline** — omit `experiment_name`. Required: `metrics`. Optional:
      `variables` (list of `{"name", "values"}` or `{"name", "first",
      "step", "last"}`), `repetitions`, `time_limit`, `setup_commands`,
      `go_commands`, `stop_condition`.

    Variable shapes (Cartesian product of all expanded values is run for
    each repetition)::

        [{"name": "density", "values": [50, 60, 70]},
         {"name": "growth-rate", "first": 0.1, "step": 0.05, "last": 0.3}]

    Long-run controls:
        - `max_total_runs` — refuse to start if `total_runs` exceeds this.
        - `timeout_seconds` — kill the launcher after this many seconds.
          Partial results in the table CSV are preserved.
        - `threads` — parallel runs (0 = let NetLogo decide; default ~75% of CPUs).

    The launcher runs in a SEPARATE JVM, so the GUI workspace this server
    is hosting is unaffected. Run before calling this only matters insofar
    as the model file must be saved on disk (it is, after open_model /
    create_model / open_comses_model).

    Returns JSON with: `output_csv`, `runs`, `metrics_summary`,
    `per_combination`, `duration_seconds`, `command`, `timed_out`. The
    full per-tick data is in `output_csv` for offline analysis.
    """
    p = _resolve_model_path_for_bspace(ctx, model_path)
    spec = await _resolve_spec(
        ctx,
        p,
        experiment_name=experiment_name,
        metrics=metrics,
        variables=variables,
        repetitions=repetitions,
        time_limit=time_limit,
        setup_commands=setup_commands,
        go_commands=go_commands,
        stop_condition=stop_condition,
        run_metrics_every_step=run_metrics_every_step,
        sequential_run_order=sequential_run_order,
    )

    total_runs = _bspace.count_runs(spec)
    if total_runs > max_total_runs:
        raise ToolError(
            f"This experiment would launch {total_runs} runs, which exceeds "
            f"max_total_runs={max_total_runs}. Either narrow the parameter "
            "ranges, lower repetitions, or raise max_total_runs explicitly. "
            "Tip: run preview_experiment first."
        )
    if timeout_seconds < 1:
        raise ToolError("timeout_seconds must be >= 1")

    # Build the setup-file XML and locate the launcher.
    try:
        launcher = _bspace.locate_headless_launcher(get_netlogo_home())
    except _bspace.BSpaceError as e:
        raise ToolError(
            f"Could not find NetLogo headless launcher: {e}. "
            "Verify NETLOGO_HOME points at a NetLogo install dir "
            "containing NetLogo_Console / netlogo-headless."
        ) from e

    runs_dir = get_exports_dir() / "experiments"
    runs_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    base = _bspace.safe_output_name(output_name or spec.name)
    setup_file = runs_dir / f"{base}_{timestamp}.setup.xml"
    table_csv = runs_dir / f"{base}_{timestamp}.table.csv"
    setup_file.write_text(_bspace.build_setup_file_xml(spec), encoding="utf-8")

    is_3d = p.suffix.lower() in (".nlogox3d", ".nlogo3d")

    try:
        outcome = _bspace.run_headless(
            launcher=launcher,
            model_path=p,
            table_csv=table_csv,
            setup_file=setup_file,
            experiment_name=spec.name,
            threads=(threads if threads and threads > 0 else None),
            is_3d=is_3d,
            timeout_seconds=int(timeout_seconds),
        )
    except _bspace.BSpaceError as e:
        raise ToolError(str(e)) from e

    payload: dict[str, Any] = {
        "model_path": str(p),
        "spec": _bspace.spec_to_dict(spec),
        "setup_file": str(setup_file),
        "output_csv": str(table_csv),
        "command": outcome.command,
        "duration_seconds": round(outcome.duration_seconds, 2),
        "timed_out": outcome.timed_out,
        "rows_returned": outcome.rows_returned,
        "return_code": outcome.return_code,
    }

    if not outcome.success:
        payload["status"] = "failed" if not outcome.timed_out else "timed_out"
        payload["stderr_tail"] = outcome.stderr_tail
        payload["message"] = (
            "BehaviorSpace did not complete cleanly. "
            "Inspect stderr_tail for clues; partial CSV at output_csv."
        )
        return json.dumps(payload, indent=2)

    # Parse the table and summarize.
    try:
        df = _bspace.parse_table_csv(table_csv)
    except _bspace.BSpaceError as e:
        payload["status"] = "parse_error"
        payload["message"] = str(e)
        return json.dumps(payload, indent=2)

    summary = _bspace.summarize_results(df, spec)
    payload["status"] = "ok"
    payload["runs"] = summary["runs"]
    payload["total_rows"] = summary["total_rows"]
    payload["metrics_summary"] = summary["metrics_summary"]
    payload["per_combination"] = summary["per_combination"]
    payload["message"] = (
        f"Completed {summary['runs']} runs in "
        f"{round(outcome.duration_seconds, 1)}s. "
        f"Full per-tick data in {table_csv.name}."
    )
    return json.dumps(payload, indent=2)
