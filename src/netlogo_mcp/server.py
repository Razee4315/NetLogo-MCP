"""NetLogo MCP Server — entry point.

Stdout discipline
-----------------
The MCP stdio transport owns stdout for JSON-RPC framing. Two writers can
corrupt it:

1. Python code — pynetlogo ``print()``s Java stack traces to stdout whenever
   a NetLogo command/reporter/load fails.
2. The JVM itself — ``System.out`` writes to the OS-level file descriptor 1,
   bypassing Python's ``sys.stdout`` entirely.

``main()`` neutralizes both before serving: fd 1 is duplicated and kept
privately for the transport, then fd 1 is re-pointed at stderr so
native/JVM writes can never reach the protocol. ``sys.stdout`` is replaced
with a hybrid object — the transport binds to its ``.buffer`` (the private
protocol fd), while text-level ``write()`` calls (``print()``, pynetlogo
stack traces) are routed to stderr. This works regardless of whether the
transport binds before or after the lifespan runs (FastMCP 3 enters the
lifespan first; the plain MCP SDK binds the streams first).

JVM startup is lazy: the 30-60s JVM boot happens on the first tool call
that needs the workspace (open_model / create_model / open_comses_model),
on a worker thread via ``asyncio.to_thread`` so the event loop and MCP
heartbeats stay responsive. Set ``NETLOGO_EAGER_START=true`` to restore
the old start-at-launch behavior.
"""

import os
import sys

# ── Import-time guard: nothing may print to real stdout before main() ──
sys.stdout = sys.stderr

import asyncio
import logging
from collections.abc import AsyncIterator, Callable, Iterator
from contextlib import asynccontextmanager, contextmanager
from typing import Any, TypeVar

from fastmcp import FastMCP

from .config import (
    get_eager_start,
    get_gui_mode,
    get_jvm_path,
    get_netlogo_home,
    gui_unavailable_reason,
)

logger = logging.getLogger("netlogo_mcp")
T = TypeVar("T")

# Keeps the transport's private stdout alive (GC would close its fd).
_protocol_stdout: Any = None


@contextmanager
def protect_stdout() -> Iterator[None]:
    """Temporarily redirect stdout to stderr during JVM/NetLogo operations."""
    previous_stdout = sys.stdout
    sys.stdout = sys.stderr
    try:
        yield
    finally:
        sys.stdout = previous_stdout


def run_with_stdout_protection(
    func: Callable[..., T], /, *args: Any, **kwargs: Any
) -> T:
    """Run a callable while shielding MCP stdout from JVM output."""
    with protect_stdout():
        return func(*args, **kwargs)


def start_netlogo() -> tuple[Any, str | None]:
    """Start the JVM + NetLogo workspace. Blocking — run on a worker thread.

    Returns the live ``NetLogoLink`` and the detected NetLogo version string
    (e.g. ``"NetLogo 7.0.3"``), or ``None`` when the version probe fails.
    """
    nl_home = get_netlogo_home()
    jvm_path = get_jvm_path()
    gui = get_gui_mode()
    mode_str = "GUI (live window)" if gui else "headless"

    # If the user asked for a GUI but the platform can't deliver one, say so
    # plainly instead of silently falling back (pynetlogo forces headless on
    # macOS). Keeps the logs honest with what server_info reports.
    reason = gui_unavailable_reason()
    if reason is not None and os.environ.get("NETLOGO_GUI", "true").lower() not in (
        "false",
        "0",
        "no",
    ):
        logger.warning("GUI requested but unavailable — running headless. %s", reason)

    logger.info("Starting Java Virtual Machine...")
    logger.info(
        "Initializing NetLogo in %s mode (NETLOGO_HOME=%s)",
        mode_str,
        nl_home,
    )

    import pynetlogo

    nl = pynetlogo.NetLogoLink(
        netlogo_home=nl_home,
        gui=gui,
        thd=False,
        jvm_path=jvm_path,
    )
    logger.info("NetLogo workspace ready (%s) — all tools available", mode_str)

    # Capture the actual NetLogo version so generated .nlogox envelopes match
    # what's actually loaded. `netlogo-version` reports e.g. "NetLogo 7.0.3"
    # and works even before any model is loaded. Failure is non-fatal —
    # _wrap_nlogox falls back to a sensible default if the report is missing.
    netlogo_version: str | None = None
    try:
        raw = nl.report("netlogo-version")
        if isinstance(raw, str) and raw.strip():
            netlogo_version = raw.strip()
            logger.info("Detected %s", netlogo_version)
    except Exception:
        logger.debug("Could not read netlogo-version; falling back to default")

    return nl, netlogo_version


def shutdown_netlogo(lifespan_context: dict[str, Any]) -> None:
    """Close the shared NetLogo workspace if it was created."""
    nl = lifespan_context.pop("netlogo", None)
    if nl is None:
        return

    logger.info("Shutting down NetLogo workspace")
    try:
        run_with_stdout_protection(nl.kill_workspace)
    except Exception:
        logger.exception("Failed to shut down NetLogo workspace cleanly")


@asynccontextmanager
async def lifespan(server: FastMCP) -> AsyncIterator[dict]:
    """Prepare shared state. The JVM starts lazily on first workspace use.

    Must not touch ``sys.stdout`` — FastMCP 3 enters the lifespan *before*
    binding the stdio transport to ``sys.stdout.buffer``, so any swap here
    would route the JSON-RPC stream to the wrong place. Stdout discipline
    lives entirely in ``_bind_protocol_stdout`` (see main()).
    """
    state: dict[str, Any] = {
        # None until the first tool call that needs the workspace.
        "netlogo": None,
        "current_model_path": None,
        "netlogo_version": None,
        # Factory used by tools._ensure_netlogo for lazy startup.
        "start_netlogo": start_netlogo,
        # Single-flight lock: NetLogo's JVM workspace is shared mutable state,
        # so concurrent tool calls would race on ticks/agentsets/globals.
        # Every tool that touches the JVM must acquire this before dispatching.
        "workspace_lock": asyncio.Lock(),
    }

    if get_eager_start():
        # Opt-in legacy behavior: boot the JVM before serving requests.
        nl, version = await asyncio.to_thread(start_netlogo)
        state["netlogo"] = nl
        state["netlogo_version"] = version

    try:
        yield state
    finally:
        shutdown_netlogo(state)


mcp = FastMCP(
    "NetLogo MCP Server",
    instructions=(
        "This server lets you create, run, and analyze NetLogo agent-based "
        "models. Use open_model or create_model first, then command/report "
        "to interact. Consult netlogo://docs/primitives for syntax help."
        "\n\nNote: the first open_model/create_model call takes 30-60 "
        "seconds while the Java Virtual Machine starts. After that, tool "
        "calls are instant."
    ),
    lifespan=lifespan,
)

# ── Register tools, resources, and prompts ──
from . import prompts as _prompts  # noqa: E402, F401
from . import resources as _resources  # noqa: E402, F401
from . import tools as _tools  # noqa: E402, F401
from .market import tools as _market_tools  # noqa: E402, F401


class _HybridStdout:
    """``sys.stdout`` stand-in that keeps the protocol and prints apart.

    The MCP stdio transport binds to ``sys.stdout.buffer`` (binary). Python
    code — ``print()``, and pynetlogo's Java stack-trace prints on NetLogo
    errors — writes text via ``sys.stdout.write``. This object hands the
    transport the private protocol buffer while routing every text-level
    write to stderr, so no Python print can ever corrupt JSON-RPC framing.
    """

    encoding = "utf-8"

    def __init__(self, protocol_buffer: Any) -> None:
        self.buffer = protocol_buffer

    def write(self, s: str) -> int:
        return sys.stderr.write(s)

    def flush(self) -> None:
        sys.stderr.flush()

    def isatty(self) -> bool:
        return False

    def fileno(self) -> int:
        return int(self.buffer.fileno())


def _bind_protocol_stdout() -> None:
    """Give the MCP transport a private stdout; send fd 1 to stderr.

    The transport binds to ``sys.stdout.buffer`` when it starts, so we hand
    it a duplicate of the real stdout via ``_HybridStdout``. fd 1 itself is
    then re-pointed at stderr — the JVM writes to fd 1 directly (bypassing
    Python), and this is the only way to keep ``System.out`` chatter out of
    the JSON-RPC stream.
    """
    global _protocol_stdout
    try:
        protocol_fd = os.dup(1)
        os.dup2(2, 1)
    except OSError:
        # No usable stderr to redirect into (rare; e.g. detached console).
        # Fall back to handing the transport the original stdout object.
        sys.stdout = sys.__stdout__
        return
    _protocol_stdout = _HybridStdout(os.fdopen(protocol_fd, "wb"))
    sys.stdout = _protocol_stdout


def _bind_protocol_stdin() -> None:
    """Give the MCP transport a private stdin; point fd 0 at devnull.

    Critical Windows fix: the stdio transport keeps a *pending blocking
    read* on the stdin pipe from a worker thread. Windows serializes
    operations on a synchronous pipe's file object, so while that read is
    pending, even metadata probes (``GetFileType``) on the same pipe block.
    The JVM probes the standard handles during ``CreateJavaVM`` — with the
    protocol's pending read parked on fd 0, JVM startup deadlocks until the
    client happens to send a byte. Privatizing stdin (transport reads a
    duplicate handle; fd 0 / STD_INPUT_HANDLE point at devnull) keeps the
    JVM away from the pipe entirely.
    """
    import io

    try:
        stdin_fd = os.dup(0)
        devnull = os.open(os.devnull, os.O_RDONLY)
        os.dup2(devnull, 0)
        os.close(devnull)
    except OSError:
        return
    sys.stdin = io.TextIOWrapper(os.fdopen(stdin_fd, "rb"), encoding="utf-8")
    if sys.platform == "win32":
        import ctypes
        import msvcrt

        # Keep the Win32 std-handle table consistent with the CRT fds —
        # native code (the JVM) resolves GetStdHandle(), not Python objects.
        for std_const, fd in ((-10, 0), (-11, 1)):
            try:
                ctypes.windll.kernel32.SetStdHandle(std_const, msvcrt.get_osfhandle(fd))
            except OSError:
                pass


def main() -> None:
    """Console-script entry point (stdio transport)."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
        stream=sys.stderr,
    )
    _bind_protocol_stdout()
    _bind_protocol_stdin()
    mcp.run()


if __name__ == "__main__":
    main()
