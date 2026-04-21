"""NetLogo MCP Server — entry point.

CRITICAL: stdout is redirected to stderr *before* any JVM-touching import.
MCP stdio transport uses stdout for JSON-RPC messages; JPype/JVM writes to
stdout by default, which would corrupt the protocol.
"""

import sys

# ── Stdout protection — must happen before ANY JVM-related import ──
_real_stdout = sys.stdout
sys.stdout = sys.stderr

import logging
from collections.abc import AsyncIterator, Callable, Iterator
from contextlib import asynccontextmanager, contextmanager
from threading import RLock
from typing import Any, TypeVar

from fastmcp import FastMCP

from .config import get_gui_mode, get_jvm_path, get_netlogo_home

logger = logging.getLogger("netlogo_mcp")
_workspace_lock = RLock()
T = TypeVar("T")


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


@contextmanager
def workspace_locked() -> Iterator[None]:
    """Serialize access to the shared NetLogo workspace."""
    with _workspace_lock:
        yield


def get_or_create_netlogo(lifespan_context: dict[str, Any]) -> Any:
    """Create the shared NetLogo workspace on first use, then reuse it.

    Lazy init: the JVM starts on the first tool call (30-60s), but
    this ensures it runs on the correct thread with the right Java
    class loader context. All subsequent calls are instant.
    """
    existing = lifespan_context.get("netlogo")
    if existing is not None:
        return existing

    with _workspace_lock:
        existing = lifespan_context.get("netlogo")
        if existing is not None:
            return existing

        with protect_stdout():
            import pynetlogo

            nl_home = get_netlogo_home()
            jvm_path = get_jvm_path()
            gui = get_gui_mode()
            mode_str = "GUI (live window)" if gui else "headless"

            logger.info("Starting Java Virtual Machine...")
            logger.info(
                "Initializing NetLogo in %s mode (NETLOGO_HOME=%s)",
                mode_str,
                nl_home,
            )

            nl = pynetlogo.NetLogoLink(
                netlogo_home=nl_home,
                gui=gui,
                thd=False,  # JPype handles Swing EDT; thd=True hangs on Windows
                jvm_path=jvm_path,
            )

        lifespan_context["netlogo"] = nl
        logger.info("NetLogo workspace ready (%s) — all tools available", mode_str)
        return nl


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
    """Start NetLogo eagerly, before accepting MCP requests.

    The JVM starts here (30-60s) so it doesn't block the asyncio
    event loop during tool calls. This matches the working gui branch.
    """
    nl_home = get_netlogo_home()
    jvm_path = get_jvm_path()
    gui = get_gui_mode()
    mode_str = "GUI (live window)" if gui else "headless"

    logger.info("Starting Java Virtual Machine...")
    logger.info(
        "Initializing NetLogo in %s mode (NETLOGO_HOME=%s)",
        mode_str,
        nl_home,
    )

    with protect_stdout():
        import pynetlogo

        nl = pynetlogo.NetLogoLink(
            netlogo_home=nl_home,
            gui=gui,
            thd=False,
            jvm_path=jvm_path,
        )
    logger.info("NetLogo workspace ready (%s) — all tools available", mode_str)

    try:
        yield {"netlogo": nl}
    finally:
        shutdown_netlogo({"netlogo": nl})


mcp = FastMCP(
    "NetLogo MCP Server",
    instructions=(
        "This server lets you create, run, and analyze NetLogo agent-based "
        "models. Use open_model or create_model first, then command/report "
        "to interact. Consult netlogo://docs/primitives for syntax help."
        "\n\nNote: server startup may take 30-60 seconds while the "
        "Java Virtual Machine starts. After startup, tool calls are instant."
    ),
    lifespan=lifespan,
)

# ── Register tools, resources, and prompts ──
from . import prompts as _prompts  # noqa: E402, F401
from . import resources as _resources  # noqa: E402, F401
from . import tools as _tools  # noqa: E402, F401


def main() -> None:
    """Console-script entry point (stdio transport)."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
        stream=sys.stderr,
    )
    # Restore real stdout for FastMCP's stdio transport
    sys.stdout = _real_stdout
    mcp.run()


if __name__ == "__main__":
    main()
